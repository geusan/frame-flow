from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from ..contracts import NodeArtifactWrite, NodeExecutionContext, NodeExecutionResult
from .media_tools import probe_media, media_duration_seconds, run_media_command, write_media_artifact, video_stream
from .performance_transfer import _runtime_revision, _ffmpeg_version


def _time(milliseconds: int) -> str:
    centiseconds = max(0, round(milliseconds / 10))
    seconds, cs = divmod(centiseconds, 100)
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours}:{minute:02d}:{sec:02d}.{cs:02d}"


def _color(value: str) -> str:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value): raise ValueError("Caption color must be #RRGGBB")
    return f"&H00{value[5:7]}{value[3:5]}{value[1:3]}"


def _text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\\", "／").replace("{", "(").replace("}", ")").replace("\n", r"\N")


def reference_tracks_ass(analysis: dict, config: dict, width: int, height: int, duration_ms: int) -> tuple[str, list[dict]]:
    if analysis.get("schema_version") != "reference.decomposition.v1": raise ValueError("Expected ReferenceAnalysis v1")
    font = re.sub(r"[,{}\\\r\n]", " ", config["font_family"]).strip()
    accent, outline = _color(config["accent_color"]), _color(config["outline_color"])
    tracks = []
    for source in [*(analysis.get("visual") or {}).get("text_tracks", []), *config["extra_tracks"]]:
        track = dict(source); ident = str(track["track_id"])
        if ident in config["text_overrides"]: track["text"] = str(config["text_overrides"][ident])
        timing = config["timing_overrides"].get(ident, {})
        start = max(0, int(timing.get("start_ms", track["start_ms"])))
        end = min(duration_ms, int(timing.get("end_ms", track["end_ms"])))
        if end <= start: continue
        positions = track.get("positions") or []
        if not positions: continue
        box = positions[0]["bbox"]
        x,y,w,h = (float(box[k]) for k in ("x","y","width","height"))
        if not (0 <= x < 1 and 0 <= y < 1 and w > 0 and h > 0 and x+w <= 1.01 and y+h <= 1.01):
            raise ValueError("Caption bounding box is outside the image")
        tracks.append({"id": ident, "text": str(track["text"]), "start_ms": start, "end_ms": end,
                       "x": round(x*width), "y": round(y*height), "w": round(w*width), "h": round(h*height)})
    if not tracks: raise ValueError("Reference analysis has no usable on-screen text tracks")
    events=[]
    def event(layer,track,tags,text):
        events.append(f"Dialogue: {layer},{_time(track['start_ms'])},{_time(track['end_ms'])},Default,,0,0,0,,{{{tags}}}{text}")
    stroke = max(0.5, config["outline_width"] * width / 1080)
    anchor=next((t for t in tracks if t['id']==config['callout_anchor_id']),None)
    if anchor:
        for t in tracks:
            if t['id'] not in config['callout_target_ids']:continue
            line=dict(t,start_ms=max(t['start_ms'],anchor['start_ms']),end_ms=min(t['end_ms'],anchor['end_ms']))
            if line['end_ms']<=line['start_ms']:continue
            x1,y1=anchor['x']+anchor['w'],anchor['y']+anchor['h']//2
            x2,y2=max(0,t['x']-round(width*.018)),t['y']+t['h']//2
            event(0,line,f"\\an7\\pos(0,0)\\p1\\c{accent}\\3c{accent}\\bord{max(1,width/720):.2f}\\shad0",f"m {x1} {y1} l {x2} {y2}")
    for t in tracks:
        boxed=t['id'] in config['boxed_track_ids']; colored=t['id'] in config['accent_track_ids']
        fill=accent if colored else "&H00FFFFFF"
        edge="&H00FFFFFF" if colored else outline
        size=max(12,round(t['h']*config['font_scale']))
        align=5 if boxed else 7
        x=t['x']+t['w']//2 if boxed else t['x'];y=t['y']+t['h']//2 if boxed else t['y']
        if boxed:
            w,h=t['w'],t['h'];r=min(round(width*.012),h//3)
            shape=f"m {r} 0 l {w-r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h-r} b {w} {h} {w} {h} {w-r} {h} l {r} {h} b 0 {h} 0 {h} 0 {h-r} l 0 {r} b 0 0 0 0 {r} 0"
            event(1,t,f"\\an7\\pos({t['x']},{t['y']})\\p1\\c&H00FFFFFF\\3c{accent}\\bord{stroke:.2f}\\shad0",shape)
            size=round(t['h']*.72)
        event(2,t,f"\\an{align}\\pos({x},{y})\\fn{font}\\fs{size}\\b1\\c{fill}\\3c{edge}\\bord{stroke:.2f}\\shad0",_text(t['text']))
    header=f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},54,&H00FFFFFF,&H00FFFFFF,&H00606060,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header+"\n".join(events)+"\n",tracks


