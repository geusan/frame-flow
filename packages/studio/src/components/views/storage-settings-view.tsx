"use client";
import { useStudioRuntime } from "../../runtime/studio-runtime";


import { useEffect, useState } from "react";
import { Database, RefreshCw, Save } from "lucide-react";
import { SettingsView } from "./settings-view";
import { PageHeader } from "../shared/page-header";
import { Button } from "../ui/button";
import { Card } from "../ui/card";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { NativeSelect } from "../ui/native-select";
import { type StorageConfiguration, type StorageMigrationPlan, type StorageProfile } from "../../lib/api";

const names: Record<string,string> = { minio: "MinIO / 로컬", r2: "Cloudflare R2", s3: "AWS S3" };
const defaults = (provider = "minio"): Record<string,string> => ({
  provider, name: names[provider], region: provider === "r2" ? "auto" : "us-east-1",
  endpoint_url: provider === "minio" ? "http://minio:9000" : "",
  public_endpoint_url: provider === "minio" ? "http://localhost:9000" : "",
  account_id: "", access_key: "", secret_key: "", session_token: "", auth_mode: "access_key",
  reference_bucket: "project-reference-private", formats_bucket: "project-derived-formats",
  generation_bucket: "project-generation-assets", renders_bucket: "project-final-renders",
  addressing_style: provider === "s3" ? "auto" : "path", signed_url_ttl_seconds: "900",
});

