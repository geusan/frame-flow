import type { JSONContent } from "@tiptap/core";

export interface RichCaptionDocument {
  schema_version: "caption.document.v1";
  content: JSONContent;
  default_style: {
    font_size: number;
    color: string;
    font_id?: string;
  };
}

export interface RichCaptionRun {
  text: string;
  bold: boolean;
  italic: boolean;
  color: string;
  fontId?: string;
  fontFamily?: string;
  fontSize: number;
}

export interface RichCaptionCue {
  start: string;
  end: string;
  runs: RichCaptionRun[];
}

const TIMESTAMP_PREFIX = /^\s*\[\s*([0-9:.]+)\s*-\s*([0-9:.]+)\s*\]\s*/;

function srtTime(value: string): string {
  const match = value.match(/^(\d+):(\d{2}):(\d{2})[,.](\d{3})$/);
  if (!match) return value;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  const fraction = Number(match[4]);
  const clock = hours
    ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${match[3]}`
    : `${String(minutes).padStart(2, "0")}:${match[3]}`;
  return `${clock}${fraction ? `.${String(fraction).padStart(3, "0")}` : ""}`;
}

export function richCaptionDocumentFromSrt(srt: string | undefined, fontSize: number): RichCaptionDocument {
  const paragraphs: JSONContent[] = [];
  for (const block of (srt ?? "").trim().split(/\r?\n\s*\r?\n/)) {
    const lines = block.split(/\r?\n/).filter(Boolean);
    const timingIndex = lines.findIndex((line) => line.includes("-->"));
    if (timingIndex < 0) continue;
    const [start, end] = lines[timingIndex].split("-->", 2).map((item) => item.trim().split(" ", 1)[0]);
    const text = lines.slice(timingIndex + 1).map((line) => line.replace(/<[^>]*>/g, "")).join(" ").trim();
    if (!start || !end || !text) continue;
    paragraphs.push({ type: "paragraph", content: [{ type: "text", text: `[${srtTime(start)}-${srtTime(end)}] ${text}` }] });
  }
  if (!paragraphs.length) {
    paragraphs.push({ type: "paragraph", content: [{ type: "text", text: "[00:00-00:03] 첫 번째 자막을 입력하세요" }] });
  }
  return {
    schema_version: "caption.document.v1",
    content: { type: "doc", content: paragraphs },
    default_style: { font_size: fontSize, color: "#FFFFFF" },
  };
}

export function richCaptionDocumentIsEmpty(document: RichCaptionDocument | undefined): boolean {
  return !document?.content?.content?.some((node) => node.type === "paragraph" && node.content?.some((child) => child.type === "text" && child.text?.trim()));
}

function inlineSegments(node: JSONContent): Array<{ text: string; marks: JSONContent[] }> {
  return (node.content ?? []).flatMap((child) => {
    if (child.type === "text" && child.text) return [{ text: child.text, marks: child.marks ?? [] }];
    if (child.type === "hardBreak") return [{ text: "\n", marks: [] }];
    return [];
  });
}

export function captionCues(document: RichCaptionDocument | undefined): RichCaptionCue[] {
  if (!document?.content.content) return [];
  const cues: RichCaptionCue[] = [];
  for (const paragraph of document.content.content) {
    if (paragraph.type !== "paragraph") continue;
    const segments = inlineSegments(paragraph);
    const source = segments.map((segment) => segment.text).join("");
    const match = source.match(TIMESTAMP_PREFIX);
    if (!match) continue;
    let cursor = 0;
    const runs: RichCaptionRun[] = [];
    for (const segment of segments) {
      const start = cursor;
      const end = cursor + segment.text.length;
      cursor = end;
      if (end <= match[0].length) continue;
      const text = segment.text.slice(Math.max(0, match[0].length - start));
      if (!text) continue;
      const textStyle = segment.marks.find((mark) => mark.type === "textStyle")?.attrs ?? {};
      const fontSize = Number.parseFloat(String(textStyle.fontSize ?? document.default_style.font_size));
      runs.push({
        text,
        bold: segment.marks.some((mark) => mark.type === "bold"),
        italic: segment.marks.some((mark) => mark.type === "italic"),
        color: String(textStyle.color ?? document.default_style.color),
        fontId: textStyle.fontId ? String(textStyle.fontId) : document.default_style.font_id,
        fontFamily: textStyle.fontFamily ? String(textStyle.fontFamily) : undefined,
        fontSize: Number.isFinite(fontSize) ? fontSize : document.default_style.font_size,
      });
    }
    cues.push({ start: match[1], end: match[2], runs });
  }
  return cues;
}

export function captionDocumentErrors(document: RichCaptionDocument | undefined): string[] {
  if (!document?.content.content) return ["자막 문서가 비어 있습니다."];
  const errors: string[] = [];
  document.content.content.forEach((paragraph, index) => {
    if (paragraph.type !== "paragraph") {
      errors.push(`${index + 1}행은 일반 자막 문단이어야 합니다.`);
      return;
    }
    const text = inlineSegments(paragraph).map((segment) => segment.text).join("");
    if (text.trim() && !TIMESTAMP_PREFIX.test(text)) errors.push(`${index + 1}행: [00:00-00:03] 형식으로 시작하세요.`);
  });
  return errors;
}
