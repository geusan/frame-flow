import type { HolisticWorkerMessage } from "@/lib/motion-preview";
import type { PerformanceFrame } from "./rig";

export class BodyTrackingSession {
  private worker: Worker | null = null;
  private stream: MediaStream | null = null;
  private generation = 0;
  private frameId = 0;
  private busy = false;
  private lastFrame = -Infinity;
  private objectUrl: string | null = null;
  private cancelInit: (() => void) | null = null;
  private timeout = 0;
  constructor(private video: HTMLVideoElement, private onFrame: (frame: PerformanceFrame, aspect: number) => void, private onStatus: (text: string, running: boolean) => void) {}
  async start(source?: File | string) {
    this.stop(false); const generation = this.generation;
    this.onStatus("전신 추적 준비 중…", false);
    try {
      const worker = new Worker(new URL("../../workers/holistic-preview.worker.ts", import.meta.url), { type: "module" }); this.worker = worker;
      await new Promise<void>((resolve, reject) => {
        this.timeout = window.setTimeout(() => reject(new Error("추적 모델을 불러오는 시간이 초과됐습니다.")), 45000);
        this.cancelInit = () => { clearTimeout(this.timeout); resolve(); };
        worker.onerror = () => { clearTimeout(this.timeout); reject(new Error("전신 추적을 시작하지 못했습니다.")); };
        worker.onmessage = (e: MessageEvent<HolisticWorkerMessage>) => {
          clearTimeout(this.timeout);
          if (e.data.type === "ready") resolve(); else if (e.data.type === "error") reject(new Error(e.data.message));
        };
        worker.postMessage({ type: "init", wasmRoot: "/mediapipe/wasm", modelUrl: "/mediapipe/holistic_landmarker.task", minConfidence: .45 });
      });
      if (generation !== this.generation) return;
      this.cancelInit = null;
      if (source) {
        this.video.crossOrigin = "anonymous";
        if (typeof source === "string") this.video.src = source;
        else { this.objectUrl = URL.createObjectURL(source); this.video.src = this.objectUrl; }
        this.video.loop = true;
      } else {
        this.onStatus("웹캠 권한을 기다리는 중…", false);
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("localhost 또는 HTTPS에서 웹캠을 사용할 수 있습니다.");
        const stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }, audio: false });
        if (generation !== this.generation) { stream.getTracks().forEach((t) => t.stop()); return; }
        this.stream = stream; this.video.srcObject = stream;
        stream.getTracks().forEach((track) => track.addEventListener("ended", () => { if (generation === this.generation) this.stop(); }));
      }
      await this.video.play();
      if (generation !== this.generation) return;
      worker.onmessage = (e: MessageEvent<HolisticWorkerMessage>) => {
        if (generation !== this.generation) return;
        this.busy = false;
        if (e.data.type === "error") { this.stop(false); this.onStatus(e.data.message, false); return; }
        if (e.data.type !== "frame") return;
        const f = e.data.frame;
        this.onFrame({ time: f.timestampMs / 1000, pose: f.pose.map((p) => [p.x, p.y, p.z ?? 0, p.visibility ?? 1]), expressions: f.blendshapes, faceLandmarks:f.face.map(p=>[p.x,p.y,p.z??0,p.visibility??1]) }, this.video.videoWidth / Math.max(1, this.video.videoHeight));
      };
      worker.onerror = () => { if (generation === this.generation) { this.stop(false); this.onStatus("전신 추적이 중단됐습니다.", false); } };
      this.onStatus(source ? "영상 추적 중" : "웹캠 연결됨", true);
      const tick = (now: number) => {
        if (generation !== this.generation) return;
        this.frameId = requestAnimationFrame(tick);
        if (this.busy || this.video.paused || this.video.readyState < 2 || now - this.lastFrame < 1000 / 20) return;
        this.lastFrame = now; this.busy = true;
        void createImageBitmap(this.video).then((bitmap) => {
          if (generation !== this.generation) { bitmap.close(); return; }
          worker.postMessage({ type: "frame", bitmap, timestampMs: now }, [bitmap]);
        }).catch(() => { if (generation === this.generation) this.busy = false; });
      };
      this.frameId = requestAnimationFrame(tick);
    } catch (error) {
      if (generation !== this.generation) return;
      this.stop(false);
      this.onStatus(error instanceof DOMException && error.name === "NotAllowedError" ? "카메라 권한이 필요합니다. 브라우저에서 허용해 주세요." : error instanceof Error ? error.message : "입력을 시작하지 못했습니다.", false);
    }
  }
  stop(report = true) {
    this.generation++; clearTimeout(this.timeout); this.cancelInit?.(); this.cancelInit = null;
    cancelAnimationFrame(this.frameId); this.worker?.terminate(); this.worker = null;
    this.stream?.getTracks().forEach((t) => t.stop()); this.stream = null;
    this.video.pause(); this.video.srcObject = null; this.video.removeAttribute("src"); this.video.load();
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl); this.objectUrl = null;
    this.busy = false; this.lastFrame = -Infinity;
    if (report) this.onStatus("입력 종료", false);
  }
}
