"use client";

import { useState } from "react";
import {
  Activity,
  ArrowRight,
  BarChart3,
  Braces,
  Check,
  CircleDot,
  Copy,
  GitCompareArrows,
  GitMerge,
  MoreHorizontal,
  Plus,
  Search,
  SlidersHorizontal,
  Sparkles,
  WandSparkles,
} from "lucide-react";
import { formats } from "@/lib/demo-data";

const beatColors = ["#675cf6", "#4388c7", "#d18a36", "#24876a"];

export function FormatLab() {
  const [selected, setSelected] = useState(formats[0]);
  const [tab, setTab] = useState<"overview" | "schema" | "evidence">("overview");

  return (
    <div className="format-layout">
      <section className="format-browser">
        <div className="format-browser-head">
          <div><span className="subtle-label">Format assets</span><strong>My formats</strong></div>
          <button className="icon-button" type="button"><Plus size={15} /></button>
        </div>
        <label className="input-shell format-search"><Search size={13} /><input placeholder="Search formats…" /></label>
        <div className="format-filter-row"><button className="active" type="button">All <span>12</span></button><button type="button">Profiles <span>7</span></button><button type="button">Variants <span>5</span></button></div>
        <div className="format-items">
          {formats.map((format, index) => (
            <button type="button" onClick={() => setSelected(format)} className={`format-item ${selected.id === format.id ? "active" : ""}`} key={format.id}>
              <span className={`format-icon f${index + 1}`}><Braces size={15} /></span>
              <span className="format-item-copy"><strong>{format.name}</strong><small>{format.sourceCount} sources · {Math.round(format.confidence * 100)}% confidence</small></span>
              <MoreHorizontal size={14} />
            </button>
          ))}
          <button type="button" className="format-item">
            <span className="format-icon f3"><WandSparkles size={15} /></span><span className="format-item-copy"><strong>Dynamic Hook Variant</strong><small>Variant · medium distance</small></span><MoreHorizontal size={14} />
          </button>
          <button type="button" className="format-item">
            <span className="format-icon f4"><GitMerge size={15} /></span><span className="format-item-copy"><strong>History × Visual Proof</strong><small>Composition · 3 sources</small></span><MoreHorizontal size={14} />
          </button>
        </div>
        <div className="format-browser-footer"><button type="button"><Sparkles size={13} /> New extraction</button><button type="button"><GitMerge size={13} /> Merge</button></div>
      </section>

      <section className="format-detail">
        <div className="format-detail-head">
          <div className="format-title-group">
            <span className="format-icon f1 large"><Braces size={18} /></span>
            <div><span className="subtle-label">FormatProfile · {selected.id}</span><h2>{selected.name}</h2></div>
          </div>
          <div className="heading-actions"><button className="secondary-button" type="button"><Copy size={13} /> Duplicate</button><button className="secondary-button" type="button"><GitCompareArrows size={13} /> Compare</button><button className="primary-button" type="button"><WandSparkles size={13} /> Create variant</button></div>
        </div>

        <div className="format-tabs">
          {(["overview", "schema", "evidence"] as const).map((key) => <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)} type="button">{key[0].toUpperCase() + key.slice(1)}</button>)}
          <button type="button">Lineage</button>
          <span className="format-save-state"><Check size={11} /> All changes saved</span>
        </div>

        {tab === "overview" && (
          <div className="format-content">
            <div className="format-metrics">
              <div><span>Target duration</span><strong>{selected.core.duration.target_ms / 1000}<small>s</small></strong><em>± 3 seconds</em></div>
              <div><span>Shot rhythm</span><strong>{(selected.core.editing.median_shot_duration_ms / 1000).toFixed(1)}<small>s</small></strong><em>median duration</em></div>
              <div><span>Cut density</span><strong>{selected.core.editing.cuts_per_10_seconds}<small>/10s</small></strong><em>fast pacing</em></div>
              <div><span>Confidence</span><strong>{Math.round(selected.confidence * 100)}<small>%</small></strong><em className="positive">high evidence</em></div>
            </div>

            <article className="format-section panel">
              <div className="panel-header"><div><h3>Narrative beat timeline</h3><p>영상의 시간 비율에 따라 추출된 서사 구조</p></div><button className="ghost-button" type="button"><SlidersHorizontal size={12} /> Edit beats</button></div>
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
                  {selected.core.narrative.beats.map((beat, index) => <div key={beat.role}><i style={{ background: beatColors[index] }} /><span><strong>{beat.role}</strong><small>{Math.round(beat.start_ratio * 100)}–{Math.round(beat.end_ratio * 100)}% {beat.pattern ? `· ${beat.pattern}` : ""}</small></span><button type="button">Evidence <ArrowRight size={10} /></button></div>)}
                </div>
              </div>
            </article>

            <div className="format-section-grid">
              <article className="panel compact-section">
                <div className="panel-header"><div><h3>Editing rhythm</h3><p>Shot duration distribution</p></div><BarChart3 size={15} /></div>
                <div className="histogram" aria-label="Shot duration histogram">{[22, 42, 68, 94, 72, 54, 36, 20, 12].map((height, i) => <i key={i} style={{ height: `${height}%` }} />)}</div>
                <div className="chart-labels"><span>0.5s</span><span>2.2s median</span><span>5.0s</span></div>
              </article>
              <article className="panel compact-section">
                <div className="panel-header"><div><h3>Voice & music energy</h3><p>Normalized intensity curve</p></div><Activity size={15} /></div>
                <div className="energy-chart"><svg viewBox="0 0 420 90" preserveAspectRatio="none"><path className="gridline" d="M0 22H420M0 45H420M0 68H420" /><path className="voice-line" d="M0 58 C35 20,55 18,82 39 S127 67,153 40 S199 20,225 44 S272 63,304 34 S350 27,420 12" /><path className="music-line" d="M0 72 C52 68,80 53,116 58 S168 43,210 49 S270 38,318 31 S373 26,420 40" /></svg><div><span><i className="voice" /> Voice pace</span><span><i className="music" /> Music energy</span></div></div>
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
            {["editing.median_shot_duration_ms", "narrative.beats[0].pattern", "voice.pace_syllables_per_second"].map((field, index) => <div className="evidence-row panel" key={field}><span className="evidence-index">0{index + 1}</span><div><strong>{field}</strong><p>Reference {index + 1} · {1.7 + index * 7.2}s–{4.4 + index * 7.2}s</p></div><span className="confidence-ring">{91 - index * 4}%</span><button className="secondary-button" type="button">View timeline</button></div>)}
          </div>
        )}
      </section>
    </div>
  );
}
