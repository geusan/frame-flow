"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Archive, ArrowLeft, GitBranch, Pencil, Play, RefreshCw, RotateCcw, Workflow } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { frameflowApi, type ArtifactListItem, type CharacterRecord, type WorkflowDefinitionRecord, type WorkflowInputDefinition, type WorkflowVersionRecord } from "@/lib/api";

function InputField({ definition, value, onChange, assetOptions = [], characterOptions = [] }: {
  definition: WorkflowInputDefinition;
  value: unknown;
  onChange: (value: unknown) => void;
  assetOptions?: ArtifactListItem[];
  characterOptions?: CharacterRecord[];
}) {
  const options = definition.options ?? (definition.validation?.options as Array<string | number> | undefined);
  if (definition.type === "artifact") {
    const allowedTypes = new Set((definition.validation?.artifact_types as string[] | undefined) ?? []);
    const candidates = allowedTypes.size ? assetOptions.filter((asset) => allowedTypes.has(asset.type)) : assetOptions;
    return <NativeSelect value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}><option value="">Select an Artifact…</option>{candidates.map((asset) => <option value={asset.id} key={asset.id}>{asset.filename} · {asset.type}</option>)}</NativeSelect>;
  }
  if (definition.type === "character") return <NativeSelect value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}><option value="">Select a Character…</option>{characterOptions.map((character) => <option value={character.id} key={character.id}>{character.name} · {character.image_count} views</option>)}</NativeSelect>;
  if (definition.type === "boolean") return <NativeSelect value={String(Boolean(value))} onChange={(event) => onChange(event.target.value === "true")}><option value="true">On</option><option value="false">Off</option></NativeSelect>;
  if (definition.type === "enum" || definition.type === "model_alias") return <NativeSelect value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>{!definition.required && <option value="">Use default</option>}{options?.map((option) => <option value={String(option)} key={String(option)}>{String(option)}</option>)}</NativeSelect>;
  if (definition.type === "prompt") return <Textarea value={String(value ?? "")} onChange={(event) => onChange(event.target.value)} placeholder={definition.description ?? definition.label} />;
  return <Input
    type={definition.type === "integer" || definition.type === "number" ? "number" : "text"}
    value={String(value ?? "")}
    onChange={(event) => onChange(definition.type === "integer" || definition.type === "number" ? Number(event.target.value) : event.target.value)}
    placeholder={definition.description}
  />;
}

function defaultInputs(version: WorkflowVersionRecord | undefined): Record<string, unknown> {
  return Object.fromEntries(version?.input_schema.inputs.flatMap((item) => item.default === undefined ? [] : [[item.key, item.default]]) ?? []);
}

