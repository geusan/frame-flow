"""Vertex Interactions capability for editing a source clip with an identity image."""
from __future__ import annotations

import base64
import json
import re
import time
from urllib.parse import quote, urljoin, urlparse

import httpx
from google.auth.transport.requests import Request

from .billing import record_provider_result, submit_with_cost
from .providers_google import GoogleProviderConfig
from .providers_performance import MediaProviderError, ProviderMedia
from .video_downloaders import VideoDownloaderError, validate_public_url


OMNI_VERTEX_MODEL = 'gemini-omni-1.1-flash-preview'
MAX_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 512 * 1024 * 1024


def edit_request(*, prompt, image, image_content_type, video, resolution):
    if not prompt.strip() or resolution not in {'720p', '1080p'}:
        raise MediaProviderError('Omni editing requires a prompt and a supported resolution')
    if image_content_type not in {'image/png', 'image/jpeg', 'image/webp'}:
        raise MediaProviderError('Omni identity image must be PNG, JPEG or WebP')
    text = ('[# Sources <VIDEO_0>@Video1] [# References <IMAGE_REF_0>@Image1] '
            + prompt.strip() + '\nUse Video1 as the source video to edit. Image1 defines only the replacement character. '
            'Preserve the full source duration and performance timing. No scene cuts or added text.')
    payload = {'model': OMNI_VERTEX_MODEL,
        'input': [{'type': 'video', 'data': base64.b64encode(video).decode(), 'mime_type': 'video/mp4'},
                  {'type': 'image', 'data': base64.b64encode(image).decode(), 'mime_type': image_content_type},
                  {'type': 'text', 'text': text}],
        'response_format': [{'type': 'video', 'resolution': resolution}],
        'generation_config': {'video_config': {'task': 'edit'}},
        'background': True, 'store': True}
    if len(json.dumps(payload).encode()) > MAX_BYTES:
        raise MediaProviderError('Omni request exceeds 64 MB')
    return payload


def interaction_id(value):
    value = str(value or '')
    if not re.fullmatch(r'[A-Za-z0-9_=-]{1,1024}', value):
        raise MediaProviderError('Omni returned an invalid interaction ID; inspect provider history before retrying')
    return value


