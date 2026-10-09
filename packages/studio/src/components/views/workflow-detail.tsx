"use client";
import { useStudioRuntime } from "../../runtime/studio-runtime";


import { useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import { Archive, ArrowLeft, ArrowRight, GitBranch, ImageIcon, ListVideo, LoaderCircle, LockKeyhole, Pencil, Play, RotateCcw, WandSparkles } from "lucide-react";
import { workflowVersionDiff } from "../../features/workflows/version-diff";
import { missingWorkflowInputs, rerunRequest, workflowPresentation } from "../../features/workflows/run-model";
import { useWorkflowRuns } from "../../features/workflows/use-workflow-runs";
import { WorkflowImageInput } from "../../features/workflows/components/workflow-image-input";
import { WorkflowRunQueue } from "../../features/workflows/components/workflow-run-queue";
import { WorkflowRunResults } from "../../features/workflows/components/workflow-run-results";
import { PageHeader } from "../shared/page-header";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { NativeSelect } from "../ui/native-select";
import { Textarea } from "../ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../ui/dialog";
import { type ArtifactListItem, type CharacterRecord, type NodeDefinitionRecord, type WorkflowDefinitionRecord, type WorkflowInputDefinition, type WorkflowVersionRecord } from "../../lib/api";
import "../../styles/features/workflow-runner.css";

interface WorkflowDetailProps {
  workflowId: string;
  onBack: () => void;
  onEditDraft: (canvasId: string) => void;
  onOpenVersion: (version: number) => void;
  onOpenRun: (runId: string) => void;
}

function defaultInputs(version?: WorkflowVersionRecord): Record<string, unknown> {
  return Object.fromEntries(version?.input_schema.inputs.flatMap((item) => item.default === undefined ? [] : [[item.key, item.default]]) ?? []);
}

function StandardInput({ definition, value, onChange, assets, characters, disabled }: { definition: WorkflowInputDefinition; value: unknown; onChange: (value: unknown) => void; assets: ArtifactListItem[]; characters: CharacterRecord[]; disabled: boolean }) {
  const common = { id: `workflow-input-${definition.key}`, disabled };
  const options = definition.options ?? (definition.validation?.options as Array<string | number> | undefined);
  if (definition.type === "artifact") {
    const allowed = definition.validation?.artifact_types as string[] | undefined;
    return <NativeSelect {...common} value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}><option value="">파일 선택…</option>{assets.filter((asset) => !allowed?.length || allowed.includes(asset.type)).map((asset) => <option value={asset.id} key={asset.id}>{asset.filename} · {asset.id.slice(-6)}</option>)}</NativeSelect>;
  }
  if (definition.type === "character") return <NativeSelect {...common} value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}><option value="">캐릭터 선택…</option>{characters.map((character) => <option value={character.id} key={character.id}>{character.name}</option>)}</NativeSelect>;
  if (definition.type === "boolean") return <NativeSelect {...common} value={value === undefined ? "" : String(value)} onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value === "true")}><option value="">선택…</option><option value="true">켜기</option><option value="false">끄기</option></NativeSelect>;
  if (definition.type === "enum" || definition.type === "model_alias") return <NativeSelect {...common} value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}><option value="">선택…</option>{options?.map((option) => <option value={String(option)} key={String(option)}>{String(option)}</option>)}</NativeSelect>;
  if (definition.type === "prompt") return <Textarea {...common} value={String(value ?? "")} onChange={(event) => onChange(event.target.value)} />;
  return <Input {...common} type={definition.type === "integer" || definition.type === "number" ? "number" : "text"} value={String(value ?? "")} onChange={(event) => onChange(definition.type === "integer" || definition.type === "number" ? event.target.value === "" ? undefined : Number(event.target.value) : event.target.value)} />;
}

export function WorkflowDetail(props: WorkflowDetailProps) {
  return <WorkflowDetailContent key={props.workflowId} {...props} />;
}

