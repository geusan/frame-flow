"use client";

import { useEffect, useState } from "react";
import { Copy, Download, ImagePlus, Pause, Play, Save, ScanFace, Trash2 } from "lucide-react";
import { freshExpressions, imageDataUrl, parseExpressions, portableExpressions, readExpressions, saveExpressions, withFaceRigSources, type ExpressionImage, type ExpressionLibrary } from "./expression-library";
import styles from "./expression-panel.module.css";

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob), link = document.createElement("a"); link.href=url; link.download=name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function ExpressionPanel({ ready, apply, focus, onLibraryChange, incomingLibrary, rigAuthoring=false }: {
  ready: boolean; apply: (entry: ExpressionImage, strength: number, duration: number) => Promise<void>; focus: (enabled: boolean) => void;
  onLibraryChange?: (library:ExpressionLibrary)=>void; incomingLibrary?:ExpressionLibrary|null; rigAuthoring?:boolean;
}) {
  const [library, setLibrary] = useState<ExpressionLibrary>(freshExpressions);
  const [message, setMessage] = useState("같은 캐릭터의 표정을 골라 보세요."), [dirty,setDirty] = useState(false);
  const [cycling, setCycling] = useState(false), [closeup,setCloseup] = useState(false), [busy,setBusy] = useState(false), [loaded,setLoaded] = useState(false);
  const selected = library.entries.find((entry) => entry.id === library.selected)!;
  useEffect(()=>{if(incomingLibrary)void Promise.resolve().then(()=>{setLibrary(incomingLibrary);setDirty(true);});},[incomingLibrary]);
  useEffect(()=>{if(loaded)onLibraryChange?.(library);},[library,loaded,onLibraryChange]);
  useEffect(() => {
    let active=true;
    readExpressions().then((saved) => { if (active && saved) { setLibrary(rigAuthoring?withFaceRigSources(saved):saved); setMessage("저장한 표정 모음을 불러왔습니다."); } })
      .catch(() => { if (active) setMessage("저장된 표정을 읽지 못해 기본 모음을 열었습니다."); })
      .finally(() => { if (active) setLoaded(true); });
    return () => { active=false; };
  }, [rigAuthoring]);
  useEffect(() => {
    if (!ready || !loaded) return;
    let active=true;
    void apply(selected,library.strength,library.transition_ms).catch(() => { if (active) setMessage("표정 이미지를 표시하지 못했습니다. 다른 표정이나 이미지를 선택해 주세요."); });
    return () => { active=false; };
  }, [ready,loaded,selected,library.strength,library.transition_ms,apply]);
  useEffect(() => {
    if (!cycling || !ready) return;
    const timer=setInterval(() => { setLibrary((current) => ({ ...current, selected: current.entries[(current.entries.findIndex((e) => e.id===current.selected)+1)%current.entries.length].id })); setDirty(true); }, 3000);
    const hidden=() => { if(document.hidden)setCycling(false); };
    document.addEventListener('visibilitychange',hidden);
    return () => { clearInterval(timer);document.removeEventListener('visibilitychange',hidden); };
  }, [cycling,ready]);
  const change = (next: ExpressionLibrary) => { setLibrary(next); setDirty(true); };
  const update = (patch: Partial<ExpressionImage>) => change({ ...library, entries: library.entries.map((entry) => entry.id===selected.id ? { ...entry,...patch } : entry) });
  const addImage = async (file: File, replace=false) => {
    setCycling(false); setBusy(true);
    try {
      if (!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size>5_000_000) throw new Error("5MB 이하의 PNG·JPG·WebP 이미지를 선택하세요.");
      if (!replace && library.entries.length>=24) throw new Error("표정은 원본을 포함해 최대 24개까지 추가할 수 있습니다.");
      const data=await imageDataUrl(file), image=new Image(); image.src=data; await image.decode();
      if (image.width>2048 || image.height>2048 || image.width<64 || image.height<64) throw new Error("이미지의 가로·세로는 각각 64~2048px이어야 합니다.");
      const layout=Math.abs(image.width/image.height-2/3)<.05 ? 'full' : 'face';
      const entry: ExpressionImage={ id: `expr_${crypto.randomUUID()}`, name: file.name.replace(/\.[^.]+$/,'').slice(0,40) || "새 표정", image:data, layout, offsetX:0, offsetY:0, scale:1 };
      const next = replace ? { ...library,entries:library.entries.map((old) => old.id===selected.id ? { ...entry,id:old.id,name:old.name } : old) } : { ...library, selected:entry.id,entries:[...library.entries,entry] };
      change(parseExpressions(next)); setMessage("이미지를 추가했습니다. 얼굴 위치를 확인하고 모음을 저장하세요.");
    } catch(error) { setMessage(error instanceof Error ? error.message : "이미지를 추가하지 못했습니다."); }
    finally { setBusy(false); }
  };
  return <section className={styles.panel} aria-label="2D 표정 라이브러리">
    <div className={styles.title}><span>04</span><h2>{rigAuthoring ? "표정 제작 자료" : "표정 라이브러리"}</h2><button type="button" disabled={!ready} aria-pressed={closeup} onClick={() => { setCloseup(!closeup);focus(!closeup); }}><ScanFace size={14} />{closeup ? "전신 보기" : "얼굴 확대"}</button></div>
    <p>{rigAuthoring ? "얼굴 리그의 목표 모양을 정하는 이미지 자료입니다. 적용 결과는 위 얼굴 리그에서 테스트하세요." : "원본 그림을 바탕으로 만든 표정입니다. 몸 동작을 유지하며 얼굴만 바뀝니다."}</p>
    <div className={styles.grid}>{library.entries.map((entry) => <button type="button" key={entry.id} className={entry.id===selected.id ? styles.selected : ""} aria-pressed={entry.id===selected.id} aria-label={`표정 ${entry.name}`} disabled={!ready || !loaded || busy} onClick={() => { setCycling(false); change({ ...library,selected:entry.id }); }}>
      <span className={`${styles.thumbnail} ${entry.layout==='face' ? styles.portrait : ''}`} style={{ backgroundImage:`url("${entry.image}")` }} /><span>{entry.name}</span>
    </button>)}</div>
    <div className={styles.actions}>{!rigAuthoring && <button type="button" disabled={!ready || !loaded || busy} aria-pressed={cycling} onClick={() => setCycling(!cycling)}>{cycling ? <Pause size={14}/> : <Play size={14}/>} {cycling ? "순환 중지" : "표정 순환"}</button>}<label className={styles.file}><ImagePlus size={14}/> 이미지 추가<input aria-label="표정 이미지 추가" type="file" accept="image/png,image/jpeg,image/webp" disabled={busy || !loaded} onChange={(e) => { const file=e.target.files?.[0]; e.target.value=''; if(file) void addImage(file); }}/></label></div>
    <details className={styles.editor}>
      <summary>선택한 표정 편집 · {selected.name}</summary>
      <label>표정 이름<input aria-label="표정 이름" value={selected.name} disabled={selected.id==='neutral' || busy} maxLength={40} onChange={(e) => update({ name:e.target.value })}/></label>
      <div className={styles.actions}><button type="button" disabled={busy || library.entries.length>=24} onClick={() => { const entry={ ...selected,id:`expr_${crypto.randomUUID()}`,name:`${selected.name.slice(0,35)} 복사` };change({ ...library,selected:entry.id,entries:[...library.entries,entry] });setCycling(false); }}><Copy size={13}/> 복제</button><button type="button" disabled={busy || selected.id==='neutral'} onClick={() => { change({ ...library,selected:'neutral',entries:library.entries.filter((e) => e.id!==selected.id) });setCycling(false); }}><Trash2 size={13}/> 삭제</button></div>
      {selected.id!=='neutral' && <>
        <label className={styles.file}>선택 이미지 교체<input aria-label="선택 표정 이미지 교체" type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={(e) => { const file=e.target.files?.[0];e.target.value='';if(file)void addImage(file,true); }}/></label>
        <label>이미지 구성<select aria-label="표정 이미지 구성" value={selected.layout} onChange={(e) => update({layout:e.target.value as 'full'|'face'})}><option value="full">원본과 같은 전신 이미지</option><option value="face">얼굴 클로즈업</option></select></label>
        {([['offsetX','얼굴 가로 위치',-100,100,1],['offsetY','얼굴 세로 위치',-100,100,1],['scale','얼굴 이미지 크기',.5,2,.01]] as const).map(([key,label,min,max,step]) => <label key={key}>{label}<span>{selected[key].toFixed(key==='scale'?2:0)}</span><input aria-label={label} type="range" min={min} max={max} step={step} value={selected[key]} onChange={(e) => update({[key]:Number(e.target.value)})}/></label>)}
        <button type="button" onClick={() => update({offsetX:0,offsetY:0,scale:1})}>정렬 초기화</button>
      </>}
      <label>원본과 겹쳐보기<span>{Math.round(library.strength*100)}%</span><input aria-label="표정 이미지 적용 비율" type="range" min={0} max={1} step={.05} value={library.strength} onChange={(e) => change({...library,strength:Number(e.target.value)})}/></label>
      <label>표정 전환 시간<span>{library.transition_ms} ms</span><input aria-label="표정 전환 시간" type="range" min={0} max={600} step={20} value={library.transition_ms} onChange={(e) => change({...library,transition_ms:Number(e.target.value)})}/></label>
    </details>
    <div className={styles.actions}><button type="button" disabled={busy || !loaded} onClick={async () => { setBusy(true);try { await saveExpressions(library);setDirty(false);setMessage("표정 모음과 이미지를 이 브라우저에 저장했습니다."); }catch(error){setMessage(error instanceof Error ? error.message : "저장 공간이 부족합니다. 모음을 내보내 주세요.");}finally{setBusy(false);} }}><Save size={14}/> 모음 저장{dirty ? ' *' : ''}</button><button type="button" disabled={busy || !loaded} onClick={async () => {setBusy(true);try{const portable=await portableExpressions(library);download(new Blob([JSON.stringify(portable)],{type:'application/json'}),'cat-2d-expressions.json');setMessage("이미지가 포함된 표정 모음을 내보냈습니다.");}catch{setMessage("표정 모음을 내보내지 못했습니다.");}finally{setBusy(false);}}}><Download size={14}/> 모음 내보내기</button></div>
    <label className={styles.import}>표정 모음 불러오기<input aria-label="표정 모음 불러오기" type="file" accept=".json" disabled={busy || !loaded} onChange={async (e) => {const file=e.target.files?.[0];e.target.value='';if(!file)return;setBusy(true);try{if(file.size>40_000_000)throw new Error("표정 모음은 40MB 이하여야 합니다.");change(parseExpressions(JSON.parse(await file.text())));setCycling(false);setMessage("표정 모음을 불러왔습니다. 확인 후 저장하세요.");}catch(error){setMessage(error instanceof Error ? error.message : "표정 모음 오류");}finally{setBusy(false);}}}/></label>
    <button type="button" className={styles.restore} disabled={busy} onClick={() => {change(freshExpressions());setCycling(false);setMessage("기본 표정 모음으로 되돌렸습니다. 저장 전까지 기존 저장본은 유지됩니다.");}}>기본 표정 모음 복원</button>
    <p>{rigAuthoring ? "웹캠 구동 중에는 자료 카드를 눌러도 얼굴 리그가 계속 동작합니다. 정지 이미지를 확인하려면 ‘제작 자료 보기’를 선택하세요." : "표정 이미지를 선택하면 눈·입 모양이 고정됩니다. 기존 깜빡임·입 벌리기를 쓰려면 ‘원본’을 선택하세요. 새 이미지의 위치는 편집에서 맞출 수 있습니다."}</p>
    <p className={styles.message} role="status">{busy ? "표정 모음을 처리하고 있습니다…" : message}</p>
  </section>;
}
