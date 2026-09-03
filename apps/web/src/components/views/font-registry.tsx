"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Archive, ArchiveRestore, Check, CircleAlert, RefreshCw, Save, SlidersHorizontal, Type, Upload } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { frameflowApi, type RegisteredFont } from "@/lib/api";
import { fontPreviewStyle, loadRegisteredFont } from "@/lib/fonts";

interface FontDraft {
  displayName: string;
  licenseName: string;
  sizeAdjust: number;
  baselineShift: number;
}

function draftFor(font: RegisteredFont): FontDraft {
  return {
    displayName: font.display_name,
    licenseName: font.license_name,
    sizeAdjust: font.size_adjust,
    baselineShift: font.baseline_shift,
  };
}

function formatBytes(value: number): string {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function FontRegistry() {
  const [fonts, setFonts] = useState<RegisteredFont[]>([]);
  const [drafts, setDrafts] = useState<Record<string, FontDraft>>({});
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const records = await frameflowApi.listFonts(true);
      setFonts(records);
      setDrafts(Object.fromEntries(records.map((font) => [font.id, draftFor(font)])));
      await Promise.allSettled(records.map(loadRegisteredFont));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Font registry loading failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    frameflowApi.listFonts(true)
      .then(async (records) => {
        await Promise.allSettled(records.map(loadRegisteredFont));
        if (!active) return;
        setFonts(records);
        setDrafts(Object.fromEntries(records.map((font) => [font.id, draftFor(font)])));
      })
      .catch((loadError: unknown) => { if (active) setError(loadError instanceof Error ? loadError.message : "Font registry loading failed"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const register = useCallback(async (file: File) => {
    setUploading(true);
    setError(null);
    try {
      const font = await frameflowApi.registerFont(file);
      await loadRegisteredFont(font);
      await load();
      setSaved(font.id);
      window.setTimeout(() => setSaved((current) => current === font.id ? null : current), 1800);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Font registration failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }, [load]);

  const save = useCallback(async (font: RegisteredFont) => {
    const draft = drafts[font.id] ?? draftFor(font);
    setSaving(font.id);
    setError(null);
    try {
      const updated = await frameflowApi.updateFont(font.id, {
        display_name: draft.displayName,
        license_name: draft.licenseName,
        size_adjust: draft.sizeAdjust,
        baseline_shift: draft.baselineShift,
      });
      setFonts((current) => current.map((item) => item.id === font.id ? updated : item));
      setDrafts((current) => ({ ...current, [font.id]: draftFor(updated) }));
      setSaved(font.id);
      window.setTimeout(() => setSaved((current) => current === font.id ? null : current), 1800);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Font profile save failed");
    } finally {
      setSaving(null);
    }
  }, [drafts]);

  const toggleLifecycle = useCallback(async (font: RegisteredFont) => {
    setSaving(font.id);
    setError(null);
    try {
      const updated = await frameflowApi.updateFont(font.id, { lifecycle: font.lifecycle === "ACTIVE" ? "RETIRED" : "ACTIVE" });
      setFonts((current) => current.map((item) => item.id === font.id ? updated : item));
    } catch (toggleError) {
      setError(toggleError instanceof Error ? toggleError.message : "Font lifecycle update failed");
    } finally {
      setSaving(null);
    }
  }, []);

  const activeCount = useMemo(() => fonts.filter((font) => font.lifecycle === "ACTIVE").length, [fonts]);

  return <div className="view-page fonts-page">
    <PageHeader
      title="Caption Fonts"
      description="자막 렌더러와 TipTap 미리보기가 함께 사용할 TTF/OTF Face와 시각 크기 보정을 관리합니다."
      actions={<>
        <input ref={fileInputRef} type="file" accept=".ttf,.otf,font/ttf,font/otf" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void register(file); }} />
        <Button type="button" onClick={() => fileInputRef.current?.click()} disabled={uploading}><Upload size={14} />{uploading ? "Registering…" : "Register font"}</Button>
        <Button type="button" variant="secondary" onClick={() => void load()} disabled={loading}><RefreshCw className={loading ? "spin" : undefined} size={14} /> Refresh</Button>
      </>}
    />

    <Card className="font-registry-callout">
      <span><Type size={19} /></span>
      <div><strong>One file, one immutable face</strong><p>등록 파일의 SHA-256은 고정됩니다. 크기 보정은 Caption Document에 Snapshot되어 과거 렌더를 바꾸지 않습니다.</p></div>
      <Badge variant="success">{activeCount} active</Badge>
    </Card>

    {error && <Card className="font-registry-error" role="alert"><CircleAlert size={17} /><span>{error}</span></Card>}
    {!error && loading && <p className="experiment-history-state">Loading caption fonts…</p>}
    {!loading && fonts.length === 0 && <Card className="font-registry-empty"><Type size={25} /><h3>No fonts registered</h3><p>TTF 또는 OTF Face를 등록하면 Caption Designer의 글꼴 목록에 바로 표시됩니다.</p><Button type="button" onClick={() => fileInputRef.current?.click()}><Upload size={14} /> Register first font</Button></Card>}

    <div className="font-card-grid">
      {fonts.map((font) => {
        const draft = drafts[font.id] ?? draftFor(font);
        const previewFont = { ...font, size_adjust: draft.sizeAdjust, baseline_shift: draft.baselineShift };
        return <Card className={`font-card ${font.lifecycle.toLowerCase()}`} key={font.id}>
          <header><span className="font-card-icon"><Type size={18} /></span><div><strong>{draft.displayName}</strong><small>{font.family_name} · {font.subfamily_name}</small></div><Badge variant={font.lifecycle === "ACTIVE" ? "success" : "warning"}>{font.lifecycle}</Badge></header>
          <div className="font-preview">
            <span style={fontPreviewStyle(previewFont)}>가나다라마바사 Aa 0123</span>
            <small>Visual scale {draft.sizeAdjust.toFixed(3)} · 1.000 is the font&apos;s native em size</small>
          </div>
          <div className="font-profile-fields">
            <label><span>Display name</span><Input value={draft.displayName} onChange={(event) => setDrafts((current) => ({ ...current, [font.id]: { ...draft, displayName: event.target.value } }))} /></label>
            <label><span>License</span><Input value={draft.licenseName} onChange={(event) => setDrafts((current) => ({ ...current, [font.id]: { ...draft, licenseName: event.target.value } }))} /></label>
            <label className="font-adjust-field"><span><SlidersHorizontal size={12} /> Visual size <b>{draft.sizeAdjust.toFixed(3)}</b></span><input type="range" min="0.5" max="2" step="0.005" value={draft.sizeAdjust} onChange={(event) => setDrafts((current) => ({ ...current, [font.id]: { ...draft, sizeAdjust: Number(event.target.value) } }))} /></label>
          </div>
          <dl><div><dt>Weight</dt><dd>{font.weight}</dd></div><div><dt>File</dt><dd>{formatBytes(font.size_bytes)}</dd></div><div><dt>Fingerprint</dt><dd><code title={font.sha256}>{font.sha256.slice(0, 12)}</code></dd></div></dl>
          <footer>
            <Button type="button" variant="ghost" size="sm" onClick={() => void toggleLifecycle(font)} disabled={saving === font.id}>{font.lifecycle === "ACTIVE" ? <Archive size={13} /> : <ArchiveRestore size={13} />}{font.lifecycle === "ACTIVE" ? "Retire" : "Restore"}</Button>
            <Button type="button" size="sm" onClick={() => void save(font)} disabled={saving === font.id}><Save size={13} />{saving === font.id ? "Saving…" : saved === font.id ? <><Check size={13} /> Saved</> : "Save profile"}</Button>
          </footer>
        </Card>;
      })}
    </div>
  </div>;
}
