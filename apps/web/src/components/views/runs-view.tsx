"use client";

import { CalendarDays, CircleDollarSign, Clock3, Filter, MoreHorizontal, Play, RotateCcw, Search, SquareArrowOutUpRight } from "lucide-react";
import { runs } from "@/lib/demo-data";
import { StatusPill } from "@/components/ui/status-pill";

export function RunsView() {
  return (
    <div className="view-page runs-page">
      <div className="view-heading">
        <div><h2>Workflow runs</h2><p>실행 상태, 비용, Attempt와 Artifact Lineage를 추적합니다.</p></div>
        <div className="heading-actions"><button className="secondary-button" type="button"><RotateCcw size={13} /> Reconcile</button><button className="primary-button" type="button"><Play size={13} /> New run</button></div>
      </div>
      <div className="run-summary-grid">
        <div className="panel"><span className="summary-icon purple"><Play size={16} /></span><span><small>Runs today</small><strong>8</strong><em>3 active</em></span></div>
        <div className="panel"><span className="summary-icon blue"><Clock3 size={16} /></span><span><small>Avg. duration</small><strong>09:42</strong><em>−12% this week</em></span></div>
        <div className="panel"><span className="summary-icon green"><CircleDollarSign size={16} /></span><span><small>Spend today</small><strong>$18.47</strong><em>$42.00 budget</em></span></div>
        <div className="panel"><span className="summary-icon amber"><CalendarDays size={16} /></span><span><small>Success rate</small><strong>94.2%</strong><em>Last 30 days</em></span></div>
      </div>
      <div className="toolbar-row">
        <label className="input-shell"><Search size={14} /><input placeholder="Search run or ID…" /></label>
        <select className="select-shell"><option>All statuses</option><option>Running</option><option>Needs review</option><option>Failed</option></select>
        <button className="icon-button" type="button"><Filter size={14} /></button>
      </div>
      <section className="panel data-table-panel">
        <table className="data-table">
          <thead><tr><th>Run</th><th>Status</th><th>Progress</th><th>Started</th><th>Duration</th><th>Cost</th><th /></tr></thead>
          <tbody>{runs.map((run) => <tr key={run.id}>
            <td><span className="run-name"><span className="run-glyph"><Play size={12} /></span><span><strong>{run.name}</strong><small>{run.id}</small></span></span></td>
            <td><StatusPill status={run.status} /></td>
            <td><span className="table-progress"><span><i style={{ width: `${run.progress}%` }} /></span><small>{run.nodesDone}/{run.nodesTotal} nodes</small></span></td>
            <td>{run.startedAt}</td><td>{run.duration}</td><td><strong>${run.cost.toFixed(2)}</strong></td>
            <td><span className="row-actions"><button type="button" className="icon-button tiny"><SquareArrowOutUpRight size={13} /></button><button type="button" className="icon-button tiny"><MoreHorizontal size={14} /></button></span></td>
          </tr>)}</tbody>
        </table>
      </section>
    </div>
  );
}

