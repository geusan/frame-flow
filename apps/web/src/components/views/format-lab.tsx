"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  BarChart3,
  Braces,
  CircleDot,
  MoreHorizontal,
  Plus,
  Search,
  SlidersHorizontal,
  Sparkles,
  WandSparkles,
} from "lucide-react";
import { frameflowApi, type FormatRecord } from "@/lib/api";
import type { FormatProfile } from "@/lib/types";
import { useStudioStore } from "@/lib/store";

const beatColors = ["#675cf6", "#4388c7", "#d18a36", "#24876a"];

function toFormatProfile(row: FormatRecord): FormatProfile {
  const confidenceValues = Object.values(row.payload.evidence ?? {}).map((value) => Number((value as { confidence?: number }).confidence ?? 0)).filter((value) => Number.isFinite(value));
  const exactModelId = row.lineage.exact_model_id ? String(row.lineage.exact_model_id) : null;
  return {
    id: row.id,
    name: row.name,
    sourceCount: row.parent_ids.length,
    createdAt: new Date(row.created_at).toLocaleString("ko-KR"),
    confidence: confidenceValues.length ? confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length : 0,
    tags: exactModelId ? [row.kind, exactModelId] : [row.kind],
    core: row.payload.core,
    extensions: row.payload.extensions ?? {},
    evidence: row.payload.evidence ?? {},
    lineage: row.lineage,
  };
}

function confidenceLabel(confidence: number): string {
  if (confidence >= 0.8) return "high confidence";
  if (confidence >= 0.5) return "medium confidence";
  if (confidence > 0) return "low confidence";
  return "no scored evidence";
}

function pacingLabel(cutsPer10Seconds: number): string {
  if (cutsPer10Seconds >= 5) return "very fast pacing";
  if (cutsPer10Seconds >= 3) return "fast pacing";
  if (cutsPer10Seconds >= 1.5) return "moderate pacing";
  return "slow pacing";
}

