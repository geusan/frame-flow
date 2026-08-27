import type { FormatProfile, ModelEntry, ReferenceItem, RunSummary } from "./types";

export const references: ReferenceItem[] = [
  {
    id: "ref_01",
    title: "Why Roman concrete still survives",
    creator: "History Field Notes",
    duration: "00:38",
    source: "YouTube",
    language: "English",
    rights: "analysis_only",
    status: "analyzed",
    thumbnail: "linear-gradient(135deg, #272d48 0%, #887c5c 52%, #d0aa73 100%)",
    profiles: 2,
  },
  {
    id: "ref_02",
    title: "The design mistake hiding in plain sight",
    creator: "Everyday Systems",
    duration: "00:42",
    source: "Upload",
    language: "Korean",
    rights: "owned",
    status: "analyzed",
    thumbnail: "linear-gradient(135deg, #161a22 0%, #265b61 50%, #8fc3ac 100%)",
    profiles: 1,
  },
  {
    id: "ref_03",
    title: "One tiny habit that changes your mornings",
    creator: "Better in Small Steps",
    duration: "00:34",
    source: "YouTube",
    language: "English",
    rights: "analysis_only",
    status: "processing",
    thumbnail: "linear-gradient(135deg, #252036 0%, #774f61 55%, #dc9779 100%)",
    profiles: 0,
  },
  {
    id: "ref_04",
    title: "Coffee science in 45 seconds",
    creator: "Counter Culture Lab",
    duration: "00:45",
    source: "GCS",
    language: "Korean",
    rights: "licensed",
    status: "ready",
    thumbnail: "linear-gradient(135deg, #221c1a 0%, #744b32 48%, #deb887 100%)",
    profiles: 0,
  },
];

export const formats: FormatProfile[] = [
  {
    id: "fmt_history_01",
    name: "Contrarian History Reveal",
    sourceCount: 3,
    createdAt: "오늘 14:32",
    confidence: 0.91,
    tags: ["fast hook", "myth busting", "35s"],
    core: {
      schema_version: "format.core.v1",
      duration: { target_ms: 36000 },
      narrative: {
        beats: [
          { role: "hook", start_ratio: 0, end_ratio: 0.08, pattern: "contradiction" },
          { role: "context", start_ratio: 0.08, end_ratio: 0.3 },
          { role: "escalation", start_ratio: 0.3, end_ratio: 0.76 },
          { role: "payoff", start_ratio: 0.76, end_ratio: 0.95 },
        ],
      },
      editing: { median_shot_duration_ms: 2200, cuts_per_10_seconds: 4.4, transition_policy: "mostly_hard_cut" },
      captions: { position: "center_lower", max_lines: 2, max_chars_per_line: 12, words_per_chunk: 4 },
      voice: { tone: "confident_explanatory", pace_syllables_per_second: 4.7 },
      music: { bpm_range: [110, 120], ducking_under_voice_db: -8 },
      visual: { motion_intensity: 0.65, preferred_shot_types: ["close_up", "medium", "detail"] },
    },
    extensions: { historical_storytelling_v2: { fact_reveal_position: 0.78, myth_busting_pattern: "common_belief_reversal" } },
  },
  {
    id: "fmt_explainer_02",
    name: "Calm Visual Explainer",
    sourceCount: 2,
    createdAt: "어제 18:07",
    confidence: 0.87,
    tags: ["calm", "visual proof", "42s"],
    core: {
      schema_version: "format.core.v1",
      duration: { target_ms: 42000 },
      narrative: {
        beats: [
          { role: "hook", start_ratio: 0, end_ratio: 0.1, pattern: "open_question" },
          { role: "context", start_ratio: 0.1, end_ratio: 0.34 },
          { role: "escalation", start_ratio: 0.34, end_ratio: 0.8 },
          { role: "payoff", start_ratio: 0.8, end_ratio: 0.97 },
        ],
      },
      editing: { median_shot_duration_ms: 3100, cuts_per_10_seconds: 3.2, transition_policy: "soft_match_cut" },
      captions: { position: "lower_third", max_lines: 2, max_chars_per_line: 14, words_per_chunk: 5 },
      voice: { tone: "warm_explanatory", pace_syllables_per_second: 4.1 },
      music: { bpm_range: [92, 106], ducking_under_voice_db: -10 },
      visual: { motion_intensity: 0.42, preferred_shot_types: ["medium", "detail", "wide"] },
    },
    extensions: { visual_explainer_v1: { proof_shot_ratio: 0.55 } },
  },
];

export const runs: RunSummary[] = [
  { id: "run_8K2P", name: "로마 콘크리트의 비밀", status: "WAITING_INPUT", progress: 67, startedAt: "오늘 15:41", duration: "08:24", cost: 2.84, nodesDone: 12, nodesTotal: 18 },
  { id: "run_7JM4", name: "커피가 식으면 맛이 변하는 이유", status: "RUNNING", progress: 44, startedAt: "오늘 14:12", duration: "05:18", cost: 1.62, nodesDone: 8, nodesTotal: 18 },
  { id: "run_4QW1", name: "아침 루틴의 과학", status: "SUCCEEDED", progress: 100, startedAt: "어제 21:06", duration: "12:43", cost: 4.18, nodesDone: 18, nodesTotal: 18 },
  { id: "run_2AR9", name: "도시 표지판의 숨은 규칙", status: "FAILED", progress: 72, startedAt: "어제 17:32", duration: "09:11", cost: 2.13, nodesDone: 13, nodesTotal: 18 },
];

export const models: ModelEntry[] = [
  { alias: "google.text.fast", modelId: "gemini-2.5-flash", provider: "Google", kind: "Text", region: "global", status: "active", quota: "60 RPM", fallback: "google.text.quality" },
  { alias: "google.text.quality", modelId: "gemini-2.5-pro", provider: "Google", kind: "Text", region: "global", status: "active", quota: "30 RPM" },
  { alias: "google.image.fast", modelId: "gemini-3.1-flash-image", provider: "Google", kind: "Image", region: "global", status: "active", quota: "8 concurrent" },
  { alias: "google.video.fast", modelId: "veo-3.1-fast-generate-001", provider: "Google", kind: "Video", region: "us-central1", status: "active", quota: "2 concurrent", fallback: "google.video.quality" },
  { alias: "google.video.quality", modelId: "veo-3.1-generate-001", provider: "Google", kind: "Video", region: "us-central1", status: "active", quota: "1 concurrent" },
  { alias: "google.tts.fast", modelId: "gemini-2.5-flash-tts", provider: "Google", kind: "Audio", region: "asia-northeast3", status: "active", quota: "5 concurrent" },
  { alias: "google.stt.default", modelId: "chirp_3", provider: "Google", kind: "Audio", region: "asia-northeast3", status: "active", quota: "10 concurrent" },
  { alias: "google.music.experimental", modelId: "lyria-3-preview", provider: "Google", kind: "Music", region: "us-central1", status: "experimental", quota: "1 concurrent" },
];

