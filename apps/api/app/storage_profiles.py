"""Versioned storage connections and default selection; secrets remain server-side."""
from __future__ import annotations
import uuid
from functools import lru_cache
from urllib.parse import urlparse
from sqlalchemy import select
from .database import SessionLocal, ProviderSettingRecord
from .domain import utc_now
from .storage import StorageSettings, StorageBuckets, S3CompatibleObjectStorage, StorageError

PROVIDERS = ('minio', 'r2', 's3')
SECRET_FIELDS = {'access_key', 'secret_key', 'session_token'}
CONFIG_FIELDS = {'name', 'provider', 'endpoint_url', 'public_endpoint_url', 'account_id', 'region',
                 'reference_bucket', 'formats_bucket', 'generation_bucket', 'renders_bucket',
                 'signed_url_ttl_seconds', 'addressing_style', 'auth_mode'}


def _record(db, profile_id):
    row = db.get(ProviderSettingRecord, profile_id)
    if not row or not row.provider.startswith('storagep_'):
        raise StorageError('Storage connection not found')
    return row


def _settings(row):
    c, s = row.configuration, row.secrets
    return StorageSettings(provider=c['provider'], endpoint_url=c.get('endpoint_url') or None,
        public_endpoint_url=c.get('public_endpoint_url') or c.get('endpoint_url') or None,
        access_key=s.get('access_key') or None, secret_key=s.get('secret_key') or None,
        region=c['region'], auto_create_buckets=False, signed_url_ttl_seconds=c['signed_url_ttl_seconds'],
        buckets=StorageBuckets(**{k:c[k+'_bucket'] for k in ('reference','formats','generation','renders')}),
        profile_id=row.id, session_token=s.get('session_token') or None, addressing_style=c['addressing_style'])


def _public(row):
    return {'id':row.id, **row.configuration, 'has_access_key':bool(row.secrets.get('access_key')),
            'has_secret_key':bool(row.secrets.get('secret_key')), 'has_session_token':bool(row.secrets.get('session_token')),
            'created_at':row.created_at.isoformat() if row.created_at else None}


def storage_from_profile(profile_id):
    with SessionLocal() as db:
        settings = _settings(_record(db, profile_id))
    return _connection(settings)


@lru_cache(maxsize=64)
def _connection(settings):
    from botocore.exceptions import BotoCoreError
    try:
        return S3CompatibleObjectStorage(settings)
    except BotoCoreError as exc:
        raise StorageError(f"Could not initialize storage credentials or endpoint: {type(exc).__name__}") from None


def selected_profile_id():
    with SessionLocal() as db:
        row = db.get(ProviderSettingRecord, 'storage_selection')
        return (row.configuration or {}).get('active_profile_id') if row else None


def legacy_profile_id():
    with SessionLocal() as db:
        row = db.get(ProviderSettingRecord, 'storage_selection')
        return (row.configuration or {}).get('legacy_profile_id') if row else None


def _new_record(config, secrets):
    key = 'storagep_' + uuid.uuid4().hex[:18]
    return ProviderSettingRecord(id=key, provider=key, enabled=True, configuration=config, secrets=secrets,
                                 source='database', updated_at=utc_now())


def _environment_record():
    settings = StorageSettings.from_env()
    if settings.provider == 'memory':
        raise StorageError('Memory storage is test-only and cannot be activated as a saved connection')
    config = {'name':'Original environment storage','provider':settings.provider,
              'endpoint_url':settings.endpoint_url or '', 'public_endpoint_url':settings.public_endpoint_url or '',
              'region':settings.region,'signed_url_ttl_seconds':settings.signed_url_ttl_seconds,
              'addressing_style':settings.addressing_style,
              'auth_mode':'iam_role' if settings.provider=='s3' and not settings.access_key else 'access_key',
              **{k+'_bucket':getattr(settings.buckets,k) for k in ('reference','formats','generation','renders')}}
    return _new_record(config, {'access_key':settings.access_key or '', 'secret_key':settings.secret_key or '',
                                'session_token':settings.session_token or ''})


