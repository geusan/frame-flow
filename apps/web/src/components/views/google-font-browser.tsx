"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Check, ChevronLeft, ChevronRight, CircleAlert, Download, ExternalLink, LoaderCircle, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { frameflowApi, type GoogleFontFamily, type GoogleFontSearchResult, type RegisteredFont } from "@/lib/api";
import { loadRegisteredFont } from "@/lib/fonts";

function variantLabel(variant: string): string {
  const weight = Number.parseInt(variant, 10);
  const names: Record<number, string> = { 100: "Thin", 200: "Extra Light", 300: "Light", 400: "Regular", 500: "Medium", 600: "Semi Bold", 700: "Bold", 800: "Extra Bold", 900: "Black" };
  return `${names[weight] ?? weight} ${weight}${variant.endsWith("i") ? " Italic" : ""}`;
}

function findRegisteredFont(fonts: RegisteredFont[], family: string, variant: string): RegisteredFont | undefined {
  return fonts.find((font) => font.lifecycle === "ACTIVE" && (
    (font.google_fonts?.family === family && font.google_fonts.variant === variant)
    || (font.family_name === family && font.weight === Number.parseInt(variant, 10) && font.style === (variant.endsWith("i") ? "italic" : "normal"))
  ));
}

function GoogleFontCard({ family, fonts, importing, selectable, onImport }: {
  family: GoogleFontFamily;
  fonts: RegisteredFont[];
  importing: string | null;
  selectable: boolean;
  onImport: (family: string, variant: string) => void;
}) {
  const [variant, setVariant] = useState(family.variants.includes("400") ? "400" : family.variants[0]);
  const [preview, setPreview] = useState<{ key: string; failed: boolean } | null>(null);
  const key = `${family.family}:${variant}`;
  const weight = Number.parseInt(variant, 10);
  const italic = variant.endsWith("i");
  const sample = family.subsets.includes("korean") ? "당신의 이야기를 담는 글꼴" : "Every story starts here.";
  const installed = Boolean(findRegisteredFont(fonts, family.family, variant));

  useEffect(() => {
    let active = true;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://fonts.googleapis.com/css2?" + new URLSearchParams({
      family: `${family.family}:ital,wght@${Number(italic)},${weight}`,
      text: sample,
      display: "swap",
    });
    const finish = (failed: boolean) => { if (active) setPreview({ key, failed }); };
    const timeout = window.setTimeout(() => finish(true), 15000);
    link.onload = () => {
      document.fonts.load(`${italic ? "italic" : "normal"} ${weight} 28px ${JSON.stringify(family.family)}`, sample)
        .then((faces) => finish(faces.length === 0)).catch(() => finish(true))
        .finally(() => window.clearTimeout(timeout));
    };
    link.onerror = () => { window.clearTimeout(timeout); finish(true); };
    document.head.appendChild(link);
    return () => { active = false; window.clearTimeout(timeout); link.remove(); };
  }, [family.family, italic, key, sample, weight]);

  return <Card className="google-font-card">
    <header>
      <div><h4>{family.family}</h4><span>{family.category} · {family.variants.length} styles</span></div>
      {family.subsets.includes("korean") && <Badge variant="outline">한글</Badge>}
    </header>
    <div className="google-font-preview" aria-label={`${family.family} 미리보기`}>
      <p style={{ fontFamily: `${JSON.stringify(family.family)}, sans-serif`, fontWeight: weight, fontStyle: italic ? "italic" : "normal", visibility: preview?.key === key && !preview.failed ? "visible" : "hidden" }}>{sample}</p>
      {preview?.key !== key && <span><LoaderCircle size={14} className="spin" /> 미리보기 로딩 중…</span>}
      {preview?.key === key && preview.failed && <span>미리보기를 불러오지 못했습니다.</span>}
    </div>
    <footer>
      <NativeSelect aria-label={`${family.family} 스타일`} value={variant} disabled={importing === key} onChange={(event) => setVariant(event.target.value)}>
        {family.variants.map((value) => <option key={value} value={value}>{variantLabel(value)}</option>)}
      </NativeSelect>
      <Button type="button" size="sm" variant={installed ? "secondary" : "default"} disabled={(installed && !selectable) || importing !== null} onClick={() => onImport(family.family, variant)}>
        {installed ? <Check size={14} /> : importing === key ? <LoaderCircle size={14} className="spin" /> : <Download size={14} />}
        {importing === key ? "준비 중…" : installed ? (selectable ? "적용" : "등록됨") : selectable ? "선택 · 적용" : "다운로드 · 적용"}
      </Button>
    </footer>
  </Card>;
}

