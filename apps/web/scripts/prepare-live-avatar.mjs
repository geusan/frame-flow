import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile, copyFile, readdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const root = resolve(import.meta.dirname, "../public/mediapipe");
const wasmSource = resolve(dirname(require.resolve("@mediapipe/tasks-vision")), "wasm");
await mkdir(resolve(root, "wasm"), { recursive: true });
for (const file of await readdir(wasmSource)) {
  if (/\.(js|wasm)$/.test(file)) await copyFile(resolve(wasmSource, file), resolve(root, "wasm", file));
}
const modelPath = resolve(root, "face_landmarker.task");
const expected = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff";
let data;
try { data = await readFile(modelPath); } catch { /* Download the pinned public model on first build. */ }
if (!data || createHash("sha256").update(data).digest("hex") !== expected) {
  const response = await fetch("https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task", { signal: AbortSignal.timeout(60000) });
  if (!response.ok) throw new Error(`Face model download failed: ${response.status}`);
  data = Buffer.from(await response.arrayBuffer());
  if (createHash("sha256").update(data).digest("hex") !== expected) throw new Error("Face model checksum mismatch");
  await writeFile(modelPath, data);
}
console.log("Live Avatar model and WASM assets ready (local serving)");

const holisticPath = resolve(root, "holistic_landmarker.task");
const holisticHash = "e2dab61191e2dcd0a15f943d8e3ed1dce13c82dfa597b9dd39f562975a50c3f8";
let holistic;
try { holistic = await readFile(holisticPath); } catch { /* First-time preparation. */ }
if (!holistic || createHash("sha256").update(holistic).digest("hex") !== holisticHash) {
  const response = await fetch("https://storage.googleapis.com/mediapipe-models/holistic_landmarker/holistic_landmarker/float16/latest/holistic_landmarker.task", { signal: AbortSignal.timeout(60000) });
  if (!response.ok) throw new Error(`Body model download failed: ${response.status}`);
  holistic = Buffer.from(await response.arrayBuffer());
  if (createHash("sha256").update(holistic).digest("hex") !== holisticHash) throw new Error("Body model checksum mismatch");
  await writeFile(holisticPath, holistic);
}
console.log("2D Avatar body tracking model ready (checksum pinned)");
