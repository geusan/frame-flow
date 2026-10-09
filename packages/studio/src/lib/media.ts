export function maximizePlaybackVolume(media: HTMLMediaElement, unmute = true): void {
  media.volume = 1;
  if (unmute) media.muted = false;
}
