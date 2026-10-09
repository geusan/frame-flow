"use client";

import { Fragment, useState } from "react";
import { Check, Clock3, ListVideo, LoaderCircle, RefreshCw, RotateCcw, X } from "lucide-react";
import { Button } from "../../../components/ui/button";
import type { ArtifactListItem, CanvasRunRecord, WorkflowRunRecord, WorkflowVersionRecord } from "../../../lib/api";
import { isActiveRun, runStatusLabel } from "../run-model";
import { WorkflowRunInspection } from "./workflow-run-inspection";

export function WorkflowRunQueue({ runs, versions, assets, selectedId, detail, loading, error, canceling, submitting, onSelect, onCancel, onRepeat, onRefresh }: {
  runs: WorkflowRunRecord[]; versions: WorkflowVersionRecord[]; assets: ArtifactListItem[]; selectedId: string | null; detail?: CanvasRunRecord;
  loading: boolean; error: string | null; canceling: string | null; submitting: boolean;
  onSelect: (id: string) => void; onCancel: (id: string) => void; onRepeat: (id: string) => void; onRefresh: () => void;
}) {
  const [filter, setFilter] = useState("all");
  const activeCount = runs.filter((run) => isActiveRun(run.status)).length;
  const rows = runs.filter((run) => filter === "all" || (filter === "active" ? isActiveRun(run.status) : !isActiveRun(run.status)));
  const detailVersion = versions.find((version) => version.id === detail?.workflow_version_id);
  return <section className="workflow-queue" aria-label="실행 Queue">
    <header className="workflow-section-heading"><div><h2><ListVideo size={18} />실행 Queue <span>{activeCount ? `${activeCount}개 진행 중` : ""}</span></h2><p>실행 상태는 자동으로 갱신됩니다. 다음 사진을 넣어 새 실행을 추가할 수 있습니다.</p></div><Button variant="ghost" size="sm" onClick={onRefresh}><RefreshCw size={14} />새로고침</Button></header>
    <div className="workflow-queue-filters" role="group" aria-label="실행 상태 필터">{[["all", "전체", runs.length], ["active", "대기·진행", activeCount], ["finished", "종료", runs.length - activeCount]].map(([key, label, count]) => <button type="button" key={key} aria-pressed={filter === key} onClick={() => setFilter(String(key))}>{label} <span>{count}</span></button>)}</div>
    {error && <p className="workflow-inline-error" role="alert">{error}</p>}
    {loading && <p className="workflow-empty-note" role="status">실행 목록을 불러오는 중…</p>}
    {!loading && !rows.length && <div className="workflow-queue-empty"><Clock3 size={22} /><strong>{runs.length ? "이 상태의 실행이 없습니다." : "아직 실행한 작업이 없습니다."}</strong><p>위에서 사진을 넣고 Run을 누르면 여기에 추가됩니다.</p></div>}
    <div className="workflow-queue-list">{rows.map((run) => {
      const version = versions.find((item) => item.id === run.workflow_version_id);
      return <Fragment key={run.id}><article className={`workflow-queue-row ${selectedId === run.id ? "is-selected" : ""}`}>
        <button type="button" className="workflow-queue-select" aria-pressed={selectedId === run.id} aria-expanded={selectedId === run.id} aria-controls={selectedId === run.id ? `workflow-run-${run.id}` : undefined} aria-label={`${new Date(run.created_at).toLocaleTimeString("ko-KR")} 실행 상세 보기`} onClick={() => onSelect(run.id)}>
          <span className={`workflow-run-status status-${run.status.toLowerCase()}`}>{run.status === "SUCCEEDED" ? <Check size={14} /> : isActiveRun(run.status) ? <LoaderCircle size={14} className={run.status === "RUNNING" ? "spin" : ""} /> : null}{runStatusLabel(run.status)}</span>
          <span className="workflow-run-time"><strong>{new Date(run.created_at).toLocaleString("ko-KR")}</strong><small>v{version?.version_number ?? "—"} · {run.id.slice(-8)}</small></span>
          <span className="workflow-queue-progress"><progress value={run.progress} max={100} aria-label="실행 진행률" /><small>{run.nodes_done}/{run.nodes_total} 단계 · {Math.round(run.progress)}%</small></span>
        </button>
        <div className="workflow-queue-actions">{isActiveRun(run.status) ? <Button variant="secondary" size="sm" disabled={canceling !== null} aria-label={`${run.id} 실행 취소`} onClick={() => onCancel(run.id)}>{canceling === run.id ? <LoaderCircle size={13} className="spin" /> : <X size={13} />}취소</Button> : <Button variant="secondary" size="sm" disabled={submitting} aria-label={`${run.id} 같은 입력으로 다시 실행`} onClick={() => onRepeat(run.id)}><RotateCcw size={13} />다시 실행</Button>}</div>
      </article>{selectedId === run.id && (detail?.id === run.id ? <WorkflowRunInspection key={detail.id} run={detail} version={detailVersion} assets={assets} /> : <p id={`workflow-run-${run.id}`} className="workflow-empty-note" role="status">실행 원본과 결과를 불러오는 중…</p>)}</Fragment>;
    })}</div>
  </section>;
}
