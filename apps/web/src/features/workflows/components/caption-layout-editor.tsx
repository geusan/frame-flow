"use client";

import { Extension, type Editor, type JSONContent } from "@tiptap/core";
import { TextStyleKit } from "@tiptap/extension-text-style";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { AlignCenter, AlignLeft, AlignRight, Bold, Italic, Move, RotateCcw, Type } from "lucide-react";

import { NativeSelect } from "@/components/ui/native-select";
import { VideoPlayer } from "@/components/ui/video-player";
import {
  captionCues,
  captionDocumentErrors,
  richCaptionDocumentFromSrt,
  richCaptionDocumentIsEmpty,
  type RichCaptionDocument,
} from "@/features/workflows/rich-caption";
import { frameflowApi, type RegisteredFont } from "@/lib/api";
import type { CaptionAlignment } from "@/lib/canvas-model";
import { loadRegisteredFont } from "@/lib/fonts";

export interface CaptionLayoutValue {
  x: number;
  y: number;
  align: CaptionAlignment;
  fontSize: number;
}

interface CaptionLayoutEditorProps {
  videoUrl?: string;
  videoMimeType?: string;
  subtitleText?: string;
  value: CaptionLayoutValue;
  captionDocument?: RichCaptionDocument;
  richText?: boolean;
  layoutControls?: boolean;
  onChange: (value: CaptionLayoutValue) => void;
  onCaptionDocumentChange?: (document: RichCaptionDocument) => void;
}

interface DragGesture {
  pointerId: number;
  offsetX: number;
  offsetY: number;
}

const DEFAULT_LAYOUT: CaptionLayoutValue = { x: 0.5, y: 0.82, align: "center", fontSize: 54 };

const FontReference = Extension.create({
  name: "fontReference",
  addGlobalAttributes() {
    return [{
      types: ["textStyle"],
      attributes: {
        fontId: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-font-id"),
          renderHTML: (attributes) => attributes.fontId ? { "data-font-id": attributes.fontId } : {},
        },
      },
    }];
  },
});

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function anchorTransform(align: CaptionAlignment) {
  if (align === "left") return "translate(0,-50%)";
  if (align === "right") return "translate(-100%,-50%)";
  return "translate(-50%,-50%)";
}

function selectedParagraph(editor: Editor): number {
  const position = editor.state.selection.from;
  let selected = 0;
  editor.state.doc.forEach((node, offset, index) => {
    if (position >= offset && position <= offset + node.nodeSize) selected = index;
  });
  return selected;
}

function buildDocument(content: JSONContent, current: RichCaptionDocument, defaultFontSize: number): RichCaptionDocument {
  return {
    schema_version: "caption.document.v1",
    content,
    default_style: {
      ...current.default_style,
      font_size: defaultFontSize,
      color: current.default_style.color || "#FFFFFF",
    },
  };
}

