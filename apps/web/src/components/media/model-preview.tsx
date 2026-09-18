"use client";

import { useEffect, useRef, useState } from "react";
import type { ModelViewerElement } from "@google/model-viewer";
import { Download, LoaderCircle, RotateCcw, Camera } from "lucide-react";
import Link from "next/link";
import styles from "./model-preview.module.css";

const DEFAULT_ORBIT = "45deg 80deg 105%";

export function ModelPreview({ src, title, artifactId }: { src: string; title: string; artifactId?: string }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<ModelViewerElement | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    let disposed = false;
    let viewer: ModelViewerElement | undefined;
    const onLoad = () => { if (!disposed) setStatus("ready"); };
    const onError = () => { if (!disposed) setStatus("error"); };
    // Load the WebGL renderer only while the detail preview is open, never
    // during SSR or once per card on a large Canvas.
    void import("@google/model-viewer").then(() => {
      if (disposed) return;
      viewer = document.createElement("model-viewer") as ModelViewerElement;
      viewer.addEventListener("load", onLoad);
      viewer.addEventListener("error", onError);
      viewer.src = src;
      viewer.alt = title;
      viewer.cameraControls = true;
      viewer.cameraOrbit = DEFAULT_ORBIT;
      viewer.environmentImage = "neutral";
      viewer.shadowIntensity = 0.7;
      viewer.touchAction = "none";
      viewer.interactionPrompt = "none";
      viewer.className = styles.viewer;
      viewerRef.current = viewer;
      mount.appendChild(viewer);
    }).catch(onError);
    return () => {
      disposed = true;
      viewer?.removeEventListener("load", onLoad);
      viewer?.removeEventListener("error", onError);
      viewer?.remove();
      viewerRef.current = null;
    };
  }, [src, title]);

  const resetView = () => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.cameraOrbit = DEFAULT_ORBIT;
    viewer.cameraTarget = "auto auto auto";
    viewer.fieldOfView = "auto";
    viewer.jumpCameraToGoal();
  };

  return <div className={styles.preview} data-model-status={status}>
    <div ref={mountRef} className={styles.stage} aria-label="3D model preview" />
    {status === "loading" && <div className={styles.message} role="status"><LoaderCircle className="spin" size={20} /><span>3D 모델 불러오는 중…</span></div>}
    {status === "error" && <div className={styles.message} role="alert"><strong>3D 미리보기를 불러오지 못했습니다.</strong><span>아래에서 GLB를 다운로드해 확인할 수 있습니다.</span></div>}
    <footer className={styles.toolbar}>
      <span>드래그로 회전 · 휠로 확대/축소</span>
      <div>
        {artifactId && <Link href={`/live-avatar/${encodeURIComponent(artifactId)}`}><Camera size={14} /> 웹캠 연결</Link>}
        <button type="button" onClick={resetView} disabled={status !== "ready"}><RotateCcw size={14} /> 초기 시점</button>
        <a href={src} download="character.glb" target="_blank" rel="noreferrer"><Download size={14} /> GLB 다운로드</a>
      </div>
    </footer>
  </div>;
}