class GoogleOmniEditService:
    task = 'edit'
    operation = 'interactions_edit'

    def __init__(self, *, config=None, client=None, poll_interval=5):
        self.config = config or GoogleProviderConfig.from_env()
        if not self.config.credentials or not re.fullmatch(r'[a-zA-Z0-9:._-]+', self.config.project or ''):
            raise MediaProviderError('Vertex Omni requires a configured Google service account and project')
        self.base = f'https://aiplatform.googleapis.com/v1beta1/projects/{self.config.project}/locations/global/interactions'
        self.client = client or httpx.Client(timeout=httpx.Timeout(180, connect=30), follow_redirects=False)
        self.poll_interval = poll_interval

    def close(self):
        self.client.close()

    def headers(self):
        credentials = self.config.credentials
        if not credentials.valid:
            credentials.refresh(Request())
        return {'Authorization': 'Bearer ' + credentials.token}

    def download(self, uri):
        if uri.startswith('gs://'):
            from google.cloud import storage
            parsed = urlparse(uri)
            if not parsed.netloc or not parsed.path.strip('/'):
                raise MediaProviderError('Omni returned an invalid Cloud Storage object')
            client = storage.Client(project=self.config.project, credentials=self.config.credentials)
            try:
                blob = client.bucket(parsed.netloc).blob(parsed.path.lstrip('/'))
                blob.reload()
                if not blob.size or blob.size > MAX_OUTPUT_BYTES:
                    raise MediaProviderError('Omni result is empty or exceeds 512 MB')
                return blob.download_as_bytes(if_generation_match=blob.generation)
            finally:
                client.close()
        for _ in range(5):
            try:
                if urlparse(uri).scheme != 'https':
                    raise ValueError('https required')
                validate_public_url(uri)
            except (ValueError, VideoDownloaderError) as exc:
                raise MediaProviderError('Omni returned an invalid public result URL') from exc
            # Never forward the service-account token to a result URL or redirect.
            with self.client.stream('GET', uri, follow_redirects=False) as response:
                if response.is_redirect:
                    if not response.headers.get('location'):
                        raise MediaProviderError('Omni result redirect has no destination')
                    uri = urljoin(uri, response.headers['location'])
                    continue
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes(1024 * 1024):
                    data.extend(chunk)
                    if len(data) > MAX_OUTPUT_BYTES:
                        raise MediaProviderError('Omni result exceeds 512 MB')
                if not data:
                    raise MediaProviderError('Omni returned an empty video')
                return bytes(data)
        raise MediaProviderError('Omni result has too many redirects')

    def result(self, task, ident):
        usage = task.get('usage') or {}
        record_provider_result('google', OMNI_VERTEX_MODEL, ident, usage,
                               context={'channel': 'vertex', 'location': 'global', 'task': self.task})
        if task.get('model') not in {None, OMNI_VERTEX_MODEL}:
            raise MediaProviderError('Omni result model does not match the requested model')
        outputs = [task.get('output_video') or {}, *(task.get('outputs') or [])]
        for step in task.get('steps') or []:
            outputs.extend(step.get('content') or [])
        for output in outputs:
            if output.get('type', 'video') != 'video':
                continue
            if output.get('data'):
                if len(output['data']) > MAX_OUTPUT_BYTES * 4 // 3 + 4:
                    raise MediaProviderError('Omni inline result exceeds 512 MB')
                try:
                    content = base64.b64decode(output['data'], validate=True)
                except ValueError as exc:
                    raise MediaProviderError('Omni inline video is not valid base64') from exc
            elif output.get('uri'):
                content = self.download(output['uri'])
            else:
                continue
            if not content:
                raise MediaProviderError('Omni returned an empty video')
            return ProviderMedia(content, output.get('mime_type') or 'video/mp4', ident,
                                 {'cost_status': 'provider_billed_unreported', 'provider_usage': usage})
        raise MediaProviderError('Completed Omni interaction has no video output; the saved interaction can be inspected')

    def edit(self, payload, *, timeout_seconds, resume_id, remember, progress):
        ident = interaction_id(resume_id) if resume_id else None
        task = None
        if not ident:
            try:
                progress(15, 'Submitting media to Vertex Gemini Omni')
                response = submit_with_cost('google', self.operation, OMNI_VERTEX_MODEL,
                    self.client.post, self.base, request_id_field='id', headers=self.headers(), json=payload)
                response.raise_for_status()
                task = response.json()
                ident = interaction_id(task.get('id'))
                remember(ident)
            except httpx.HTTPError as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else 'network'
                rejected = status in {400, 401, 403, 404, 413, 422, 429}
                if rejected:
                    remember('rejected')
                raise MediaProviderError(f'Omni submission failed ({status}); automatic resubmission is disabled', rejected=rejected) from exc
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                if task is None:
                    response = self.client.get(self.base + '/' + quote(ident, safe=''), headers=self.headers())
                    response.raise_for_status()
                    task = response.json()
                status = task.get('status')
                if status == 'completed':
                    progress(85, 'Downloading the completed Omni video')
                    return self.result(task, ident)
                if status in {'failed', 'cancelled', 'canceled', 'incomplete', 'requires_action'}:
                    if task.get('usage'):
                        record_provider_result('google', OMNI_VERTEX_MODEL, ident, task['usage'])
                    raise MediaProviderError(f'Omni interaction {status}: {ident}; inspect the saved interaction')
                if status not in {'in_progress', 'queued', 'pending'}:
                    raise MediaProviderError('Omni returned an unknown interaction status')
                progress(50, 'Gemini Omni is generating the video')
                task = None
                time.sleep(self.poll_interval)
            except httpx.HTTPError as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {408, 429} or exc.response.status_code >= 500
                raise MediaProviderError(f'Omni query/download interrupted; resume interaction {ident}', retryable=retryable) from exc
        raise MediaProviderError(f'Omni interaction pending; resume {ident}', retryable=True)


def animation_request(*, prompt, image, image_content_type, resolution, aspect_ratio, duration_seconds):
    if not prompt.strip() or resolution not in {'720p', '1080p'} or aspect_ratio not in {'9:16', '16:9'}:
        raise MediaProviderError('Omni image animation requires a prompt, resolution and aspect ratio')
    if type(duration_seconds) is not int or not 3 <= duration_seconds <= 10:
        raise MediaProviderError('Omni image animation duration must be an integer from 3 to 10 seconds')
    if image_content_type not in {'image/png', 'image/jpeg', 'image/webp'} or not image:
        raise MediaProviderError('Omni starting image must be PNG, JPEG or WebP')
    # Duration is prompted; the current Interactions schema has no duration field.
    # The executor separately verifies the actual returned video clock.
    text = (f'[# Sources <FIRST_FRAME>@Image1] Generate one continuous {duration_seconds}-second shot. '
            'Use Image1 as the exact starting frame. ' + prompt.strip())
    payload = {'model': OMNI_VERTEX_MODEL,
        'input': [{'type':'image','data':base64.b64encode(image).decode(),'mime_type':image_content_type},
                  {'type':'text','text':text}],
        'response_format': [{'type':'video','resolution':resolution,'aspect_ratio':aspect_ratio}],
        'generation_config': {'video_config': {'task':'image_to_video'}}, 'background':True, 'store':True}
    if len(json.dumps(payload).encode()) > MAX_BYTES:
        raise MediaProviderError('Omni request exceeds 64 MB')
    return payload


class GoogleOmniAnimationService(GoogleOmniEditService):
    task = 'image_to_video'
    operation = 'interactions_image_animation'

    def generate(self, payload, **kwargs):
        return self.edit(payload, **kwargs)
