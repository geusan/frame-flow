/** A separate authoring document: body rig profiles and source art stay immutable. */
export const EXPRESSION_ASSET = "cat-2d-v1";
export const EXPRESSION_ROOT = "/avatars/cat-2d-v1/expressions-v1";
export const BASE_IMAGE = "/avatars/cat-2d-v1/base.png";
export const EXPRESSION_SOURCE_SHA = "cf8192ed7f3be78f1a22022fc0bb173c842cfc3b7eeb4592c4387515c563b42b";
export const FACE_REGION = { x: 508, y: 219, rx: 73, ry: 62, feather: .10 } as const;
export interface ExpressionImage {
  id: string; name: string; image: string;
  layout: "full" | "face"; offsetX: number; offsetY: number; scale: number;
}
export interface ExpressionLibrary {
  schema_version: "avatar.expression_library.v1";
  asset: typeof EXPRESSION_ASSET;
  source_sha256: typeof EXPRESSION_SOURCE_SHA;
  selected: string; strength: number; transition_ms: number;
  entries: ExpressionImage[];
}
export const BUNDLED_EXPRESSIONS = [["neutral", "원본"], ["smile", "미소"], ["laugh", "웃음"], ["surprise", "놀람"], ["sad", "슬픔"], ["angry", "화남"], ["wink", "윙크"], ["mouth-open", "입 벌림"]] as const;
export function freshExpressions(): ExpressionLibrary {
  return { schema_version: "avatar.expression_library.v1", asset: EXPRESSION_ASSET, source_sha256: EXPRESSION_SOURCE_SHA, selected: "neutral", strength: 1, transition_ms: 140,
    entries: BUNDLED_EXPRESSIONS.map(([id, name]) => ({ id, name, image: id === "neutral" ? BASE_IMAGE : `${EXPRESSION_ROOT}/${id}.png`, layout: "full", offsetX: 0, offsetY: 0, scale: 1 })) };
}
/** Add the isolated jaw reference to pre-existing authoring libraries without changing their entries. */
export function withFaceRigSources(library:ExpressionLibrary):ExpressionLibrary {
  if(library.entries.some(e=>e.id==='mouth-open')||library.entries.length>=24)return library;
  return {...library,entries:[...library.entries,freshExpressions().entries.find(e=>e.id==='mouth-open')!]};
}
export function expressionRect(entry: ExpressionImage): [number, number, number, number] {
  const rect = entry.layout === "full" ? [0, 0, 1024, 1536] : [398, 110, 224, 224];
  return [508 + (rect[0] - 508) * entry.scale + entry.offsetX, 219 + (rect[1] - 219) * entry.scale + entry.offsetY, rect[2] * entry.scale, rect[3] * entry.scale];
}
export function faceMask(x: number, y: number): number {
  const radius = Math.hypot((x - FACE_REGION.x) / FACE_REGION.rx, (y - FACE_REGION.y) / FACE_REGION.ry);
  const t = Math.max(0, Math.min(1, (radius - (1 - FACE_REGION.feather)) / FACE_REGION.feather));
  return 1 - t * t * (3 - 2 * t);
}
export function parseExpressions(value: unknown): ExpressionLibrary {
  const p = value as ExpressionLibrary;
  if (!p || p.schema_version !== "avatar.expression_library.v1" || p.asset !== EXPRESSION_ASSET || p.source_sha256 !== EXPRESSION_SOURCE_SHA) throw new Error("이 캐릭터용 표정 모음 파일이 아닙니다.");
  if (!Array.isArray(p.entries) || p.entries.length < 1 || p.entries.length > 24) throw new Error("표정은 원본을 포함해 최대 24개까지 관리할 수 있습니다.");
  if (!Number.isFinite(p.strength) || p.strength < 0 || p.strength > 1 || !Number.isFinite(p.transition_ms) || p.transition_ms < 0 || p.transition_ms > 600) throw new Error("표정 전환 설정이 올바르지 않습니다.");
  const ids = new Set<string>();
  let imageBytes = 0;
  const entries = p.entries.map((entry) => {
    if (!entry || typeof entry.id !== "string" || !/^[a-z0-9_-]{1,80}$/.test(entry.id) || ids.has(entry.id)) throw new Error("표정 ID가 잘못되거나 중복됐습니다.");
    ids.add(entry.id);
    if (typeof entry.name !== "string" || !entry.name.trim() || entry.name.length > 40) throw new Error("표정 이름은 1~40자로 입력해 주세요.");
    const local = entry.image === BASE_IMAGE || BUNDLED_EXPRESSIONS.some(([id]) => id !== "neutral" && entry.image === `${EXPRESSION_ROOT}/${id}.png`);
    const embedded = typeof entry.image === "string" && entry.image.length <= 8_000_000 && /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/]+=*$/.test(entry.image);
    if (!local && !embedded) throw new Error("PNG·JPG·WebP 표정 이미지가 필요합니다.");
    imageBytes += entry.image.length;
    if (imageBytes > 32_000_000) throw new Error("표정 이미지 모음은 32MB 이하여야 합니다.");
    if (!["full", "face"].includes(entry.layout) || !Number.isFinite(entry.scale) || entry.scale < .5 || entry.scale > 2 || !Number.isFinite(entry.offsetX) || Math.abs(entry.offsetX) > 100 || !Number.isFinite(entry.offsetY) || Math.abs(entry.offsetY) > 100) throw new Error("얼굴 이미지 정렬 범위를 확인해 주세요.");
    if (entry.id === "neutral" && (entry.image !== BASE_IMAGE || entry.layout !== "full" || entry.offsetX || entry.offsetY || entry.scale !== 1)) throw new Error("원본 표정은 변경할 수 없습니다. 복제 후 편집하세요.");
    return { id: entry.id, name: entry.name.trim(), image: entry.image, layout: entry.layout, offsetX: entry.offsetX, offsetY: entry.offsetY, scale: entry.scale };
  });
  if (!ids.has("neutral") || !ids.has(p.selected)) throw new Error("원본 또는 선택한 표정이 없습니다.");
  return { schema_version: p.schema_version, asset: p.asset, source_sha256: p.source_sha256, selected: p.selected, strength: p.strength, transition_ms: p.transition_ms, entries };
}

