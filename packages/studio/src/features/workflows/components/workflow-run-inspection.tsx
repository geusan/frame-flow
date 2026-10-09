"use client";
import { useStudioRuntime } from "../../../runtime/studio-runtime";


import { useState } from "react";
import Image from "next/image";
import { ExternalLink, ImageOff } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../../../components/ui/dialog";
import { type ArtifactListItem, type CanvasRunRecord, type WorkflowVersionRecord } from "../../../lib/api";
import { runStatusLabel, workflowRunInputs } from "../run-model";
import { WorkflowRunResults } from "./workflow-run-results";

function InputImage({ url, label, onPreview }: { url: string; label: string; onPreview: () => void }) {
  const [failed, setFailed] = useState(false);
  return failed ? <div className="workflow-run-source-unavailable"><ImageOff size={24} /><span>원본 이미지를 불러오지 못했습니다.</span></div> :
    <button type="button" className="workflow-run-source-image" aria-label={`${label} 원본 크게 보기`} onClick={onPreview}>
      <Image src={url} alt={`${label} · 실행 시 입력한 원본`} fill unoptimized className="workflow-contained-image" onError={() => setFailed(true)} />
    </button>;
}

export function WorkflowRunInspection({ run, version, assets }: { run: CanvasRunRecord; version?: WorkflowVersionRecord; assets: ArtifactListItem[] }) {
  const { API_BASE } = useStudioRuntime();
  const [preview, setPreview] = useState<{ url: string; label: string }>();
  const inputs = workflowRunInputs(run, version, assets);
  return <section className="workflow-run-inspection" id={`workflow-run-${run.id}`} aria-label="선택한 실행의 원본과 결과">
    <header><h3>선택한 실행 · v{version?.version_number ?? "—"}</h3><p>{new Date(run.created_at).toLocaleString("ko-KR")} · {runStatusLabel(run.status)}</p></header>
    <div className="workflow-run-comparison">
      <section aria-label="실행 시 입력한 원본"><h4>실행 시 입력한 원본</h4><p className="workflow-input-help">이 실행에 저장된 입력입니다. 이미지를 누르면 크게 볼 수 있습니다.</p>
        <div className="workflow-run-inputs">{inputs.map((input) => {
          const url = input.artifactId ? `${API_BASE}/artifacts/${encodeURIComponent(input.artifactId)}/content` : undefined;
          return <figure className="workflow-run-source" key={input.key}>
            {url && input.artifactType === "Image" ? <InputImage key={url} url={url} label={input.label} onPreview={() => setPreview({ url, label: input.label })} /> :
              url && ["Video", "FinalVideo"].includes(input.artifactType ?? "") ? <video src={url} controls playsInline preload="metadata" /> :
              url && input.artifactType === "Audio" ? <audio src={url} controls preload="metadata" /> :
              <p className="workflow-output-text">{input.filename ?? (input.value == null ? "입력 없음" : String(input.value))}</p>}
            <figcaption><strong>{input.label}</strong>{url && <Button asChild variant="secondary" size="sm"><a href={url} target="_blank" rel="noreferrer"><ExternalLink size={13} />입력 원본 열기</a></Button>}</figcaption>
          </figure>;
        })}</div>
        {!inputs.length && <p className="workflow-empty-note">별도 입력 없이 실행했습니다.</p>}
      </section>
      <section aria-label="선택한 실행 결과"><h4>실행 결과</h4><WorkflowRunResults run={run} version={version} /></section>
    </div>
    <details className="workflow-run-details" open={run.status === "FAILED" || run.status === "WAITING_INPUT"}>
      <summary>단계별 실행 상태와 로그</summary>
      <ol className="workflow-node-progress">{run.node_runs.map((node) => {
        const ui = version?.graph.nodes.find((item) => item.id === node.canvas_node_id)?.ui as { label?: string } | undefined;
        return <li key={node.id}><div><strong>{ui?.label ?? node.node_key}</strong><span>{runStatusLabel(node.status)}</span></div>{node.error && <p className="workflow-inline-error">{node.error}</p>}{node.logs.length > 0 && <details><summary>실행 로그</summary><ul>{node.logs.map((log, index) => <li key={index}>{log}</li>)}</ul></details>}</li>;
      })}</ol>
    </details>
    <Dialog open={Boolean(preview)} onOpenChange={(open) => { if (!open) setPreview(undefined); }}><DialogContent className="workflow-reference-dialog" showCloseButton><DialogTitle>{preview?.label} · 입력 원본</DialogTitle><DialogDescription>선택한 실행에 사용한 원본 이미지입니다.</DialogDescription>{preview && <div className="workflow-reference-preview"><Image src={preview.url} alt={preview.label} fill unoptimized className="workflow-contained-image" /></div>}</DialogContent></Dialog>
  </section>;
}
