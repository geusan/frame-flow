import type { FaceFrame } from "./face-state";

export class CameraSession {
  private worker: Worker | null = null;
  private stream: MediaStream | null = null;
  private frameId = 0;
  private generation = 0;
  private busy = false;
  private lastFrame = -Infinity;
  private videoUrl: string | null = null;
  private cancelInit: (() => void) | null = null;
  private video: HTMLVideoElement;
  private onFrame: (frame: FaceFrame) => void;
  private onStatus: (status: string, running: boolean) => void;
  constructor(video: HTMLVideoElement, onFrame: (frame: FaceFrame) => void, onStatus: (status: string, running: boolean) => void) {
    this.video = video; this.onFrame = onFrame; this.onStatus = onStatus;
  }

  async start(file?: File) {
    this.stop(false);
    const generation = this.generation;
    this.onStatus("얼굴 추적 준비 중…", false);
    try {
      if (!file && !navigator.mediaDevices?.getUserMedia) throw new Error("HTTPS 또는 localhost에서 카메라를 사용할 수 있습니다.");
      const worker = new Worker(new URL("../../workers/face-tracking.worker.ts", import.meta.url), { type: "module" });
      this.worker = worker;
      await new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(() => reject(new Error("얼굴 추적 모델 로딩 시간이 초과됐습니다.")), 45000);
        this.cancelInit = () => { clearTimeout(timeout); resolve(); };
        worker.onerror = () => { clearTimeout(timeout); reject(new Error("얼굴 추적 Worker를 불러오지 못했습니다.")); };
        worker.onmessage = (event) => {
          clearTimeout(timeout);
          if (event.data.type === "ready") resolve(); else reject(new Error(event.data.message));
        };
        worker.postMessage({ type: "init" });
      });
      if (generation !== this.generation) return;
      this.cancelInit = null;
      if (file) {
        this.videoUrl = URL.createObjectURL(file); this.video.src = this.videoUrl; this.video.loop = true;
      } else {
        this.onStatus("웹캠 사용 권한을 기다리는 중…", false);
        const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
        if (generation !== this.generation) { stream.getTracks().forEach((track) => track.stop()); return; }
        this.stream = stream; this.video.srcObject = stream;
        stream.getVideoTracks().forEach((track) => track.addEventListener("ended", () => { if (generation === this.generation) this.stop(); }));
      }
      await this.video.play();
      if (generation !== this.generation) return;
      worker.onmessage = (event: MessageEvent<{ type: string; frame: FaceFrame; message: string }>) => {
        if (generation !== this.generation) return;
        this.busy = false;
        if (event.data.type === "frame") this.onFrame(event.data.frame);
        else { this.stop(false); this.onStatus(event.data.message || "얼굴 추적 오류", false); }
      };
      worker.onerror = () => { if (generation !== this.generation) return; this.stop(false); this.onStatus("얼굴 추적 Worker가 중단됐습니다.", false); };
      this.onStatus(file ? "영상 테스트 · 로컬 추적" : "웹캠 연결됨 · 로컬 추적", true);
      const tick = (now: number) => {
        if (generation !== this.generation) return;
        this.frameId = requestAnimationFrame(tick);
        if (this.busy || now - this.lastFrame < 1000 / 24 || this.video.readyState < 2) return;
        this.busy = true;
        this.lastFrame = now;
        const scale = Math.min(1, 720 / Math.max(1, this.video.videoWidth, this.video.videoHeight));
        void createImageBitmap(this.video, { resizeWidth: Math.max(1, Math.round(this.video.videoWidth * scale)), resizeHeight: Math.max(1, Math.round(this.video.videoHeight * scale)), resizeQuality: "low" }).then((bitmap) => {
          if (generation !== this.generation) { bitmap.close(); return; }
          worker.postMessage({ type: "frame", bitmap, timestamp: now }, [bitmap]);
        }).catch(() => { this.busy = false; });
      };
      this.frameId = requestAnimationFrame(tick);
    } catch (error) {
      if (generation !== this.generation) return;
      this.stop(false);
      const message = error instanceof DOMException && error.name === "NotAllowedError" ? "카메라 권한이 거부됐습니다. 브라우저 권한을 확인해 주세요." : error instanceof Error ? error.message : "웹캠을 시작하지 못했습니다.";
      this.onStatus(message, false);
    }
  }

  stop(report = true) {
    this.generation++;
    this.cancelInit?.(); this.cancelInit = null;
    cancelAnimationFrame(this.frameId);
    this.worker?.terminate(); this.worker = null;
    this.stream?.getTracks().forEach((track) => track.stop()); this.stream = null;
    this.video.pause(); this.video.srcObject = null;
    this.video.removeAttribute("src"); this.video.load();
    if (this.videoUrl) URL.revokeObjectURL(this.videoUrl); this.videoUrl = null;
    this.busy = false; this.lastFrame = -Infinity;
    if (report) this.onStatus("웹캠 종료됨", false);
  }
}
