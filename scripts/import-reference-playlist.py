"""Resumable, analysis-only playlist ingestion. Run inside the configured API environment.

python -c 'exec(open("/tmp/import-reference-playlist.py").read())' -- \
  --playlist /tmp/japanese-playlist.json --state /tmp/japanese-playlist-state.json
The playlist must be an already inspected yt-dlp flat playlist JSON with entries.
"""
from __future__ import annotations
import argparse,json,time,threading,tempfile,subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from sqlalchemy import select
from app.database import SessionLocal,ReferenceRecord,ReferenceSetRecord,ArtifactRecord
from app.service import canonicalize_url,create_artifact,new_id,audit
from app.video_downloaders import get_video_downloader


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--playlist',required=True);parser.add_argument('--state',required=True);parser.add_argument('--workers',type=int,default=1);args=parser.parse_args()
    playlist=json.loads(Path(args.playlist).read_text());path=Path(args.state);lock=threading.Lock()
    state=json.loads(path.read_text()) if path.exists() else {'playlist_id':playlist['id'],'title':playlist['title'],'total':len(playlist['entries']),'items':{},'status':'running'}
    if state['playlist_id']!=playlist['id']:raise ValueError('Checkpoint belongs to a different playlist')
    state['status']='running'
    with SessionLocal() as db:
        name=f"{playlist['title']} · {playlist['id']}"
        refset=db.scalar(select(ReferenceSetRecord).where(ReferenceSetRecord.name==name))
        if refset is None:
            refset=ReferenceSetRecord(id=new_id('refset'),name=name,reference_ids=[]);db.add(refset);db.commit()
        state['reference_set_id']=refset.id
    def save():
        state['updated_at']=time.time();tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2));tmp.replace(path)
    def sync_set():
        with SessionLocal() as db:
            refset=db.get(ReferenceSetRecord,state['reference_set_id'])
            refset.reference_ids=[state['items'][e['id']]['reference_id'] for e in playlist['entries'] if state['items'].get(e['id'],{}).get('status')=='downloaded'];db.commit()
    def one(index,entry):
        url=f"https://www.youtube.com/watch?v={entry['id']}";canonical=canonicalize_url(url)
        with SessionLocal() as db:
            existing=db.scalar(select(ReferenceRecord).where(ReferenceRecord.canonical_url==canonical))
            if existing:
                artifacts=list(db.scalars(select(ArtifactRecord).where(ArtifactRecord.type.in_(['ReferenceOriginal','ProxyVideo','Thumbnail']))))
                ids={a.type:a.id for a in artifacts if a.metadata_json.get('reference_id')==existing.id}
                if 'ReferenceOriginal' in ids:return {'status':'downloaded','reference_id':existing.id,'artifact_ids':ids,'title':existing.title,'duration_ms':existing.duration_ms,'deduplicated':True,'index':index}
        provider=get_video_downloader('yt-dlp');provider.download_subtitles=False;inspected=provider.inspect(url)
        media=provider.download(url,max_duration_seconds=7200,max_filesize_bytes=1024**3)
        with tempfile.TemporaryDirectory(prefix='playlist-preview-') as temp:
            source=Path(temp)/'source.mp4';target=Path(temp)/'preview.mp4';source.write_bytes(media.video)
            preview_seconds=min(60,inspected.duration_ms/1000)
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(source),'-t',str(preview_seconds),'-vf','scale=540:960:force_original_aspect_ratio=decrease,pad=540:960:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p','-c:v','libx264','-preset','veryfast','-crf','28','-c:a','aac','-b:a','96k','-movflags','+faststart',str(target)],check=True,capture_output=True,timeout=240)
            proxy=target.read_bytes()
        with SessionLocal() as db:
            reference=ReferenceRecord(id=new_id('ref'),canonical_url=canonical,source_id=inspected.source_id,title=inspected.title,creator=inspected.creator,duration_ms=inspected.duration_ms,rights_basis='analysis_only',allow_generation_input=False,allow_direct_asset_use=False,status='ready',metadata_json={'canonical_url':canonical,'inspected':inspected.__dict__,'playlist_id':playlist['id'],'playlist_index':index,'playlist_title':playlist['title']})
            db.add(reference);ids={}
            base={'reference_id':reference.id,'access_scope':'reference-analyzer-only','storage_scope':'reference','playlist_id':playlist['id'],'playlist_index':index,'source_url':canonical}
            for typ,content,mime,name,extra in [
                ('ReferenceOriginal',media.video,media.video_content_type,inspected.title+'.mp4',{'duration_ms':inspected.duration_ms}),
                ('ProxyVideo',proxy,'video/mp4','preview.mp4',{'duration_ms':round(preview_seconds*1000),'source_duration_ms':inspected.duration_ms,'preview_only':preview_seconds*1000<inspected.duration_ms}),
                ('Thumbnail',media.thumbnail,media.thumbnail_content_type,'thumbnail.'+media.thumbnail_content_type.split('/')[-1],{}),
            ]:
                a=create_artifact(db,typ,content=content,content_type=mime,filename=name,metadata={**base,**extra,'filename':name});ids[typ]=a.id
            if media.subtitle:
                sub=create_artifact(db,'Subtitle',schema_id='subtitle.source.v1',content=media.subtitle,content_type=media.subtitle_content_type,filename='subtitle.srt',metadata=base);ids['Subtitle']=sub.id
            reference.metadata_json={**reference.metadata_json,'artifact_ids':ids,'source_id':inspected.source_id}
            audit(db,'reference.imported',reference.id,{'rights_basis':'analysis_only','playlist_id':playlist['id'],'playlist_index':index});db.commit()
        return {'status':'downloaded','reference_id':reference.id,'artifact_ids':ids,'title':inspected.title,'duration_ms':inspected.duration_ms,'size_bytes':len(media.video),'index':index}
    def worker(index,entry):
        with lock:
            if state['items'].get(entry['id'],{}).get('status')=='downloaded':return
            state['items'][entry['id']]={'status':'downloading','title':entry.get('title'),'index':index};save()
        for attempt in range(3):
            try:
                result=one(index,entry);break
            except Exception as exc:
                details=[];current=exc
                for _ in range(6):
                    if current is None:break
                    details.append(str(current).lower());current=current.__cause__ or current.__context__
                combined=' '.join(details)
                reason=next((label for token,label in [('429','rate_limit'),('403','http_forbidden'),('subtitle','subtitle_request'),('not available','unavailable'),('private video','private'),('timed out','timeout'),('sign in','authentication')] if token in combined),'download_error')
                result={'status':'failed','title':entry.get('title'),'index':index,'error':str(exc)[:1200],'reason':reason,'attempts':attempt+1}
                if attempt<2:time.sleep(20*(attempt+1))
        with lock:
            state['items'][entry['id']]=result;save();sync_set()
            counts={s:sum(v['status']==s for v in state['items'].values()) for s in ['downloaded','failed','downloading']}
            print(json.dumps({'index':index,'video_id':entry['id'],**counts,'status':result['status']},ensure_ascii=False),flush=True)
        time.sleep(8)
    save()
    with ThreadPoolExecutor(max_workers=max(1,min(3,args.workers))) as pool:
        futures=[pool.submit(worker,e.get('playlist_index',i),e) for i,e in enumerate(playlist['entries'],1)]
        for future in as_completed(futures):future.result()
    state['status']='complete' if all(state['items'].get(e['id'],{}).get('status')=='downloaded' for e in playlist['entries']) else 'completed_with_failures';save();sync_set();print(state['status'],flush=True)

if __name__=='__main__':main()
