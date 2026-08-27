"use client";

import { useEffect, useMemo, useState } from "react";
import { Boxes, CircleDollarSign, ShieldCheck, Zap } from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { SearchField } from "@/components/shared/search-field";
import { NativeSelect } from "@/components/ui/native-select";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { frameflowApi, type ModelRecord } from "@/lib/api";

export function ModelRegistry() {
  const [models, setModels] = useState<ModelRecord[]>([]);
  const [query, setQuery] = useState("");
  const [modality, setModality] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    frameflowApi.listModels()
      .then((rows) => { if (active) setModels(rows); })
      .catch((loadError) => { if (active) setError(loadError instanceof Error ? loadError.message : "Model loading failed"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const configured = models.filter((model) => model.configured).length;
  const totalUsage = models.reduce((total, model) => total + model.usage_count, 0);
  const totalCost = models.reduce((total, model) => total + model.recorded_cost_usd, 0);
  const visibleModels = useMemo(() => models.filter((model) => `${model.logical_alias} ${model.exact_model_id}`.toLowerCase().includes(query.toLowerCase()) && (modality === "all" || model.modality === modality)), [models, modality, query]);
  return (
    <div className="view-page models-page">
      <PageHeader title="Model Registry" description="노드는 논리적 별칭만 사용하며, 실제 Provider 모델과 수명주기는 여기서 관리합니다." />
      <Card className="registry-callout"><span className="callout-icon"><ShieldCheck size={18} /></span><div><strong>No model IDs are hardcoded in workflows</strong><p>활성 모델을 교체해도 과거 Run에는 실행 당시의 정확한 모델 ID와 파라미터가 보존됩니다.</p></div></Card>
      <div className="mb-3.5 flex items-center gap-2"><SearchField className="min-w-[250px] max-w-[380px] flex-1" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search alias or model ID…" /><NativeSelect value={modality} onChange={(event) => setModality(event.target.value)}><option value="all">All modalities</option><option value="video">Video</option><option value="image">Image</option><option value="text">Text</option><option value="chat">ChatGPT</option><option value="tts">TTS</option><option value="stt">STT</option></NativeSelect></div>
      {error && <p className="experiment-history-state error">{error}</p>}
      {!error && loading && <p className="experiment-history-state">Loading configured model registry…</p>}
      <Card className="data-table-panel model-table-panel">
        <table className="data-table model-table">
          <thead><tr><th>Logical alias</th><th>Exact model ID</th><th>Provider</th><th>Modality</th><th>Region</th><th>Configuration</th><th>Runs</th><th>Recorded cost</th><th>Last used</th><th>Status</th></tr></thead>
          <tbody>{visibleModels.map((model) => <tr key={model.logical_alias}>
            <td><span className="model-alias"><span><Boxes size={13} /></span><strong>{model.logical_alias}</strong></span></td>
            <td><code>{model.exact_model_id}</code></td><td>{model.provider}</td><td><Badge>{model.modality}</Badge></td><td>{model.region}</td><td><small>{model.configuration}</small></td><td>{model.usage_count}</td><td>${model.recorded_cost_usd.toFixed(2)}</td><td>{model.last_used_at ? new Date(model.last_used_at).toLocaleString("ko-KR") : "Never"}</td>
            <td><span className={`registry-status ${model.status}`}><i />{model.status}</span></td>
          </tr>)}</tbody>
        </table>
      </Card>
      <div className="registry-footer-grid"><Card><span><Zap size={15} /></span><div><strong>Provider credentials</strong><p>{configured}/{models.length} model routes are currently configured</p></div></Card><Card><span><CircleDollarSign size={15} /></span><div><strong>Recorded usage</strong><p>{totalUsage} experiments · ${totalCost.toFixed(2)} stored cost</p></div></Card></div>
    </div>
  );
}