function WorkflowDetailContent({ workflowId, onBack, onEditDraft, onOpenVersion, onOpenRun }: WorkflowDetailProps) {
  const { frameflowApi } = useStudioRuntime();
  const [workflow, setWorkflow] = useState<WorkflowDefinitionRecord | null>(null);
  const [versions, setVersions] = useState<WorkflowVersionRecord[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [inputs, setInputs] = useState<Record<string, unknown>>({});
  const [assets, setAssets] = useState<ArtifactListItem[]>([]);
  const [characters, setCharacters] = useState<CharacterRecord[]>([]);
  const [definitions, setDefinitions] = useState<NodeDefinitionRecord[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [uploadingInput, setUploadingInput] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ url: string; label: string }>();
  const submitLock = useRef(false);
  const queue = useWorkflowRuns(workflowId);

  useEffect(() => {
    let active = true;
    Promise.all([frameflowApi.getWorkflow(workflowId), frameflowApi.listWorkflowVersions(workflowId), frameflowApi.listAllArtifacts(["Image", "Video", "FinalVideo", "Audio", "Model3D"]), frameflowApi.listCharacters(), frameflowApi.listNodeDefinitions()])
      .then(([definition, items, assetItems, characterItems, registry]) => {
        if (!active) return;
        setWorkflow(definition); setVersions(items); setAssets(assetItems); setCharacters(characterItems); setDefinitions(registry);
        const number = definition.current_version_number ?? items[0]?.version_number ?? null;
        setSelectedVersion(number); setInputs(defaultInputs(items.find((item) => item.version_number === number)));
      })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "워크플로우를 불러오지 못했습니다."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [workflowId, frameflowApi]);

  const version = versions.find((item) => item.version_number === selectedVersion);
  const runVersion = versions.find((item) => item.id === queue.selectedRun?.workflow_version_id);
  const presentation = useMemo(() => version ? workflowPresentation(version, definitions, assets, characters) : { functions: [], references: [] }, [version, definitions, assets, characters]);
  const missing = missingWorkflowInputs(version?.input_schema.inputs ?? [], inputs);
  const busy = submitting || uploadingInput !== null;
  const archived = workflow?.status !== "ACTIVE";
  const selectedCharacterNames = [...new Set(presentation.references.flatMap((item) => item.characterName ? [item.characterName] : []))];

  const submit = async (repeatId?: string) => {
    if (!workflow || !version || busy || archived || submitLock.current || (!repeatId && missing.length)) return;
    submitLock.current = true; setSubmitting(true); setError(null);
    try {
      const payload = repeatId ? rerunRequest(await frameflowApi.getCanvasRun(repeatId), workflow.id, versions) : { version: version.version_number, inputs: structuredClone(inputs) };
      const run = await frameflowApi.runWorkflow(workflow.id, payload);
      queue.addRun(run);
      window.dispatchEvent(new Event("frameflow:workspace-changed"));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "실행을 시작하지 못했습니다."); }
    finally { submitLock.current = false; setSubmitting(false); }
  };
  const toggleArchive = async () => {
    if (!workflow || busy) return;
    try {
      setWorkflow(workflow.status === "ACTIVE" ? await frameflowApi.archiveWorkflow(workflow.id) : await frameflowApi.activateWorkflow(workflow.id));
      window.dispatchEvent(new Event("frameflow:workspace-changed"));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "워크플로우 상태를 변경하지 못했습니다."); }
  };

  const previous = version ? versions.filter((item) => item.version_number < version.version_number).sort((a, b) => b.version_number - a.version_number)[0] : undefined;
  const changes = version && previous ? workflowVersionDiff(previous, version) : [];
  if (loading) return <div className="view-page workflow-runner"><p role="status">워크플로우를 불러오는 중…</p></div>;
  if (!workflow) return <div className="view-page"><PageHeader title="워크플로우를 열 수 없습니다" description={error ?? "워크플로우를 찾을 수 없습니다."} actions={<Button onClick={onBack}>목록으로</Button>} /></div>;

  return <div className="view-page workflow-runner">
    <PageHeader title={workflow.name} description="입력을 넣고, 처리 방식과 고정 참조를 확인한 뒤 실행하세요." actions={<><Button variant="ghost" onClick={onBack}><ArrowLeft size={14} />목록</Button><Button variant="secondary" onClick={() => onEditDraft(workflow.draft_canvas_id)}><Pencil size={14} />편집</Button></>} />
    {error && <p className="workflow-inline-error" role="alert">{error}</p>}
    {!version ? <div className="workflow-queue-empty"><strong>아직 게시된 버전이 없습니다.</strong><p>초안을 편집하고 게시하면 여기에서 실행할 수 있습니다.</p></div> : <>
      <div className="workflow-runner-toolbar"><label>실행 버전 <NativeSelect aria-label="실행 버전" disabled={busy} value={String(version.version_number)} onChange={(event) => { const number = Number(event.target.value); setSelectedVersion(number); setInputs(defaultInputs(versions.find((item) => item.version_number === number))); setError(null); }}>{versions.map((item) => <option value={item.version_number} key={item.id}>v{item.version_number}{workflow.current_version_number === item.version_number ? " · 현재" : ""}</option>)}</NativeSelect></label><span><LockKeyhole size={13} />캐릭터와 처리 설정은 이 버전으로 고정됩니다.</span></div>
      <div className="workflow-execution-flow">
        <section className="workflow-flow-panel workflow-input-panel" aria-label="입력"><header><h3>Input <small>입력</small></h3></header>
          {version.input_schema.inputs.map((definition) => {
            const allowed = definition.validation?.artifact_types as string[] | undefined;
            const imageInput = definition.type === "artifact" && allowed?.length === 1 && allowed[0] === "Image";
            return <div className="workflow-input-field" key={`${version.id}:${definition.key}`}><label htmlFor={`workflow-input-${definition.key}`}>{definition.label}{definition.required && <span>필수</span>}</label>
              {imageInput ? <WorkflowImageInput label={definition.label} value={inputs[definition.key]} assets={assets} disabled={busy || archived} onSelect={(id) => setInputs((current) => ({ ...current, [definition.key]: id }))} onAsset={(asset) => setAssets((current) => [asset, ...current.filter((item) => item.id !== asset.id)])} onBusy={(value) => setUploadingInput(value ? definition.key : null)} /> : <StandardInput definition={definition} value={inputs[definition.key]} assets={assets} characters={characters} disabled={busy || archived} onChange={(value) => setInputs((current) => ({ ...current, [definition.key]: value }))} />}
              {definition.description && <p className="workflow-input-help">{definition.description}</p>}
            </div>;
          })}
          {!version.input_schema.inputs.length && <p className="workflow-empty-note">추가 입력 없이 고정 설정으로 실행합니다.</p>}
        </section>
        <ArrowRight className="workflow-flow-arrow" size={20} aria-hidden="true" />
        <section className="workflow-flow-panel workflow-function-panel" aria-label="처리 방식과 고정 참조"><header><h3>Function <small>처리 방식</small></h3></header>
          <ol className="workflow-function-list">{presentation.functions.map((item) => <li key={item.id}><WandSparkles size={16} /><div><strong>{item.label}</strong><p>{item.description}</p></div></li>)}</ol>
          {presentation.references.length > 0 && <div className="workflow-fixed-references"><h4><LockKeyhole size={13} />고정 참조 <span>{presentation.references.length}장</span></h4>{selectedCharacterNames.length > 0 && <p className="workflow-character-name">{selectedCharacterNames.join(" · ")}</p>}<div className="workflow-reference-grid">{presentation.references.map((item) => <button type="button" key={item.id} disabled={!item.url} onClick={() => item.url && setPreview({ url: item.url, label: item.label })}><span className="workflow-reference-image">{item.url ? <Image src={item.url} alt={item.label} fill unoptimized className="workflow-contained-image" /> : <ImageIcon size={22} />}</span><strong>{item.label}</strong></button>)}</div><small>사진을 누르면 크게 볼 수 있습니다.</small></div>}
        </section>
        <ArrowRight className="workflow-flow-arrow" size={20} aria-hidden="true" />
        <section className="workflow-flow-panel workflow-output-panel" aria-label="결과"><header><h3>Output <small>결과</small></h3></header><WorkflowRunResults run={queue.selectedRun} version={runVersion} />{!queue.selectedRun && <p className="workflow-input-help">{version.output_schema.outputs.map((item) => String(item.label || item.key)).join(" · ")}</p>}</section>
      </div>
      <div className="workflow-run-bar"><div><strong>{archived ? "보관된 워크플로우입니다." : uploadingInput ? "이미지를 준비하고 있습니다…" : missing.length ? `${missing.join(", ")} 입력을 준비해 주세요.` : "실행할 준비가 됐습니다."}</strong><span>실행하면 아래 Queue에 추가됩니다.</span></div><Button size="lg" disabled={busy || archived || missing.length > 0} onClick={() => void submit()}>{submitting ? <LoaderCircle className="spin" size={16} /> : <Play size={16} fill="currentColor" />}{submitting ? "추가 중…" : "Run · 실행 추가"}</Button></div>
    </>}
    <WorkflowRunQueue runs={queue.runs} versions={versions} assets={assets} selectedId={queue.selectedId} detail={queue.selectedRun} loading={queue.loading} error={queue.error} canceling={queue.canceling} submitting={busy || archived} onSelect={queue.selectRun} onCancel={(id) => void queue.cancelRun(id)} onRepeat={(id) => void submit(id)} onRefresh={queue.refresh} />
    <details className="workflow-version-management"><summary><GitBranch size={15} />버전 및 워크플로우 관리</summary><p>{workflow.description}</p><div className="workflow-version-list">{versions.map((item) => <Button key={item.id} variant="secondary" onClick={() => onOpenVersion(item.version_number)}>v{item.version_number} 보기</Button>)}<Button variant="secondary" onClick={() => onOpenRun(queue.selectedId ?? "")}><ListVideo size={14} />전체 실행 목록</Button><Button variant="ghost" disabled={busy} onClick={() => void toggleArchive()}>{archived ? <RotateCcw size={14} /> : <Archive size={14} />}{archived ? "활성화" : "보관"}</Button></div>{changes.length > 0 && <details><summary>이전 버전과 변경 사항 {changes.length}개</summary><ul>{changes.map((change) => <li key={change.path}>{change.path}: {JSON.stringify(change.before) ?? "—"} → {JSON.stringify(change.after) ?? "—"}</li>)}</ul></details>}</details>
    <Dialog open={Boolean(preview)} onOpenChange={(open) => { if (!open) setPreview(undefined); }}><DialogContent className="workflow-reference-dialog" showCloseButton><DialogTitle>{preview?.label}</DialogTitle><DialogDescription>이 워크플로우에 고정된 참조 이미지입니다.</DialogDescription>{preview && <div><Image src={preview.url} alt={preview.label} fill unoptimized className="workflow-contained-image" /></div>}</DialogContent></Dialog>
  </div>;
}
