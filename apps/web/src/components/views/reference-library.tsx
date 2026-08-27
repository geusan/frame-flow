"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Clock3,
  ExternalLink,
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
import { frameflowApi, type InspectResult, type ReferenceRecord } from "@/lib/api";

const rightsLabel: Record<string, string> = {
  owned: "Owned",
  licensed: "Licensed",
  creative_commons: "CC",
  analysis_only: "Analysis only",
  unknown: "Unknown",
};

export function ReferenceLibrary() {
  const [references, setReferences] = useState<ReferenceRecord[]>([]);
  const [query, setQuery] = useState("");
  const [rightsFilter, setRightsFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [showImport, setShowImport] = useState(false);
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [sourceUrls, setSourceUrls] = useState("");
  const [rightsBasis, setRightsBasis] = useState<ReferenceRecord["rights_basis"]>("analysis_only");
  const [inspecting, setInspecting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [inspection, setInspection] = useState<InspectResult[]>([]);
  const [inspectError, setInspectError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const filtered = useMemo(
    () => references.filter((item) => `${item.title} ${item.creator}`.toLowerCase().includes(query.toLowerCase()) && (rightsFilter === "all" || item.rights_basis === rightsFilter) && (statusFilter === "all" || item.status === statusFilter)),
    [query, references, rightsFilter, statusFilter],
  );

  const loadReferences = async () => setReferences(await frameflowApi.listReferences());

  useEffect(() => {
    let active = true;
    frameflowApi.listReferences()
      .then((items) => { if (active) setReferences(items); })
      .catch((error) => { if (active) setInspectError(error instanceof Error ? error.message : "Reference loading failed"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const inspect = async () => {
    setInspecting(true);
    setInspectError(null);
    try {
      const urls = sourceUrls.split("\n").map((url) => url.trim()).filter(Boolean);
      if (!urls.length) throw new Error("검사할 URL을 한 개 이상 입력하세요.");
      setInspection(await frameflowApi.inspectReferences(urls));
    } catch (error) {
      setInspectError(error instanceof Error ? error.message : "Metadata inspection failed");
    } finally {
      setInspecting(false);
    }
  };

  const importInspected = async () => {
    setImporting(true);
    setInspectError(null);
    try {
      for (const metadata of inspection) await frameflowApi.importReference(metadata, rightsBasis);
      await loadReferences();
      setInspection([]);
      setShowImport(false);
    } catch (error) {
      setInspectError(error instanceof Error ? error.message : "Reference import failed");
    } finally {
      setImporting(false);
    }
  };

  const completedCount = references.filter((item) => item.status === "analyzed" || item.status === "ready").length;
  const processingCount = references.filter((item) => item.status === "processing").length;
  const approvedCount = references.filter((item) => item.allow_generation_input).length;

  const extractSelectedFormat = async () => {
    if (!selectedIds.length) return;
    setExtracting(true);
    setInspectError(null);
    try {
      const referenceSet = await frameflowApi.createReferenceSet(`Canvas references ${new Date().toLocaleString("ko-KR")}`, selectedIds);
      await frameflowApi.extractFormat(referenceSet.id, `Extracted format ${new Date().toLocaleDateString("ko-KR")}`);
      setSelectedIds([]);
    } catch (error) {
      setInspectError(error instanceof Error ? error.message : "Format extraction failed");
    } finally {
      setExtracting(false);
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
          <button type="button" className="secondary-button" onClick={() => void extractSelectedFormat()} disabled={!selectedIds.length || extracting}><FolderPlus size={14} /> {extracting ? "Extracting…" : `Extract format${selectedIds.length ? ` (${selectedIds.length})` : ""}`}</button>
          <button type="button" className="primary-button" onClick={() => setShowImport(true)}><Plus size={14} /> Add references</button>
        </div>
      </div>

      {inspectError && !showImport && <div className="inspect-error">{inspectError}</div>}

      <div className="reference-stats">
        <div><span className="stat-icon violet"><Tv size={16} /></span><span><strong>{references.length}</strong><small>Total references</small></span></div>
        <div><span className="stat-icon green"><CheckCircle2 size={16} /></span><span><strong>{completedCount}</strong><small>Ready references</small></span></div>
        <div><span className="stat-icon amber"><Clock3 size={16} /></span><span><strong>{processingCount}</strong><small>In processing</small></span></div>
        <div><span className="stat-icon blue"><ShieldCheck size={16} /></span><span><strong>{approvedCount}</strong><small>Generation approved</small></span></div>
      </div>

      <div className="toolbar-row">
        <label className="input-shell">
          <Search size={14} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title, creator, or tag…" />
        </label>
        <select className="select-shell" value={rightsFilter} onChange={(event) => setRightsFilter(event.target.value)}><option value="all">All rights</option><option value="owned">Owned</option><option value="licensed">Licensed</option><option value="analysis_only">Analysis only</option></select>
        <select className="select-shell" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">All status</option><option value="analyzed">Analyzed</option><option value="processing">Processing</option><option value="ready">Ready</option></select>
        <div className="toolbar-spacer" />
        <div className="segmented-control">
          <button className={layout === "grid" ? "active" : ""} type="button" onClick={() => setLayout("grid")}><Grid2X2 size={13} /></button>
          <button className={layout === "list" ? "active" : ""} type="button" onClick={() => setLayout("list")}><List size={14} /></button>
        </div>
      </div>

      <div className={layout === "grid" ? "reference-grid" : "reference-list"}>
        {filtered.map((item) => (
          <article className="reference-card" key={item.id}>
            <div className={`reference-thumb ${item.thumbnail_url ? "" : "no-thumbnail"}`} style={item.thumbnail_url ? { background: `center / cover url(${item.thumbnail_url})` } : undefined}>
              <div className="thumb-grid" />
              {!item.thumbnail_url && <Tv className="reference-thumb-empty" size={24} />}
              <button type="button" className="thumb-play" onClick={() => window.open(String(item.metadata.canonical_url ?? ""), "_blank", "noopener,noreferrer")}><Play size={14} fill="currentColor" /></button>
              <span className="duration-badge">{`${Math.floor(item.duration_ms / 60000).toString().padStart(2, "0")}:${Math.floor(item.duration_ms / 1000 % 60).toString().padStart(2, "0")}`}</span>
              <label className="card-check"><input type="checkbox" checked={selectedIds.includes(item.id)} onChange={(event) => setSelectedIds((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} /><span /></label>
            </div>
            <div className="reference-card-body">
              <div className="card-title-row">
                <div><h3>{item.title}</h3><p>{item.creator}</p></div>
              </div>
              <div className="card-meta"><span>{String(item.metadata.source_id ?? "URL")}</span><i /> <span>{item.allow_generation_input ? "Generation enabled" : "Analysis only"}</span></div>
              <div className="card-footer">
                <span className={`rights-pill ${item.rights_basis}`}><ShieldCheck size={11} /> {rightsLabel[item.rights_basis]}</span>
                <span className={`analysis-state ${item.status}`}>
                  {item.status === "processing" && <span className="mini-progress"><i /></span>}
                  {item.status === "analyzed" ? "Analyzed" : item.status === "processing" ? "Analyzing" : "Ready"}
                </span>
              </div>
            </div>
          </article>
        ))}
      </div>
      {loading && <p className="experiment-history-state">Loading stored references…</p>}
      {!loading && !filtered.length && <p className="experiment-history-state">조건에 맞는 Reference가 없습니다.</p>}

      {showImport && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setShowImport(false)}>
          <section className="modal-card import-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-heading">
              <div><h2>Add references</h2><p>URL을 검사한 뒤 권리 범위와 가져올 자산을 선택합니다.</p></div>
              <button className="icon-button" type="button" onClick={() => setShowImport(false)}><X size={16} /></button>
            </div>
            <div className="import-tabs"><span className="active"><Link2 size={14} /> URL</span></div>
            <label className="url-textarea">
              <span>Source URLs</span>
              <textarea value={sourceUrls} onChange={(event) => setSourceUrls(event.target.value)} placeholder="https://www.youtube.com/watch?v=…" />
              <small>한 줄에 URL 하나 · 사설 IP와 로컬 파일 접근은 차단됩니다.</small>
            </label>
            <label className="field-label"><span>Rights basis</span><select value={rightsBasis} onChange={(event) => setRightsBasis(event.target.value as ReferenceRecord["rights_basis"])}><option value="analysis_only">Analysis only</option><option value="owned">Owned</option><option value="licensed">Licensed</option><option value="creative_commons">Creative Commons</option><option value="unknown">Unknown</option></select></label>
            {inspectError && <div className="inspect-error">{inspectError} · API가 꺼져 있다면 <code>make dev-api</code>를 실행하세요.</div>}
            {inspection.length > 0 && <div className="inspection-results">{inspection.map((item) => <div key={item.canonical_url}><span className="inspection-thumb"><Play size={12} /></span><span><strong>{item.title}</strong><small>{Math.round(item.duration_ms / 1000)}s · {item.width}×{item.height} · {(item.estimated_bytes / 1_000_000).toFixed(1)} MB</small></span>{item.duplicate_reference_id ? <span className="tag amber">Duplicate</span> : <CheckCircle2 size={14} />}</div>)}</div>}
            <div className="rights-notice"><ShieldCheck size={17} /><span><strong>Analysis-only by default</strong><small>가져온 원본 프레임·음원은 생성 단계에서 사용할 수 없습니다.</small></span><ExternalLink size={13} /></div>
            <div className="modal-actions"><button className="secondary-button" type="button" onClick={() => setShowImport(false)}>Cancel</button><button className="primary-button" type="button" onClick={() => void (inspection.length ? importInspected() : inspect())} disabled={inspecting || importing}>{inspecting ? "Inspecting…" : importing ? "Importing media…" : inspection.length ? "Import references" : "Inspect metadata"} <span>→</span></button></div>
          </section>
        </div>
      )}
    </div>
  );
}
