"use client";
import { useStudioRuntime } from "../../runtime/studio-runtime";


import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Check, ChevronLeft, ChevronRight, CircleAlert, Download, ExternalLink, LoaderCircle, Search } from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card } from "../ui/card";
import { Input } from "../ui/input";
import { NativeSelect } from "../ui/native-select";
import { type NoonnuFontDetail, type NoonnuFontSearchResult, type NoonnuFontVariant, type RegisteredFont } from "../../lib/api";
import { loadRegisteredFont } from "../../lib/fonts";

function NoonnuPreview({ fontId, face }: { fontId: number; face: NoonnuFontVariant | null }) {
  const root = useRef<HTMLDivElement>(null);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const cssFamily = `ff-noonnu-preview-${fontId}-${face?.key ?? "none"}`;
  useEffect(() => {
    if (!face || !root.current) return;
    let active = true;
    let font: FontFace | null = null;
    let timeout: number | undefined;
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      timeout = window.setTimeout(() => { if (active) setFailed(cssFamily); }, 15000);
      font = new FontFace(cssFamily, `url(${JSON.stringify(face.url)})`, { weight: String(face.weight), style: face.style });
      font.load().then((loadedFont) => {
        if (!active) return;
        document.fonts.add(loadedFont);
        setLoaded(cssFamily);
      }).catch(() => { if (active) setFailed(cssFamily); }).finally(() => window.clearTimeout(timeout));
    }, { rootMargin: "100px" });
    observer.observe(root.current);
    return () => { active = false; observer.disconnect(); window.clearTimeout(timeout); if (font) document.fonts.delete(font); };
  }, [cssFamily, face]);
  return <div className="google-font-preview" ref={root}>
    <p style={{ fontFamily: JSON.stringify(cssFamily), fontWeight: face?.weight, fontStyle: face?.style, visibility: loaded === cssFamily ? "visible" : "hidden" }}>당신의 이야기를 담는 글꼴</p>
    {loaded !== cssFamily && <span>{!face || failed === cssFamily ? "원본 페이지에서 미리보기를 확인하세요." : <><LoaderCircle size={14} className="spin" /> 미리보기 로딩 중…</>}</span>}
  </div>;
}

