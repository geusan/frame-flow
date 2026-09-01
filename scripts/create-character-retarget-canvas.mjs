const API_BASE = process.env.FRAMEFLOW_API_BASE ?? "http://localhost:8000";
const WEB_BASE = process.env.FRAMEFLOW_WEB_BASE ?? "http://localhost:3001";
const finalArtifactId = process.argv[2] ?? "art_e957e30384d643368e";
const clipDurationSeconds = 8;
const existingCanvasId = process.env.FRAMEFLOW_CANVAS_ID;

async function request(path, options) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "content-type": "application/json", ...(options?.headers ?? {}) },
    ...options,
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  return response.json();
}

const [lineage, definitions] = await Promise.all([
  request(`/artifacts/${encodeURIComponent(finalArtifactId)}/lineage?direction=ancestors&depth=12`),
  request("/node-definitions"),
]);

const definitionByKey = new Map(definitions.map((definition) => [`${definition.type_key}@${definition.contract_version}`, definition]));
const definition = (typeKey, version = 1) => {
  const value = definitionByKey.get(`${typeKey}@${version}`);
  if (!value) throw new Error(`Node Definition is unavailable: ${typeKey}@${version}`);
  return value;
};
const lineageNodes = lineage.nodes ?? [];
const operation = (node) => node.derivation?.operation ?? "";
const original = lineageNodes.find((node) => (
  node.type === "Video"
  && ["asset.url.import", "asset.file.upload"].includes(operation(node))
  && (node.input_artifact_ids ?? []).length === 0
));
const characterImage = lineageNodes.find((node) => node.type === "Image" && node.schema_id === "character.view.v1");
const generatedVideos = lineageNodes.filter((node) => node.type === "Video" && operation(node) === "video.generate");
const motionTrack = lineageNodes.find((node) => node.type === "MotionTrack" && operation(node) === "motion.extract");
if (!original) throw new Error("The lineage does not contain an uploaded/imported source Video");
if (!characterImage) throw new Error("The lineage does not contain a character.view.v1 Image");
if (!generatedVideos.length) throw new Error("The lineage does not contain generated Video clips");

const clipCount = generatedVideos.length;
const sourceDurationSeconds = Number(motionTrack?.metadata?.duration_ms ?? original.metadata?.duration_ms ?? 0) / 1000;
if (!(sourceDurationSeconds > 0)) throw new Error("The source duration is unavailable in the lineage");
const generatedDurationSeconds = clipCount * clipDurationSeconds;
const fastSpeed = generatedDurationSeconds / sourceDurationSeconds;
const slowSpeed = 1 / fastSpeed;
const prompt = String(generatedVideos[0]?.derivation?.prompt ?? "Preserve the reference motion and apply the connected character consistently.");
const columnGap = 440;
const branchRowGap = 250;
const columnX = (index) => index * columnGap;
const branchY = (index) => index * branchRowGap;
const mainLaneY = branchY(Math.floor((clipCount - 1) / 2));
const sourceInputY = branchY(clipCount) + 100;

function graphNode(id, typeKey, config, position, options = {}) {
  const contract = definition(typeKey);
  return {
    id,
    type_key: typeKey,
    contract_version: 1,
    definition_digest: contract.definition_digest,
    config,
    execution: {
      model_alias: options.modelAlias ?? contract.execution.model_alias,
      provider: options.provider ?? contract.execution.provider,
    },
    ui: {
      order: options.order ?? 0,
      position,
      label: options.label ?? contract.display.label,
      description: options.description ?? contract.display.description,
      react_flow: {},
    },
    editor: { legacy_data: {} },
  };
}

let order = 0;
const nodes = [
  graphNode("source-video", "asset.select", { artifact_id: original.id, artifact_type: "Video" }, { x: columnX(0), y: mainLaneY }, { order: order++, label: "1. 업로드된 원본 영상" }),
  graphNode("source-character", "asset.select", { artifact_id: characterImage.id, artifact_type: "Image" }, { x: columnX(3), y: sourceInputY }, { order: order++, label: "캐릭터 기준 이미지" }),
  graphNode("source-prompt", "prompt.input", { text: prompt }, { x: columnX(2), y: sourceInputY }, { order: order++, label: "캐릭터 적용 Prompt" }),
  graphNode("extract-audio", "audio.extract", {}, { x: columnX(1), y: mainLaneY + branchRowGap * 2 }, { order: order++, label: "7. 원본 오디오 추출" }),
  graphNode("extract-motion", "motion.extract", {
    motion_sample_fps: 24,
    motion_max_width: 720,
    motion_min_confidence: 0.65,
    motion_face_blendshapes: false,
  }, { x: columnX(1), y: mainLaneY - branchRowGap * 2 }, { order: order++, label: "2. Holistic 모션 추출" }),
  graphNode("slow-video", "video.retime", {
    speed_multiplier: Number(slowSpeed.toFixed(10)),
    output_fps: 24,
    preserve_audio: false,
  }, { x: columnX(1), y: mainLaneY }, {
    order: order++,
    label: `3. ${slowSpeed.toFixed(6)}× Slow (${generatedDurationSeconds}s)`,
    description: `${sourceDurationSeconds.toFixed(3)}초 원본을 ${generatedDurationSeconds}초로 늘립니다.`,
  }),
  graphNode("split-video", "video.split", {
    segment_duration_seconds: clipDurationSeconds,
    remainder_policy: "keep",
    output_fps: 24,
    max_segments: 16,
  }, { x: columnX(2), y: mainLaneY }, { order: order++, label: `3. ${clipDurationSeconds}초씩 ${clipCount}개 분할` }),
];

