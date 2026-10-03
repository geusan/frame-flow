"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, LoaderCircle } from "lucide-react";
import { FontCatalogBrowser } from "@/components/views/font-catalog-browser";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import type { RegisteredFont } from "@/lib/api";
import { loadRegisteredFont } from "@/lib/fonts";

export function CaptionFontPicker({ fonts, selectedFontId, onImported, onApply }: {
  fonts: RegisteredFont[];
  selectedFontId: string;
  onImported: (font: RegisteredFont) => void;
  onApply: (font: RegisteredFont | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectionSession = useRef(0);
  const selected = fonts.find((font) => font.id === selectedFontId);

  useEffect(() => () => { selectionSession.current += 1; }, []);

  function changeOpen(next: boolean) {
    selectionSession.current += 1;
    setOpen(next);
    setPending(null);
    setError(null);
  }

  function apply(font: RegisteredFont | null) {
    onApply(font);
    changeOpen(false);
  }

  async function chooseRegistered(font: RegisteredFont) {
    const session = selectionSession.current;
    setPending(font.id);
    setError(null);
    try {
      await loadRegisteredFont(font);
      if (session === selectionSession.current) apply(font);
    } catch (cause) {
      if (session === selectionSession.current) setError(cause instanceof Error ? cause.message : "폰트를 불러오지 못했습니다.");
    } finally {
      if (session === selectionSession.current) setPending(null);
    }
  }

  return <Dialog open={open} onOpenChange={changeOpen}>
    <DialogTrigger asChild><Button type="button" variant="secondary" className="caption-font-picker-trigger" aria-label="Font family"><span>{selected?.display_name ?? (selectedFontId ? "등록 폰트" : "기본 글꼴")}</span><ChevronDown size={13} /></Button></DialogTrigger>
    <DialogContent className="caption-font-picker" overlayClassName="caption-font-picker-overlay" showCloseButton>
      <DialogHeader>
        <DialogTitle>자막 글꼴 선택</DialogTitle>
        <DialogDescription>텍스트를 선택한 뒤 글꼴을 적용하세요. 커서만 있으면 이후 입력할 텍스트에 적용됩니다.</DialogDescription>
      </DialogHeader>
      <section className="caption-font-picker-registered" aria-label="등록된 글꼴">
        <h3>등록된 글꼴 <span>{fonts.length}</span></h3>
        <div>
          <Button type="button" size="sm" variant={!selectedFontId ? "default" : "secondary"} disabled={pending !== null} onClick={() => apply(null)}>기본 글꼴</Button>
          {fonts.map((font) => <Button key={font.id} type="button" size="sm" variant={font.id === selectedFontId ? "default" : "secondary"} disabled={pending !== null} onClick={() => void chooseRegistered(font)}>{pending === font.id && <LoaderCircle size={13} className="spin" />}{font.display_name}</Button>)}
        </div>
        {error && <p role="alert">{error}</p>}
      </section>
      {open && <FontCatalogBrowser fonts={fonts} onImported={onImported} onApply={apply} />}
    </DialogContent>
  </Dialog>;
}
