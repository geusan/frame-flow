"use client";

import { useEffect, useMemo, useState } from "react";
import { Boxes, CircleDollarSign, Search, ShieldCheck, Zap } from "lucide-react";
import { frameflowApi, type ModelRecord } from "@/lib/api";

export function ModelRegistry() {
  const [models, setModels] = useState<ModelRecord[]>([]);
  const [query, setQuery] = useState("");
  const [modality, setModality] = useState("all");
  useEffect(() => {
    frameflowApi.listModels().then(setModels).catch(() => setModels([]));
  }, []);
  const configured = models.filter((model) => model.configured).length;
  const visibleModels = useMemo(() => models.filter((model) => `${model.logical_alias} ${model.exact_model_id}`.toLowerCase().includes(query.toLowerCase()) && (modality === "all" || model.modality === modality)), [models, modality, query]);
  return (
    <div className="view-page models-page">
      <div className="view-heading">
        <div><h2>Model Registry</h2><p>노드는 논리적 별칭만 사용하며, 실제 Provider 모델과 수명주기는 여기서 관리합니다.</p></div>
      </div>
      <div className="registry-callout panel"><span className="callout-icon"><ShieldCheck size={18} /></span><div><strong>No model IDs are hardcoded in workflows</strong><p>활성 모델을 교체해도 과거 Run에는 실행 당시의 정확한 모델 ID와 파라미터가 보존됩니다.</p></div></div>
      <div className="toolbar-row"><label className="input-shell"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search alias or model ID…" /></label><select className="select-shell" value={modality} onChange={(event) => setModality(event.target.value)}><option value="all">All modalities</option><option value="video">Video</option><option value="image">Image</option><option value="text">Text</option><option value="chat">ChatGPT</option><option value="tts">TTS</option><option value="stt">STT</option></select></div>
      <section className="panel data-table-panel model-table-panel">
        <table className="data-table model-table">
          <thead><tr><th>Logical alias</th><th>Exact model ID</th><th>Modality</th><th>Region</th><th>Quota</th><th>Status</th><th>Fallback</th><th /></tr></thead>
          <tbody>{visibleModels.map((model) => <tr key={model.logical_alias}>
            <td><span className="model-alias"><span><Boxes size={13} /></span><strong>{model.logical_alias}</strong></span></td>
            <td><code>{model.exact_model_id}</code></td><td><span className="tag">{model.modality}</span></td><td>{model.region}</td><td>Provider managed</td>
            <td><span className={`registry-status ${model.status}`}><i />{model.status}</span></td><td><span className="muted-dash">—</span></td>
            <td />
          </tr>)}</tbody>
        </table>
      </section>
      <div className="registry-footer-grid"><div className="panel"><span><Zap size={15} /></span><div><strong>Configured models</strong><p>{configured}/{models.length} models have Google Cloud configuration</p></div></div><div className="panel"><span><CircleDollarSign size={15} /></span><div><strong>Cost source</strong><p>Actual run records · provider billing remains authoritative</p></div></div></div>
    </div>
  );
}