export function WorkflowDetail({ workflowId, onBack, onEditDraft, onOpenVersion, onOpenRun }: {
  workflowId: string;
  onBack: () => void;
  onEditDraft: (canvasId: string) => void;
  onOpenVersion: (version: number) => void;
  onOpenRun: (runId: string) => void;
}) {
  const [workflow, setWorkflow] = useState<WorkflowDefinitionRecord | null>(null);
  const [versions, setVersions] = useState<WorkflowVersionRecord[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [inputs, setInputs] = useState<Record<string, unknown>>({});
  const [assetOptions, setAssetOptions] = useState<ArtifactListItem[]>([]);
  const [characterOptions, setCharacterOptions] = useState<CharacterRecord[]>([]);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [definition, versionItems, assets, characters] = await Promise.all([
        frameflowApi.getWorkflow(workflowId),
        frameflowApi.listWorkflowVersions(workflowId),
        frameflowApi.listAllArtifacts(["Image", "Video", "FinalVideo", "Audio"]),
        frameflowApi.listCharacters(),
      ]);
      setWorkflow(definition);
      setVersions(versionItems);
      setAssetOptions(assets);
      setCharacterOptions(characters);
      const nextVersion = definition.current_version_number ?? versionItems[0]?.version_number ?? null;
      setSelectedVersion(nextVersion);
      setInputs(defaultInputs(versionItems.find((item) => item.version_number === nextVersion)));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Workflow loading failed");
    } finally {
      setLoading(false);
    }
  }, [workflowId]);

  useEffect(() => {
    let active = true;
    Promise.all([
      frameflowApi.getWorkflow(workflowId),
      frameflowApi.listWorkflowVersions(workflowId),
      frameflowApi.listAllArtifacts(["Image", "Video", "FinalVideo", "Audio"]),
      frameflowApi.listCharacters(),
    ])
      .then(([definition, versionItems, assets, characters]) => {
        if (!active) return;
        setWorkflow(definition);
        setVersions(versionItems);
        setAssetOptions(assets);
        setCharacterOptions(characters);
        const nextVersion = definition.current_version_number ?? versionItems[0]?.version_number ?? null;
        setSelectedVersion(nextVersion);
        setInputs(defaultInputs(versionItems.find((item) => item.version_number === nextVersion)));
      })
      .catch((loadError) => { if (active) setError(loadError instanceof Error ? loadError.message : "Workflow loading failed"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [workflowId]);
  const version = useMemo(() => versions.find((item) => item.version_number === selectedVersion), [selectedVersion, versions]);

  const run = async () => {
    if (!workflow || !version) return;
    setRunning(true);
    setError(null);
    try {
      const result = await frameflowApi.runWorkflow(workflow.id, { version: version.version_number, inputs });
      window.dispatchEvent(new Event("frameflow:workspace-changed"));
      onOpenRun(result.id);
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Workflow Run failed to start");
    } finally {
      setRunning(false);
    }
  };

  const toggleArchive = async () => {
    if (!workflow) return;
    try {
      const next = workflow.status === "ACTIVE"
        ? await frameflowApi.archiveWorkflow(workflow.id)
        : await frameflowApi.activateWorkflow(workflow.id);
      setWorkflow(next);
      window.dispatchEvent(new Event("frameflow:workspace-changed"));
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Workflow status update failed");
    }
  };

  if (loading) return <p className="experiment-history-state">Loading Workflow…</p>;
  if (!workflow) return <div className="view-page"><PageHeader title="Workflow unavailable" description={error ?? "Workflow not found"} actions={<Button onClick={onBack}><ArrowLeft size={14} /> Back</Button>} /></div>;

  return <div className="view-page canvas-library-page">
    <PageHeader title={workflow.name} description={workflow.description || "Versioned reusable Workflow"} actions={<>
      <Button type="button" variant="secondary" onClick={onBack}><ArrowLeft size={14} /> Workflows</Button>
      <Button type="button" variant="secondary" onClick={() => onEditDraft(workflow.draft_canvas_id)}><Pencil size={14} /> Edit draft</Button>
      <Button type="button" variant="secondary" onClick={() => void toggleArchive()}>{workflow.status === "ACTIVE" ? <><Archive size={14} /> Archive</> : <><RotateCcw size={14} /> Activate</>}</Button>
    </>} />
    {error && <p className="experiment-history-state error">{error}</p>}
    <div className="canvas-document-grid">
      <article className="canvas-document-card">
        <div className="canvas-document-open"><span className="canvas-document-icon"><Workflow size={18} /></span><span className="canvas-document-copy"><strong>Current state</strong><small>{workflow.status} · immutable published graph</small></span><span className="canvas-document-count"><b>{workflow.current_version_number ? `v${workflow.current_version_number}` : "—"}</b><small>current</small></span></div>
        <div className="canvas-document-meta"><span><GitBranch size={12} /> {workflow.version_count} versions</span><span>Draft remains editable</span></div>
      </article>
      {versions.map((item) => <article className="canvas-document-card" key={item.id}>
        <button type="button" className="canvas-document-open" onClick={() => onOpenVersion(item.version_number)}><span className="canvas-document-icon"><GitBranch size={18} /></span><span className="canvas-document-copy"><strong>Version {item.version_number}</strong><small>{item.release_notes || item.content_hash.slice(0, 12)}</small></span><span className="canvas-document-count"><b>{item.graph.nodes.length}</b><small>nodes</small></span></button>
        <div className="canvas-document-meta"><span>{new Date(item.published_at).toLocaleString("ko-KR")}</span><span>{item.published_by}</span></div>
      </article>)}
    </div>

    {version && <section className="settings-section">
      <div className="settings-section-heading"><div><span className="subtle-label">Run published version</span><h2>Workflow inputs</h2></div><Button type="button" variant="secondary" onClick={() => void load()}><RefreshCw size={14} /> Refresh</Button></div>
      <label className="field-label"><span>Version</span><NativeSelect value={String(version.version_number)} onChange={(event) => { const next = Number(event.target.value); setSelectedVersion(next); setInputs(defaultInputs(versions.find((item) => item.version_number === next))); }}>{versions.map((item) => <option value={item.version_number} key={item.id}>v{item.version_number}</option>)}</NativeSelect></label>
      {version.input_schema.inputs.map((definition) => <label className="field-label" key={definition.key}><span>{definition.label}{definition.required ? " *" : ""}</span><InputField definition={definition} value={inputs[definition.key]} assetOptions={assetOptions} characterOptions={characterOptions} onChange={(value) => setInputs((current) => ({ ...current, [definition.key]: value }))} />{definition.description && <small>{definition.description}</small>}</label>)}
      {!version.input_schema.inputs.length && <p className="step-run-help">이 Version은 실행 입력 없이 게시된 상수 설정을 사용합니다.</p>}
      <Button type="button" onClick={() => void run()} disabled={running || workflow.status !== "ACTIVE"}><Play size={14} fill="currentColor" /> {running ? "Starting…" : `Run v${version.version_number}`}</Button>
    </section>}
  </div>;
}