export function GoogleFontBrowser({ fonts, onImported, onApply }: {
  fonts: RegisteredFont[];
  onImported: (font: RegisteredFont) => void;
  onApply?: (font: RegisteredFont) => void;
}) {
  const [search, setSearch] = useState({ query: "", koreanOnly: false, offset: 0, retry: 0 });
  const [result, setResult] = useState<GoogleFontSearchResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [importing, setImporting] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [counts, setCounts] = useState<{ total: number; korean: number } | null>(null);
  const mounted = useRef(false);
  const headingId = useId();

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      frameflowApi.searchGoogleFonts(search.query, search.koreanOnly, search.offset, controller.signal)
        .then((data) => {
          if (controller.signal.aborted) return;
          setResult(data);
          setCounts({ total: data.catalog_total, korean: data.korean_total });
        })
        .catch((error: unknown) => { if (!controller.signal.aborted) setSearchError(error instanceof Error ? error.message : "글꼴 검색에 실패했습니다."); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 300);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [search]);

  function updateSearch(next: Partial<typeof search>) {
    setLoading(true);
    setSearchError(null);
    setResult(null);
    setSearch((current) => ({ ...current, offset: 0, ...next }));
  }

  async function importFont(family: string, variant: string) {
    setImporting(`${family}:${variant}`);
    setImportError(null);
    setNotice(null);
    try {
      const existing = findRegisteredFont(fonts, family, variant);
      const font = existing ?? await frameflowApi.importGoogleFont(family, variant);
      onImported(font);
      if (onApply) {
        await loadRegisteredFont(font);
        // Closing the picker cancels applying to the document, even if a
        // download that was already submitted finishes in the background.
        if (mounted.current) onApply(font);
      } else {
        if (mounted.current) setNotice(`${font.display_name} 등록 완료. Caption Designer에서 바로 선택할 수 있습니다.`);
        void loadRegisteredFont(font).catch(() => {});
      }
    } catch (error) {
      if (mounted.current) setImportError(error instanceof Error ? error.message : "폰트 다운로드에 실패했습니다.");
    } finally {
      if (mounted.current) setImporting(null);
    }
  }

  return <section className="google-font-browser" aria-labelledby={headingId}>
    <header className="google-font-heading">
      <div><h3 id={headingId}>Google Fonts {counts && <span className="google-font-total">전체 {counts.total.toLocaleString()}종 · 한글 {counts.korean}종</span>}</h3><p>{onApply ? "전체 목록에서 글꼴을 선택하면 필요한 파일을 자동으로 받아 선택한 자막에 적용합니다." : "전체 Google Fonts 목록을 검색할 수 있습니다. 원하는 글꼴과 굵기를 선택해 추가하세요."}</p></div>
      <a href="https://fonts.google.com" target="_blank" rel="noreferrer">Google Fonts 열기 <ExternalLink size={13} /></a>
    </header>
    <div className="google-font-search">
      <div><Search size={16} /><Input aria-label="Google Fonts 검색" placeholder="글꼴 이름 검색 (예: Noto Sans KR, Nanum, Roboto)" maxLength={160} value={search.query} onChange={(event) => updateSearch({ query: event.target.value })} /></div>
      <label><input type="checkbox" checked={search.koreanOnly} onChange={(event) => updateSearch({ koreanOnly: event.target.checked })} /> 한글 지원만</label>
    </div>
    {searchError && <div className="google-font-feedback" role="alert"><CircleAlert size={16} /><span>{searchError}</span><Button type="button" size="sm" variant="secondary" onClick={() => updateSearch({ retry: search.retry + 1 })}>다시 시도</Button></div>}
    {importError && <div className="google-font-feedback" role="alert"><CircleAlert size={16} /><span>{importError}</span></div>}
    {notice && <div className="google-font-feedback success" role="status"><Check size={16} /><span>{notice}</span></div>}
    <div aria-busy={loading}>
      {loading && <div className="google-font-state" role="status"><LoaderCircle size={18} className="spin" /> Google Fonts 검색 중…</div>}
      {!loading && result?.total === 0 && <div className="google-font-state">검색 결과가 없습니다. 다른 이름을 입력하거나 한글 필터를 해제해 주세요.</div>}
      {!loading && result && result.total > 0 && <>
        <div className="google-font-grid">
          {result.items.map((family) => <GoogleFontCard key={family.family} family={family} fonts={fonts} importing={importing} selectable={Boolean(onApply)} onImport={(name, variant) => void importFont(name, variant)} />)}
        </div>
        <div className="google-font-pagination">
          <span>{result.offset + 1}–{result.offset + result.items.length} / {result.total.toLocaleString()}개 글꼴</span>
          <div><Button type="button" variant="ghost" size="sm" aria-label="이전 글꼴" disabled={result.offset === 0} onClick={() => updateSearch({ offset: Math.max(0, result.offset - result.limit) })}><ChevronLeft size={15} /> 이전</Button><Button type="button" variant="ghost" size="sm" aria-label="다음 글꼴" disabled={result.offset + result.limit >= result.total} onClick={() => updateSearch({ offset: result.offset + result.limit })}>다음 <ChevronRight size={15} /></Button></div>
        </div>
      </>}
    </div>
  </section>;
}
