import hashlib
import io
import json
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError
from app import storage, storage_profiles, storage_migration
from app.database import SessionLocal, ArtifactRecord
from app.service import create_artifact


class Body(io.BytesIO):
    def iter_chunks(self, chunk_size=1024):
        while chunk := self.read(chunk_size):
            yield chunk


class FakeS3:
    def __init__(self, objects, endpoint):
        self.objects=objects;self.endpoint=endpoint
    def put_object(self, **kw):
        self.objects[(self.endpoint,kw['Bucket'],kw['Key'])]=bytes(kw['Body']);return {'ETag':'"test"'}
    def get_object(self, **kw):
        return {'Body':Body(self.objects[(self.endpoint,kw['Bucket'],kw['Key'])])}
    def head_object(self, **kw):
        if (self.endpoint,kw['Bucket'],kw['Key']) not in self.objects:
            raise ClientError({'Error':{'Code':'404'}},'HeadObject')
        return {}
    def upload_fileobj(self, body, bucket, key, **kw):
        self.objects[(self.endpoint,bucket,key)]=body.read()
    def delete_object(self, **kw):
        self.objects.pop((self.endpoint,kw['Bucket'],kw['Key']),None)
    def generate_presigned_url(self, operation, Params, **kwargs):
        return self.endpoint+'/'+Params['Bucket']+'/'+Params['Key']


@pytest.fixture
def configured(client,monkeypatch):
    monkeypatch.setenv('STORAGE_PROVIDER','minio')
    monkeypatch.setenv('STORAGE_ENDPOINT','http://minio:9000')
    monkeypatch.setenv('STORAGE_PUBLIC_ENDPOINT','http://minio:9000')
    objects={};real=storage.S3CompatibleObjectStorage
    def factory(settings):
        fake=FakeS3(objects,settings.endpoint_url or 'https://s3.amazonaws.com')
        return real(settings,client=fake,public_client=fake)
    monkeypatch.setattr(storage,'S3CompatibleObjectStorage',factory)
    monkeypatch.setattr(storage_profiles,'S3CompatibleObjectStorage',factory)
    import requests
    def get(url,**kwargs):
        match=next((body for (ep,b,k),body in objects.items() if url==ep+'/'+b+'/'+k),None)
        return SimpleNamespace(status_code=200 if match is not None else 404,content=match)
    monkeypatch.setattr(requests,'get',get)
    storage.reset_storage_cache()
    yield client,objects
    storage.reset_storage_cache()


def values(provider='r2'):
    return {'provider':provider,'name':'Target','account_id':'a'*32,'region':'auto' if provider=='r2' else 'ap-northeast-2',
            'access_key':'test-access','secret_key':'super-private-secret','reference_bucket':'references-private',
            'formats_bucket':'formats','generation_bucket':'assets','renders_bucket':'renders'}


def save(client,provider='r2'):
    response=client.post('/settings/storage/profiles',json={'values':values(provider)})
    assert response.status_code==201,response.text
    return response.json()


def test_connections_are_write_only_and_immutable(configured):
    client,_=configured;p=save(client)
    assert 'super-private-secret' not in client.get('/settings/storage').text
    assert p['has_secret_key'] and 'secret_key' not in p
    copy=client.post('/settings/storage/profiles',json={'base_profile_id':p['id'],'values':{'name':'New revision','generation_bucket':'new-assets'}}).json()
    assert copy['id']!=p['id'] and copy['has_secret_key']
    profiles=client.get('/settings/storage').json()['profiles']
    assert next(x for x in profiles if x['id']==p['id'])['generation_bucket']=='assets'
    assert client.post('/settings/storage/profiles',json={'values':{**values(),'reference_bucket':'assets'}}).status_code==422


def test_switching_write_default_preserves_old_reads_and_urls(configured):
    client,_=configured
    with SessionLocal() as db:
        old=create_artifact(db,'Video',content=b'original-video',content_type='video/mp4');db.commit();old_id=old.id
    p=save(client);activated=client.post('/settings/storage/profiles/'+p['id']+'/activate')
    assert activated.status_code==200,activated.text
    with SessionLocal() as db:
        old=db.get(ArtifactRecord,old_id)
        assert storage.get_artifact_storage(old.uri,old.metadata_json).settings.provider=='minio'
        bucket,key=storage.storage_location(old.uri,old.metadata_json)
        assert storage.get_artifact_storage(old.uri,old.metadata_json).get_bytes(bucket=bucket,key=key)==b'original-video'
        new=create_artifact(db,'Video',content=b'new-video',content_type='video/mp4');db.commit()
        assert new.metadata_json['storage']['profile_id']==p['id']
        assert new.metadata_json['storage']['provider']=='r2'
    response=client.get('/artifacts/'+old_id+'/download-url').json()
    assert response['provider']=='minio' and response['url'].startswith('http://minio:9000/')


