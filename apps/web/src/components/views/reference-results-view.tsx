"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import {
  Activity,
  ArrowLeft,
  AudioLines,
  Captions,
  CheckCircle2,
  Clapperboard,
  Download,
  ExternalLink,
  FileAudio,
  FileChartColumnIncreasing,
  FileJson,
  Film,
  FolderPlus,
  MessageSquareText,
  Music2,
  Play,
  RefreshCw,
  ScanText,
  Sparkles,
  Volume2,
  Waves,
} from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { SearchField } from "@/components/shared/search-field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { API_BASE, frameflowApi, type ArtifactDetail, type ArtifactListItem } from "@/lib/api";
import { maximizePlaybackVolume } from "@/lib/media";

interface TimedEvent {
  start_ms: number;
  end_ms: number;
  label: string;
  confidence: number;
}

interface ReferenceAction extends TimedEvent {
  subject: string;
  object: string;
  evidence_shot_indices: number[];
}

interface ReferenceShot {
  index: number;
  start_ms: number;
  end_ms: number;
  transition_in: string;
  scene_score: number;
}

interface ReferenceTextTrack {
  track_id: string;
  text: string;
  kind: string;
  start_ms: number;
  end_ms: number;
  confidence: number;
  movement: string;
  positions: Array<{
    timestamp_ms: number;
    bbox: { x: number; y: number; width: number; height: number };
  }>;
}

interface TranscriptSegment {
  index: number;
  start_ms: number;
  end_ms: number;
  text: string;
}

interface ReferenceManifest {
  schema_version: string;
  source: {
    duration_ms: number;
    width: number;
    height: number;
    fps: string;
    has_audio: boolean;
    content_type: string;
  };
  components: Record<string, string>;
  speech: {
    language_code: string | null;
    text: string;
    segments: TranscriptSegment[];
  };
  audio: {
    music_intervals: TimedEvent[];
    sound_effects: TimedEvent[];
    separation: {
      type: string | null;
      status: string;
      contains_sound_effects_possible: boolean;
    };
  };
  visual: {
    shots: ReferenceShot[];
    actions: ReferenceAction[];
    text_tracks: ReferenceTextTrack[];
  };
  artifacts: Record<string, string>;
  quality: { completeness: string; warnings: string[] };
  provenance: {
    analyzer_revision: string;
    semantic_model: string;
    semantic_provider_request_id: string;
    scene_threshold: number;
  };
}

interface ReferenceResult {
  asset: Pick<ArtifactListItem, "id" | "created_at" | "filename">;
  detail: ArtifactDetail;
  manifest: ReferenceManifest;
}

type TimelineKind = "shot" | "action" | "text" | "music" | "sfx";

interface TimelineLane {
  label: string;
  kind: TimelineKind;
  items: Array<{ id: string; start: number; end: number; label: string }>;
}

function parseManifest(detail: ArtifactDetail): ReferenceManifest | null {
  const text = detail.metadata.output?.text;
  if (!text) return null;
  try {
    const parsed = JSON.parse(text) as ReferenceManifest;
    return parsed.schema_version === "reference.decomposition.v1" ? parsed : null;
  } catch {
    return null;
  }
}

function resultFromDetail(detail: ArtifactDetail): ReferenceResult | null {
  const manifest = parseManifest(detail);
  if (!manifest) return null;
  return {
    asset: {
      id: detail.id,
      created_at: detail.created_at,
      filename: detail.metadata.filename ?? detail.metadata.output?.title ?? "Reference analysis",
    },
    detail,
    manifest,
  };
}

function resultFromOutput(title: string, text?: string): ReferenceResult | null {
  if (!text) return null;
  const detail: ArtifactDetail = {
    id: "",
    created_at: new Date().toISOString(),
    type: "ReferenceAnalysis",
    uri: "",
    sha256: "",
    input_artifact_ids: [],
    metadata: { output: { kind: "json", title, text } },
  };
  return resultFromDetail(detail);
}

