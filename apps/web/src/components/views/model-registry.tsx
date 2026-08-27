"use client";

import { Boxes, CircleDollarSign, Filter, MoreHorizontal, Plus, Search, ShieldCheck, Zap } from "lucide-react";
import { models } from "@/lib/demo-data";

export function ModelRegistry() {
  return (
    <div className="view-page models-page">
      <div className="view-heading">
        <div><h2>Model Registry</h2><p>노드는 논리적 별칭만 사용하며, 실제 Provider 모델과 수명주기는 여기서 관리합니다.</p></div>
        <button type="button" className="primary-button"><Plus size={14} /> Register model</button>
      </div>
      <div className="registry-callout panel"><span className="callout-icon"><ShieldCheck size={18} /></span><div><strong>No model IDs are hardcoded in workflows</strong><p>활성 모델을 교체해도 과거 Run에는 실행 당시의 정확한 모델 ID와 파라미터가 보존됩니다.</p></div><button className="secondary-button" type="button">View policy</button></div>
      <div className="toolbar-row"><label className="input-shell"><Search size={14} /><input placeholder="Search alias or model ID…" /></label><select className="select-shell"><option>All providers</option><option>Google</option></select><select className="select-shell"><option>All modalities</option><option>Video</option><option>Image</option></select><button className="icon-button" type="button"><Filter size={14} /></button></div>
      <section className="panel data-table-panel model-table-panel">
        <table className="data-table model-table">
          <thead><tr><th>Logical alias</th><th>Exact model ID</th><th>Modality</th><th>Region</th><th>Quota</th><th>Status</th><th>Fallback</th><th /></tr></thead>
          <tbody>{models.map((model) => <tr key={model.alias}>
            <td><span className="model-alias"><span><Boxes size={13} /></span><strong>{model.alias}</strong></span></td>
            <td><code>{model.modelId}</code></td><td><span className="tag">{model.kind}</span></td><td>{model.region}</td><td>{model.quota}</td>
            <td><span className={`registry-status ${model.status}`}><i />{model.status}</span></td><td>{model.fallback ? <code>{model.fallback}</code> : <span className="muted-dash">—</span>}</td>
            <td><button className="icon-button tiny" type="button"><MoreHorizontal size={14} /></button></td>
          </tr>)}</tbody>
        </table>
      </section>
      <div className="registry-footer-grid"><div className="panel"><span><Zap size={15} /></span><div><strong>Provider pools</strong><p>Video Fast 2 · Image Fast 8 · TTS 5</p></div></div><div className="panel"><span><CircleDollarSign size={15} /></span><div><strong>Cost policy</strong><p>Workspace daily cap · $42.00</p></div></div></div>
    </div>
  );
}