@pytest.mark.parametrize("provider", ["minio", "r2"])
@pytest.mark.parametrize("inline_output", [False, True])
def test_reference_json_content_is_readable_without_storage_redirect(configured, provider, inline_output):
    client, _ = configured
    if provider == "r2":
        profile = save(client)
        assert client.post(f"/settings/storage/profiles/{profile['id']}/activate").status_code == 200

    manifest = {"schema_version": "reference.decomposition.v1", "source": {"duration_ms": 3000}}
    content = json.dumps(manifest).encode()
    metadata = {"output": {"kind": "json", "text": content.decode()}} if inline_output else {}
    with SessionLocal() as db:
        artifact = create_artifact(
            db, "ReferenceAnalysis", schema_id="reference.decomposition.v1",
            content=content, content_type="application/json", metadata=metadata,
        )
        db.commit()
        artifact_id = artifact.id

    before = client.get(f"/artifacts/{artifact_id}").json()
    response = client.get(
        f"/artifacts/{artifact_id}/content",
        headers={"Origin": "http://localhost:3000"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "location" not in response.headers
    assert response.json() == manifest
    assert client.get(f"/artifacts/{artifact_id}").json() == before
    assert ("output" in before["metadata"]) is inline_output


def test_binary_content_keeps_storage_redirect(configured):
    client, _ = configured
    with SessionLocal() as db:
        artifact = create_artifact(db, "Video", content=b"video", content_type="video/mp4")
        db.commit()
        artifact_id = artifact.id
    response = client.get(f"/artifacts/{artifact_id}/content", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"].startswith("http://minio:9000/")


@pytest.mark.parametrize("provider", ["minio", "r2"])
@pytest.mark.parametrize("content_type", ["font/ttf", "font/otf", "application/octet-stream"])
def test_font_bytes_are_served_with_api_cors_without_storage_redirect(configured, provider, content_type):
    from test_font_registry_and_caption_documents import minimal_font

    client, _ = configured
    if provider == "r2":
        profile = save(client)
        assert client.post(f"/settings/storage/profiles/{profile['id']}/activate").status_code == 200
    content = minimal_font()
    with SessionLocal() as db:
        artifact = create_artifact(db, "Font", schema_id="font.face.v1", content=content, content_type=content_type)
        db.commit()
        artifact_id = artifact.id
    response = client.get(f"/artifacts/{artifact_id}/content", headers={"Origin": "http://localhost:3000"}, follow_redirects=False)
    assert response.status_code == 200
    assert "location" not in response.headers
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["content-type"] == content_type
    assert response.content == content


def test_failed_connection_never_changes_active_provider(configured,monkeypatch):
    client,_=configured;p=save(client)
    monkeypatch.setattr(storage_profiles,'check_storage_profile',lambda *_: (_ for _ in ()).throw(storage.StorageError('permission denied')))
    assert client.post('/settings/storage/profiles/'+p['id']+'/activate').status_code==422
    assert client.get('/settings/storage').json()['active_profile_id'] is None


def test_streaming_migration_is_verified_idempotent_and_keeps_source(configured):
    client,objects=configured
    with SessionLocal() as db:
        original=create_artifact(db,'Video',content=b'migrate-me',content_type='video/mp4');db.commit();id=original.id;sha=original.sha256;old_uri=original.uri
    target=save(client)
    plan=client.get('/settings/storage/profiles/'+target['id']+'/migration-plan').json()
    assert id in plan['artifact_ids'] and plan['source_deleted'] is False
    result=client.post('/settings/storage/migrate',json={'target_profile_id':target['id'],'artifact_ids':[id]}).json()
    assert result['results'][0]['status']=='migrated',result
    with SessionLocal() as db:
        artifact=db.get(ArtifactRecord,id)
        assert artifact.sha256==sha and artifact.metadata_json['storage']['verified']
        assert artifact.metadata_json['storage_history'][0]['uri']==old_uri
        bucket,key=storage.storage_location(artifact.uri,artifact.metadata_json)
        assert storage.get_artifact_storage(artifact.uri,artifact.metadata_json).get_bytes(bucket=bucket,key=key)==b'migrate-me'
    assert sum(v==b'migrate-me' for v in objects.values())==2
    assert storage_migration.migrate_artifact(id,target['id'])['status']=='already_migrated'


def test_checksum_mismatch_does_not_switch_locator(configured,monkeypatch):
    client,_=configured
    with SessionLocal() as db:
        a=create_artifact(db,'Video',content=b'original',content_type='video/mp4');db.commit();id=a.id;uri=a.uri;meta=dict(a.metadata_json)
    target=save(client)
    monkeypatch.setattr(storage_migration,'_digest',lambda *_:('bad',8))
    result=client.post('/settings/storage/migrate',json={'target_profile_id':target['id'],'artifact_ids':[id]}).json()
    assert result['results'][0]['status']=='failed'
    with SessionLocal() as db:
        a=db.get(ArtifactRecord,id);assert a.uri==uri and a.metadata_json==meta


def test_s3_native_endpoint_role_and_credential_rotation(configured):
    client,_=configured
    response=client.post('/settings/storage/profiles',json={'values':{**values('s3'),'auth_mode':'iam_role','access_key':'','secret_key':''}})
    assert response.status_code==201,response.text
    p=response.json();assert p['endpoint_url']=='' and not p['has_access_key']
    connection=storage_profiles.storage_from_profile(p['id'])
    assert connection.settings.endpoint_url is None and connection.settings.region=='ap-northeast-2'
    key_profile=save(client,'s3')
    rotated=client.put('/settings/storage/profiles/'+key_profile['id']+'/credentials',json={'values':{'access_key':'rotated','secret_key':'new-secret'}})
    assert rotated.status_code==200
    assert 'new-secret' not in rotated.text
    assert storage_profiles.storage_from_profile(key_profile['id']).settings.access_key=='rotated'


def test_unknown_profile_fails_closed(configured):
    with pytest.raises(storage.StorageError,match='not found'):
        storage.get_artifact_storage('s3://assets/a',{'storage':{'profile_id':'unknown'}})


def test_switch_to_s3_keeps_r2_objects_readable_after_cache_reset(configured):
    client,_=configured
    r2=save(client)
    assert client.post('/settings/storage/profiles/'+r2['id']+'/activate').status_code==200
    with SessionLocal() as db:
        a=create_artifact(db,'Image',content=b'r2-picture',content_type='image/png');db.commit();id=a.id
    s3=save(client,'s3')
    assert client.post('/settings/storage/profiles/'+s3['id']+'/activate').status_code==200
    storage.reset_storage_cache()
    assert storage.get_storage().settings.provider=='s3'
    with SessionLocal() as db:
        a=db.get(ArtifactRecord,id);backend=storage.get_artifact_storage(a.uri,a.metadata_json)
        bucket,key=storage.storage_location(a.uri,a.metadata_json)
        assert backend.settings.provider=='r2'
        assert backend.get_bytes(bucket=bucket,key=key)==b'r2-picture'
    assert 'super-private-secret' not in client.get('/settings/storage').text


def test_s3_training_zip_does_not_require_r2_credentials(configured):
    client,objects=configured
    from app.r2_training_storage import get_training_dataset_store
    target=save(client,'s3')
    assert client.post('/settings/storage/profiles/'+target['id']+'/activate').status_code==200
    dataset=get_training_dataset_store().put_archive(character_id='character-test',archive=b'zip-content')
    assert dataset.provider=='s3'
    assert dataset.profile_id==target['id']
    assert dataset.bucket=='assets'
    assert any(content==b'zip-content' for content in objects.values())


@pytest.mark.parametrize("legacy_enabled", [True, False])
def test_r2_can_reuse_existing_provider_secret_without_exposing_it(configured, legacy_enabled):
    client,_=configured
    client.get('/settings/providers')
    response=client.put('/settings/providers/r2',json={'enabled':legacy_enabled,'values':{'account_id':'a'*32,'bucket':'training','access_key_id':'existing-access','secret_access_key':'existing-secret'}})
    assert response.status_code==200
    payload={**values(),'account_id':'','access_key':'','secret_key':'','auth_mode':'provider_r2'}
    result=client.post('/settings/storage/profiles',json={'values':payload})
    assert result.status_code==201,result.text
    assert 'existing-secret' not in result.text
    settings=storage_profiles.storage_from_profile(result.json()['id']).settings
    assert settings.access_key=='existing-access' and settings.secret_key=='existing-secret'


def test_connection_error_exposes_safe_provider_code_not_credentials(configured,monkeypatch):
    client,_=configured;p=save(client)
    def fail(self,**kwargs):
        raise ClientError({'Error':{'Code':'AccessDenied','Message':'super-private-secret'}},'PutObject')
    monkeypatch.setattr(FakeS3,'put_object',fail)
    response=client.post('/settings/storage/profiles/'+p['id']+'/test')
    assert response.status_code==422
    assert 'AccessDenied' in response.text
    assert 'super-private-secret' not in response.text
