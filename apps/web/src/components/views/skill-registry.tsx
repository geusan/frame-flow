"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  CircleAlert,
  Copy,
  FileText,
  Fingerprint,
  RefreshCw,
  SearchX,
  ShieldCheck,
  Sparkles,
  Terminal,
  Upload,
  X,
} from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { SearchField } from "@/components/shared/search-field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { frameflowApi, type ProjectSkillRecord } from "@/lib/api";

function shortVersion(version: string): string {
  return version.slice(0, 10);
}

export function SkillRegistry() {
  const [skills, setSkills] = useState<ProjectSkillRecord[]>([]);
  const [query, setQuery] = useState("");
  const [selectedSkillId, setSelectedSkillId] = useState<string | null>(null);
  const [copiedSkillId, setCopiedSkillId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selectedVersions, setSelectedVersions] = useState<ProjectSkillRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const skillFileRef = useRef<HTMLInputElement>(null);

  const refreshSkills = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      setSkills(await frameflowApi.listSkills(true));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Skill registry loading failed");
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    frameflowApi.listSkills(true)
      .then((rows) => { if (active) setSkills(rows); })
      .catch((loadError) => { if (active) setError(loadError instanceof Error ? loadError.message : "Skill registry loading failed"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const visibleSkills = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) return skills;
    return skills.filter((skill) =>
      `${skill.display_name} ${skill.id} ${skill.description}`.toLowerCase().includes(normalizedQuery),
    );
  }, [query, skills]);

  const selectedSkill = skills.find((skill) => skill.id === selectedSkillId) ?? null;

  useEffect(() => {
    if (!selectedSkillId) return;
    let active = true;
    frameflowApi.listSkillVersions(selectedSkillId)
      .then((versions) => { if (active) setSelectedVersions(versions); })
      .catch((loadError) => { if (active) setError(loadError instanceof Error ? loadError.message : "Skill versions loading failed"); });
    return () => { active = false; };
  }, [selectedSkillId]);

  const registerSkill = useCallback(async (file: File) => {
    setUploading(true);
    setError(null);
    try {
      const registered = await frameflowApi.registerSkill(file);
      const rows = await frameflowApi.listSkills(true);
      setSkills(rows);
      setSelectedSkillId(registered.id);
      setSelectedVersions(await frameflowApi.listSkillVersions(registered.id));
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Skill registration failed");
    } finally {
      setUploading(false);
      if (skillFileRef.current) skillFileRef.current.value = "";
    }
  }, []);

  const activateVersion = useCallback(async (skillId: string, versionNumber: number) => {
    setError(null);
    try {
      const activated = await frameflowApi.activateSkillVersion(skillId, versionNumber);
      setSkills((current) => current.map((item) => item.id === skillId ? activated : item));
      setSelectedVersions(await frameflowApi.listSkillVersions(skillId));
    } catch (activateError) {
      setError(activateError instanceof Error ? activateError.message : "Skill activation failed");
    }
  }, []);

  const toggleInstallation = useCallback(async (skill: ProjectSkillRecord) => {
    setError(null);
    try {
      const updated = await frameflowApi.setSkillEnabled(skill.id, !skill.enabled);
      setSkills((current) => current.map((item) => item.id === skill.id ? updated : item));
    } catch (toggleError) {
      setError(toggleError instanceof Error ? toggleError.message : "Skill installation update failed");
    }
  }, []);

  const copyInvocation = useCallback(async (skillId: string) => {
    try {
      await navigator.clipboard.writeText(`$${skillId}`);
      setCopiedSkillId(skillId);
      window.setTimeout(() => setCopiedSkillId((current) => current === skillId ? null : current), 1600);
    } catch {
      setCopiedSkillId(null);
      setError("호출문을 복사하지 못했습니다. 스킬 ID를 직접 복사해 주세요.");
    }
  }, []);

  return (
    <div className="view-page skills-page">
      <PageHeader
        title="Skill Registry"
        description="워크플로우에서 실행할 수 있는 신뢰된 프로젝트 스킬과 버전을 확인합니다."
        actions={<>
          <input ref={skillFileRef} type="file" accept=".md,text/markdown,text/plain" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void registerSkill(file); }} />
          <Button type="button" onClick={() => skillFileRef.current?.click()} disabled={uploading}><Upload size={14} />{uploading ? "Registering…" : "Register SKILL.md"}</Button>
          <Button variant="secondary" type="button" onClick={() => void refreshSkills()} disabled={refreshing}>
            <RefreshCw className={refreshing ? "spin" : undefined} size={14} />
            {refreshing ? "Refreshing…" : "Refresh registry"}
          </Button>
        </>}
      />

      <Card className="skill-registry-callout">
        <span className="skill-callout-icon"><ShieldCheck size={18} /></span>
        <div>
          <strong>Trusted, project-scoped instructions</strong>
          <p>Bundled·업로드·Seed 경로에서 검증된 Skill은 immutable DB version으로 등록되고 실행 Snapshot에 digest가 고정됩니다.</p>
        </div>
        <Badge variant="success"><span className="skill-status-dot" />{skills.length} available</Badge>
      </Card>

      <div className="skill-registry-toolbar">
        <SearchField
          className="skill-registry-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search name, ID, or description…"
          aria-label="Search registered skills"
        />
        <span>{visibleSkills.length} of {skills.length} skills</span>
      </div>

      {error && (
        <Card className="skill-registry-error" role="alert">
          <CircleAlert size={17} />
          <div><strong>Registry unavailable</strong><p>{error}</p></div>
          <Button variant="secondary" size="sm" type="button" onClick={() => void refreshSkills()}>Try again</Button>
        </Card>
      )}

      {!error && loading && (
        <div className="skill-card-grid" aria-label="Loading registered skills">
          {[0, 1, 2].map((item) => <Card className="skill-card skill-card-loading" key={item}><span /><span /><span /></Card>)}
        </div>
      )}

      {!error && !loading && visibleSkills.length > 0 && (
        <div className="skill-card-grid">
          {visibleSkills.map((skill) => (
            <Card className="skill-card" key={skill.id}>
              <div className="skill-card-head">
                <span className="skill-card-icon"><Sparkles size={18} /></span>
                <Badge variant={skill.enabled && skill.lifecycle === "ACTIVE" ? "success" : "warning"}><span className="skill-status-dot" />{skill.enabled ? skill.lifecycle : "Disabled"}</Badge>
              </div>
              <div className="skill-card-copy">
                <h3>{skill.display_name}</h3>
                <code>${skill.id}</code>
                <p>{skill.description}</p>
              </div>
              <div className="skill-card-meta">
                <span><Fingerprint size={13} /> v{skill.version_number} <code>{shortVersion(skill.version)}</code></span>
                <span><FileText size={13} /> {skill.source}</span>
              </div>
              <div className="skill-card-actions">
                <Button variant="ghost" size="sm" type="button" onClick={() => void copyInvocation(skill.id)}>
                  {copiedSkillId === skill.id ? <Check size={13} /> : <Copy size={13} />}
                  {copiedSkillId === skill.id ? "Copied" : "Copy reference"}
                </Button>
                <Button variant="secondary" size="sm" type="button" onClick={() => { setSelectedVersions([]); setSelectedSkillId(skill.id); }}>
                  Details <ArrowRight size={13} />
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {!error && !loading && visibleSkills.length === 0 && (
        <Card className="skill-registry-empty">
          <span><SearchX size={21} /></span>
          <h3>{skills.length ? "No matching skills" : "No skills registered"}</h3>
          <p>{skills.length ? "다른 이름이나 스킬 ID로 검색해 보세요." : "SKILL.md를 등록하거나 Seed CLI로 trusted Skill directory를 가져오세요."}</p>
          {query && <Button variant="secondary" size="sm" type="button" onClick={() => setQuery("")}>Clear search</Button>}
        </Card>
      )}

      <Sheet open={Boolean(selectedSkill)} onOpenChange={(open) => { if (!open) { setSelectedSkillId(null); setSelectedVersions([]); } }}>
        {selectedSkill && (
          <SheetContent className="skill-detail-drawer">
            <SheetDescription className="sr-only">Registration details for {selectedSkill.display_name}</SheetDescription>
            <div className="skill-detail-head">
              <span className="skill-card-icon"><Sparkles size={18} /></span>
              <div>
                <small>Registered skill</small>
                <SheetTitle>{selectedSkill.display_name}</SheetTitle>
              </div>
              <SheetClose asChild><Button variant="ghost" size="icon" type="button" aria-label="Close skill details"><X size={16} /></Button></SheetClose>
            </div>

            <div className="skill-detail-body">
              <div className="skill-detail-status">
                <span><ShieldCheck size={16} /></span>
                <div><strong>{selectedSkill.enabled ? "Available for execution" : "Installation disabled"}</strong><p>The registry parsed, versioned, and stored this Skill in the database.</p></div>
                <Badge variant={selectedSkill.enabled ? "success" : "warning"}><span className="skill-status-dot" />{selectedSkill.enabled ? "Ready" : "Disabled"}</Badge>
              </div>

              <section className="skill-detail-section">
                <h3>Registration</h3>
                <dl>
                  <div><dt>Skill ID</dt><dd><code>{selectedSkill.id}</code></dd></div>
                  <div><dt>Current version</dt><dd><code>v{selectedSkill.version_number}</code></dd></div>
                  <div><dt>Version fingerprint</dt><dd title={selectedSkill.version}><code>{selectedSkill.version}</code></dd></div>
                  <div><dt>Source</dt><dd><code>{selectedSkill.source}</code></dd></div>
                  <div><dt>Lifecycle</dt><dd><code>{selectedSkill.lifecycle}</code></dd></div>
                </dl>
              </section>

              <section className="skill-detail-section">
                <h3>Immutable versions</h3>
                <div className="skill-version-list">
                  {selectedVersions.map((version) => <div key={version.version}>
                    <span><strong>v{version.version_number}</strong><code title={version.version}>{shortVersion(version.version)}</code></span>
                    {version.version === selectedSkill.version
                      ? <Badge variant="success">Current</Badge>
                      : <Button variant="secondary" size="sm" type="button" onClick={() => void activateVersion(selectedSkill.id, version.version_number)}>Activate</Button>}
                  </div>)}
                </div>
              </section>

              <section className="skill-detail-section">
                <h3>Description</h3>
                <p>{selectedSkill.description}</p>
              </section>

              <section className="skill-detail-section">
                <h3>Use this skill</h3>
                <div className="skill-invocation">
                  <Terminal size={15} />
                  <code>${selectedSkill.id}</code>
                  <Button variant="ghost" size="icon-sm" type="button" aria-label="Copy skill reference" onClick={() => void copyInvocation(selectedSkill.id)}>
                    {copiedSkillId === selectedSkill.id ? <Check size={13} /> : <Copy size={13} />}
                  </Button>
                </div>
                <p>Skill Execute 노드의 입력이나 지원되는 프롬프트에서 이 참조를 사용하세요.</p>
              </section>

              <div className="skill-security-note">
                <ShieldCheck size={15} />
                <p>신뢰 지침 본문은 관리 UI에 노출되지 않습니다. 컴파일된 실행에는 이 버전 지문이 저장되어 재현성을 보호합니다.</p>
              </div>
            </div>

            <div className="skill-detail-foot">
              <Button variant="secondary" type="button" onClick={() => void toggleInstallation(selectedSkill)}>{selectedSkill.enabled ? "Disable" : "Enable"}</Button>
              <Button type="button" onClick={() => void copyInvocation(selectedSkill.id)}>
                {copiedSkillId === selectedSkill.id ? <Check size={14} /> : <Copy size={14} />}
                {copiedSkillId === selectedSkill.id ? "Reference copied" : "Copy skill reference"}
              </Button>
            </div>
          </SheetContent>
        )}
      </Sheet>
    </div>
  );
}