export function CaptionLayoutEditor({
  videoUrl,
  videoMimeType,
  subtitleText,
  value,
  captionDocument,
  richText = false,
  layoutControls = true,
  onChange,
  onCaptionDocumentChange,
}: CaptionLayoutEditorProps) {
  const [initialDocument] = useState(() => richCaptionDocumentIsEmpty(captionDocument)
      ? richCaptionDocumentFromSrt(subtitleText, value.fontSize)
      : captionDocument!);
  const [draft, setDraft] = useState(value);
  const [documentValue, setDocumentValue] = useState<RichCaptionDocument>(initialDocument);
  const [fonts, setFonts] = useState<RegisteredFont[]>([]);
  const [activeCueIndex, setActiveCueIndex] = useState(0);
  const [videoRatio, setVideoRatio] = useState("9 / 16");
  const [stageShortEdge, setStageShortEdge] = useState(320);
  const [fontError, setFontError] = useState<string | null>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragGesture | null>(null);
  const draftRef = useRef(value);
  const documentRef = useRef(initialDocument);
  const emittedInitialRef = useRef(false);

  const emitDocument = useCallback((next: RichCaptionDocument) => {
    documentRef.current = next;
    setDocumentValue(next);
    if (richText) onCaptionDocumentChange?.(next);
  }, [onCaptionDocumentChange, richText]);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        blockquote: false,
        bulletList: false,
        code: false,
        codeBlock: false,
        heading: false,
        horizontalRule: false,
        listItem: false,
        orderedList: false,
        strike: false,
      }),
      TextStyleKit.configure({ backgroundColor: false, lineHeight: false }),
      FontReference,
    ],
    content: initialDocument.content,
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class: "caption-tiptap-content",
        "aria-label": "Timestamped rich captions",
        spellcheck: "false",
      },
    },
  });

  useEffect(() => {
    if (!editor) return;
    const update = () => {
      emitDocument(buildDocument(editor.getJSON(), documentRef.current, draftRef.current.fontSize));
      setActiveCueIndex(selectedParagraph(editor));
    };
    const updateSelection = () => setActiveCueIndex(selectedParagraph(editor));
    editor.on("update", update);
    editor.on("selectionUpdate", updateSelection);
    return () => {
      editor.off("update", update);
      editor.off("selectionUpdate", updateSelection);
    };
  }, [editor, emitDocument]);

  useEffect(() => {
    if (emittedInitialRef.current) return;
    emittedInitialRef.current = true;
    if (richText) onCaptionDocumentChange?.(initialDocument);
  }, [initialDocument, onCaptionDocumentChange, richText]);

  useEffect(() => {
    let active = true;
    frameflowApi.listFonts()
      .then(async (records) => {
        await Promise.allSettled(records.map(loadRegisteredFont));
        if (active) setFonts(records);
      })
      .catch((error: unknown) => { if (active) setFontError(error instanceof Error ? error.message : "등록 글꼴을 불러오지 못했습니다."); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (dragRef.current) return;
    setDraft(value);
    draftRef.current = value;
  }, [value]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const measure = () => {
      const rect = stage.getBoundingClientRect();
      setStageShortEdge(Math.min(rect.width || 320, rect.height || 320));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(stage);
    return () => observer.disconnect();
  }, [videoUrl]);

  const updateDraft = (next: CaptionLayoutValue, commit = false) => {
    draftRef.current = next;
    setDraft(next);
    if (commit) onChange(next);
  };

  const beginDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const stage = stageRef.current;
    if (!stage) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = stage.getBoundingClientRect();
    dragRef.current = {
      pointerId: event.pointerId,
      offsetX: event.clientX - (rect.left + draftRef.current.x * rect.width),
      offsetY: event.clientY - (rect.top + draftRef.current.y * rect.height),
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const moveCaption = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const stage = stageRef.current;
    const gesture = dragRef.current;
    if (!stage || !gesture || gesture.pointerId !== event.pointerId) return;
    event.preventDefault();
    const rect = stage.getBoundingClientRect();
    updateDraft({
      ...draftRef.current,
      x: clamp((event.clientX - rect.left - gesture.offsetX) / rect.width, 0.06, 0.94),
      y: clamp((event.clientY - rect.top - gesture.offsetY) / rect.height, 0.08, 0.92),
    });
  };

  const finishDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const gesture = dragRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    onChange(draftRef.current);
  };

  const setHorizontal = (align: CaptionAlignment) => {
    updateDraft({ ...draftRef.current, align, x: align === "left" ? 0.08 : align === "right" ? 0.92 : 0.5 }, true);
  };

  const setVertical = (y: number) => updateDraft({ ...draftRef.current, y }, true);
  const setDefaultFontSize = (fontSize: number) => {
    const next = { ...draftRef.current, fontSize };
    updateDraft(next, true);
    emitDocument(buildDocument(documentRef.current.content, documentRef.current, fontSize));
  };

  const applyFont = (fontId: string) => {
    if (!editor) return;
    if (!fontId) {
      editor.chain().focus().setMark("textStyle", { fontId: null, fontFamily: null }).removeEmptyTextStyle().run();
      return;
    }
    const font = fonts.find((candidate) => candidate.id === fontId);
    if (font) editor.chain().focus().setMark("textStyle", { fontId: font.id, fontFamily: font.css_family }).run();
  };

  const setSelectedFontSize = (fontSize: number) => {
    if (editor && Number.isFinite(fontSize)) editor.chain().focus().setFontSize(`${clamp(fontSize, 8, 240)}px`).run();
  };

  const cues = useMemo(() => captionCues(documentValue), [documentValue]);
  const activeCue = cues[Math.min(activeCueIndex, Math.max(0, cues.length - 1))];
  const validationErrors = useMemo(() => captionDocumentErrors(documentValue), [documentValue]);
  const textStyle = editor?.getAttributes("textStyle") ?? {};
  const selectedFontId = String(textStyle.fontId ?? "");
  const selectedFontSize = Number.parseFloat(String(textStyle.fontSize ?? draft.fontSize));
  const selectedColor = /^#[0-9a-fA-F]{6}$/.test(String(textStyle.color ?? "")) ? String(textStyle.color) : "#ffffff";

  return <div className="caption-layout-editor rich-caption-designer">
    {layoutControls && <><div ref={stageRef} className={`caption-layout-stage ${videoUrl ? "has-video" : "missing-video"}`} style={{ aspectRatio: videoRatio }}>
      {videoUrl ? <VideoPlayer className="caption-layout-video" src={videoUrl} mimeType={videoMimeType} title="Caption layout preview" compact preload="metadata" onMetadata={({ width, height }) => { if (width && height) setVideoRatio(`${width} / ${height}`); }} /> : <div className="caption-layout-empty"><Move size={19} /><strong>Video를 연결하세요</strong><span>연결된 영상 위에서 Rich Caption을 확인할 수 있습니다.</span></div>}
      {videoUrl && <button type="button" className={`caption-layout-overlay ${richText ? "rich " : ""}align-${draft.align}`} aria-label="드래그하여 자막 위치 조정" style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%`, transform: anchorTransform(draft.align), textAlign: draft.align }} onPointerDown={beginDrag} onPointerMove={moveCaption} onPointerUp={finishDrag} onPointerCancel={finishDrag}>
        <span>{activeCue?.runs.length ? activeCue.runs.map((run, index) => {
          const font = fonts.find((candidate) => candidate.id === run.fontId);
          const visualScale = font?.size_adjust ?? 1;
          return <span style={{ color: run.color, fontFamily: run.fontFamily ? `"${run.fontFamily}", "Noto Sans KR", sans-serif` : undefined, fontSize: Math.max(8, run.fontSize * stageShortEdge / 1080 * visualScale), fontWeight: run.bold ? 700 : font?.weight, fontStyle: run.italic ? "italic" : font?.style }} key={`${index}-${run.text}`}>{run.text}</span>;
        }) : "[00:00-00:03] 형식으로 자막을 입력하세요"}</span>
        <i><Move size={11} /> drag</i>
      </button>}
      {activeCue && <span className="caption-preview-time">{activeCue.start}–{activeCue.end}</span>}
    </div>

    <div className="caption-layout-controls">
      <div className="caption-layout-control-row"><span>가로 정렬</span><div className="caption-layout-segmented"><button type="button" className={draft.align === "left" ? "active" : ""} onClick={() => setHorizontal("left")} aria-label="왼쪽 정렬"><AlignLeft size={14} /> 왼쪽</button><button type="button" className={draft.align === "center" ? "active" : ""} onClick={() => setHorizontal("center")} aria-label="가운데 정렬"><AlignCenter size={14} /> 가운데</button><button type="button" className={draft.align === "right" ? "active" : ""} onClick={() => setHorizontal("right")} aria-label="오른쪽 정렬"><AlignRight size={14} /> 오른쪽</button></div></div>
      <div className="caption-layout-control-row"><span>세로 위치</span><div className="caption-layout-segmented compact"><button type="button" className={Math.abs(draft.y - 0.18) < 0.02 ? "active" : ""} onClick={() => setVertical(0.18)}>상단</button><button type="button" className={Math.abs(draft.y - 0.5) < 0.02 ? "active" : ""} onClick={() => setVertical(0.5)}>중앙</button><button type="button" className={Math.abs(draft.y - 0.82) < 0.02 ? "active" : ""} onClick={() => setVertical(0.82)}>하단</button></div></div>
      <label className="caption-size-control"><span>기본 글자 크기 <b>{draft.fontSize}px</b></span><input type="range" min="30" max="88" step="2" value={draft.fontSize} onChange={(event) => setDefaultFontSize(Number(event.target.value))} /></label>
      <div className="caption-layout-coordinates"><span>X {Math.round(draft.x * 100)}%</span><span>Y {Math.round(draft.y * 100)}%</span><button type="button" onClick={() => updateDraft(DEFAULT_LAYOUT, true)}><RotateCcw size={12} /> 초기화</button></div>
    </div></>}

    {richText && <section className="caption-document-panel">
      <header><div><small>Caption document · TipTap</small><strong>한 문단에 자막 하나를 입력하세요</strong></div><span>{cues.length} cues</span></header>
      <div className="caption-editor-toolbar" role="toolbar" aria-label="Caption text formatting">
        <button type="button" className={editor?.isActive("bold") ? "active" : ""} onMouseDown={(event) => event.preventDefault()} onClick={() => editor?.chain().focus().toggleBold().run()} aria-label="Bold"><Bold size={14} /></button>
        <button type="button" className={editor?.isActive("italic") ? "active" : ""} onMouseDown={(event) => event.preventDefault()} onClick={() => editor?.chain().focus().toggleItalic().run()} aria-label="Italic"><Italic size={14} /></button>
        <span className="caption-toolbar-divider" />
        <label className="caption-color-control" title="Text color"><input type="color" value={selectedColor} onInput={(event) => editor?.chain().focus().setColor(event.currentTarget.value).run()} /><span style={{ background: selectedColor }} /></label>
        <NativeSelect className="caption-font-select" value={selectedFontId} onChange={(event) => applyFont(event.target.value)} aria-label="Font family"><option value="">Renderer default · Noto Sans CJK KR</option>{fonts.map((font) => <option value={font.id} key={font.id}>{font.display_name} · {font.subfamily_name}</option>)}</NativeSelect>
        <label className="caption-inline-size"><Type size={13} /><input type="number" min="8" max="240" value={Number.isFinite(selectedFontSize) ? selectedFontSize : draft.fontSize} onChange={(event) => setSelectedFontSize(Number(event.target.value))} /><span>px</span></label>
      </div>
      <EditorContent editor={editor} />
      <footer><code>[00:00-00:03] 자막1</code><span>텍스트를 선택한 뒤 색상·폰트·크기를 적용하세요.</span></footer>
      {fontError && <p className="caption-document-warning">Font Registry: {fontError}</p>}
      {validationErrors.length > 0 && <p className="caption-document-warning">{validationErrors[0]}</p>}
    </section>}
  </div>;
}
