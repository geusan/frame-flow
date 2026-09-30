import json
import os
import subprocess
from pathlib import Path

import pytest

from app import video_downloaders
from app.database import SessionLocal
from app.provider_settings import get_provider_record, update_provider_settings
from app.youtube_session import is_youtube_url, load_youtube_cookies, normalize_youtube_cookies, sanitize_download_metadata

COOKIE = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\ttest-private-session\n"


def test_session_lifecycle_and_secret_redaction(client):
    client.get('/settings/providers')
    result = client.put('/settings/providers/youtube', json={
        'enabled': True, 'auth_method': 'cookies',
        'values': {'account_label': '작업 계정', 'cookies_txt': COOKIE},
    })
    assert result.status_code == 200
    assert result.json()['configured']
    assert result.json()['connection']['account'] == '작업 계정'
    assert 'test-private-session' not in result.text
    assert 'test-private-session' not in client.get('/settings/providers').text
    assert load_youtube_cookies() == COOKIE
    assert 'YOUTUBE_COOKIES_TXT' not in os.environ
    replacement = COOKIE.replace('test-private-session', 'new-session')
    assert client.put('/settings/providers/youtube', json={'enabled': True, 'values': {'cookies_txt': replacement}}).status_code == 200
    assert 'new-session' in load_youtube_cookies()
    client.put('/settings/providers/youtube', json={'enabled': False, 'values': {}})
    assert load_youtube_cookies() == ''
    removed = client.put('/settings/providers/youtube', json={'enabled': True, 'values': {}, 'clear_fields': ['cookies_txt']})
    assert removed.status_code == 200
    assert not removed.json()['configured']
    assert load_youtube_cookies() == ''


def test_validation_is_atomic_and_filters_unrelated_accounts(client):
    client.get('/settings/providers')
    extra = '.example.com\tTRUE\t/\tTRUE\t4102444800\tSID\tother-secret\n'
    assert normalize_youtube_cookies(COOKIE + extra) == COOKIE
    client.put('/settings/providers/youtube', json={'enabled': True, 'values': {'cookies_txt': COOKIE + extra}})
    rejected = client.put('/settings/providers/youtube', json={'enabled': True, 'values': {'cookies_txt': 'not cookies'}})
    assert rejected.status_code == 422
    assert load_youtube_cookies() == COOKIE
    with SessionLocal() as db:
        assert 'other-secret' not in json.dumps(get_provider_record(db, 'youtube').secrets)


@pytest.mark.parametrize('value', [
    '', '# Netscape HTTP Cookie File\ninvalid',
    COOKIE.replace('4102444800', 'not-an-expiry'),
    COOKIE.replace('SID', 'PREF'),
    COOKIE + ('x' * 262144),
])
def test_invalid_cookie_file(value):
    with pytest.raises(ValueError):
        normalize_youtube_cookies(value)


def test_expired_status_and_runtime_failure(client):
    client.get('/settings/providers')
    saved = client.put('/settings/providers/youtube', json={'enabled': True, 'values': {'cookies_txt': COOKIE.replace('4102444800', '1')}})
    assert not saved.json()['configured']
    assert saved.json()['connection']['state'] == 'needs_session'
    with pytest.raises(ValueError, match='expired'):
        load_youtube_cookies()


@pytest.mark.parametrize('url,expected', [
    ('https://www.youtube.com/watch?v=x', True), ('https://youtu.be/x', True),
    ('https://youtube.com.attacker.example/x', False), ('https://tiktok.com/x', False),
])
def test_domain_scope(url, expected):
    assert is_youtube_url(url) is expected


@pytest.mark.parametrize('failure', [False, True, 'timeout'])
def test_private_temporary_cookie_file_and_cleanup(monkeypatch, failure):
    monkeypatch.setattr(video_downloaders, 'load_youtube_cookies', lambda: COOKIE)
    paths = []
    def run(command, **kwargs):
        path = Path(command[command.index('--cookies') + 1]);paths.append(path)
        assert path.read_text() == COOKIE
        assert path.stat().st_mode & 0o777 == 0o600
        assert 'test-private-session' not in ' '.join(command)
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, 1, stderr=b'test-private-session')
        if failure:
            raise subprocess.CalledProcessError(1, command, stderr='test-private-session')
        return subprocess.CompletedProcess(command, 0, stdout='{}')
    monkeypatch.setattr(video_downloaders.subprocess, 'run', run)
    adapter = video_downloaders.YtDlpVideoDownloaderAdapter()
    args = dict(url='https://youtube.com/watch?v=x', timeout=1, failure_message='failed')
    if failure:
        with pytest.raises(video_downloaders.VideoDownloaderError) as exc:
            adapter._run(['yt-dlp', '--', args['url']], **args)
        assert 'test-private-session' not in str(exc.value)
    else:
        adapter._run(['yt-dlp', '--', args['url']], **args)
    assert paths and all(not path.exists() for path in paths)


