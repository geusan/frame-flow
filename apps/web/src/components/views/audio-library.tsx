"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, ExternalLink, FileAudio, RefreshCw, Waves, X } from "lucide-react";

import { SearchField } from "@/components/shared/search-field";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { frameflowApi, type ArtifactListItem } from "@/lib/api";
import { maximizePlaybackVolume } from "@/lib/media";

function formatBytes(value: number): string {
  if (!value) return "Size unavailable";
  if (value < 1_000_000) return `${Math.round(value / 1_000)} KB`;
  return `${(value / 1_000_000).toFixed(1)} MB`;
}

function formatDuration(durationMs: number): string {
  if (!durationMs) return "Duration on playback";
  const seconds = Math.round(durationMs / 1000);
  return `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
}

function sourceLabel(source: string): string {
  return {
    canvas_upload: "File upload",
    generated: "Generated",
    reference_audio_export: "Reference Analyzer",
  }[source] ?? source.replaceAll("_", " ");
}

function Waveform() {
  return <span className="audio-asset-waveform" aria-hidden>{[17, 29, 42, 23, 48, 33, 54, 21, 38, 46, 25, 50, 31, 41, 19, 35, 47, 26, 39, 18].map((height, index) => <i style={{ height: `${height}%` }} key={`${height}-${index}`} />)}</span>;
}

function AudioDetail({ asset, onClose }: { asset: ArtifactListItem; onClose: () => void }) {
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent className="audio-asset-dialog" overlayClassName="scene-search-backdrop">
      <DialogDescription className="sr-only">Listen to and download {asset.filename}</DialogDescription>
      <div className="scene-search-head"><span><small>Audio asset</small><DialogTitle asChild><strong title={asset.filename}>{asset.filename}</strong></DialogTitle></span><DialogClose asChild><button type="button" aria-label="Close audio"><X size={16} /></button></DialogClose></div>
      <div className="audio-asset-dialog-body">
        <span className="audio-asset-dialog-icon"><Waves size={30} /></span>
        <Waveform />
        <audio controls autoPlay preload="metadata" src={asset.url} aria-label={`${asset.filename} player`} onPlay={(event) => maximizePlaybackVolume(event.currentTarget)} />
        <div className="audio-asset-dialog-meta">
          <span><small>Source</small><strong>{sourceLabel(asset.source)}</strong></span>
          <span><small>Duration</small><strong>{formatDuration(asset.duration_ms)}</strong></span>
          <span><small>Size</small><strong>{formatBytes(asset.size_bytes)}</strong></span>
          <span><small>Created</small><strong>{new Date(asset.created_at).toLocaleString("ko-KR")}</strong></span>
        </div>
      </div>
      <div className="audio-asset-dialog-foot"><code>{asset.id}</code><div><Button variant="secondary" asChild><a href={asset.url} download><Download size={13} /> Download</a></Button><Button asChild><a href={asset.url} target="_blank" rel="noreferrer"><ExternalLink size={13} /> Open original</a></Button></div></div>
    </DialogContent>
  </Dialog>;
}

export function AudioLibrary({ selectedAssetId, onOpenAsset, onCloseAsset }: { selectedAssetId?: string; onOpenAsset: (artifactId: string) => void; onCloseAsset: () => void }) {
  const [assets, setAssets] = useState<ArtifactListItem[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAssets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setAssets(await frameflowApi.listAllArtifacts(["Audio"]));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Audio asset loading failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    frameflowApi.listAllArtifacts(["Audio"])
      .then((items) => { if (active) setAssets(items); })
      .catch((loadError) => { if (active) setError(loadError instanceof Error ? loadError.message : "Audio asset loading failed"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const visibleAssets = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return assets.filter((asset) => !normalized || `${asset.filename} ${asset.source}`.toLowerCase().includes(normalized));
  }, [assets, query]);
  const selectedAsset = selectedAssetId ? assets.find((asset) => asset.id === selectedAssetId) : undefined;

  return <div className="view-page asset-page audio-asset-page">
    <div className="asset-toolbar asset-toolbar-simple">
      <SearchField className="asset-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search audio…" />
      <Button type="button" variant="secondary" onClick={() => void loadAssets()} disabled={loading}><RefreshCw size={14} className={loading ? "spin" : ""} /> Refresh</Button>
    </div>

    {error && <div className="asset-library-state error">{error}</div>}
    {!error && loading && <div className="asset-library-state"><RefreshCw size={18} className="spin" /> Loading audio…</div>}
    {!error && !loading && !visibleAssets.length && <div className="asset-library-state"><span className="asset-empty-icon"><FileAudio size={22} /></span><strong>No audio found</strong><small>Reference Results에서 stem을 Audio에 추가하거나 Canvas에서 오디오 파일을 업로드하세요.</small></div>}

    {!error && !loading && visibleAssets.length > 0 && <div className="audio-asset-grid">
      {visibleAssets.map((asset) => <article className="audio-asset-card" key={asset.id}>
        <button type="button" className="audio-asset-card-open" onClick={() => onOpenAsset(asset.id)} aria-label={`Open ${asset.filename}`}><span><FileAudio size={17} /></span><strong title={asset.filename}>{asset.filename}</strong><small>{sourceLabel(asset.source)}</small></button>
        <Waveform />
        <audio controls preload="none" src={asset.url} aria-label={`${asset.filename} preview`} onPlay={(event) => maximizePlaybackVolume(event.currentTarget)} />
        <footer><span>{formatDuration(asset.duration_ms)} · {formatBytes(asset.size_bytes)}</span><time>{new Date(asset.created_at).toLocaleDateString("ko-KR")}</time></footer>
      </article>)}
    </div>}

    {selectedAsset && <AudioDetail asset={selectedAsset} onClose={onCloseAsset} key={selectedAsset.id} />}
  </div>;
}
