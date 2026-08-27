"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Camera,
  CircleCheck,
  ExternalLink,
  Film,
  HardDrive,
  Image as ImageIcon,
  RefreshCw,
  Search,
} from "lucide-react";

import { frameflowApi, type ArtifactListItem, type CapturedFrameArtifact } from "@/lib/api";

type AssetTab = "images" | "videos";

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

function AssetCard({ asset, onCaptured }: { asset: ArtifactListItem; onCaptured: (captured: CapturedFrameArtifact) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentTimestampMs, setCurrentTimestampMs] = useState(0);
  const [capturing, setCapturing] = useState(false);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const duration = formatDuration(asset.duration_ms);
  const currentTimestamp = formatPlaybackTimestamp(currentTimestampMs);

  const captureCurrentFrame = async () => {
    if (!isVideo(asset)) return;
    const timestampMs = Math.max(0, Math.round((videoRef.current?.currentTime ?? 0) * 1000));
    setCapturing(true);
    setCaptureError(null);
    try {
      onCaptured(await frameflowApi.captureVideoFrame(asset.id, timestampMs));
    } catch (error) {
      setCaptureError(error instanceof Error ? error.message : "Frame capture failed");
    } finally {
      setCapturing(false);
    }
  };

  return <article className="asset-card">
    <div className={`asset-card-media ${isVideo(asset) ? "video" : "image"}`}>
      {isVideo(asset)
        ? <video
            ref={videoRef}
            src={asset.url}
            controls
            muted
            playsInline
            preload="metadata"
            onLoadedMetadata={(event) => setCurrentTimestampMs(Math.round(event.currentTarget.currentTime * 1000))}
            onTimeUpdate={(event) => setCurrentTimestampMs(Math.round(event.currentTarget.currentTime * 1000))}
            onSeeked={(event) => setCurrentTimestampMs(Math.round(event.currentTarget.currentTime * 1000))}
          />
        : <div className="asset-card-image" role="img" aria-label={asset.filename} style={{ backgroundImage: `url(${asset.url})` }} />}
      <span className="asset-kind-badge">{isVideo(asset) ? <Film size={11} /> : <ImageIcon size={11} />}{isVideo(asset) ? "Video" : "Image"}</span>
      {duration && <span className="asset-duration">{duration}</span>}
    </div>
    <div className="asset-card-copy">
      <div className="asset-card-title"><strong title={asset.filename}>{asset.filename}</strong><button type="button" onClick={() => window.open(asset.url, "_blank", "noopener,noreferrer")} aria-label={`Open ${asset.filename}`}><ExternalLink size={13} /></button></div>
      <span><small>{sourceLabel(asset.source)}</small><i /> <small>{formatBytes(asset.size_bytes)}</small></span>
      <time dateTime={asset.created_at}>{new Date(asset.created_at).toLocaleString("ko-KR")}</time>
      {isVideo(asset) && <div className="asset-capture-actions">
        <span><small>Current frame</small><strong>{currentTimestamp}</strong></span>
        <button className="asset-capture-button" type="button" onClick={() => void captureCurrentFrame()} disabled={capturing}><Camera size={13} /> {capturing ? "Capturing…" : "Capture frame"}</button>
      </div>}
      {captureError && <p className="asset-capture-error">{captureError}</p>}
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
          {visibleAssets.map((asset) => <AssetCard asset={asset} onCaptured={handleCaptured} key={asset.id} />)}
        </div>
      )}
    </div>
  );
}