async function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("frameflow-avatar-expressions", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("libraries");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
export async function readExpressions(): Promise<ExpressionLibrary | null> {
  const db = await database();
  try { return await new Promise((resolve, reject) => {
    const request = db.transaction("libraries").objectStore("libraries").get(EXPRESSION_ASSET);
    request.onsuccess = () => { try { resolve(request.result ? parseExpressions(request.result) : null); } catch (error) { reject(error); } };
    request.onerror = () => reject(request.error);
  }); } finally { db.close(); }
}
export async function saveExpressions(value: ExpressionLibrary): Promise<void> {
  const valid = parseExpressions(value), db = await database();
  try { await new Promise<void>((resolve, reject) => {
    const tx = db.transaction("libraries", "readwrite");
    tx.objectStore("libraries").put(valid, EXPRESSION_ASSET);
    tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error);
  }); } finally { db.close(); }
}
export function imageDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(reader.error); reader.readAsDataURL(blob); });
}
export async function portableExpressions(library: ExpressionLibrary): Promise<ExpressionLibrary> {
  const entries = await Promise.all(library.entries.map(async (entry) => {
    if (entry.id === "neutral" || entry.image.startsWith("data:")) return entry;
    const response = await fetch(entry.image); if (!response.ok) throw new Error("표정 이미지 내보내기에 실패했습니다.");
    return { ...entry, image: await imageDataUrl(await response.blob()) };
  }));
  return parseExpressions({ ...library, entries });
}