export function StorageSettingsView() {
  const { frameflowApi } = useStudioRuntime();
  const [state,setState]=useState<StorageConfiguration|null>(null);
  const [selected,setSelected]=useState("");
  const [draft,setDraft]=useState(defaults());
  const [busy,setBusy]=useState(false);
  const [legacyAvailable,setLegacyAvailable]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const [plan,setPlan]=useState<StorageMigrationPlan|null>(null);
  const profile=state?.profiles.find(p=>p.id===selected);
  const active=state?.profiles.find(p=>p.id===state.active_profile_id);
  const baseline=defaults(profile?.provider);
  if(profile) Object.keys(baseline).forEach(k=>{if(k in profile && !["access_key","secret_key","session_token"].includes(k)) baseline[k]=String(profile[k as keyof StorageProfile]??"");});
  const unsaved=Boolean(selected) && Object.keys(draft).some(k=>draft[k]!==baseline[k]);
  function choose(p?: StorageProfile) {
    setSelected(p?.id??""); setPlan(null); setError(""); setMessage("");
    const next=defaults(p?.provider);
    if(p) Object.keys(next).forEach(k=>{if(k in p && !["access_key","secret_key","session_token"].includes(k)) next[k]=String(p[k as keyof StorageProfile]??"");});
    setDraft(next);
  }
  useEffect(()=>{frameflowApi.storageSettings().then(data=>{setState(data);choose(data.profiles.find(p=>p.id===data.active_profile_id));}).catch(e=>setError(String(e)));},[frameflowApi]);
  useEffect(()=>{
    let active=true;
    const load=()=>{void frameflowApi.listProviderSettings().then(providers=>{
      const old=providers.find(p=>p.provider==="r2");
      if(active)setLegacyAvailable(Boolean(old?.configured || old?.fields.some(f=>f.secret && f.has_value)));
    }).catch(()=>{});};
    load();window.addEventListener("frameflow:provider-settings-changed",load);
    return ()=>{active=false;window.removeEventListener("frameflow:provider-settings-changed",load);};
  },[frameflowApi]);
  async function run(action:()=>Promise<void>) {
    setBusy(true);setError("");setMessage("");
    try { await action(); } catch(e) { setError(e instanceof Error?e.message:String(e)); } finally { setBusy(false); }
  }
  const change=(key:string,value:string)=>{ setPlan(null);setDraft(d=>({...d,[key]:value})); };
  function field(key:string,label:string,secret=false,placeholder="") {
    return <Label className="grid gap-2" key={key} htmlFor={`storage-${key}`}><span>{label}</span><Input id={`storage-${key}`} type={secret?"password":"text"} autoComplete="off" value={draft[key]??""} disabled={busy} placeholder={placeholder || (secret && profile ? "저장된 값 유지 · 변경할 때만 입력" : "")} onChange={e=>change(key,e.target.value)} /></Label>;
  }
  return <div className="view-page settings-page">
    <PageHeader title="File storage" description="파일 저장소와 인증 정보를 이곳에서 관리합니다. 새 파일은 선택한 저장소에 저장하고, 기존 파일은 원래 연결로 계속 엽니다." />
    <Card className="p-5 mb-4"><p className="flex gap-2 items-center"><Database size={18}/>현재 저장소: <strong>{active ? `${active.name} · ${names[active.provider]}` : `환경변수 · ${names[state?.environment_provider??""]??state?.environment_provider??"불러오는 중"}`}</strong></p></Card>
    <Card className="p-5 grid gap-5">
      <Label className="grid gap-2" htmlFor="storage-connection"><span>저장된 연결</span><NativeSelect id="storage-connection" disabled={busy} value={selected} onChange={e=>choose(state?.profiles.find(p=>p.id===e.target.value))}><option value="">새 연결 만들기</option>{state?.profiles.map(p=><option key={p.id} value={p.id}>{p.name} · {names[p.provider]}{p.id===state.active_profile_id?" · 사용 중":""}</option>)}</NativeSelect></Label>
      <div className="grid gap-4 md:grid-cols-2">
        <Label className="grid gap-2" htmlFor="storage-provider"><span>Storage provider</span><NativeSelect id="storage-provider" disabled={busy || Boolean(selected)} value={draft.provider} onChange={e=>setDraft(defaults(e.target.value))}>{Object.entries(names).map(([key,name])=><option key={key} value={key}>{name}</option>)}</NativeSelect></Label>
        {field("name","연결 이름")}
        {draft.provider==="r2" && <><Label className="grid gap-2" htmlFor="storage-r2-auth"><span>R2 인증</span><NativeSelect id="storage-r2-auth" disabled={busy} value={draft.auth_mode} onChange={e=>change("auth_mode",e.target.value)}><option value="access_key">Access key 직접 입력</option>{legacyAvailable && <option value="provider_r2">이전 R2 인증 가져오기</option>}</NativeSelect></Label>{field("account_id","Cloudflare Account ID (이전 인증을 가져오면 생략 가능)")}</>}
        {field("region","Region")}
        {field("endpoint_url",draft.provider==="s3"?"S3 endpoint (AWS 기본 주소는 비워 두세요)":draft.provider==="r2"?"S3 endpoint (R2 기본 주소는 Account ID로 생성)":"MinIO 서버 endpoint")}
        {field("public_endpoint_url","브라우저용 endpoint (같으면 비워 두세요)")}
        {draft.provider==="s3" && <Label className="grid gap-2" htmlFor="storage-auth"><span>인증 방식</span><NativeSelect id="storage-auth" disabled={busy} value={draft.auth_mode} onChange={e=>change("auth_mode",e.target.value)}><option value="access_key">Access key</option><option value="iam_role">실행 서버의 IAM role / AWS credential chain</option></NativeSelect></Label>}
        {draft.auth_mode==="access_key" && <>{field("access_key","Access Key ID",true)}{field("secret_key","Secret Access Key",true)}{draft.provider==="s3" && field("session_token","Session token (임시 자격증명 사용 시)",true)}</>}
      </div>
      {draft.auth_mode==="provider_r2" && <p>이전 R2 키를 복사해 새 저장소 연결로 저장합니다. 이후 인증 변경은 이 화면의 저장된 연결에서 관리합니다.</p>}
      <p>미리 생성한 비공개 버킷을 지정하세요. 분석 원본은 생성 파일과 별도 버킷으로 보관합니다.</p>
      <div className="grid gap-4 md:grid-cols-2">{field("reference_bucket","분석 원본 버킷")}{field("formats_bucket","포맷·대본 버킷")}{field("generation_bucket","생성 에셋 버킷")}{field("renders_bucket","완성 영상 버킷")}{field("signed_url_ttl_seconds","서명 URL 유효 시간 (초)")}</div>
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy} onClick={()=>void run(async()=>{const saved=await frameflowApi.saveStorage({...draft,signed_url_ttl_seconds:Number(draft.signed_url_ttl_seconds)},selected||undefined);setState(await frameflowApi.storageSettings());choose(saved);setMessage("연결을 저장했습니다. 연결 확인 후 기본 저장소로 선택하세요.");})}><Save size={14}/>연결 저장</Button>
        <Button variant="secondary" disabled={busy||!selected||unsaved} onClick={()=>void run(async()=>{await frameflowApi.testStorage(selected);setMessage("모든 버킷의 업로드·다운로드 검증이 완료됐습니다.");})}>연결 확인</Button>
        <Button variant="secondary" disabled={busy||!selected||unsaved||selected===state?.active_profile_id} onClick={()=>void run(async()=>{setState(await frameflowApi.activateStorage(selected));setMessage("새 파일의 기본 저장소를 변경했습니다. 기존 파일은 계속 원래 위치에서 읽습니다.");})}>이 저장소 사용</Button>
        {selected && draft.auth_mode==="access_key" && <Button variant="secondary" disabled={busy||!draft.access_key||!draft.secret_key} onClick={()=>void run(async()=>{const p=await frameflowApi.rotateStorageCredentials(selected,{access_key:draft.access_key,secret_key:draft.secret_key,session_token:draft.session_token||""});choose(p);setState(await frameflowApi.storageSettings());setMessage("기존 연결의 자격증명을 갱신했습니다.");})}>자격증명 갱신</Button>}
      </div>
      {unsaved && <p>변경한 연결 정보를 먼저 저장하세요.</p>}
      <small>버킷·주소를 변경해 저장하면 새 연결로 보존됩니다. 키만 교체할 때는 ‘자격증명 갱신’을 사용하세요.</small>
    </Card>
    <Card className="p-5 mt-4 grid gap-3">
      <h3>기존 파일 이전</h3><p>선택한 연결로 파일을 복사하고 SHA-256과 크기를 확인한 후 저장 위치를 전환합니다. 원본 파일은 보존됩니다.</p>
      <Button variant="secondary" disabled={busy||!selected||unsaved} onClick={()=>void run(async()=>{setPlan(await frameflowApi.storageMigrationPlan(selected));})}><RefreshCw size={14}/>이전 대상 확인</Button>
      {plan && <><p>{plan.count.toLocaleString()}개 · {(plan.size_bytes/1024**3).toFixed(2)} GiB</p><Button disabled={busy||unsaved||plan.count===0} onClick={()=>void run(async()=>{
        let completed=0;
        for(let i=0;i<plan.artifact_ids.length;i+=5){
          const batch=await frameflowApi.migrateStorage(plan.target_profile_id,plan.artifact_ids.slice(i,i+5));
          const failed=batch.results.find(r=>r.status==="failed");if(failed)throw new Error(`${failed.artifact_id}: ${failed.error}`);
          completed+=batch.results.length;setMessage(`${completed} / ${plan.count}개 복사·검증 완료`);
        }
        setPlan(await frameflowApi.storageMigrationPlan(plan.target_profile_id));setMessage("파일 이전이 완료됐습니다. 원본은 보존되어 있습니다.");
      })}>복사·검증 후 이전</Button></>}
    </Card>
    {legacyAvailable && <details className="mt-5 rounded-lg border border-[var(--line)] p-4">
      <summary className="cursor-pointer">이전 버전 호환 설정</summary>
      <p className="my-3">이전에 저장한 LoRA 학습용 R2 연결입니다. 현재 파일 저장소를 바꾸는 설정은 아닙니다. 기존 인증을 가져오려면 위에서 Cloudflare R2 → 이전 R2 인증 가져오기를 선택하세요.</p>
      <SettingsView legacyStorage />
    </details>}
    {error && <p role="alert" className="provider-save-message error">{error}</p>}
    {message && <p role="status" className="provider-save-message success">{message}</p>}
    {busy && <p>처리 중입니다. 이전 중 화면을 닫아도 완료된 파일은 보존되며 다시 실행하면 이어집니다.</p>}
  </div>;
}
