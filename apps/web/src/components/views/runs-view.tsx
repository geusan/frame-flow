"use client";

import { useEffect, useMemo, useState } from "react";
import { CalendarDays, CircleDollarSign, Clock3, Play } from "lucide-react";
import { frameflowApi, type WorkflowRunRecord } from "@/lib/api";
import type { NodeStatus } from "@/lib/types";
import { PageHeader } from "@/components/shared/page-header";
import { SearchField } from "@/components/shared/search-field";
import { NativeSelect } from "@/components/ui/native-select";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { StatusPill } from "@/components/ui/status-pill";

function formatDuration(durationMs?: number): string {
  if (!durationMs) return "Not recorded";
  if (durationMs < 1000) return `${durationMs}ms`;
  return `${Math.round(durationMs / 100) / 10}s`;
}

export function RunsView() {
  const [runs, setRuns] = useState<WorkflowRunRecord[]>([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    frameflowApi.listWorkflowRuns()
      .then((rows) => { if (active) setRuns(rows); })
      .catch((loadError) => { if (active) setError(loadError instanceof Error ? loadError.message : "Run loading failed"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const summary = useMemo(() => {
    const terminal = runs.filter((run) => ["SUCCEEDED", "FAILED", "CANCELED"].includes(run.status));
    return {
      active: runs.filter((run) => ["READY", "QUEUED", "RUNNING", "WAITING_INPUT", "RETRY_WAIT"].includes(run.status)).length,
      spend: runs.reduce((total, run) => total + run.cost_usd, 0),
      successRate: terminal.length ? terminal.filter((run) => run.status === "SUCCEEDED").length / terminal.length * 100 : 0,
      completedNodes: runs.reduce((total, run) => total + run.nodes_done, 0),
    };
  }, [runs]);
  const visibleRuns = useMemo(() => runs.filter((run) => `${run.name} ${run.id} ${run.run_type}`.toLowerCase().includes(query.toLowerCase()) && (statusFilter === "all" || run.status === statusFilter)), [query, runs, statusFilter]);
  return (
    <div className="view-page runs-page">
      <PageHeader title="Workflow runs" description="저장된 Generation Run과 Canvas DAG Run의 실제 실행 상태를 함께 표시합니다." />
      <div className="run-summary-grid">
        <Card><span className="summary-icon purple"><Play size={16} /></span><span><small>Stored runs</small><strong>{runs.length}</strong><em>{summary.active} active</em></span></Card>
        <Card><span className="summary-icon blue"><Clock3 size={16} /></span><span><small>Completed nodes</small><strong>{summary.completedNodes}</strong><em>Persisted node results</em></span></Card>
        <Card><span className="summary-icon green"><CircleDollarSign size={16} /></span><span><small>Recorded cost</small><strong>${summary.spend.toFixed(2)}</strong><em>Stored experiment costs</em></span></Card>
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
          <tbody>{visibleRuns.map((run) => <tr key={run.id}>
            <td><span className="run-name"><span className="run-glyph"><Play size={12} /></span><span><strong>{run.name}</strong><small>{run.id}</small></span></span></td>
            <td><Badge>{run.run_type}</Badge></td>
            <td><StatusPill status={run.status as NodeStatus} /></td>
            <td><span className="table-progress"><span><i style={{ width: `${run.progress}%` }} /></span><small>{run.nodes_done}/{run.nodes_total} nodes</small></span></td>
            <td>{new Date(run.created_at).toLocaleString("ko-KR")}</td><td>{formatDuration(run.duration_ms)}</td><td>{run.attempt_count}</td><td><strong>${run.cost_usd.toFixed(2)}</strong></td>
          </tr>)}</tbody>
        </table>
      </Card>}
    </div>
  );
}