def list_storage_profiles():
    with SessionLocal() as db:
        rows=db.scalars(select(ProviderSettingRecord).where(ProviderSettingRecord.provider.startswith('storagep_')).order_by(ProviderSettingRecord.created_at)).all()
        selector=db.get(ProviderSettingRecord,'storage_selection')
        return {'providers':list(PROVIDERS),'active_profile_id':selector.configuration.get('active_profile_id') if selector else None,
                'environment_provider':StorageSettings.from_env().provider, 'profiles':[_public(r) for r in rows]}


def save_storage_profile(values, *, base_profile_id=None):
    if set(values)-CONFIG_FIELDS-SECRET_FIELDS:
        raise StorageError('Unknown storage settings field')
    with SessionLocal() as db:
        base=_record(db,base_profile_id) if base_profile_id else None
        c=dict(base.configuration) if base else {}
        secrets=dict(base.secrets) if base else {}
        c.update({k:v for k,v in values.items() if k in CONFIG_FIELDS})
        for key in SECRET_FIELDS:
            if values.get(key):secrets[key]=str(values[key])
        provider=c.get('provider')
        if provider not in PROVIDERS:raise StorageError('Choose MinIO, Cloudflare R2, or AWS S3')
        if base and base.configuration['provider'] != provider:
            raise StorageError('Create a separate connection when changing providers')
        if c.get('auth_mode')=='provider_r2':
            if provider!='r2':raise StorageError('Saved R2 credentials can only be used for R2')
            existing=db.scalar(select(ProviderSettingRecord).where(ProviderSettingRecord.provider=='r2'))
            if not existing or not (existing.secrets or {}).get('access_key_id') or not (existing.secrets or {}).get('secret_access_key'):
                raise StorageError('No previous R2 credentials are available. Enter credentials in File storage')
            secrets={'access_key':existing.secrets['access_key_id'],'secret_key':existing.secrets['secret_access_key']}
            c['account_id']=c.get('account_id') or existing.configuration.get('account_id','')
            c['endpoint_url']=c.get('endpoint_url') or existing.configuration.get('endpoint_url','')
            c['auth_mode']='access_key'
        c['name']=str(c.get('name') or provider.upper()).strip()[:160]
        c['region']=str(c.get('region') or ('auto' if provider=='r2' else 'us-east-1')).strip()
        c['addressing_style']=c.get('addressing_style') or ('auto' if provider=='s3' else 'path')
        if c['addressing_style'] not in {'auto','path','virtual'}:raise StorageError('Invalid addressing style')
        try:
            c['signed_url_ttl_seconds']=int(c.get('signed_url_ttl_seconds',900))
        except (TypeError,ValueError):
            raise StorageError('Signed URL lifetime must be an integer') from None
        if not 60<=c['signed_url_ttl_seconds']<=604800:raise StorageError('Signed URL lifetime must be 60..604800 seconds')
        if provider=='r2' and not c.get('endpoint_url'):
            account=str(c.get('account_id') or '')
            if len(account)!=32 or any(ch not in '0123456789abcdefABCDEF' for ch in account):raise StorageError('R2 account ID must be 32 hexadecimal characters')
            c['endpoint_url']=f'https://{account}.r2.cloudflarestorage.com'
        for field in ('endpoint_url','public_endpoint_url'):
            value=str(c.get(field) or '').strip();c[field]=value
            if value:
                url=urlparse(value)
                if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise StorageError('Storage endpoints must be HTTP(S) URLs without embedded credentials or query strings')
        c['auth_mode']=c.get('auth_mode') or 'access_key'
        if c['auth_mode'] not in {'access_key','iam_role'} or (provider!='s3' and c['auth_mode']=='iam_role'):raise StorageError('IAM role authentication is supported for AWS S3 only')
        if c['auth_mode']=='iam_role':secrets={}
        if provider!='s3' and not c.get('endpoint_url'):raise StorageError('Storage endpoint is required')
        if bool(secrets.get('access_key'))!=bool(secrets.get('secret_key')):raise StorageError('Provide both access key and secret key')
        if c['auth_mode']=='access_key' and not secrets.get('access_key'):raise StorageError('Access key and secret key are required')
        for scope in ('reference','formats','generation','renders'):
            name=str(c.get(scope+'_bucket') or '').strip()
            if not name or len(name)>63 or '/' in name or '\\' in name:raise StorageError(f'{scope} bucket is required (bucket name only)')
            c[scope+'_bucket']=name
        if c['reference_bucket'] in {c['formats_bucket'],c['generation_bucket'],c['renders_bucket']}:
            raise StorageError('Keep reference media in a separate private bucket')
        row=_new_record(c,secrets);db.add(row);db.commit();db.refresh(row)
        return _public(row)