for (let index = 0; index < clipCount; index += 1) {
  const y = branchY(index);
  nodes.push(graphNode(`clip-${index + 1}`, "video.clip.select", { clip_index: index }, { x: columnX(3), y }, {
    order: order++,
    label: `Clip ${index + 1} · ${index * clipDurationSeconds}-${(index + 1) * clipDurationSeconds}s`,
  }));
  nodes.push(graphNode(`generate-${index + 1}`, "video.generate", {
    resolution: "1080p",
    aspect_ratio: "9:16",
    duration_seconds: clipDurationSeconds,
    output_count: 1,
  }, { x: columnX(4), y }, {
    order: order++,
    label: `4. 캐릭터 영상 ${index + 1}/${clipCount}`,
    modelAlias: "google.video.omni",
    provider: "google",
  }));
}

nodes.push(
  graphNode("concat-video", "video.edit", {
    resolution: "1080p",
    aspect_ratio: "9:16",
    transition: "hard_cut",
    target_duration_seconds: generatedDurationSeconds,
  }, { x: columnX(5), y: mainLaneY }, { order: order++, label: `5. 생성 영상 ${clipCount}개 이어붙이기` }),
  graphNode("fast-video", "video.retime", {
    speed_multiplier: Number(fastSpeed.toFixed(10)),
    output_fps: 24,
    preserve_audio: false,
  }, { x: columnX(6), y: mainLaneY }, {
    order: order++,
    label: `6. ${fastSpeed.toFixed(6)}× Fast (${sourceDurationSeconds.toFixed(3)}s)`,
    description: `${generatedDurationSeconds}초 생성 영상을 원본 ${sourceDurationSeconds.toFixed(3)}초로 복원합니다.`,
  }),
  graphNode("replace-audio", "video.change_voice", {}, { x: columnX(7), y: mainLaneY }, { order: order++, label: "7. 원본 오디오 그대로 적용" }),
);

let edgeIndex = 0;
const edges = [];
function edge(source, target, sourcePort, targetPort) {
  edgeIndex += 1;
  edges.push({
    id: `edge-${String(edgeIndex).padStart(2, "0")}`,
    source,
    target,
    source_port: sourcePort,
    target_port: targetPort,
    ui: {},
  });
}

edge("source-video", "extract-audio", "artifact", "video");
edge("source-video", "extract-motion", "artifact", "video");
edge("source-video", "slow-video", "artifact", "video");
edge("slow-video", "split-video", "video", "video");
for (let index = 0; index < clipCount; index += 1) {
  const suffix = index + 1;
  edge("split-video", `clip-${suffix}`, "clips", "clips");
  edge(`clip-${suffix}`, `generate-${suffix}`, "video", "video");
  edge("source-character", `generate-${suffix}`, "artifact", "image");
  edge("source-prompt", `generate-${suffix}`, "prompt", "prompt");
  edge(`generate-${suffix}`, "concat-video", "video", "videos");
}
edge("concat-video", "fast-video", "video", "video");
edge("fast-video", "replace-audio", "video", "video");
edge("extract-audio", "replace-audio", "audio", "audio");

const document = {
  schema_version: "canvas.document.v1",
  graph: {
    schema_version: "canvas.graph.v1",
    nodes,
    elements: [],
    edges,
  },
  runtime: { schema_version: "canvas.runtime.v1", nodes: {} },
};
const canvasPayload = {
  name: `캐릭터 모션 리타게팅 · ${clipDurationSeconds}초 × ${clipCount}`,
  document,
  draft_contract: {
      schema_version: "workflow.contract.draft.v1",
      inputs: [],
      bindings: [],
      outputs: [
        { key: "final_video", label: "원본 오디오가 적용된 최종 영상", node_id: "replace-audio", port_type: "media.video.v1", primary: true },
        { key: "motion_track", label: "Holistic MotionTrack", node_id: "extract-motion", port_type: "data.motion_track.v1", primary: false },
      ],
  },
};
if (existingCanvasId) {
  const existing = await request(`/canvases/${encodeURIComponent(existingCanvasId)}`);
  canvasPayload.expected_revision = existing.revision;
}
const canvas = await request(existingCanvasId ? `/canvases/${encodeURIComponent(existingCanvasId)}` : "/canvases", {
  method: existingCanvasId ? "PUT" : "POST",
  body: JSON.stringify(canvasPayload),
});

console.log(JSON.stringify({
  canvas_id: canvas.id,
  canvas_url: `${WEB_BASE}/canvases/${canvas.id}`,
  source_artifact_id: original.id,
  character_artifact_id: characterImage.id,
  source_duration_seconds: sourceDurationSeconds,
  clip_count: clipCount,
  clip_duration_seconds: clipDurationSeconds,
  slow_speed_multiplier: Number(slowSpeed.toFixed(10)),
  fast_speed_multiplier: Number(fastSpeed.toFixed(10)),
}, null, 2));
