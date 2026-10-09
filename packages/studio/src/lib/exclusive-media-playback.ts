/** Coordinate native media, including Vidstack providers and plain audio elements. */
export function installExclusiveMediaPlayback(root: Document, channel: BroadcastChannel | null) {
  const pauseOthers = (active?: HTMLMediaElement) => {
    root.querySelectorAll<HTMLMediaElement>("video, audio").forEach((media) => {
      if (media !== active && !media.paused) media.pause();
    });
  };
  const onPlay = (event: Event) => {
    // Vidstack also emits a play event from its wrapper; only handle native media.
    if (!(event.target instanceof HTMLMediaElement)) return;
    pauseOthers(event.target);
    channel?.postMessage("play");
  };
  const onRemotePlay = (event: MessageEvent) => {
    if (event.data === "play") pauseOthers();
  };
  root.addEventListener("play", onPlay, { capture: true });
  channel?.addEventListener("message", onRemotePlay);
  return () => {
    root.removeEventListener("play", onPlay, { capture: true });
    channel?.removeEventListener("message", onRemotePlay);
    channel?.close();
  };
}

let subscribers = 0;
let dispose: (() => void) | undefined;

export function subscribeExclusiveMediaPlayback() {
  if (subscribers++ === 0) {
    const channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel("frameflow-media-playback");
    dispose = installExclusiveMediaPlayback(document, channel);
  }
  return () => {
    if (--subscribers === 0) {
      dispose?.();
      dispose = undefined;
    }
  };
}
