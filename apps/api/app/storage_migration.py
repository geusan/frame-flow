"""Copy verified object bytes between storage connections without changing Artifact identity."""
from __future__ import annotations
import hashlib
from sqlalchemy import select
from boto3.s3.transfer import TransferConfig
from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import BotoCoreError
from .database import SessionLocal, ArtifactRecord
from .storage import StorageError, get_artifact_storage, storage_location, bucket_for_artifact
from .storage_profiles import storage_from_profile


def _digest(client, bucket, key):
    body=client.get_object(Bucket=bucket,Key=key)['Body'];digest=hashlib.sha256();size=0
    try:
        for chunk in body.iter_chunks(chunk_size=1024*1024):
            digest.update(chunk);size+=len(chunk)
    finally:body.close()
    return digest.hexdigest(),size


def migration_plan(target_profile_id):
    storage_from_profile(target_profile_id)
    with SessionLocal() as db:
        rows=list(db.scalars(select(ArtifactRecord).order_by(ArtifactRecord.created_at)))
        pending=[r for r in rows if (r.metadata_json.get('storage') or {}).get('profile_id')!=target_profile_id]
        return {'target_profile_id':target_profile_id,'artifact_ids':[r.id for r in pending],
                'count':len(pending),'size_bytes':sum(int((r.metadata_json.get('storage') or {}).get('size_bytes') or 0) for r in pending),
                'source_deleted':False}


def migrate_artifact(artifact_id, target_profile_id):
    target=storage_from_profile(target_profile_id)
    with SessionLocal() as db:
        record=db.get(ArtifactRecord,artifact_id)
        if record is None:raise StorageError('Artifact not found')
        snapshot=dict(record.metadata_json);original=dict(snapshot.get('storage') or {});uri=record.uri;sha=record.sha256
        if original.get('profile_id')==target_profile_id:return {'artifact_id':artifact_id,'status':'already_migrated'}
        source=get_artifact_storage(uri,snapshot);source_bucket,source_key=storage_location(uri,snapshot)
        bucket=bucket_for_artifact(target.settings,record.type,snapshot);key=source_key
        expected_size=int(original['size_bytes']) if 'size_bytes' in original else None
        mime=original.get('content_type') or 'application/octet-stream'
    from botocore.exceptions import ClientError
    try:
        try:
            target.client.head_object(Bucket=bucket,Key=key);exists=True
        except ClientError as exc:
            if str(exc.response.get('Error',{}).get('Code')) not in {'404','NoSuchKey','NotFound'}:raise
            exists=False
        if not exists:
            response=source.client.get_object(Bucket=source_bucket,Key=source_key)
            body=response['Body']
            try:
                target.client.upload_fileobj(body,bucket,key,ExtraArgs={'ContentType':mime,'Metadata':{'sha256':sha,'artifact-id':artifact_id}},
                    Config=TransferConfig(multipart_threshold=16*1024*1024,multipart_chunksize=16*1024*1024,max_concurrency=2))
            finally:body.close()
        actual_sha,size=_digest(target.client,bucket,key)
        if actual_sha!=sha or (expected_size is not None and size!=expected_size):
            raise StorageError('Destination checksum/size mismatch; original Artifact location was preserved')
    except ClientError as exc:
        raise StorageError('Storage copy failed: '+str(exc.response.get('Error',{}).get('Code','unknown'))) from None
    with SessionLocal() as db:
        record=db.get(ArtifactRecord,artifact_id,with_for_update=True)
        if record.uri!=uri or (record.metadata_json.get('storage') or {})!=original:
            raise StorageError('Artifact storage changed during migration; refresh and retry')
        history=list(record.metadata_json.get('storage_history') or [])
        # Freeze the source connection for rollback even if it originally came from env.
        previous={**original,'uri':uri}
        if source.settings.profile_id:previous['profile_id']=source.settings.profile_id
        history.append(previous)
        record.uri=f's3://{bucket}/{key}'
        record.metadata_json={**record.metadata_json,'storage_history':history,'storage':{
            'provider':target.settings.provider,'profile_id':target_profile_id,'bucket':bucket,'key':key,
            'content_type':mime,'size_bytes':size,'sha256':sha,'verified':True}}
        db.commit()
    return {'artifact_id':artifact_id,'status':'migrated','size_bytes':size,'sha256':sha,'source_deleted':False}


def migrate_batch(target_profile_id, artifact_ids):
    results=[]
    for artifact_id in dict.fromkeys(artifact_ids):
        try:results.append(migrate_artifact(artifact_id,target_profile_id))
        except StorageError as exc:results.append({'artifact_id':artifact_id,'status':'failed','error':str(exc)})
        except (BotoCoreError, S3UploadFailedError) as exc:results.append({'artifact_id':artifact_id,'status':'failed','error':f'Storage transfer failed ({type(exc).__name__}); check credentials and network.'})
    return {'results':results,'source_deleted':False}


if __name__=='__main__':
    import argparse,json
    parser=argparse.ArgumentParser();parser.add_argument('--target',required=True);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    plan=migration_plan(args.target);print(json.dumps(plan),flush=True)
    if args.apply:
        for id in plan['artifact_ids']:
            result=migrate_batch(args.target,[id]);print(json.dumps(result),flush=True)
            if result['results'][0]['status']=='failed':raise SystemExit(1)
