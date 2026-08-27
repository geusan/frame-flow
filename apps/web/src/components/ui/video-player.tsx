"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  Controls,
  FullscreenButton,
  Gesture,
  MediaAnnouncer,
  MediaPlayer,
  MediaProvider,
  MuteButton,
  PlayButton,
  Time,
  TimeSlider,
  VolumeSlider,
  useMediaState,
  type MediaPlayerInstance,
} from "@vidstack/react";
import {
  LoaderCircle,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  RotateCcw,
  Volume2,
  VolumeX,
} from "lucide-react";

export interface VideoPlayerMetadata {
  width: number;
  height: number;
  duration: number;
}

export interface VideoPlayerHandle {
  getCurrentTime: () => number;
  seek: (seconds: number) => void;
  play: () => Promise<void>;
  pause: () => void;
}

interface VideoPlayerProps {
  src: string;
  title?: string;
  className?: string;
  style?: CSSProperties;
  autoPlay?: boolean;
  muted?: boolean;
  loop?: boolean;
  controls?: boolean;
  compact?: boolean;
  fit?: "contain" | "cover";
  preload?: "none" | "metadata" | "auto";
  onMetadata?: (metadata: VideoPlayerMetadata) => void;
  onTimeUpdate?: (seconds: number) => void;
}

type PlayerStyle = CSSProperties & { [name: `--${string}`]: string | number | null | undefined };

function PlayerTelemetry({ onMetadata, onTimeUpdate }: Pick<VideoPlayerProps, "onMetadata" | "onTimeUpdate">) {
  const currentTime = useMediaState("currentTime");
  const duration = useMediaState("duration");
  const width = useMediaState("mediaWidth");
  const height = useMediaState("mediaHeight");
  const metadataKey = useRef("");

  useEffect(() => {
    onTimeUpdate?.(currentTime);
  }, [currentTime, onTimeUpdate]);

  useEffect(() => {
    if (!width || !height) return;
    const key = `${width}x${height}:${duration}`;
    if (metadataKey.current === key) return;
    metadataKey.current = key;
    onMetadata?.({ width, height, duration: Number.isFinite(duration) ? duration : 0 });
  }, [duration, height, onMetadata, width]);

  return null;
}

function PlayerControls({ compact }: { compact: boolean }) {
  const paused = useMediaState("paused");
  const ended = useMediaState("ended");
  const muted = useMediaState("muted");
  const fullscreen = useMediaState("fullscreen");
  const waiting = useMediaState("waiting");

  return <>
    <Gesture className="ff-video-gesture" event="pointerup" action="toggle:paused" />
    <Gesture className="ff-video-gesture" event="dblpointerup" action="toggle:fullscreen" />
    {waiting && <span className="ff-video-buffering"><LoaderCircle size={compact ? 21 : 29} className="spin" /></span>}
    <PlayButton className="ff-video-center-play" aria-label={paused ? "Play video" : "Pause video"}>
      {ended ? <RotateCcw size={compact ? 20 : 28} /> : paused ? <Play size={compact ? 20 : 28} fill="currentColor" /> : <Pause size={compact ? 20 : 28} fill="currentColor" />}
    </PlayButton>
    <Controls.Root className="ff-video-controls" hideDelay={1900}>
      <div className="ff-video-controls-gradient" />
      <div className="ff-video-controls-bottom">
        <Controls.Group className="ff-video-timeline-row">
          <TimeSlider.Root className="ff-video-time-slider" aria-label="Video timeline">
            <TimeSlider.Track className="ff-video-slider-track">
              <TimeSlider.Progress className="ff-video-slider-progress" />
              <TimeSlider.TrackFill className="ff-video-slider-fill" />
            </TimeSlider.Track>
            <TimeSlider.Thumb className="ff-video-slider-thumb" />
          </TimeSlider.Root>
        </Controls.Group>
        <Controls.Group className="ff-video-control-row">
          <PlayButton className="ff-video-control-button" aria-label={paused ? "Play" : "Pause"}>
            {paused ? <Play size={16} fill="currentColor" /> : <Pause size={16} fill="currentColor" />}
          </PlayButton>
          <span className="ff-video-time"><Time type="current" /> <i>/</i> <Time type="duration" /></span>
          <span className="ff-video-control-spacer" />
          <MuteButton className="ff-video-control-button" aria-label={muted ? "Unmute" : "Mute"}>
            {muted ? <VolumeX size={17} /> : <Volume2 size={17} />}
          </MuteButton>
          {!compact && <VolumeSlider.Root className="ff-video-volume-slider" aria-label="Volume">
            <VolumeSlider.Track className="ff-video-slider-track">
              <VolumeSlider.TrackFill className="ff-video-slider-fill" />
            </VolumeSlider.Track>
            <VolumeSlider.Thumb className="ff-video-slider-thumb" />
          </VolumeSlider.Root>}
          <FullscreenButton className="ff-video-control-button" aria-label={fullscreen ? "Exit fullscreen" : "Enter fullscreen"}>
            {fullscreen ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
          </FullscreenButton>
        </Controls.Group>
      </div>
    </Controls.Root>
  </>;
}

export const VideoPlayer = forwardRef<VideoPlayerHandle, VideoPlayerProps>(function VideoPlayer({
  src,
  title = "Video",
  className = "",
  style,
  autoPlay = false,
  muted = true,
  loop = false,
  controls = true,
  compact = false,
  fit = "contain",
  preload = "metadata",
  onMetadata,
  onTimeUpdate,
}, ref) {
  const playerRef = useRef<MediaPlayerInstance>(null);
  const [metadata, setMetadata] = useState<VideoPlayerMetadata | null>(null);

  useImperativeHandle(ref, () => ({
    getCurrentTime: () => playerRef.current?.currentTime ?? 0,
    seek: (seconds) => { if (playerRef.current) playerRef.current.currentTime = Math.max(0, seconds); },
    play: async () => { await playerRef.current?.play(); },
    pause: () => { playerRef.current?.pause(); },
  }), []);

  const handleMetadata = (next: VideoPlayerMetadata) => {
    setMetadata(next);
    onMetadata?.(next);
  };
  const aspectRatio = metadata?.width && metadata.height ? `${metadata.width} / ${metadata.height}` : undefined;

  return <MediaPlayer
    ref={playerRef}
    className={`ff-video-player ${compact ? "compact" : ""} ${controls ? "with-controls" : "preview-only"} ${className}`.trim()}
    src={src}
    title={title}
    autoPlay={autoPlay}
    muted={muted}
    loop={loop}
    playsInline
    preload={preload}
    style={{ ...style, aspectRatio: style?.aspectRatio ?? aspectRatio, "--ff-video-fit": fit } as PlayerStyle}
  >
    <MediaProvider />
    {controls && <MediaAnnouncer />}
    <PlayerTelemetry onMetadata={handleMetadata} onTimeUpdate={onTimeUpdate} />
    {controls && <PlayerControls compact={compact} />}
  </MediaPlayer>;
});
