"use client";

import Image from "next/image";
import { Download, ImageIcon, LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { CanvasRunRecord, WorkflowVersionRecord } from "@/lib/api";
import { isActiveRun, runStatusLabel, workflowRunOutputs } from "../run-model";

export function WorkflowRunResults({ run, version }: { run?: CanvasRunRecord; version?: WorkflowVersionRecord }) {
  const outputs = workflowRunOutputs(run, version);
  const mainOutputs = outputs.some((item) => item.primary) ? outputs.filter((item) => item.primary) : outputs;
  const hasOutput = mainOutputs.some((item) => item.node?.status === "SUCCEEDED" && item.node.output.kind);
  return <div className="workflow-results">
    {run && <p className="workflow-result-caption">선택한 실행 · {new Date(run.created_at).toLocaleTimeString("ko-KR")} · v{version?.version_number ?? "—"}</p>}
    {!hasOutput && <div className="workflow-result-empty">
      {run && isActiveRun(run.status) ? <><LoaderCircle size={28} className="spin" /><strong>{runStatusLabel(run.status)}</strong><span>완성된 결과가 여기에 표시됩니다.</span></> : <><ImageIcon size={32} /><strong>{run ? runStatusLabel(run.status) : "어떤 결과가 나올까요?"}</strong><span>{run?.status === "FAILED" ? "아래 실행 목록에서 오류를 확인해 주세요." : "사진을 넣고 Run을 눌러 보세요."}</span></>}
    </div>}
    {outputs.filter((item) => item.node?.status === "SUCCEEDED").map(({ key, label, node, primary }) => {
      const output = node?.output;
      if (!output?.kind) return null;
      if (output.kind === "text" && !primary) return <details className="workflow-result-text" key={key}><summary>{label}</summary><p className="workflow-output-text">{output.text}</p></details>;
      return <figure className="workflow-result-item" key={key}>
        {output.kind === "image" && output.url && <div className="workflow-result-image"><Image src={output.url} alt={label} fill unoptimized className="workflow-contained-image" /></div>}
        {output.kind === "video" && output.url && <video src={output.url} controls playsInline preload="metadata" />}
        {output.kind === "audio" && output.url && <audio src={output.url} controls preload="metadata" />}
        {output.kind === "text" && <p className="workflow-output-text">{output.text}</p>}
        {output.kind === "json" && <p>{output.title || "구조화된 결과가 준비됐습니다."}</p>}
        <figcaption><span>{label}</span>{output.url && <Button asChild variant="secondary" size="sm"><a href={output.url} target="_blank" rel="noreferrer"><Download size={13} />결과 열기</a></Button>}</figcaption>
      </figure>;
    })}
  </div>;
}
