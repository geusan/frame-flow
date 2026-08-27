"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Camera,
  CircleCheck,
  ExternalLink,
  Film,
  GitBranch,
  HardDrive,
  Image as ImageIcon,
  Play,
  RefreshCw,
  Search,
  Sparkles,
  X,
} from "lucide-react";

import { frameflowApi, type ArtifactLineageGraph, type ArtifactListItem, type CapturedFrameArtifact, type SceneSearchCandidate, type SceneSearchResult } from "@/lib/api";

type AssetTab = "images" | "videos";
type SceneSearchProvider = "google" | "openai";

const sceneSearchModels: Record<SceneSearchProvider, Array<{ value: string; label: string }>> = {
  google: [
    { value: "google.text.fast", label: "Gemini Flash" },
    { value: "google.text.quality", label: "Gemini Pro" },
  ],
  openai: [
    { value: "openai.text.fast", label: "GPT-5.6 Luna" },
    { value: "openai.text.quality", label: "GPT-5.6 Terra" },
    { value: "openai.chat.latest", label: "ChatGPT Latest" },
  ],
};

function isVideo(asset: ArtifactListItem): boolean {
  return asset.type === "Video" || asset.type === "FinalVideo";
}

function sourceLabel(source?: string): string {
  if (!source) return "Artifact";
  return {
    canvas_upload: "File upload",
    canvas_url_import: "URL import",
    video_frame_capture: "Frame capture",
    generated: "Generated",
    artifact: "Artifact",
  }[source] ?? source.replaceAll("_", " ");
}

function formatBytes(value?: number): string {
  if (!value) return "Size unavailable";
  if (value < 1_000_000) return `${(value / 1_000).toFixed(0)} KB`;
  return `${(value / 1_000_000).toFixed(1)} MB`;
}

