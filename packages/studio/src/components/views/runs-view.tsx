"use client";
import { useStudioRuntime } from "../../runtime/studio-runtime";


import { Fragment, useEffect, useMemo, useState } from "react";
import { CalendarDays, ChevronDown, CircleDollarSign, Clock3, Play, RefreshCw } from "lucide-react";
import { type WorkflowRunRecord } from "../../lib/api";
import type { NodeStatus } from "../../lib/types";
import { PageHeader } from "../shared/page-header";
import { SearchField } from "../shared/search-field";
import { NativeSelect } from "../ui/native-select";
import { Badge } from "../ui/badge";
import { Card } from "../ui/card";
import { StatusPill } from "../ui/status-pill";
import { Button } from "../ui/button";
import { CostValue } from "../shared/cost-value";
import { formatCostAmount } from "../../lib/cost";
import { RunCostDetails } from "./run-cost-details";

function formatDuration(durationMs?: number): string {
  if (!durationMs) return "Not recorded";
  if (durationMs < 1000) return `${durationMs}ms`;
  return `${Math.round(durationMs / 100) / 10}s`;
}

export function RunsView() {
  const { frameflowApi } = useStudioRuntime();
  const [runs, setRuns] = useState<WorkflowRunRecord[]>([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [expandedCost, setExpandedCost] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    let pending = false;
    const refresh = () => {
      if (pending) return;
      pending = true;
      void frameflowApi.listWorkflowRuns()
      .then((rows) => { if (active) { setRuns(rows); setError(null); } })
      .catch((loadError) => { if (active) setError(loadError instanceof Error ? loadError.message : "Run loading failed"); })
      .finally(() => { pending = false; if (active) setLoading(false); });
    };
    refresh();
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") refresh(); }, 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, [refreshKey, frameflowApi]);
  const summary = useMemo(() => {
    const terminal = runs.filter((run) => ["SUCCEEDED", "FAILED", "CANCELED"].includes(run.status));
    return {
      active: runs.filter((run) => ["READY", "QUEUED", "RUNNING", "WAITING_INPUT", "RETRY_WAIT"].includes(run.status)).length,
      spend: runs.reduce((total, run) => total + (run.cost_summary && run.cost_summary.status !== "legacy" ? Number(run.cost_summary.known_cost_usd) : 0), 0),
      unresolved: runs.filter((run) => !run.cost_summary || ["pending", "unreported", "partial", "legacy"].includes(run.cost_summary.status)).length,
      successRate: terminal.length ? terminal.filter((run) => run.status === "SUCCEEDED").length / terminal.length * 100 : 0,
      completedNodes: runs.reduce((total, run) => total + run.nodes_done, 0),
    };
  }, [runs]);
  const visibleRuns = useMemo(() => runs.filter((run) => `${run.name} ${run.id} ${run.run_type}`.toLowerCase().includes(query.toLowerCase()) && (statusFilter === "all" || run.status === statusFilter)), [query, runs, statusFilter]);
  return (
    <div className="view-page runs-page">
      <PageHeader title="Workflow runs" description="Workflow·Canvas·개별 실행의 사용량과 비용을 확인합니다. 비용은 10초마다 갱신됩니다." actions={<Button variant="secondary" onClick={() => setRefreshKey((value) => value + 1)}><RefreshCw size={14} /> Refresh</Button>} />
      <div className="run-summary-grid">
        <Card><span className="summary-icon purple"><Play size={16} /></span><span><small>Stored runs</small><strong>{runs.length}</strong><em>{summary.active} active</em></span></Card>
        <Card><span className="summary-icon blue"><Clock3 size={16} /></span><span><small>Completed nodes</small><strong>{summary.completedNodes}</strong><em>Persisted node results</em></span></Card>
        <Card><span className="summary-icon green"><CircleDollarSign size={16} /></span><span><small>확인된 비용 소계</small><strong>{formatCostAmount(summary.spend)}</strong><em>요금표 계산 포함 · {summary.unresolved}개 금액 확인 필요</em></span></Card>
        <Card><span className="summary-icon amber"><CalendarDays size={16} /></span><span><small>Success rate</small><strong>{summary.successRate.toFixed(1)}%</strong><em>Terminal runs only</em></span></Card>
      </div>
      <div className="mb-3.5 flex items-center gap-2">
        <SearchField className="min-w-[250px] max-w-[380px] flex-1" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search run or ID…" />
        <NativeSelect value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">All statuses</option><option value="RUNNING">Running</option><option value="WAITING_INPUT">Needs review</option><option value="FAILED">Failed</option><option value="SUCCEEDED">Succeeded</option><option value="CANCELED">Canceled</option></NativeSelect>
      </div>
      {error && <p className="experiment-history-state error">{error}</p>}
      {!error && loading && <p className="experiment-history-state">Loading persisted runs…</p>}
      {!error && !loading && !visibleRuns.length && <p className="experiment-history-state">저장된 실행이 없습니다.</p>}
      {!error && !loading && visibleRuns.length > 0 && <Card className="data-table-panel">
        <table className="data-table">
          <thead><tr><th>Run</th><th>Type</th><th>Status</th><th>Progress</th><th>Created</th><th>Recorded duration</th><th>Attempts</th><th>Cost</th></tr></thead>
          <tbody>{visibleRuns.map((run) => <Fragment key={run.id}><tr>
            <td><span className="run-name"><span className="run-glyph"><Play size={12} /></span><span><strong>{run.name}</strong><small>{run.id}</small></span></span></td>
            <td><Badge>{run.run_type}</Badge></td>
            <td><StatusPill status={run.status as NodeStatus} /></td>
            <td><span className="table-progress"><span><i style={{ width: `${run.progress}%` }} /></span><small>{run.nodes_done}/{run.nodes_total} nodes</small></span></td>
            <td>{new Date(run.created_at).toLocaleString("ko-KR")}</td><td>{formatDuration(run.duration_ms)}</td><td>{run.attempt_count}</td><td><button type="button" className="inline-flex items-center gap-2 rounded p-1 text-left hover:bg-[var(--panel-muted)]" aria-label={`비용 상세 ${run.name}`} aria-expanded={expandedCost === run.id} onClick={() => setExpandedCost((current) => current === run.id ? null : run.id)}><CostValue cost={run.cost_summary} legacyCost={run.cost_usd} /><ChevronDown size={14} /></button></td>
          </tr>{expandedCost === run.id && <tr><td colSpan={8}><RunCostDetails key={`${run.id}:${run.cost_summary?.status}:${run.cost_summary?.known_cost_usd}`} ownerId={run.id} /></td></tr>}</Fragment>)}</tbody>
        </table>
      </Card>}
    </div>
  );
}
