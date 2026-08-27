export type NodeStatus =
  | "BLOCKED"
  | "READY"
  | "QUEUED"
  | "CLAIMED"
  | "SUBMITTED"
  | "RUNNING"
  | "WAITING_INPUT"
  | "RETRY_WAIT"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELED"
  | "STALE";

export type PortType =
  | "Text"
  | "Prompt"
  | "ReferenceAsset"
  | "ReferenceSet"
  | "Transcript"
  | "SceneList"
  | "AudioProfile"
  | "FormatProfile"
  | "FormatVariant"
  | "GenerationSpec"
  | "Script"
  | "ShotPlan"
  | "Image"
  | "ImageList"
  | "VideoClipList"
  | "Audio"
  | "Subtitle"
  | "Timeline"
  | "Video"
  | "QCReport"
  | "Any";

export type StudioView = "canvas" | "references" | "formats" | "runs" | "models";

export interface FormatCore {
  schema_version: "format.core.v1";
  duration: { target_ms: number };
  narrative: {
    beats: Array<{
      role: "hook" | "context" | "escalation" | "payoff";
      start_ratio: number;
      end_ratio: number;
      pattern?: string;
    }>;
  };
  editing: {
    median_shot_duration_ms: number;
    cuts_per_10_seconds: number;
    transition_policy: string;
  };
  captions: {
    position: string;
    max_lines: number;
    max_chars_per_line: number;
    words_per_chunk: number;
  };
  voice: { tone: string; pace_syllables_per_second: number };
  music: { bpm_range: [number, number]; ducking_under_voice_db: number };
  visual: { motion_intensity: number; preferred_shot_types: string[] };
}

export interface FormatProfile {
  id: string;
  name: string;
  sourceCount: number;
  createdAt: string;
  confidence: number;
  core: FormatCore;
  extensions: Record<string, unknown>;
  tags: string[];
}

export interface ReferenceItem {
  id: string;
  title: string;
  creator: string;
  duration: string;
  source: string;
  language: string;
  rights: "owned" | "licensed" | "creative_commons" | "analysis_only" | "unknown";
  status: "analyzed" | "processing" | "ready";
  thumbnail: string;
  profiles: number;
}

export interface RunSummary {
  id: string;
  name: string;
  status: NodeStatus;
  progress: number;
  startedAt: string;
  duration: string;
  cost: number;
  nodesDone: number;
  nodesTotal: number;
}

export interface ModelEntry {
  alias: string;
  modelId: string;
  provider: string;
  kind: string;
  region: string;
  status: "active" | "experimental" | "disabled";
  quota: string;
  fallback?: string;
}