function formatDuration(durationMs?: number): string | null {
  if (!durationMs) return null;
  const seconds = Math.round(durationMs / 1000);
  return `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
}

function formatPlaybackTimestamp(timestampMs: number): string {
  const totalTenths = Math.max(0, Math.floor(timestampMs / 100));
  const tenths = totalTenths % 10;
  const totalSeconds = Math.floor(totalTenths / 10);
  return `${Math.floor(totalSeconds / 60).toString().padStart(2, "0")}:${(totalSeconds % 60).toString().padStart(2, "0")}.${tenths}`;
}

function lineageColumns(graph: ArtifactLineageGraph): Array<{ level: number; nodes: ArtifactLineageGraph["nodes"] }> {
  const levels = new Map<string, number>([[graph.root_artifact_id, 0]]);
  for (let pass = 0; pass < graph.nodes.length; pass += 1) {
    let changed = false;
    for (const edge of graph.edges) {
      const parentLevel = levels.get(edge.parent_artifact_id);
      const childLevel = levels.get(edge.child_artifact_id);
      if (parentLevel !== undefined && childLevel === undefined) {
        levels.set(edge.child_artifact_id, parentLevel + 1);
        changed = true;
      } else if (childLevel !== undefined && parentLevel === undefined) {
        levels.set(edge.parent_artifact_id, childLevel - 1);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const grouped = new Map<number, ArtifactLineageGraph["nodes"]>();
  for (const node of graph.nodes) {
    const level = levels.get(node.id) ?? 0;
    grouped.set(level, [...(grouped.get(level) ?? []), node]);
  }
  return [...grouped.entries()].sort(([left], [right]) => left - right).map(([level, nodes]) => ({ level, nodes }));
}

function ComparisonMedia({ node, label, seekMs = 0 }: { node: ArtifactLineageGraph["nodes"][number]; label: string; seekMs?: number }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  return <div className="asset-compare-item">
    <span>{label}</span>
    <div className="asset-compare-media">
      {isVideo(node)
        ? <video ref={videoRef} src={node.url} controls muted playsInline preload="metadata" onLoadedMetadata={(event) => { event.currentTarget.currentTime = Math.min(seekMs / 1000, event.currentTarget.duration || 0); }} />
        : <div role="img" aria-label={node.filename} style={{ backgroundImage: `url(${node.url})` }} />}
    </div>
    <strong title={node.filename}>{node.filename}</strong>
  </div>;
}

function AssetLineageDrawer({ asset, onClose }: { asset: ArtifactListItem; onClose: () => void }) {
  const [lineage, setLineage] = useState<ArtifactLineageGraph | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    frameflowApi.getArtifactLineage(asset.id)
      .then((graph) => { if (active) setLineage(graph); })
      .catch((loadError) => { if (active) setError(loadError instanceof Error ? loadError.message : "Lineage loading failed"); });
    return () => { active = false; };
  }, [asset.id]);

  const columns = lineage ? lineageColumns(lineage) : [];
  const nodeById = new Map((lineage?.nodes ?? []).map((node) => [node.id, node]));
  const rootNode = lineage?.nodes.find((node) => node.id === lineage.root_artifact_id);
  const parentEdge = lineage?.edges.find((edge) => edge.child_artifact_id === lineage.root_artifact_id);
  const parentNode = parentEdge ? nodeById.get(parentEdge.parent_artifact_id) : undefined;
  const comparableTypes = new Set(["Image", "Video", "FinalVideo"]);
  const canCompare = Boolean(rootNode && parentNode && comparableTypes.has(rootNode.type) && comparableTypes.has(parentNode.type));
  const captureMetadata = (rootNode?.metadata.capture ?? {}) as { timestamp_ms?: number };
  return <div className="asset-detail-backdrop" role="presentation" onMouseDown={onClose}>
    <aside className="asset-detail-drawer" role="dialog" aria-modal="true" aria-label={`Asset details for ${asset.filename}`} onMouseDown={(event) => event.stopPropagation()}>
      <div className="asset-detail-head"><span><small>Artifact lineage</small><strong title={asset.filename}>{asset.filename}</strong></span><button type="button" onClick={onClose} aria-label="Close asset details"><X size={16} /></button></div>
      <div className="asset-detail-scroll">
        <div className={`asset-detail-preview ${isVideo(asset) ? "video" : "image"}`}>
          {isVideo(asset) ? <video src={asset.url} controls muted playsInline preload="metadata" /> : <div role="img" aria-label={asset.filename} style={{ backgroundImage: `url(${asset.url})` }} />}
        </div>
        <div className="asset-detail-summary">
          <div><small>Type</small><strong>{isVideo(asset) ? "Video" : "Image"}</strong></div>
          <div><small>Source</small><strong>{sourceLabel(asset.source)}</strong></div>
          <div><small>Size</small><strong>{formatBytes(asset.size_bytes)}</strong></div>
          <div><small>Created</small><strong>{new Date(asset.created_at).toLocaleString("ko-KR")}</strong></div>
        </div>

        {rootNode && <section className="asset-derivation-section">
          <div className="asset-detail-section-head"><span><GitBranch size={14} /> How this asset was created</span><small>{rootNode.derivation.operation}</small></div>
          <div className="asset-derivation-card">
            <strong>{rootNode.derivation.title}</strong>
            <p>{rootNode.derivation.description}</p>
            {rootNode.derivation.prompt && <div><small>Prompt</small><blockquote>{rootNode.derivation.prompt}</blockquote></div>}
            <div className="asset-derivation-meta">
              {rootNode.derivation.model_alias && <span><small>Model</small><strong>{rootNode.derivation.model_alias}</strong></span>}
              {rootNode.derivation.exact_model_id && <span><small>Exact version</small><strong>{rootNode.derivation.exact_model_id}</strong></span>}
              {rootNode.derivation.execution_mode && <span><small>Execution</small><strong>{rootNode.derivation.execution_mode}</strong></span>}
            </div>
            {!!Object.keys(rootNode.derivation.parameters ?? {}).length && <details><summary>Parameters</summary><pre>{JSON.stringify(rootNode.derivation.parameters, null, 2)}</pre></details>}
          </div>
        </section>}

        {canCompare && rootNode && parentNode && <section className="asset-comparison-section">
          <div className="asset-detail-section-head"><span>Before / After</span><small>{parentEdge?.role ?? "input"}</small></div>
          <div className="asset-comparison-grid">
            <ComparisonMedia node={parentNode} label="Before" seekMs={Number(captureMetadata.timestamp_ms ?? 0)} />
            <ComparisonMedia node={rootNode} label="After" />
          </div>
        </section>}

        <section className="asset-lineage-section">
          <div className="asset-detail-section-head"><span><GitBranch size={14} /> Lineage graph</span><small>{lineage ? `${lineage.nodes.length} assets · ${lineage.edges.length} relations` : "Loading…"}</small></div>
          {error && <div className="asset-lineage-state error">{error}</div>}
          {!error && !lineage && <div className="asset-lineage-state"><RefreshCw size={15} className="spin" /> Loading lineage…</div>}
          {lineage && <>
            <div className="asset-lineage-graph">
              {columns.map((column) => <div className="asset-lineage-column" key={column.level}>
                <small>{column.level < 0 ? "Ancestors" : column.level > 0 ? "Derived" : "Selected"}</small>
                {column.nodes.map((node) => <article className={node.is_root ? "root" : ""} key={node.id}>
                  <span>{node.type === "Image" ? <ImageIcon size={13} /> : <Film size={13} />}</span>
                  <div><strong title={node.filename}>{node.filename}</strong><small>{node.type} · {node.id.slice(0, 10)}</small></div>
                </article>)}
              </div>)}
            </div>
            {!!lineage.edges.length && <div className="asset-lineage-relations">{lineage.edges.map((edge) => <div key={edge.id}><span><strong>{nodeById.get(edge.parent_artifact_id)?.filename ?? edge.parent_artifact_id}</strong><small>{edge.role}</small></span><span>→</span><span><strong>{nodeById.get(edge.child_artifact_id)?.filename ?? edge.child_artifact_id}</strong><small>{edge.operation_id ?? "derived"}</small></span></div>)}</div>}
            {!lineage.edges.length && <div className="asset-lineage-state">This is a root asset with no recorded derivations.</div>}
          </>}
        </section>
      </div>
      <div className="asset-detail-foot"><code>{asset.id}</code><button type="button" onClick={() => window.open(asset.url, "_blank", "noopener,noreferrer")}><ExternalLink size={13} /> Open original</button></div>
    </aside>
  </div>;
}

function SceneSearchDialog({ asset, onClose, onCaptured }: { asset: ArtifactListItem; onClose: () => void; onCaptured: (captured: CapturedFrameArtifact) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const videoStageRef = useRef<HTMLDivElement>(null);
  const [prompt, setPrompt] = useState("");
  const [provider, setProvider] = useState<SceneSearchProvider>("google");
  const [modelAlias, setModelAlias] = useState("google.text.fast");
  const [result, setResult] = useState<SceneSearchResult | null>(null);
  const [selected, setSelected] = useState<SceneSearchCandidate | null>(null);
  const [searching, setSearching] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [currentTimestampMs, setCurrentTimestampMs] = useState(0);
  const [videoDimensions, setVideoDimensions] = useState<{ width: number; height: number } | null>(null);
  const [playerSize, setPlayerSize] = useState<{ width: number; height: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selected || !videoRef.current || videoRef.current.readyState < 1) return;
    videoRef.current.currentTime = Math.min(selected.timestamp_ms / 1000, videoRef.current.duration || 0);
  }, [selected]);

  useEffect(() => {
    const stage = videoStageRef.current;
    if (!stage || !videoDimensions?.width || !videoDimensions.height) return;
    const fitPlayer = () => {
      const style = window.getComputedStyle(stage);
      const availableWidth = Math.max(1, stage.clientWidth - Number.parseFloat(style.paddingLeft) - Number.parseFloat(style.paddingRight));
      const availableHeight = Math.max(1, stage.clientHeight - Number.parseFloat(style.paddingTop) - Number.parseFloat(style.paddingBottom));
      const videoRatio = videoDimensions.width / videoDimensions.height;
      const stageRatio = availableWidth / availableHeight;
      const next = stageRatio > videoRatio
        ? { width: availableHeight * videoRatio, height: availableHeight }
        : { width: availableWidth, height: availableWidth / videoRatio };
      setPlayerSize((current) => current && Math.abs(current.width - next.width) < 1 && Math.abs(current.height - next.height) < 1 ? current : next);
    };
    fitPlayer();
    const observer = new ResizeObserver(fitPlayer);
    observer.observe(stage);
    return () => observer.disconnect();
  }, [videoDimensions]);

  const searchScenes = async () => {
    if (!prompt.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const nextResult = await frameflowApi.searchVideoScenes(asset.id, prompt.trim(), provider, modelAlias);
      setResult(nextResult);
      setSelected(nextResult.candidates[0] ?? null);
    } catch (searchError) {
      setError(searchError instanceof Error ? searchError.message : "Scene search failed");
    } finally {
      setSearching(false);
    }
  };

  const captureSelected = async () => {
    if (!result || !selected) return;
    setCapturing(true);
    setError(null);
    try {
      const captured = await frameflowApi.captureVideoFrame(asset.id, selected.timestamp_ms, {
        search_id: result.search_id,
        search_prompt: result.prompt,
        search_score: selected.score,
        search_reason: selected.reason,
        search_provider: result.provider as SceneSearchProvider,
        search_model_alias: result.model_alias,
        search_model: result.exact_model_id,
        provider_request_id: result.provider_request_id,
      });
      onCaptured(captured);
      onClose();
    } catch (captureError) {
      setError(captureError instanceof Error ? captureError.message : "Scene capture failed");
    } finally {
      setCapturing(false);
    }
  };

  const captureCurrent = async () => {
    const timestampMs = Math.max(0, Math.round((videoRef.current?.currentTime ?? 0) * 1000));
    setCapturing(true);
    setError(null);
    try {
      onCaptured(await frameflowApi.captureVideoFrame(asset.id, timestampMs));
      onClose();
    } catch (captureError) {
      setError(captureError instanceof Error ? captureError.message : "Frame capture failed");
    } finally {
      setCapturing(false);
    }
  };

  return <div className="scene-search-backdrop" role="presentation" onMouseDown={onClose}>
    <section className="scene-search-dialog video-asset-dialog" role="dialog" aria-modal="true" aria-label={`Play and search ${asset.filename}`} onMouseDown={(event) => event.stopPropagation()}>
      <div className="scene-search-head"><span><small>Video asset</small><strong>{asset.filename}</strong></span><button type="button" onClick={onClose} aria-label="Close video"><X size={16} /></button></div>
      <div className="scene-search-body">
        <div className="scene-search-source" ref={videoStageRef}>
          <video ref={videoRef} src={asset.url} controls muted playsInline autoPlay preload="metadata" style={{ aspectRatio: videoDimensions ? `${videoDimensions.width} / ${videoDimensions.height}` : "auto", width: playerSize?.width, height: playerSize?.height }} onLoadedMetadata={(event) => {
            setVideoDimensions({ width: event.currentTarget.videoWidth, height: event.currentTarget.videoHeight });
            setCurrentTimestampMs(Math.round(event.currentTarget.currentTime * 1000));
            if (selected) event.currentTarget.currentTime = Math.min(selected.timestamp_ms / 1000, event.currentTarget.duration || 0);
          }} onTimeUpdate={(event) => setCurrentTimestampMs(Math.round(event.currentTarget.currentTime * 1000))} />
        </div>
        <aside className="scene-search-panel">
          <section className="video-asset-description">
            <small>About this video</small>
            <h3>{asset.filename}</h3>
            <p>{sourceLabel(asset.source)}로 저장된 영상입니다. 영상을 직접 재생하거나, 아래 프롬프트로 원하는 장면을 찾아 해당 시점으로 이동할 수 있습니다.</p>
            <div><span><small>Resolution</small><strong>{videoDimensions ? `${videoDimensions.width} × ${videoDimensions.height}` : "Loading…"}</strong></span><span><small>Duration</small><strong>{formatDuration(asset.duration_ms) ?? "—"}</strong></span><span><small>Size</small><strong>{formatBytes(asset.size_bytes)}</strong></span></div>
          </section>
          <section className="scene-search-compose">
            <div><span><Sparkles size={14} /> Prompt scene search</span><small>Describe a visual moment</small></div>
            <form onSubmit={(event) => { event.preventDefault(); void searchScenes(); }}>
              <label><Search size={14} /><input value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="예: 인물이 카메라를 바라보는 장면" autoFocus /></label>
              <button type="submit" disabled={searching || !prompt.trim()}>{searching ? <RefreshCw size={14} className="spin" /> : <Sparkles size={14} />}{searching ? "Searching…" : "Search"}</button>
            </form>
            <div className="scene-search-model-settings">
              <label><span>Provider</span><select value={provider} onChange={(event) => { const nextProvider = event.target.value as SceneSearchProvider; setProvider(nextProvider); setModelAlias(sceneSearchModels[nextProvider][0].value); setResult(null); setSelected(null); }}><option value="google">Google</option><option value="openai">OpenAI</option></select></label>
              <label><span>Model</span><select value={modelAlias} onChange={(event) => { setModelAlias(event.target.value); setResult(null); setSelected(null); }}>{sceneSearchModels[provider].map((model) => <option value={model.value} key={model.value}>{model.label}</option>)}</select></label>
            </div>
            {result && <div className="scene-search-provider"><span>{result.provider} · {result.model_alias} → {result.exact_model_id}</span><code>{result.provider_request_id}</code></div>}
            {error && <div className="scene-search-error">{error}</div>}
          </section>
          <div className="scene-search-results">
            <div><strong>Scene candidates</strong><small>{result ? `${result.candidates.length} matches` : "프롬프트를 입력해 장면을 검색하세요"}</small></div>
            {!result && !searching && <div className="scene-search-empty"><Sparkles size={22} /><span>프롬프트와 가장 관련 있는 장면을 찾아 타임스탬프와 점수로 보여줍니다.</span></div>}
            {searching && <div className="scene-search-empty"><RefreshCw size={22} className="spin" /><span>Sampling and ranking video frames…</span></div>}
            {result && <div className="scene-candidate-grid">{result.candidates.map((candidate) => <button type="button" className={selected?.index === candidate.index ? "selected" : ""} onClick={() => setSelected(candidate)} key={`${candidate.index}-${candidate.timestamp_ms}`}>
              <span style={{ backgroundImage: `url(${candidate.thumbnail_data_url})` }}><Play size={15} fill="currentColor" /><b>{formatPlaybackTimestamp(candidate.timestamp_ms)}</b></span>
              <div><strong>{Math.round(candidate.score * 100)}% match</strong><small>{candidate.reason}</small></div>
            </button>)}</div>}
          </div>
        </aside>
      </div>
      <div className="scene-search-foot"><span>{selected ? `Selected · ${formatPlaybackTimestamp(selected.timestamp_ms)} · ${Math.round(selected.score * 100)}%` : `Current · ${formatPlaybackTimestamp(currentTimestampMs)}`}</span><div><button type="button" onClick={() => void captureCurrent()} disabled={capturing}><Camera size={14} /> Capture current frame</button><button type="button" onClick={() => void captureSelected()} disabled={!selected || capturing}><Sparkles size={14} /> Capture searched frame</button></div></div>
    </section>
  </div>;
}

function AssetCard({ asset, onInspect, onOpenVideo }: { asset: ArtifactListItem; onInspect: () => void; onOpenVideo: () => void }) {
  const [videoDimensions, setVideoDimensions] = useState<{ width: number; height: number } | null>(null);
  const [aspectRatio, setAspectRatio] = useState(16 / 10);
  const duration = formatDuration(asset.duration_ms);
  const galleryStyle = {
    "--asset-ratio": aspectRatio,
    "--asset-basis": `${aspectRatio * 260}px`,
  } as CSSProperties;

  return <article className={`asset-card ${isVideo(asset) ? "video" : "image"}`} style={galleryStyle}>
    <div className={`asset-card-media ${isVideo(asset) ? "video" : "image"}`} role={isVideo(asset) ? "button" : undefined} tabIndex={isVideo(asset) ? 0 : undefined} aria-label={isVideo(asset) ? `Play ${asset.filename}` : undefined} onClick={() => { if (isVideo(asset)) onOpenVideo(); }} onKeyDown={(event) => { if (isVideo(asset) && ["Enter", " "].includes(event.key)) { event.preventDefault(); onOpenVideo(); } }}>
      {isVideo(asset)
        ? <video
            src={asset.url}
            muted
            playsInline
            preload="metadata"
            onLoadedMetadata={(event) => {
              setVideoDimensions({ width: event.currentTarget.videoWidth, height: event.currentTarget.videoHeight });
              if (event.currentTarget.videoWidth && event.currentTarget.videoHeight) setAspectRatio(event.currentTarget.videoWidth / event.currentTarget.videoHeight);
            }}
          />
        : <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img className="asset-card-image" src={asset.url} alt={asset.filename} loading="lazy" onLoad={(event) => {
              if (event.currentTarget.naturalWidth && event.currentTarget.naturalHeight) setAspectRatio(event.currentTarget.naturalWidth / event.currentTarget.naturalHeight);
            }} />
          </>}
      {isVideo(asset) && <span className="asset-video-dialog-trigger"><Play size={20} fill="currentColor" /></span>}
      <div className="asset-tile-top">
        <span className="asset-kind-badge">{isVideo(asset) ? <Film size={11} /> : <ImageIcon size={11} />}{isVideo(asset) ? "Video" : "Image"}</span>
        <span className="asset-tile-quick-actions">
          {duration && <small>{duration}</small>}
          <button type="button" onClick={(event) => { event.stopPropagation(); onInspect(); }} aria-label={`View lineage for ${asset.filename}`}><GitBranch size={13} /></button>
          <button type="button" onClick={(event) => { event.stopPropagation(); window.open(asset.url, "_blank", "noopener,noreferrer"); }} aria-label={`Open ${asset.filename}`}><ExternalLink size={13} /></button>
        </span>
      </div>
      <div className="asset-tile-info">
        <strong title={asset.filename}>{asset.filename}</strong>
        <span>{sourceLabel(asset.source)} · {formatBytes(asset.size_bytes)} · {new Date(asset.created_at).toLocaleDateString("ko-KR")}</span>
        {isVideo(asset) && <span>Original {videoDimensions ? `${videoDimensions.width}×${videoDimensions.height}` : "ratio"} · Click to play</span>}
      </div>
    </div>
  </article>;
}

export function AssetLibrary() {
  const [assets, setAssets] = useState<ArtifactListItem[]>([]);
  const [tab, setTab] = useState<AssetTab>("images");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [capturedAsset, setCapturedAsset] = useState<CapturedFrameArtifact | null>(null);
  const [inspectedAsset, setInspectedAsset] = useState<ArtifactListItem | null>(null);
  const [sceneSearchAsset, setSceneSearchAsset] = useState<ArtifactListItem | null>(null);

  const loadAssets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await frameflowApi.listAllArtifacts(["Image", "Video", "FinalVideo"]);
      setAssets(items);
      setTab((current) => current === "images" && !items.some((item) => item.type === "Image") && items.some(isVideo) ? "videos" : current);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Asset loading failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    frameflowApi.listAllArtifacts(["Image", "Video", "FinalVideo"])
      .then((items) => {
        if (!active) return;
        setAssets(items);
        setTab((current) => current === "images" && !items.some((item) => item.type === "Image") && items.some(isVideo) ? "videos" : current);
      })
      .catch((loadError) => { if (active) setError(loadError instanceof Error ? loadError.message : "Asset loading failed"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const imageCount = assets.filter((asset) => asset.type === "Image").length;
  const videoCount = assets.filter(isVideo).length;
  const visibleAssets = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return assets.filter((asset) => {
      const matchesTab = tab === "images" ? asset.type === "Image" : isVideo(asset);
      return matchesTab && (!normalizedQuery || `${asset.filename} ${asset.source} ${asset.type}`.toLowerCase().includes(normalizedQuery));
    });
  }, [assets, query, tab]);

  const handleCaptured = useCallback((captured: CapturedFrameArtifact) => {
    setAssets((current) => [captured, ...current.filter((asset) => asset.id !== captured.id)]);
    setCapturedAsset(captured);
  }, []);

  return (
    <div className="view-page asset-page">
      <div className="view-heading">
        <div>
          <h2>Asset Library</h2>
          <p>업로드하거나 생성한 이미지와 비디오를 한곳에서 확인하고 Canvas에서 다시 사용할 수 있습니다.</p>
        </div>
        <button type="button" className="secondary-button" onClick={() => void loadAssets()} disabled={loading}>
          <RefreshCw size={14} className={loading ? "spin" : ""} /> Refresh
        </button>
      </div>

      <div className="asset-summary">
        <button type="button" className={tab === "images" ? "active" : ""} onClick={() => setTab("images")}>
          <span className="asset-summary-icon image"><ImageIcon size={17} /></span>
          <span><small>Images</small><strong>{imageCount}</strong></span>
        </button>
        <button type="button" className={tab === "videos" ? "active" : ""} onClick={() => setTab("videos")}>
          <span className="asset-summary-icon video"><Film size={17} /></span>
          <span><small>Videos</small><strong>{videoCount}</strong></span>
        </button>
        <div className="asset-storage-note"><HardDrive size={16} /><span><strong>{imageCount + videoCount} media assets</strong><small>Newest assets are shown first</small></span></div>
      </div>

      <div className="asset-toolbar">
        <div className="asset-tabs" role="tablist" aria-label="Asset type">
          <button type="button" role="tab" aria-selected={tab === "images"} className={tab === "images" ? "active" : ""} onClick={() => setTab("images")}><ImageIcon size={14} /> Images <span>{imageCount}</span></button>
          <button type="button" role="tab" aria-selected={tab === "videos"} className={tab === "videos" ? "active" : ""} onClick={() => setTab("videos")}><Film size={14} /> Videos <span>{videoCount}</span></button>
        </div>
        <label className="input-shell asset-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Search ${tab}…`} /></label>
      </div>

      {capturedAsset && <div className="asset-capture-notice"><CircleCheck size={16} /><span><strong>Frame saved as an image asset</strong><small>{capturedAsset.filename}</small></span><button type="button" onClick={() => { setTab("images"); setQuery(capturedAsset.filename); setCapturedAsset(null); }}>View image</button><button type="button" className="close" onClick={() => setCapturedAsset(null)} aria-label="Dismiss capture notice">×</button></div>}

      {error && <div className="asset-library-state error">{error}</div>}
      {!error && loading && <div className="asset-library-state"><RefreshCw size={18} className="spin" /> Loading assets…</div>}
      {!error && !loading && !visibleAssets.length && <div className="asset-library-state"><span className="asset-empty-icon">{tab === "images" ? <ImageIcon size={22} /> : <Film size={22} />}</span><strong>No {tab} found</strong><small>Canvas에서 파일을 업로드하거나 영상 URL을 붙여넣으면 여기에 표시됩니다.</small></div>}

      {!error && !loading && visibleAssets.length > 0 && (
        <div className="asset-grid">
          {visibleAssets.map((asset) => <AssetCard asset={asset} onInspect={() => setInspectedAsset(asset)} onOpenVideo={() => setSceneSearchAsset(asset)} key={asset.id} />)}
        </div>
      )}
      {inspectedAsset && <AssetLineageDrawer asset={inspectedAsset} onClose={() => setInspectedAsset(null)} key={inspectedAsset.id} />}
      {sceneSearchAsset && <SceneSearchDialog asset={sceneSearchAsset} onClose={() => setSceneSearchAsset(null)} onCaptured={handleCaptured} key={sceneSearchAsset.id} />}
    </div>
  );
}
