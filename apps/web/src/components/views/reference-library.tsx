"use client";

import { useMemo, useState } from "react";
import {
  CheckCircle2,
  CircleEllipsis,
  Clock3,
  ExternalLink,
  FileUp,
  Filter,
  FolderPlus,
  Grid2X2,
  Link2,
  List,
  Play,
  Plus,
  Search,
  ShieldCheck,
  Tv,
  X,
} from "lucide-react";
import { references } from "@/lib/demo-data";
import { frameflowApi, type InspectResult } from "@/lib/api";

const rightsLabel: Record<string, string> = {
  owned: "Owned",
  licensed: "Licensed",
  creative_commons: "CC",
  analysis_only: "Analysis only",
  unknown: "Unknown",
};

export function ReferenceLibrary() {
  const [query, setQuery] = useState("");
  const [showImport, setShowImport] = useState(false);
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [sourceUrls, setSourceUrls] = useState("https://youtube.com/watch?v=example\nhttps://youtube.com/shorts/example2");
  const [inspecting, setInspecting] = useState(false);
  const [inspection, setInspection] = useState<InspectResult[]>([]);
  const [inspectError, setInspectError] = useState<string | null>(null);
  const filtered = useMemo(
    () => references.filter((item) => `${item.title} ${item.creator}`.toLowerCase().includes(query.toLowerCase())),
    [query],
  );

  const inspect = async () => {
    setInspecting(true);
    setInspectError(null);
    try {
      const urls = sourceUrls.split("\n").map((url) => url.trim()).filter(Boolean);
      setInspection(await frameflowApi.inspectReferences(urls));
    } catch (error) {
      setInspectError(error instanceof Error ? error.message : "Metadata inspection failed");
    } finally {
      setInspecting(false);
    }
  };

  return (
    <div className="view-page reference-page">
      <div className="view-heading">
        <div>
          <h2>Reference Library</h2>
          <p>원본은 분석 전용으로 격리되며, 생성 Worker에는 구조화된 Format만 전달됩니다.</p>
        </div>
        <div className="heading-actions">
          <button type="button" className="secondary-button"><FolderPlus size={14} /> Collection</button>
          <button type="button" className="primary-button" onClick={() => setShowImport(true)}><Plus size={14} /> Add references</button>
        </div>
      </div>

      <div className="reference-stats">
        <div><span className="stat-icon violet"><Tv size={16} /></span><span><strong>24</strong><small>Total references</small></span></div>
        <div><span className="stat-icon green"><CheckCircle2 size={16} /></span><span><strong>18</strong><small>Analysis complete</small></span></div>
        <div><span className="stat-icon amber"><Clock3 size={16} /></span><span><strong>3</strong><small>In processing</small></span></div>
        <div><span className="stat-icon blue"><ShieldCheck size={16} /></span><span><strong>7</strong><small>Generation approved</small></span></div>
      </div>

      <div className="toolbar-row">
        <label className="input-shell">
          <Search size={14} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title, creator, or tag…" />
        </label>
        <select className="select-shell" defaultValue="all"><option value="all">All rights</option><option>Owned</option><option>Analysis only</option></select>
        <select className="select-shell" defaultValue="all"><option value="all">All status</option><option>Analyzed</option><option>Processing</option></select>
        <button type="button" className="icon-button"><Filter size={14} /></button>
        <div className="toolbar-spacer" />
        <div className="segmented-control">
          <button className={layout === "grid" ? "active" : ""} type="button" onClick={() => setLayout("grid")}><Grid2X2 size={13} /></button>
          <button className={layout === "list" ? "active" : ""} type="button" onClick={() => setLayout("list")}><List size={14} /></button>
        </div>
      </div>

      <div className={layout === "grid" ? "reference-grid" : "reference-list"}>
        {filtered.map((item) => (
          <article className="reference-card" key={item.id}>
            <div className="reference-thumb" style={{ background: item.thumbnail }}>
              <div className="thumb-grid" />
              <button type="button" className="thumb-play"><Play size={14} fill="currentColor" /></button>
              <span className="duration-badge">{item.duration}</span>
              <label className="card-check"><input type="checkbox" /><span /></label>
            </div>
            <div className="reference-card-body">
              <div className="card-title-row">
                <div><h3>{item.title}</h3><p>{item.creator}</p></div>
                <button type="button" className="icon-button tiny"><CircleEllipsis size={15} /></button>
              </div>
              <div className="card-meta"><span>{item.source}</span><i /> <span>{item.language}</span><i /> <span>{item.profiles} formats</span></div>
              <div className="card-footer">
                <span className={`rights-pill ${item.rights}`}><ShieldCheck size={11} /> {rightsLabel[item.rights]}</span>
                <span className={`analysis-state ${item.status}`}>
                  {item.status === "processing" && <span className="mini-progress"><i /></span>}
                  {item.status === "analyzed" ? "Analyzed" : item.status === "processing" ? "Analyzing 62%" : "Ready"}
                </span>
              </div>
            </div>
          </article>
        ))}
      </div>

      {showImport && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setShowImport(false)}>
          <section className="modal-card import-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-heading">
              <div><h2>Add references</h2><p>URL을 검사한 뒤 권리 범위와 가져올 자산을 선택합니다.</p></div>
              <button className="icon-button" type="button" onClick={() => setShowImport(false)}><X size={16} /></button>
            </div>
            <div className="import-tabs"><button className="active" type="button"><Link2 size={14} /> URL</button><button type="button"><FileUp size={14} /> Upload</button><button type="button"><Tv size={14} /> Search</button></div>
            <label className="url-textarea">
              <span>Source URLs</span>
              <textarea value={sourceUrls} onChange={(event) => setSourceUrls(event.target.value)} />
              <small>한 줄에 URL 하나 · 사설 IP와 로컬 파일 접근은 차단됩니다.</small>
            </label>
            {inspectError && <div className="inspect-error">{inspectError} · API가 꺼져 있다면 <code>make dev-api</code>를 실행하세요.</div>}
            {inspection.length > 0 && <div className="inspection-results">{inspection.map((item) => <div key={item.canonical_url}><span className="inspection-thumb"><Play size={12} /></span><span><strong>{item.title}</strong><small>{Math.round(item.duration_ms / 1000)}s · {item.width}×{item.height} · {(item.estimated_bytes / 1_000_000).toFixed(1)} MB</small></span>{item.duplicate_reference_id ? <span className="tag amber">Duplicate</span> : <CheckCircle2 size={14} />}</div>)}</div>}
            <div className="rights-notice"><ShieldCheck size={17} /><span><strong>Analysis-only by default</strong><small>가져온 원본 프레임·음원은 생성 단계에서 사용할 수 없습니다.</small></span><ExternalLink size={13} /></div>
            <div className="modal-actions"><button className="secondary-button" type="button" onClick={() => setShowImport(false)}>Cancel</button><button className="primary-button" type="button" onClick={inspect} disabled={inspecting}>{inspecting ? "Inspecting…" : inspection.length ? "Continue to import" : "Inspect metadata"} <span>→</span></button></div>
          </section>
        </div>
      )}
    </div>
  );
}