def check_storage_profile(profile_id):
    storage=storage_from_profile(profile_id)
    # Verify upload, read-back and a signed GET without changing bucket policy.
    import requests
    from botocore.exceptions import BotoCoreError, ClientError
    results=[]
    for bucket in storage.settings.buckets.all():
        key=f'.frameflow-check/{uuid.uuid4().hex}.txt';payload=b'frameflow-storage-check';written=False
        try:
            storage.put_bytes(bucket=bucket,key=key,data=payload,content_type='text/plain');written=True
            if storage.get_bytes(bucket=bucket,key=key)!=payload:raise StorageError('Storage read-back did not match')
            signed=storage.client.generate_presigned_url("get_object",Params={"Bucket":bucket,"Key":key},ExpiresIn=60)
            response=requests.get(signed,timeout=20)
            if response.status_code!=200 or response.content!=payload:raise StorageError('Signed download URL verification failed')
            results.append({'bucket':bucket,'ok':True})
        except (StorageError, BotoCoreError, ClientError, requests.RequestException) as exc:
            cause=exc
            for _ in range(6):
                if isinstance(cause,ClientError) or cause.__cause__ is None:break
                cause=cause.__cause__
            code=str(cause.response.get('Error',{}).get('Code')) if isinstance(cause,ClientError) else type(exc).__name__
            if not code.replace('_','').replace('-','').isalnum() or len(code)>64:code='ProviderError'
            raise StorageError(f'Storage check failed for {bucket}: {code}. Check endpoint, region and bucket permissions.') from None
        finally:
            if written:
                try:storage.client.delete_object(Bucket=bucket,Key=key)
                except (BotoCoreError,ClientError):pass
    return {'profile_id':profile_id,'ok':True,'buckets':results}


def activate_storage_profile(profile_id):
    check_storage_profile(profile_id)
    with SessionLocal() as db:
        _record(db,profile_id)
        selector=db.get(ProviderSettingRecord,'storage_selection')
        if selector is None:
            legacy=_environment_record();db.add(legacy);db.flush()
            selector=ProviderSettingRecord(id='storage_selection',provider='storage_selection',enabled=True,
                configuration={'legacy_profile_id':legacy.id},secrets={},source='database',updated_at=utc_now());db.add(selector)
        selector.configuration={**selector.configuration,'active_profile_id':profile_id};selector.updated_at=utc_now();db.commit()
    return list_storage_profiles()


def rotate_storage_credentials(profile_id, values):
    if not values or set(values)-SECRET_FIELDS:
        raise StorageError('Only storage credential fields may be rotated')
    with SessionLocal() as db:
        row=_record(db,profile_id)
        if row.configuration.get('auth_mode')=='iam_role':
            raise StorageError('IAM role connections use the execution host credential chain')
        secrets={**row.secrets, **{k:str(v) for k,v in values.items()}}
        if not secrets.get('access_key') or not secrets.get('secret_key'):
            raise StorageError('Access key and secret key are required')
        row.secrets=secrets;row.updated_at=utc_now();db.commit();db.refresh(row)
        return _public(row)