function formatTime(milliseconds: number): string {
  const value = Math.max(0, Math.round(milliseconds));
  const minutes = Math.floor(value / 60_000);
  const seconds = Math.floor(value / 1_000) % 60;
  const tenths = Math.floor(value / 100) % 10;
  return `${minutes}:${String(seconds).padStart(2, "0")}.${tenths}`;
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

function confidence(value: number): string {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function contentUrl(artifactId: string): string {
  return `${API_BASE}/artifacts/${encodeURIComponent(artifactId)}/content`;
}

function framePreviewUrl(artifactId: string, timestampMs: number): string {
  const query = new URLSearchParams({ timestamp_ms: String(Math.max(0, Math.round(timestampMs))) });
  return `${API_BASE}/artifacts/${encodeURIComponent(artifactId)}/frame-preview?${query}`;
}

function resultTitle(result: ReferenceResult): string {
  return result.detail.metadata.output?.title || result.asset.filename || "Reference analysis";
}

async function fetchReferenceResults(): Promise<{ results: ReferenceResult[]; missing: number }> {
  const assets = await frameflowApi.listAllArtifacts(["ReferenceAnalysis"]);
  const details = await Promise.all(assets.map((asset) => frameflowApi.getArtifact(asset.id)));
  const results = assets.flatMap((asset, index) => {
    const manifest = parseManifest(details[index]);
    return manifest ? [{ asset, detail: details[index], manifest }] : [];
  });
  return { results, missing: assets.length - results.length };
}

function timelineLanes(manifest: ReferenceManifest): TimelineLane[] {
  return [
    {
      label: "Shots",
      kind: "shot",
      items: manifest.visual.shots.map((shot) => ({ id: `shot-${shot.index}`, start: shot.start_ms, end: shot.end_ms, label: `Shot ${shot.index + 1}` })),
    },
    {
      label: "Actions",
      kind: "action",
      items: manifest.visual.actions.map((item, index) => ({ id: `action-${index}`, start: item.start_ms, end: item.end_ms, label: item.label })),
    },
    {
      label: "Text",
      kind: "text",
      items: manifest.visual.text_tracks.map((item) => ({ id: item.track_id, start: item.start_ms, end: item.end_ms, label: item.text })),
    },
    {
      label: "Music",
      kind: "music",
      items: manifest.audio.music_intervals.map((item, index) => ({ id: `music-${index}`, start: item.start_ms, end: item.end_ms, label: item.label })),
    },
    {
      label: "SFX",
      kind: "sfx",
      items: manifest.audio.sound_effects.map((item, index) => ({ id: `sfx-${index}`, start: item.start_ms, end: item.end_ms, label: item.label })),
    },
  ];
}

function SourceVideoPlayer({
  sourceArtifactId,
  videoRef,
  playheadMs,
  selectedCue,
  onTimeUpdate,
}: {
  sourceArtifactId?: string;
  videoRef: RefObject<HTMLVideoElement | null>;
  playheadMs: number;
  selectedCue: { label: string; kind: TimelineKind; timestampMs: number } | null;
  onTimeUpdate: (milliseconds: number) => void;
}) {
  return (
    <Card className="reference-source-player-card">
      <CardHeader className="reference-section-head">
        <span><Film size={16} /><span><strong>Source video</strong><small>Timeline cue를 클릭하면 해당 위치로 이동해 재생합니다.</small></span></span>
        <Badge variant="outline">{formatTime(playheadMs)}</Badge>
      </CardHeader>
      <CardContent className="reference-source-player-content">
        <div className="reference-source-video-stage">
          {sourceArtifactId ? (
            <video
              ref={videoRef}
              src={contentUrl(sourceArtifactId)}
              controls
              playsInline
              preload="metadata"
              onPlay={(event) => maximizePlaybackVolume(event.currentTarget)}
              onTimeUpdate={(event) => onTimeUpdate(event.currentTarget.currentTime * 1000)}
              onSeeked={(event) => onTimeUpdate(event.currentTarget.currentTime * 1000)}
            />
          ) : <span><Film size={28} /> Source video unavailable</span>}
        </div>
        <div className="reference-source-video-context">
          <span className="subtle-label">Selected timeline cue</span>
          {selectedCue ? (
            <>
              <span className={`reference-cue-kind ${selectedCue.kind}`}>{selectedCue.kind}</span>
              <strong>{selectedCue.label}</strong>
              <p>{formatTime(selectedCue.timestampMs)}부터 재생 중입니다.</p>
            </>
          ) : (
            <>
              <span className="reference-cue-empty-icon"><Play size={18} /></span>
              <strong>Choose a timeline block</strong>
              <p>Shots, Actions, Text, Music 또는 SFX 블록을 클릭하세요.</p>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function ResultCard({ result, onOpen }: { result: ReferenceResult; onOpen: () => void }) {
  const { manifest } = result;
  return (
    <button type="button" className="reference-result-card" onClick={onOpen}>
      <span className="reference-result-card-visual">
        <span className="reference-result-card-icon"><FileChartColumnIncreasing size={24} /></span>
        <span className="reference-result-card-duration">{formatTime(manifest.source.duration_ms)}</span>
        <span className="reference-result-card-schema">{manifest.schema_version}</span>
      </span>
      <span className="reference-result-card-body">
        <span className="reference-result-card-head">
          <span><strong>{resultTitle(result)}</strong><small>{formatDate(result.asset.created_at)}</small></span>
          <Badge variant={manifest.quality.completeness === "complete" ? "success" : "warning"}>{manifest.quality.completeness}</Badge>
        </span>
        <span className="reference-result-card-metrics">
          <span><b>{manifest.visual.shots.length}</b> shots</span>
          <span><b>{manifest.visual.actions.length}</b> actions</span>
          <span><b>{manifest.visual.text_tracks.length}</b> texts</span>
          <span><b>{manifest.audio.sound_effects.length}</b> SFX</span>
        </span>
        <span className="reference-result-card-foot">
          <span>{manifest.speech.language_code ?? "No speech"}</span>
          <span>{manifest.provenance.semantic_model}</span>
          <ExternalLink size={13} />
        </span>
      </span>
    </button>
  );
}

function Timeline({ manifest, playheadMs, onSeek }: { manifest: ReferenceManifest; playheadMs: number; onSeek: (timestampMs: number, label: string, kind: TimelineKind) => void }) {
  const duration = Math.max(1, manifest.source.duration_ms);
  const lanes = timelineLanes(manifest);
  return (
    <Card className="reference-timeline-card">
      <CardHeader className="reference-section-head">
        <span><Activity size={16} /><span><strong>Unified timeline</strong><small>영상·음성 분석 결과를 같은 시간축에서 비교합니다.</small></span></span>
        <Badge variant="outline">{formatTime(duration)}</Badge>
      </CardHeader>
      <CardContent className="reference-timeline-content">
        <div className="reference-timeline-scale"><span>0:00</span><span>{formatTime(duration / 2)}</span><span>{formatTime(duration)}</span></div>
        {lanes.map((lane) => (
          <div className="reference-timeline-lane" key={lane.kind}>
            <strong>{lane.label}</strong>
            <div className="reference-timeline-track">
              <span className="reference-timeline-playhead" style={{ left: `${Math.min(100, Math.max(0, playheadMs / duration * 100))}%` }} />
              {lane.items.map((item) => {
                const left = Math.min(100, Math.max(0, item.start / duration * 100));
                const width = Math.min(100 - left, Math.max(0.8, (item.end - item.start) / duration * 100));
                const active = playheadMs >= item.start && playheadMs < item.end;
                return (
                  <button
                    type="button"
                    className={`reference-timeline-block ${lane.kind}${active ? " active" : ""}`}
                    style={{ left: `${left}%`, width: `${width}%` }}
                    title={`${formatTime(item.start)}–${formatTime(item.end)} · ${item.label}`}
                    aria-label={`Seek to ${formatTime(item.start)} · ${item.label}`}
                    onClick={() => onSeek(item.start, item.label, lane.kind)}
                    key={item.id}
                  >
                    <span>{item.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function TranscriptCard({ manifest }: { manifest: ReferenceManifest }) {
  return (
    <Card className="reference-transcript-card">
      <CardHeader className="reference-section-head">
        <span><MessageSquareText size={16} /><span><strong>Transcript</strong><small>{manifest.speech.language_code ?? "Speech not detected"}</small></span></span>
        <Badge variant="info">{manifest.speech.segments.length} segments</Badge>
      </CardHeader>
      <CardContent>
        {manifest.speech.text ? <p className="reference-transcript-copy">{manifest.speech.text}</p> : <p className="reference-empty-copy">음성 구간이 감지되지 않았습니다.</p>}
        {!!manifest.speech.segments.length && (
          <div className="reference-segment-list">
            {manifest.speech.segments.map((segment) => (
              <div key={segment.index}><span>{formatTime(segment.start_ms)}–{formatTime(segment.end_ms)}</span><p>{segment.text}</p></div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ShotGallery({ manifest, sourceArtifactId, onSeek }: { manifest: ReferenceManifest; sourceArtifactId?: string; onSeek: (timestampMs: number, label: string, kind: TimelineKind) => void }) {
  return (
    <Card className="reference-shot-gallery-card">
      <CardHeader className="reference-section-head">
        <span><Clapperboard size={16} /><span><strong>Shot screenshots</strong><small>각 컷의 중간 시점에서 추출한 대표 프레임입니다.</small></span></span>
        <Badge variant="outline">{manifest.visual.shots.length} shots</Badge>
      </CardHeader>
      <CardContent className="reference-shot-gallery">
        {manifest.visual.shots.map((shot) => {
          const representativeMs = shot.start_ms + Math.max(0, shot.end_ms - shot.start_ms) / 2;
          return (
            <article key={shot.index}>
              <button
                type="button"
                className="reference-shot-image"
                aria-label={`Shot ${shot.index + 1} at ${formatTime(representativeMs)}`}
                style={sourceArtifactId ? { backgroundImage: `url(${framePreviewUrl(sourceArtifactId, representativeMs)})` } : undefined}
                onClick={() => onSeek(shot.start_ms, `Shot ${shot.index + 1}`, "shot")}
              >
                {!sourceArtifactId && <Film size={22} />}
                <b>{String(shot.index + 1).padStart(2, "0")}</b>
                <small>{formatTime(representativeMs)}</small>
                <span className="reference-shot-play"><Play size={14} fill="currentColor" /></span>
              </button>
              <span className="reference-shot-copy">
                <strong>Shot {shot.index + 1}</strong>
                <small>{formatTime(shot.start_ms)}–{formatTime(shot.end_ms)}</small>
                <span><Badge variant="outline">{shot.transition_in.replaceAll("_", " ")}</Badge><em>score {shot.scene_score.toFixed(3)}</em></span>
              </span>
            </article>
          );
        })}
      </CardContent>
    </Card>
  );
}

function AudioCard({ manifest }: { manifest: ReferenceManifest }) {
  const [exporting, setExporting] = useState<Record<string, boolean>>({});
  const [exported, setExported] = useState<Record<string, string>>({});
  const [exportError, setExportError] = useState<string | null>(null);
  const audioArtifacts = [
    ["audio_mix", "Original mix", FileAudio],
    ["vocals", "Vocals stem", AudioLines],
    ["accompaniment", "Accompaniment", Music2],
  ] as const;
  const artifactLinks = [
    ["subtitle", "Subtitle SRT", Captions],
    ["transcript", "Transcript JSON", FileJson],
  ] as const;

  const addToAudio = async (artifactId: string) => {
    setExporting((current) => ({ ...current, [artifactId]: true }));
    setExportError(null);
    try {
      const asset = await frameflowApi.createAudioAsset(artifactId);
      setExported((current) => ({ ...current, [artifactId]: asset.artifact_id }));
      window.dispatchEvent(new Event("frameflow:workspace-changed"));
    } catch (error) {
      setExportError(error instanceof Error ? error.message : "Audio asset 저장에 실패했습니다.");
    } finally {
      setExporting((current) => ({ ...current, [artifactId]: false }));
    }
  };

  return (
    <Card className="reference-audio-card">
      <CardHeader className="reference-section-head">
        <span><Waves size={16} /><span><strong>Audio analysis</strong><small>{manifest.audio.separation.status} · {manifest.audio.separation.type ?? "no stems"}</small></span></span>
        <Badge variant={manifest.audio.separation.status === "succeeded" ? "success" : "warning"}>{manifest.audio.separation.status}</Badge>
      </CardHeader>
      <CardContent>
        <div className="reference-audio-events">
          {[...manifest.audio.music_intervals.map((item) => ({ ...item, kind: "music" })), ...manifest.audio.sound_effects.map((item) => ({ ...item, kind: "sfx" }))].map((item, index) => (
            <div key={`${item.kind}-${index}`}><span className={item.kind}>{item.kind === "music" ? <Music2 size={13} /> : <Volume2 size={13} />}</span><span><strong>{item.label}</strong><small>{formatTime(item.start_ms)}–{formatTime(item.end_ms)} · {confidence(item.confidence)}</small></span></div>
          ))}
          {!manifest.audio.music_intervals.length && !manifest.audio.sound_effects.length && <p className="reference-empty-copy">음악 또는 효과음 이벤트가 없습니다.</p>}
        </div>
        <div className="reference-audio-stems">
          {audioArtifacts.map(([key, label, Icon]) => {
            const artifactId = manifest.artifacts[key];
            if (!artifactId) return null;
            const savedId = exported[artifactId];
            return <section key={key}>
              <header><span><Icon size={14} /><strong>{label}</strong></span><small>{key.replaceAll("_", " ")}</small></header>
              <audio controls preload="none" src={contentUrl(artifactId)} aria-label={`${label} preview`} onPlay={(event) => maximizePlaybackVolume(event.currentTarget)} />
              <div>
                <Button variant="ghost" size="sm" asChild><a href={contentUrl(artifactId)} target="_blank" rel="noreferrer"><Download size={12} /> Download</a></Button>
                {savedId
                  ? <Button variant="secondary" size="sm" asChild><Link href={`/asset/audio/${encodeURIComponent(savedId)}`}><CheckCircle2 size={12} /> Open Audio</Link></Button>
                  : <Button size="sm" type="button" onClick={() => void addToAudio(artifactId)} disabled={exporting[artifactId]}>{exporting[artifactId] ? <RefreshCw size={12} className="spin" /> : <FolderPlus size={12} />}{exporting[artifactId] ? "Saving…" : "Add to Audio"}</Button>}
              </div>
            </section>;
          })}
        </div>
        {exportError && <p className="reference-audio-export-error">{exportError}</p>}
        <div className="reference-download-grid">
          {artifactLinks.map(([key, label, Icon]) => manifest.artifacts[key] && (
            <Button variant="secondary" asChild key={key}><a href={contentUrl(manifest.artifacts[key])} target="_blank" rel="noreferrer"><Icon size={13} />{label}<Download size={12} /></a></Button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function VisualFindings({ manifest }: { manifest: ReferenceManifest }) {
  return (
    <div className="reference-findings-grid">
      <Card>
        <CardHeader className="reference-section-head"><span><Clapperboard size={16} /><span><strong>Shots & actions</strong><small>{manifest.visual.shots.length} shots · {manifest.visual.actions.length} actions</small></span></span></CardHeader>
        <CardContent className="reference-finding-list">
          {manifest.visual.actions.map((action, index) => (
            <article key={`${action.start_ms}-${index}`}>
              <span className="reference-finding-index">{String(index + 1).padStart(2, "0")}</span>
              <span><strong>{action.label}</strong><p>{action.subject}{action.object ? ` → ${action.object}` : ""}</p><small>{formatTime(action.start_ms)}–{formatTime(action.end_ms)} · {confidence(action.confidence)} · shots {action.evidence_shot_indices.map((value) => value + 1).join(", ")}</small></span>
            </article>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="reference-section-head"><span><ScanText size={16} /><span><strong>On-screen text</strong><small>{manifest.visual.text_tracks.length} detected tracks</small></span></span></CardHeader>
        <CardContent className="reference-finding-list text-tracks">
          {manifest.visual.text_tracks.map((track, index) => (
            <article key={track.track_id}>
              <span className="reference-finding-index">{String(index + 1).padStart(2, "0")}</span>
              <span><strong>{track.text}</strong><p>{track.kind.replaceAll("_", " ")} · {track.movement}</p><small>{formatTime(track.start_ms)}–{formatTime(track.end_ms)} · {confidence(track.confidence)}</small></span>
            </article>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function ResultDetail({ result, onBack, backLabel = "All results", embedded = false }: { result: ReferenceResult; onBack: () => void; backLabel?: string; embedded?: boolean }) {
  const { manifest, detail } = result;
  const sourceArtifactId = detail.input_artifact_ids[0];
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playheadMs, setPlayheadMs] = useState(0);
  const [selectedCue, setSelectedCue] = useState<{ label: string; kind: TimelineKind; timestampMs: number } | null>(null);

  const seekTo = useCallback((timestampMs: number, label: string, kind: TimelineKind) => {
    const video = videoRef.current;
    const applySeek = () => {
      if (!video) return;
      video.currentTime = Math.max(0, Math.min(timestampMs / 1000, Number.isFinite(video.duration) ? video.duration : timestampMs / 1000));
      setPlayheadMs(timestampMs);
      setSelectedCue({ label, kind, timestampMs });
      void video.play().catch(() => undefined);
    };
    if (video && video.readyState === 0) video.addEventListener("loadedmetadata", applySeek, { once: true });
    else applySeek();
  }, []);

  return (
    <div className={`view-page reference-results-page reference-result-detail${embedded ? " reference-result-detail-embedded" : ""}`}>
      <div className="reference-result-detail-nav">
        <Button type="button" variant="ghost" onClick={onBack}><ArrowLeft size={15} /> {backLabel}</Button>
        <span />
        {sourceArtifactId && <Button variant="secondary" asChild><Link href={`/asset/videos/${encodeURIComponent(sourceArtifactId)}`}><Film size={14} /> Open source video</Link></Button>}
        {result.asset.id && <Button variant="secondary" asChild><a href={contentUrl(result.asset.id)} target="_blank" rel="noreferrer"><FileJson size={14} /> Analysis JSON</a></Button>}
      </div>

      <header className="reference-result-detail-head">
        <span className="reference-result-detail-icon"><Sparkles size={23} /></span>
        <div><span className="subtle-label">Reference decomposition</span><h2>{resultTitle(result)}</h2><p>{formatDate(result.asset.created_at)} · {manifest.source.width}×{manifest.source.height} · {manifest.source.fps} fps</p></div>
        <Badge variant={manifest.quality.completeness === "complete" ? "success" : "warning"}><CheckCircle2 size={12} />{manifest.quality.completeness}</Badge>
      </header>

      <div className="reference-result-summary">
        <Card><span><Film size={16} /></span><div><strong>{formatTime(manifest.source.duration_ms)}</strong><small>Duration</small></div></Card>
        <Card><span><Clapperboard size={16} /></span><div><strong>{manifest.visual.shots.length}</strong><small>Shots</small></div></Card>
        <Card><span><Activity size={16} /></span><div><strong>{manifest.visual.actions.length}</strong><small>Actions</small></div></Card>
        <Card><span><ScanText size={16} /></span><div><strong>{manifest.visual.text_tracks.length}</strong><small>Text tracks</small></div></Card>
        <Card><span><Volume2 size={16} /></span><div><strong>{manifest.audio.sound_effects.length}</strong><small>Sound effects</small></div></Card>
      </div>

      <SourceVideoPlayer sourceArtifactId={sourceArtifactId} videoRef={videoRef} playheadMs={playheadMs} selectedCue={selectedCue} onTimeUpdate={setPlayheadMs} />
      <Timeline manifest={manifest} playheadMs={playheadMs} onSeek={seekTo} />
      <ShotGallery manifest={manifest} sourceArtifactId={sourceArtifactId} onSeek={seekTo} />
      <div className="reference-analysis-grid"><TranscriptCard manifest={manifest} /><AudioCard manifest={manifest} /></div>
      <VisualFindings manifest={manifest} />
      <Card className="reference-provenance-card">
        <CardContent>
          <span><strong>Model</strong><code>{manifest.provenance.semantic_model}</code></span>
          <span><strong>Analyzer</strong><code>{manifest.provenance.analyzer_revision}</code></span>
          <span><strong>Scene threshold</strong><code>{manifest.provenance.scene_threshold}</code></span>
          <span><strong>Artifact</strong><code>{result.asset.id || "Preview only"}</code></span>
        </CardContent>
      </Card>
    </div>
  );
}

export function ReferenceResultDetail({
  artifactId,
  fallbackTitle = "Reference analysis",
  fallbackText,
  onBack,
}: {
  artifactId?: string;
  fallbackTitle?: string;
  fallbackText?: string;
  onBack: () => void;
}) {
  const fallbackResult = useMemo(() => resultFromOutput(fallbackTitle, fallbackText), [fallbackText, fallbackTitle]);
  const [request, setRequest] = useState<{ artifactId: string; result: ReferenceResult | null; error: string | null } | null>(null);

  useEffect(() => {
    if (!artifactId) return;
    let active = true;

    frameflowApi.getArtifact(artifactId)
      .then((detail) => {
        if (!active) return;
        const loaded = resultFromDetail(detail);
        if (!loaded) throw new Error("Reference analysis result could not be parsed.");
        setRequest({ artifactId, result: loaded, error: null });
      })
      .catch((loadError) => {
        if (!active) return;
        setRequest({ artifactId, result: null, error: loadError instanceof Error ? loadError.message : "Reference result loading failed" });
      });

    return () => { active = false; };
  }, [artifactId]);

  const matchingRequest = artifactId && request?.artifactId === artifactId ? request : null;
  const loading = Boolean(artifactId && !matchingRequest);
  const error = matchingRequest?.error ?? null;
  const result = artifactId ? matchingRequest?.result ?? (error ? fallbackResult : null) : fallbackResult;

  if (result) return <ResultDetail result={result} onBack={onBack} backLabel="Canvas" embedded />;
  return (
    <div className="view-page reference-results-page reference-result-detail reference-result-detail-embedded">
      <div className="reference-results-state">
        {loading ? <RefreshCw size={20} className="spin" /> : <FileChartColumnIncreasing size={24} />}
        <strong>{loading ? "Loading reference analysis…" : "Analysis result unavailable"}</strong>
        {error && <small>{error}</small>}
        {!loading && <Button type="button" variant="secondary" onClick={onBack}><ArrowLeft size={14} /> Canvas</Button>}
      </div>
    </div>
  );
}

export function ReferenceResultsView({
  selectedResultId,
  onOpenResult,
  onCloseResult,
}: {
  selectedResultId?: string;
  onOpenResult: (artifactId: string) => void;
  onCloseResult: () => void;
}) {
  const [results, setResults] = useState<ReferenceResult[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadResults = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const loaded = await fetchReferenceResults();
      setResults(loaded.results);
      if (loaded.missing) setError(`${loaded.missing} analysis result could not be parsed.`);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Reference result loading failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    fetchReferenceResults()
      .then((loaded) => {
        if (!active) return;
        setResults(loaded.results);
        if (loaded.missing) setError(`${loaded.missing} analysis result could not be parsed.`);
      })
      .catch((loadError) => { if (active) setError(loadError instanceof Error ? loadError.message : "Reference result loading failed"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const visibleResults = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return results.filter((result) => !normalized || `${resultTitle(result)} ${result.manifest.speech.text} ${result.manifest.provenance.semantic_model}`.toLowerCase().includes(normalized));
  }, [query, results]);
  const selectedResult = selectedResultId ? results.find((result) => result.asset.id === selectedResultId) : undefined;

  if (selectedResult) return <ResultDetail result={selectedResult} onBack={onCloseResult} />;
  if (selectedResultId && !loading) return (
    <div className="view-page reference-results-page">
      <div className="reference-results-state"><FileChartColumnIncreasing size={24} /><strong>Analysis result not found</strong><small>{selectedResultId}</small><Button type="button" variant="secondary" onClick={onCloseResult}><ArrowLeft size={14} /> Back to results</Button></div>
    </div>
  );

  return (
    <div className="view-page reference-results-page">
      <PageHeader
        title="Reference Results"
        description="Video Reference Analyzer가 만든 transcript, timeline, 컷, 액션, 화면 텍스트와 audio stems를 확인합니다."
        actions={<Button type="button" variant="secondary" onClick={() => void loadResults()} disabled={loading}><RefreshCw size={14} className={loading ? "spin" : ""} /> Refresh</Button>}
      />
      <div className="reference-results-toolbar">
        <SearchField value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search transcript, model, or result…" />
        <span>{visibleResults.length} results</span>
      </div>
      {error && <div className="reference-results-alert">{error}</div>}
      {loading && <div className="reference-results-state"><RefreshCw size={20} className="spin" /><strong>Loading reference analyses…</strong></div>}
      {!loading && !visibleResults.length && <div className="reference-results-state"><FileChartColumnIncreasing size={24} /><strong>No reference results yet</strong><small>Canvas에서 Video Reference Analyzer를 실행하면 완료된 분석이 여기에 표시됩니다.</small></div>}
      {!loading && visibleResults.length > 0 && <div className="reference-results-grid">{visibleResults.map((result) => <ResultCard result={result} onOpen={() => onOpenResult(result.asset.id)} key={result.asset.id} />)}</div>}
    </div>
  );
}
