"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Node, mergeAttributes, type JSONContent } from "@tiptap/core";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Placeholder } from "@tiptap/extensions";
import { ChevronDown, ChevronUp } from "lucide-react";

import { Button } from "@/components/ui/button";

export interface PromptConnectedImage {
  id: string;
  title: string;
  url?: string;
  outdated: boolean;
}

interface PromptTokenEditorProps {
  nodeId: string;
  value: string;
  images: PromptConnectedImage[];
  onCommit: (nodeId: string, value: string) => void;
}

const imageTokenPattern = /\{\{image:([^}]+)}}/g;

const ImageVariable = Node.create({
  name: "imageVariable",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes() {
    return {
      sourceId: { default: "" },
      label: { default: "Image" },
      outdated: { default: false },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-image-variable]" }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, {
      "data-image-variable": "true",
      "data-source-id": HTMLAttributes.sourceId,
      "data-outdated": String(Boolean(HTMLAttributes.outdated)),
      class: "prompt-image-variable",
      contenteditable: "false",
    }), String(HTMLAttributes.label || "Image")];
  },
});

function promptDocument(value: string, images: PromptConnectedImage[]): JSONContent {
  const byId = new Map(images.map((image, index) => [image.id, { ...image, label: `Image ${index + 1}` }]));
  const paragraphs = value.split("\n").map((line) => {
    const content: JSONContent[] = [];
    let cursor = 0;
    for (const match of line.matchAll(imageTokenPattern)) {
      if (match.index > cursor) content.push({ type: "text", text: line.slice(cursor, match.index) });
      const sourceId = match[1];
      const image = byId.get(sourceId);
      content.push({
        type: "imageVariable",
        attrs: {
          sourceId,
          label: image?.label ?? "Missing image",
          outdated: image ? image.outdated : true,
        },
      });
      cursor = match.index + match[0].length;
    }
    if (cursor < line.length) content.push({ type: "text", text: line.slice(cursor) });
    return { type: "paragraph", ...(content.length ? { content } : {}) };
  });
  return { type: "doc", content: paragraphs.length ? paragraphs : [{ type: "paragraph" }] };
}

function serializePrompt(document: JSONContent): string {
  return (document.content ?? []).map((paragraph) => (paragraph.content ?? []).map((node) => {
    if (node.type === "text") return node.text ?? "";
    if (node.type === "imageVariable") return `{{image:${String(node.attrs?.sourceId ?? "")}}}`;
    if (node.type === "hardBreak") return "\n";
    return "";
  }).join("")).join("\n");
}

function readablePrompt(value: string, images: PromptConnectedImage[]): string {
  const labels = new Map(images.map((image, index) => [image.id, `Image ${index + 1}`]));
  return value.replace(imageTokenPattern, (_, sourceId: string) => labels.get(sourceId) ?? "Missing image");
}

export function PromptTokenEditor({ nodeId, value, images, onCommit }: PromptTokenEditorProps) {
  const [collapsed, setCollapsed] = useState(false);
  const imageSignature = useMemo(() => images.map((image) => `${image.id}:${image.outdated}`).join("|"), [images]);
  const lastImageSignatureRef = useRef(imageSignature);
  const acceptedValueRef = useRef(value);
  const lastEmittedValueRef = useRef<string | null>(null);
  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: false, bulletList: false, orderedList: false, blockquote: false, codeBlock: false, horizontalRule: false }),
      Placeholder.configure({ placeholder: "이미지를 클릭해 참조를 넣고 프롬프트를 작성하세요…" }),
      ImageVariable,
    ],
    content: promptDocument(value, images),
    immediatelyRender: false,
    editorProps: {
      attributes: { class: "prompt-tiptap-prosemirror nodrag nopan nowheel" },
      handleKeyDown: (_, event) => { event.stopPropagation(); return false; },
    },
    onUpdate: ({ editor: currentEditor }) => {
      const nextValue = serializePrompt(currentEditor.getJSON());
      lastEmittedValueRef.current = nextValue;
      onCommit(nodeId, nextValue);
    },
  });

  useEffect(() => {
    if (!editor) return;
    const currentValue = serializePrompt(editor.getJSON());
    const imagesChanged = lastImageSignatureRef.current !== imageSignature;
    const valueChangedExternally = value !== acceptedValueRef.current && value !== lastEmittedValueRef.current;
    if (valueChangedExternally || imagesChanged) {
      editor.commands.setContent(promptDocument(valueChangedExternally ? value : currentValue, images), { emitUpdate: false });
    }
    acceptedValueRef.current = value;
    if (value === lastEmittedValueRef.current) lastEmittedValueRef.current = null;
    lastImageSignatureRef.current = imageSignature;
  }, [editor, imageSignature, images, value]);

  const insertImage = (image: PromptConnectedImage) => {
    if (!editor) return;
    const index = images.findIndex((candidate) => candidate.id === image.id);
    setCollapsed(false);
    editor.chain().focus().insertContent([
      { type: "imageVariable", attrs: { sourceId: image.id, label: `Image ${index + 1}`, outdated: image.outdated } },
      { type: "text", text: " " },
    ]).run();
  };

  return <div className="prompt-token-composer nodrag nopan nowheel">
    {images.length > 0 && <div className="prompt-image-inputs">
      <span className="prompt-image-inputs-label">Connected images · click to insert</span>
      <div>{images.map((image, index) => <button className={`prompt-image-input ${image.outdated ? "outdated" : ""}`} type="button" title={`Insert Image ${index + 1}: ${image.title}`} onClick={() => insertImage(image)} key={image.id}>
        <i style={image.url ? { backgroundImage: `url(${image.url})` } : undefined} />
        <span><b>Image {index + 1}</b>{image.outdated && <em>Outdated</em>}</span>
      </button>)}</div>
    </div>}
    <div className="node-prompt-editor prompt-tiptap-editor" data-collapsed={collapsed}>
      <div className="node-prompt-toolbar">
        <span className="node-prompt-label">Prompt</span>
        <Button type="button" variant="ghost" size="sm" className="node-prompt-toggle nodrag nopan" aria-expanded={!collapsed} onClick={(event) => { event.stopPropagation(); setCollapsed((current) => !current); }}>
          {collapsed ? <><ChevronDown size={13} /> 펼치기</> : <><ChevronUp size={13} /> 접기</>}
        </Button>
      </div>
      {collapsed && <p className="node-prompt-summary" title={readablePrompt(value, images)}>{readablePrompt(value, images).trim() || "프롬프트를 입력하세요…"}</p>}
      <div hidden={collapsed}><EditorContent editor={editor} /></div>
    </div>
  </div>;
}