def test_other_sites_never_load_or_receive_session(monkeypatch):
    def forbidden():
        pytest.fail('must not load YouTube session for unrelated hosts')
    monkeypatch.setattr(video_downloaders, 'load_youtube_cookies', forbidden)
    def run(command, **kwargs):
        assert '--cookies' not in command
        return subprocess.CompletedProcess(command, 0, stdout='{}')
    monkeypatch.setattr(video_downloaders.subprocess, 'run', run)
    video_downloaders.YtDlpVideoDownloaderAdapter()._run(['yt-dlp'], url='https://vimeo.com/1', timeout=1, failure_message='failed')


def test_metadata_does_not_leak_auth_headers():
    info = {'http_headers': {'Cookie': 'secret', 'Authorization': 'secret', 'User-Agent': 'agent'}, 'formats': [{'cookies': 'secret'}]}
    assert sanitize_download_metadata(info) == {'http_headers': {'User-Agent': 'agent'}, 'formats': [{}]}


def test_inspect_and_download_refresh_session_and_strip_metadata(monkeypatch):
    cookies = iter([COOKIE, COOKIE.replace('test-private-session', 'rotated-session')])
    monkeypatch.setattr(video_downloaders, 'load_youtube_cookies', lambda: next(cookies))
    monkeypatch.setattr(video_downloaders, 'validate_public_url', lambda url: url)
    monkeypatch.setattr(video_downloaders, '_probe_video_duration_seconds', lambda path: 5)
    seen = []
    def run(command, **kwargs):
        path = Path(command[command.index('--cookies') + 1])
        seen.append(path.read_text())
        info = {'id': 'video', 'webpage_url': 'https://www.youtube.com/watch?v=video',
                'http_headers': {'Cookie': 'must-not-persist'}, 'duration': 5}
        if '--dump-single-json' in command:
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(info))
        directory = kwargs['cwd']
        cached = json.loads(Path(command[command.index('--load-info-json') + 1]).read_text())
        assert 'must-not-persist' not in json.dumps(cached)
        (directory / 'video.mp4').write_bytes(b'video')
        (directory / 'video.jpg').write_bytes(b'image')
        (directory / 'video.info.json').write_text(json.dumps(info))
        return subprocess.CompletedProcess(command, 0, stdout='')
    monkeypatch.setattr(video_downloaders.subprocess, 'run', run)
    adapter = video_downloaders.YtDlpVideoDownloaderAdapter()
    inspected = adapter.inspect('https://www.youtube.com/watch?v=video')
    downloaded = adapter.download(inspected.canonical_url)
    assert 'test-private-session' in seen[0]
    assert 'rotated-session' in seen[1]
    assert 'must-not-persist' not in json.dumps(downloaded.info)


def test_http_only_cookie_survives_normalization():
    value = COOKIE.replace('.youtube.com', '#HttpOnly_.youtube.com')
    assert normalize_youtube_cookies(value) == value


def test_youtube_explicitly_enables_the_node_runtime():
    adapter = video_downloaders.YtDlpVideoDownloaderAdapter()
    for url in ['https://youtube.com/shorts/example', 'https://youtu.be/example']:
        command = adapter._base(url)
        assert command[command.index('--js-runtimes') + 1] == 'node'
    assert '--js-runtimes' not in adapter._base('https://vimeo.com/1')


def test_runtime_failure_is_not_misreported_as_bad_cookies(monkeypatch):
    monkeypatch.setattr(video_downloaders, 'load_youtube_cookies', lambda: COOKIE)
    def run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr='Signature solving failed: test-private-session')
    monkeypatch.setattr(video_downloaders.subprocess, 'run', run)
    with pytest.raises(video_downloaders.VideoDownloaderError, match='JavaScript processing failed') as exc:
        video_downloaders.YtDlpVideoDownloaderAdapter()._run(['yt-dlp'], url='https://youtube.com/watch?v=x', timeout=1, failure_message='metadata inspection failed')
    assert 'test-private-session' not in str(exc.value)
    assert 'replace cookies' not in str(exc.value)