export function NoonnuFontBrowser({ fonts, onImported, onApply }: {
  fonts: RegisteredFont[];
  onImported: (font: RegisteredFont) => void;
  onApply?: (font: RegisteredFont) => void;
}) {
  const { frameflowApi } = useStudioRuntime();
  const [search, setSearch] = useState({ query: "", page: 1, retry: 0 });
  const [result, setResult] = useState<NoonnuFontSearchResult | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<NoonnuFontDetail | null>(null);
  const [variant, setVariant] = useState("400");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const active = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      frameflowApi.searchNoonnuFonts(search.query, search.page, controller.signal)
        .then((data) => { if (!controller.signal.aborted) setResult(data); })
        .catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "눈누 검색에 실패했습니다."); });
    }, 350);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [search, frameflowApi]);

  useEffect(() => {
    if (selectedId === null) return;
    const controller = new AbortController();
    frameflowApi.getNoonnuFont(selectedId, controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      setDetail(data);
      setVariant(data.variants.find((face) => face.key === "400")?.key ?? data.variants[0]?.key ?? "400");
    }).catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "글꼴 정보를 불러오지 못했습니다."); });
    return () => controller.abort();
  }, [selectedId, search.retry, frameflowApi]);

  function updateSearch(values: Partial<typeof search>) {
    setError(null); setResult(null); setDetail(null); setSelectedId(null);
    setSearch((current) => ({ ...current, page: 1, ...values }));
  }

  function choose(fontId: number) {
    setError(null); setNotice(null); setDetail(null); setSelectedId(fontId);
  }

  const face = detail?.variants.find((item) => item.key === variant) ?? null;
  const registered = detail ? fonts.find((font) => font.lifecycle === "ACTIVE" && font.noonnu?.id === detail.id && font.noonnu.variant === variant) : undefined;
  const previewFace = useMemo(() => face?.archive_member
    ? registered ? { ...face, url: registered.url } : null
    : face, [face, registered]);

  async function importFont() {
    if (!detail || !face) return;
    setPending(true); setError(null); setNotice(null);
    try {
      const font = registered ?? await frameflowApi.importNoonnuFont(detail.id, variant);
      onImported(font);
      if (onApply) {
        await loadRegisteredFont(font);
        if (active.current) onApply(font);
      } else {
        if (active.current) setNotice(`${font.display_name} 등록 완료. 자막 편집기에서 선택할 수 있습니다.`);
        void loadRegisteredFont(font).catch(() => {});
      }
    } catch (cause) {
      if (active.current) setError(cause instanceof Error ? cause.message : "폰트를 가져오지 못했습니다.");
    } finally {
      if (active.current) setPending(false);
    }
  }

  return <section className="google-font-browser noonnu-font-browser" aria-label="눈누 폰트">
    <header className="google-font-heading"><div><h3>눈누 {result && <span className="google-font-total">무료 폰트 {result.total.toLocaleString()}종{search.query && " 검색됨"}</span>}</h3><p>한글 폰트를 검색하고, 제공되는 스타일과 사용 범위를 확인해 적용하세요.</p></div><a href="https://noonnu.cc/index" target="_blank" rel="noreferrer">눈누 열기 <ExternalLink size={13} /></a></header>
    {result?.source_audit?.verified_downloads && <p className="noonnu-audit-summary"><Check size={14} /> {result.source_audit.verified_downloads.toLocaleString()}종 다운로드 경로 확인 · Google Fonts와 제작사 배포 파일 포함</p>}
    {selectedId === null && <div className="google-font-search"><div><Search size={16} /><Input aria-label="눈누 폰트 검색" maxLength={40} placeholder="폰트 또는 제작자 검색 (예: 프리텐다드, 지마켓)" value={search.query} onChange={(event) => updateSearch({ query: event.target.value })} /></div></div>}
    {selectedId !== null && <Button className="noonnu-back" type="button" variant="ghost" size="sm" disabled={pending} onClick={() => { setSelectedId(null); setDetail(null); setError(null); }}><ArrowLeft size={14} /> 검색 목록</Button>}
    {error && <div className="google-font-feedback" role="alert"><CircleAlert size={16} /><span>{error}</span><Button type="button" size="sm" variant="secondary" disabled={pending} onClick={() => { setError(null); setSearch((current) => ({ ...current, retry: current.retry + 1 })); }}>다시 시도</Button></div>}
    {notice && <div className="google-font-feedback success" role="status"><Check size={16} /><span>{notice}</span></div>}
    {selectedId !== null ? detail ? <Card className="noonnu-font-detail">
      <header><div><h4>{detail.name}</h4><p>{detail.designer}</p></div><a href={detail.page_url} target="_blank" rel="noreferrer">눈누 상세 <ExternalLink size={13} /></a></header>
      <NoonnuPreview fontId={detail.id} face={previewFace} />
      {detail.source_audit && face && <div className="noonnu-verified-source"><Badge variant="success">다운로드 경로 확인</Badge><span>{face.archive_member ? "제작사 ZIP에서 선택한 글꼴을 가져옵니다." : face.source_kind?.startsWith("google_fonts") ? "Google Fonts 공식 배포 파일" : "확인된 원본 폰트 파일"}</span><a href={face.url} target="_blank" rel="noreferrer">{face.archive_member ? "제작사 ZIP 받기" : "원본 파일 받기"}<ExternalLink size={13} /></a></div>}
      <div className="noonnu-permissions">{["영상", "웹사이트", "임베딩"].map((key) => <Badge key={key} variant={detail.permissions[key] === "사용 가능" ? "success" : "warning"}>{key === "임베딩" ? "서버 탑재" : key} · {detail.permissions[key] ?? "원본 확인"}</Badge>)}</div>
      <details className="noonnu-license"><summary>라이선스 본문 보기</summary><p>{detail.license_text || "원본 페이지에서 라이선스를 확인해 주세요."}</p></details>
      {!detail.can_import && <p className="noonnu-unavailable">{detail.unavailable_reason}</p>}
      <footer>
        {detail.variants.length > 0 && <NativeSelect aria-label={`${detail.name} 스타일`} disabled={pending} value={variant} onChange={(event) => { setVariant(event.target.value); setNotice(null); setError(null); }}>{detail.variants.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</NativeSelect>}
        <div>{detail.download_page_url && <a href={detail.download_page_url} target="_blank" rel="noreferrer">원본 다운로드 <ExternalLink size={13} /></a>}<Button type="button" disabled={pending || !detail.can_import || (!onApply && Boolean(registered))} onClick={() => void importFont()}>{pending ? <LoaderCircle size={14} className="spin" /> : registered ? <Check size={14} /> : <Download size={14} />}{pending ? "준비 중…" : registered ? (onApply ? "적용" : "등록됨") : onApply ? "선택 · 적용" : "다운로드 · 적용"}</Button></div>
      </footer>
    </Card> : !error && <div className="google-font-state" role="status"><LoaderCircle size={18} className="spin" /> 스타일과 사용 범위를 불러오는 중…</div> : <>
      {!result && !error && <div className="google-font-state" role="status"><LoaderCircle size={18} className="spin" /> 눈누 검색 중…</div>}
      {result?.items.length === 0 && <div className="google-font-state">검색 결과가 없습니다. 다른 폰트 이름이나 제작자로 검색해 주세요.</div>}
      {result && result.items.length > 0 && <><div className="google-font-grid">{result.items.map((font) => <Card key={font.id} className="google-font-card"><header><div><h4>{font.name}</h4><span>{font.designer} · {font.variant_count}가지 스타일</span></div></header><NoonnuPreview fontId={font.id} face={font.preview} /><footer><a href={font.page_url} target="_blank" rel="noreferrer">눈누에서 보기 <ExternalLink size={12} /></a><Button type="button" size="sm" variant="secondary" onClick={() => choose(font.id)}>스타일 선택</Button></footer></Card>)}</div><div className="google-font-pagination"><span>{result.page}페이지 · {result.total.toLocaleString()}종</span><div><Button type="button" variant="ghost" size="sm" disabled={result.page === 1} aria-label="이전 눈누 폰트" onClick={() => updateSearch({ page: result.page - 1 })}><ChevronLeft size={15} /> 이전</Button><Button type="button" variant="ghost" size="sm" disabled={!result.has_more} aria-label="다음 눈누 폰트" onClick={() => updateSearch({ page: result.page + 1 })}>다음 <ChevronRight size={15} /></Button></div></div></>}
    </>}
  </section>;
}
