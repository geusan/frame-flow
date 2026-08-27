"use client";

import { useEffect, useMemo, useState } from "react";
import { CalendarDays, CircleDollarSign, Clock3, Play, Search } from "lucide-react";
import { frameflowApi } from "@/lib/api";
import type { NodeStatus, RunSummary } from "@/lib/types";
import { StatusPill } from "@/components/ui/status-pill";

export function RunsView() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  useEffect(() => {
    frameflowApi.listRuns().then((rows) => setRuns(rows.map((run) => ({
      id: run.id,
      name: run.name,
      status: run.status as NodeStatus,
      progress: run.progress,
      startedAt: new Date(run.created_at).toLocaleString("ko-KR"),
      duration: "—",
      cost: run.actual_cost_usd,
      nodesDone: run.node_runs.filter((node) => node.status === "SUCCEEDED").length,
      nodesTotal: run.node_runs.length,
    })))).catch(() => setRuns([]));
  }, []);
  const summary = useMemo(() => ({
    active: runs.filter((run) => ["RUNNING", "WAITING_INPUT"].includes(run.status)).length,
    spend: runs.reduce((total, run) => total + run.cost, 0),
    successRate: runs.length ? runs.filter((run) => run.status === "SUCCEEDED").length / runs.length * 100 : 0,
  }), [runs]);
  const visibleRuns = useMemo(() => runs.filter((run) => `${run.name} ${run.id}`.toLowerCase().includes(query.toLowerCase()) && (statusFilter === "all" || run.status === statusFilter)), [query, runs, statusFilter]);
  return (
    <div className="view-page runs-page">
      <div className="view-heading">
        <div><h2>Workflow runs</h2><p>실행 상태, 비용, Attempt와 Artifact Lineage를 추적합니다.</p></div>
      </div>
      <div className="run-summary-grid">
        <div className="panel"><span className="summary-icon purple"><Play size={16} /></span><span><small>Stored runs</small><strong>{runs.length}</strong><em>{summary.active} active</em></span></div>
        <div className="panel"><span className="summary-icon blue"><Clock3 size={16} /></span><span><small>Completed nodes</small><strong>{runs.reduce((total, run) => total + run.nodesDone, 0)}</strong><em>Immutable attempts</em></span></div>
        <div className="panel"><span className="summary-icon green"><CircleDollarSign size={16} /></span><span><small>Recorded estimate</small><strong>${summary.spend.toFixed(2)}</strong><em>Provider billing is authoritative</em></span></div>
        <div className="panel"><span className="summary-icon amber"><CalendarDays size={16} /></span><span><small>Success rate</small><strong>{summary.successRate.toFixed(1)}%</strong><em>All stored runs</em></span></div>
      </div>
      <div className="toolbar-row">
        <label className="input-shell"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search run or ID…" /></label>
        <select className="select-shell" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">All statuses</option><option value="RUNNING">Running</option><option value="WAITING_INPUT">Needs review</option><option value="FAILED">Failed</option><option value="SUCCEEDED">Succeeded</option></select>
      </div>
      <section className="panel data-table-panel">
        <table className="data-table">
          <thead><tr><th>Run</th><th>Status</th><th>Progress</th><th>Started</th><th>Duration</th><th>Cost</th><th /></tr></thead>
          <tbody>{visibleRuns.map((run) => <tr key={run.id}>
            <td><span className="run-name"><span className="run-glyph"><Play size={12} /></span><span><strong>{run.name}</strong><small>{run.id}</small></span></span></td>
            <td><StatusPill status={run.status} /></td>
            <td><span className="table-progress"><span><i style={{ width: `${run.progress}%` }} /></span><small>{run.nodesDone}/{run.nodesTotal} nodes</small></span></td>
            <td>{run.startedAt}</td><td>{run.duration}</td><td><strong>${run.cost.toFixed(2)}</strong></td>
            <td />
          </tr>)}</tbody>
        </table>
      </section>
    </div>
  );
}