class ReferenceCaptionsExecutor:
    @staticmethod
    def runtime_revision(definition, resolved_config): return _runtime_revision(definition)

    def execute(self, context: NodeExecutionContext, config: dict[str,Any], inputs: list[dict[str,Any]]) -> NodeExecutionResult:
        store=context.require_artifact_store();artifacts=store.read_inputs(inputs)
        videos=[a for a in artifacts if a.type in {'Video','FinalVideo'}]
        analyses=[a for a in artifacts if a.type=='ReferenceAnalysis']
        if len(videos)!=1 or len(analyses)!=1:raise ValueError('One video and one ReferenceAnalysis are required')
        video,analysis=videos[0],analyses[0]
        with tempfile.TemporaryDirectory(prefix='frameflow-reference-captions-') as temp:
            folder=Path(temp);source=write_media_artifact(folder,video,0)
            probe=probe_media(source);stream=video_stream(probe);duration_ms=round(media_duration_seconds(probe)*1000)
            ass,tracks=reference_tracks_ass(json.loads(analysis.data),config,int(stream['width']),int(stream['height']),duration_ms)
            caption=folder/'captions.ass';caption.write_text(ass,encoding='utf-8');output=folder/'captioned.mp4'
            context.report_progress(25,'Rendering the original timed text layer')
            run_media_command(['ffmpeg','-v','error','-y','-i',str(source),'-vf',f'ass={caption}',
                               '-map','0:v:0','-map','0:a?','-c:v','libx264','-preset','veryfast','-crf','18',
                               '-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',str(output)],timeout=300)
            roles={video.id:'source_video',analysis.id:'reference_text_tracks'}
            artifact=store.create(NodeArtifactWrite(artifact_type='Video',schema_id=context.definition.artifact_contract.schema_id,
                content=output.read_bytes(),content_type='video/mp4',filename='reference-captioned.mp4',input_artifact_ids=[video.id,analysis.id],input_artifact_roles=roles,
                metadata={'source':'node_executor_registry','immutable':True,'experiment_id':context.experiment_id,'request_hash':context.request_hash,
                          'execution_mode':_runtime_revision(context.definition),'definition_digest':context.definition.definition_digest,
                          'normalized_config':config,'duration_ms':duration_ms,'text_tracks':tracks,'ffmpeg_version':_ffmpeg_version(),
                          'filename':'reference-captioned.mp4','provider':'local','model_alias':context.model_alias,
                          'output_role':context.definition.artifact_contract.output_role}))
            store.flush()
            return NodeExecutionResult(output={'kind':'video','title':'Reference captions restored','url':store.content_url(artifact.id),'mimeType':'video/mp4'},
                output_artifact_ids=[artifact.id],provider_request_id='local_'+context.request_hash[:20],cost_usd=0,
                metadata={'artifact_type':'Video','schema_id':context.definition.artifact_contract.schema_id,'input_artifact_ids':[video.id,analysis.id],'lineage_roles':roles,'retryable':False})