export function FormatLab() {
  const [formats, setFormats] = useState<FormatProfile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<"overview" | "schema" | "evidence">("overview");
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState<"all" | "profile" | "variant">("all");
  const [creatingVariant, setCreatingVariant] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const setView = useStudioStore((state) => state.setView);

  useEffect(() => {
    frameflowApi.listFormats().then((rows) => {
      const mapped = rows.map(toFormatProfile);
      setFormats(mapped);
      setSelectedId((current) => current ?? mapped[0]?.id ?? null);
    }).catch((loadError) => setError(loadError instanceof Error ? loadError.message : "Format loading failed"))
      .finally(() => setLoading(false));
  }, []);
  const selected = formats.find((format) => format.id === selectedId) ?? formats[0];
  const visibleFormats = useMemo(() => formats.filter((format) => format.name.toLowerCase().includes(query.toLowerCase()) && (kindFilter === "all" || format.tags.includes(kindFilter))), [formats, kindFilter, query]);

  const createVariant = async () => {
    if (!selected) return;
    setCreatingVariant(true);
    try {
      await frameflowApi.createFormatVariants(selected.id, 1);
      const rows = await frameflowApi.listFormats();
      setFormats(rows.map(toFormatProfile));
    } finally {
      setCreatingVariant(false);
    }
  };

  if (!selected) return <div className="format-layout"><section className="format-browser"><div className="format-browser-head"><div><span className="subtle-label">Format assets</span><strong>My formats</strong></div></div><p className={`experiment-history-state ${error ? "error" : ""}`}>{error ?? (loading ? "Loading stored formats…" : "저장된 Format이 없습니다. Reference Set에서 추출을 실행하세요.")}</p></section></div>;

  return (
    <div className="format-layout">
      <section className="format-browser">
        <div className="format-browser-head">
          <div><span className="subtle-label">Format assets</span><strong>My formats</strong></div>
          <button className="icon-button" type="button" onClick={() => setView("references")} aria-label="Extract a new format from references"><Plus size={15} /></button>
        </div>
        <label className="input-shell format-search"><Search size={13} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search formats…" /></label>
        <div className="format-filter-row"><button className={kindFilter === "all" ? "active" : ""} onClick={() => setKindFilter("all")} type="button">All <span>{formats.length}</span></button><button className={kindFilter === "profile" ? "active" : ""} onClick={() => setKindFilter("profile")} type="button">Profiles <span>{formats.filter((format) => format.tags.includes("profile")).length}</span></button><button className={kindFilter === "variant" ? "active" : ""} onClick={() => setKindFilter("variant")} type="button">Variants <span>{formats.filter((format) => format.tags.includes("variant")).length}</span></button></div>
        <div className="format-items">
          {visibleFormats.map((format, index) => (
            <button type="button" onClick={() => setSelectedId(format.id)} className={`format-item ${selected.id === format.id ? "active" : ""}`} key={format.id}>
              <span className={`format-icon f${index + 1}`}><Braces size={15} /></span>
              <span className="format-item-copy"><strong>{format.name}</strong><small>{format.sourceCount} sources · {Math.round(format.confidence * 100)}% confidence</small></span>
              <MoreHorizontal size={14} />
            </button>
          ))}
        </div>
        <div className="format-browser-footer"><button type="button" onClick={() => setView("references")}><Sparkles size={13} /> New extraction</button></div>
      </section>

      <section className="format-detail">
        <div className="format-detail-head">
          <div className="format-title-group">
            <span className="format-icon f1 large"><Braces size={18} /></span>
            <div><span className="subtle-label">FormatProfile · {selected.id}</span><h2>{selected.name}</h2></div>
          </div>
          <div className="heading-actions"><button className="primary-button" type="button" onClick={() => void createVariant()} disabled={creatingVariant}><WandSparkles size={13} /> {creatingVariant ? "Creating…" : "Create variant"}</button></div>
        </div>

        <div className="format-tabs">
          {(["overview", "schema", "evidence"] as const).map((key) => <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)} type="button">{key[0].toUpperCase() + key.slice(1)}</button>)}
          <span className="format-save-state">Created {selected.createdAt}</span>
        </div>

        {tab === "overview" && (
          <div className="format-content">
            <div className="format-metrics">
              <div><span>Target duration</span><strong>{selected.core.duration.target_ms / 1000}<small>s</small></strong><em>stored target</em></div>
              <div><span>Shot rhythm</span><strong>{(selected.core.editing.median_shot_duration_ms / 1000).toFixed(1)}<small>s</small></strong><em>median duration</em></div>
              <div><span>Cut density</span><strong>{selected.core.editing.cuts_per_10_seconds}<small>/10s</small></strong><em>{pacingLabel(selected.core.editing.cuts_per_10_seconds)}</em></div>
              <div><span>Confidence</span><strong>{Math.round(selected.confidence * 100)}<small>%</small></strong><em className={selected.confidence >= .8 ? "positive" : ""}>{confidenceLabel(selected.confidence)}</em></div>
            </div>

            <article className="format-section panel">
                <div className="panel-header"><div><h3>Narrative beat timeline</h3><p>영상의 시간 비율에 따라 추출된 서사 구조</p></div><SlidersHorizontal size={14} /></div>
              <div className="beat-chart">
                <div className="beat-track">
                  {selected.core.narrative.beats.map((beat, index) => (
                    <div key={beat.role} className="beat-segment" style={{ width: `${(beat.end_ratio - beat.start_ratio) * 100}%`, background: beatColors[index] }}>
                      <span>{beat.role}</span>
                    </div>
                  ))}
                  <div className="beat-tail" />
                </div>
                <div className="beat-axis"><span>0s</span><span>{Math.round(selected.core.duration.target_ms * .25 / 1000)}s</span><span>{Math.round(selected.core.duration.target_ms * .5 / 1000)}s</span><span>{Math.round(selected.core.duration.target_ms * .75 / 1000)}s</span><span>{selected.core.duration.target_ms / 1000}s</span></div>
                <div className="beat-legend">
                  {selected.core.narrative.beats.map((beat, index) => <div key={beat.role}><i style={{ background: beatColors[index] }} /><span><strong>{beat.role}</strong><small>{Math.round(beat.start_ratio * 100)}–{Math.round(beat.end_ratio * 100)}% {beat.pattern ? `· ${beat.pattern}` : ""}</small></span><ArrowRight size={10} /></div>)}
                </div>
              </div>
            </article>

            <div className="format-section-grid">
              <article className="panel compact-section">
                <div className="panel-header"><div><h3>Editing rhythm</h3><p>Stored FormatCore values</p></div><BarChart3 size={15} /></div>
                <div className="format-data-list"><div><span>Median shot</span><strong>{selected.core.editing.median_shot_duration_ms}ms</strong></div><div><span>Cuts / 10s</span><strong>{selected.core.editing.cuts_per_10_seconds}</strong></div><div><span>Transition</span><strong>{selected.core.editing.transition_policy}</strong></div></div>
              </article>
              <article className="panel compact-section">
                <div className="panel-header"><div><h3>Voice & music</h3><p>Stored FormatCore values</p></div><Activity size={15} /></div>
                <div className="format-data-list"><div><span>Voice tone</span><strong>{selected.core.voice.tone}</strong></div><div><span>Voice pace</span><strong>{selected.core.voice.pace_syllables_per_second} syllables/s</strong></div><div><span>Music BPM</span><strong>{selected.core.music.bpm_range.join("–")}</strong></div><div><span>Voice ducking</span><strong>{selected.core.music.ducking_under_voice_db}dB</strong></div></div>
              </article>
            </div>

            <article className="format-section panel format-properties">
              <div className="panel-header"><div><h3>Core properties</h3><p>생성 노드가 항상 사용할 수 있는 FormatCoreV1</p></div><span className="tag purple">format.core.v1</span></div>
              <div className="property-grid">
                <div><span className="property-icon"><CircleDot size={14} /></span><span><small>Caption position</small><strong>{selected.core.captions.position}</strong></span></div>
                <div><span className="property-icon"><BarChart3 size={14} /></span><span><small>Voice tone</small><strong>{selected.core.voice.tone}</strong></span></div>
                <div><span className="property-icon"><Activity size={14} /></span><span><small>Motion intensity</small><strong>{selected.core.visual.motion_intensity}</strong></span></div>
                <div><span className="property-icon"><Sparkles size={14} /></span><span><small>Transition</small><strong>{selected.core.editing.transition_policy}</strong></span></div>
              </div>
            </article>
          </div>
        )}

        {tab === "schema" && <div className="format-content"><pre className="schema-viewer">{JSON.stringify({ schema_version: selected.core.schema_version, core: selected.core, extensions: selected.extensions }, null, 2)}</pre></div>}
        {tab === "evidence" && (
          <div className="format-content evidence-list">
            {Object.entries(selected.evidence).length ? Object.entries(selected.evidence).map(([field, evidence], index) => <div className="evidence-row panel" key={field}><span className="evidence-index">{String(index + 1).padStart(2, "0")}</span><div><strong>{field}</strong><p>Value: {JSON.stringify(evidence.manual_override ?? evidence.value)} · Confidence: {Math.round(Number(evidence.confidence ?? 0) * 100)}% · {evidence.evidence?.length ?? 0} source spans</p></div></div>) : <p className="experiment-history-state">이 Format에는 저장된 evidence가 없습니다.</p>}
          </div>
        )}
      </section>
    </div>
  );
}
