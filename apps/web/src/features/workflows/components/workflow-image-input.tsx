"use client";

import { useRef, useState, type ClipboardEvent, type DragEvent } from "react";
import Image from "next/image";
import { ImagePlus, Link as LinkIcon, LoaderCircle, Search, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { frameflowApi, type ArtifactListItem } from "@/lib/api";
import { httpImageUrl, uploadedAsset } from "../run-model";

export function WorkflowImageInput({ label, value, assets, disabled, onSelect, onAsset, onBusy }: {
  label: string; value: unknown; assets: ArtifactListItem[]; disabled: boolean;
  onSelect: (id: string) => void; onAsset: (asset: ArtifactListItem) => void; onBusy: (busy: boolean) => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const requestBusy = useRef(false);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [library, setLibrary] = useState(false);
  const [query, setQuery] = useState("");
  const selected = assets.find((asset) => asset.id === value);

  const ingest = async (source: File | string) => {
    if (disabled || requestBusy.current) return;
    setError(null);
    const remote = typeof source === "string" ? httpImageUrl(source) : null;
    if (typeof source === "string" && !remote) { setError("http 또는 https로 시작하는 이미지 주소를 넣어 주세요."); return; }
    if (source instanceof File && !source.type.startsWith("image/")) { setError("이미지 파일을 넣어 주세요."); return; }
    requestBusy.current = true; setBusy(true); onBusy(true);
    try {
      const artifact = typeof source === "string" ? await frameflowApi.importArtifactUrl(remote!) : await frameflowApi.uploadArtifact(source);
      if (artifact.type !== "Image") throw new Error("이미지 파일의 직접 URL을 넣어 주세요. 웹페이지나 영상 주소는 사용할 수 없습니다.");
      const asset = uploadedAsset(artifact);
      onAsset(asset); onSelect(asset.id); setUrl("");
      window.dispatchEvent(new Event("frameflow:workspace-changed"));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "이미지를 불러오지 못했습니다. 다시 시도해 주세요."); }
    finally { requestBusy.current = false; setBusy(false); onBusy(false); }
  };
  const paste = (event: ClipboardEvent) => {
    if (disabled || busy) return;
    const file = Array.from(event.clipboardData.items).find((item) => item.kind === "file" && item.type.startsWith("image/"))?.getAsFile();
    const text = event.clipboardData.getData("text/plain").trim();
    const html = event.clipboardData.getData("text/html");
    const pastedUrl = httpImageUrl(text) ?? (html ? httpImageUrl(new DOMParser().parseFromString(html, "text/html").querySelector("img")?.getAttribute("src") ?? "") : null);
    if (file || pastedUrl) { event.preventDefault(); void ingest(file ?? pastedUrl!); }
  };
  const drop = (event: DragEvent) => {
    event.preventDefault(); setDragging(false);
    const file = event.dataTransfer.files[0];
    const text = event.dataTransfer.getData("text/uri-list").split("\n").find((line) => line.trim() && !line.startsWith("#")) || event.dataTransfer.getData("text/plain");
    if (file || text) void ingest(file ?? text);
  };
  return <div className="workflow-image-input" onPaste={paste}>
    <div className={`workflow-dropzone ${dragging ? "is-dragging" : ""} ${selected ? "has-image" : ""}`} tabIndex={disabled ? -1 : 0} role="group" aria-label={`${label} 붙여넣기 영역`} aria-busy={busy}
      onDragOver={(event) => { event.preventDefault(); if (!disabled && !busy) setDragging(true); }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }} onDrop={drop}>
      {selected ? <>
        <Image src={selected.url} alt={`${label} 미리보기: ${selected.filename}`} fill unoptimized className="workflow-contained-image" />
        <Button className="workflow-image-remove" variant="secondary" size="icon-sm" aria-label={`${label} 선택 해제`} disabled={disabled || busy} onClick={() => { onSelect(""); setError(null); }}><X size={14} /></Button>
      </> : <div className="workflow-dropzone-copy"><ImagePlus size={30} /><strong>사진을 여기에 붙여넣으세요</strong><span>이미지 복사 후 ⌘V / Ctrl+V<br />또는 파일을 끌어 놓으세요</span></div>}
      {busy && <div className="workflow-image-loading" role="status"><LoaderCircle className="spin" size={20} />이미지 불러오는 중…</div>}
    </div>
    {selected && <span className="workflow-file-name" title={selected.filename}>{selected.filename}</span>}
    <input ref={fileInput} type="file" accept="image/*" className="sr-only" tabIndex={-1} aria-label={`${label} 파일 선택`} disabled={disabled || busy} onChange={(event) => { const file = event.currentTarget.files?.[0]; event.currentTarget.value = ""; if (file) void ingest(file); }} />
    <div className="workflow-input-actions"><Button variant="secondary" disabled={disabled || busy} onClick={() => fileInput.current?.click()}><Upload size={14} />파일 업로드</Button><Button variant="secondary" disabled={disabled || busy} onClick={() => setLibrary(true)}><Search size={14} />보관함</Button></div>
    <form className="workflow-url-input" onSubmit={(event) => { event.preventDefault(); void ingest(url); }}><LinkIcon size={15} aria-hidden="true" /><Input aria-label={`${label} URL`} type="url" placeholder="이미지 URL 붙여넣기" value={url} disabled={disabled || busy} onChange={(event) => setUrl(event.target.value)} /><Button type="submit" variant="ghost" size="sm" disabled={disabled || busy || !url.trim()}>불러오기</Button></form>
    {error && <p className="workflow-inline-error" role="alert">{error}</p>}
    <Dialog open={library} onOpenChange={setLibrary}><DialogContent className="workflow-asset-dialog" showCloseButton><DialogTitle>이미지 보관함</DialogTitle><DialogDescription>이 실행에 사용할 이미지를 선택하세요.</DialogDescription><Input aria-label="보관함 이미지 검색" placeholder="파일명으로 검색" value={query} onChange={(event) => setQuery(event.target.value)} />
      <div className="workflow-asset-grid">{assets.filter((asset) => asset.type === "Image" && `${asset.filename} ${asset.id}`.toLowerCase().includes(query.toLowerCase())).map((asset) => <button type="button" key={asset.id} aria-label={`${asset.filename} · ${asset.id.slice(-6)}`} aria-pressed={value === asset.id} onClick={() => { onSelect(asset.id); setError(null); setLibrary(false); }}><span><Image src={asset.url} alt="" fill unoptimized className="workflow-contained-image" /></span><small>{asset.filename}</small></button>)}</div>
    </DialogContent></Dialog>
  </div>;
}
