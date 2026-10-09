"use client";

import { Braces, Link2, Plus, Trash2, X } from "lucide-react";

import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { NativeSelect } from "../../../components/ui/native-select";
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetTitle } from "../../../components/ui/sheet";
import { Textarea } from "../../../components/ui/textarea";
import { bindingValue, outputReachability, renameWorkflowInput, workflowOutputOptions, workflowTargets } from "../draft-contract";
import type { StudioFlowNode } from "../../../lib/canvas-model";
import type { NodeDefinitionRecord } from "../../../lib/api";
import { Switch } from "../../../components/ui/switch";
import type { WorkflowDraftContract, WorkflowInputDefinition } from "../../../lib/api";

function defaultEditor(input: WorkflowInputDefinition, onChange: (value: unknown) => void) {
  if (input.type === "boolean") return <NativeSelect value={String(Boolean(input.default))} onChange={(event) => onChange(event.target.value === "true")}><option value="true">On</option><option value="false">Off</option></NativeSelect>;
  if ((input.type === "enum" || input.type === "model_alias") && input.options?.length) return <NativeSelect value={String(input.default ?? "")} onChange={(event) => onChange(event.target.value)}>{input.options.map((option) => <option value={String(option)} key={String(option)}>{String(option)}</option>)}</NativeSelect>;
  return <Input type={input.type === "integer" || input.type === "number" ? "number" : "text"} value={String(input.default ?? "")} onChange={(event) => onChange(input.type === "integer" || input.type === "number" ? Number(event.target.value) : event.target.value)} placeholder={input.type === "artifact" ? "Artifact ID" : input.type === "character" ? "Character Artifact ID" : "Default value"} />;
}

export function WorkflowInputsPanel({ open, contract, nodes, edges, definitions, onOpenChange, onChange }: {
  open: boolean;
  contract: WorkflowDraftContract;
  nodes: StudioFlowNode[];
  edges: Array<{ source: string; target: string }>;
  definitions: NodeDefinitionRecord[];
  onOpenChange: (open: boolean) => void;
  onChange: (contract: WorkflowDraftContract) => void;
}) {
  const targets = workflowTargets(nodes, definitions);
  const outputOptions = workflowOutputOptions(nodes, definitions);
  const reachable = outputReachability(contract.outputs, edges);
  const excluded = nodes.filter((node) => definitions.some((definition) => definition.type_key === node.data.key) && !reachable.has(node.id));
  const patchInput = (index: number, patch: Partial<WorkflowInputDefinition>) => onChange(renameWorkflowInput(contract, index, patch));
  const addInput = () => {
    let index = 1;
    while (contract.inputs.some((input) => input.key === `input_${index}`)) index++;
    onChange({ ...contract, inputs: [...contract.inputs, { key: `input_${index}`, label: `Input ${index}`, type: "prompt", required: true }] });
  };
  const removeInput = (input: WorkflowInputDefinition) => onChange({
    ...contract,
    inputs: contract.inputs.filter((item) => item.key !== input.key),
    bindings: contract.bindings.filter((binding) => binding.value.kind === "input" ? binding.value.key !== input.key : !binding.value.input_keys.includes(input.key)),
  });

  return <Sheet open={open} onOpenChange={onOpenChange}>
    <SheetContent className="w-[420px] max-w-[92vw] overflow-y-auto border-l border-[#d8dad3] bg-[#f7f7f3] p-5 shadow-[-18px_0_44px_rgba(30,32,29,.12)]">
      <div className="mb-5 flex items-start justify-between gap-3"><div><SheetTitle className="text-lg font-bold text-[#252722]">Workflow inputs & outputs</SheetTitle><SheetDescription className="mt-1 text-xs text-[#777b72]">실행 Form의 입력, Node 설정 연결, 저장할 결과를 정의합니다.</SheetDescription></div><SheetClose asChild><Button type="button" variant="ghost" size="icon-sm" aria-label="Close workflow contract"><X size={16} /></Button></SheetClose></div>
      {!contract.inputs.length && <div className="rounded-xl border border-dashed border-[#cfd1ca] bg-white p-5 text-center"><Braces className="mx-auto mb-2 text-[#858980]" size={22} /><strong className="block text-sm text-[#3f423c]">No exposed inputs</strong><p className="mt-1 text-xs text-[#777b72]">Node Inspector에서 변수화 가능한 설정을 선택하세요.</p></div>}
      <Button type="button" variant="secondary" size="sm" onClick={addInput}><Plus size={13} /> Add input</Button>
      <div className="mt-3 flex flex-col gap-3">{contract.inputs.map((input, index) => {
        const binding = contract.bindings.find((item) => item.value.kind === "input" ? item.value.key === input.key : item.value.input_keys.includes(input.key));
        return <article className="rounded-xl border border-[#d8dad3] bg-white p-3" key={index}>
          <div className="mb-3 flex items-center justify-between"><span><small className="block text-[10px] uppercase tracking-[.08em] text-[#888c83]">{input.type}</small><strong className="text-sm text-[#30332d]">{input.label}</strong></span><Button type="button" variant="ghost" size="icon-sm" aria-label={`Remove input ${input.label}`} onClick={() => removeInput(input)}><Trash2 size={13} /></Button></div>
          <div className="grid grid-cols-2 gap-2"><label className="field-label"><span>Key</span><Input value={input.key} onChange={(event) => patchInput(index, { key: event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })} /></label><label className="field-label"><span>Label</span><Input value={input.label} onChange={(event) => patchInput(index, { label: event.target.value })} /></label></div>
          <label className="field-label"><span>Type</span><NativeSelect value={input.type} onChange={(event) => patchInput(index, { type: event.target.value as WorkflowInputDefinition["type"], default: undefined })}>{["prompt", "string", "integer", "number", "boolean", "enum", "artifact", "character", "model_alias"].map((type) => <option key={type} value={type}>{type}</option>)}</NativeSelect></label>
          <label className="field-label"><span className="flex items-center justify-between">Required <Switch checked={Boolean(input.required)} onCheckedChange={(required) => patchInput(index, required ? { required, default: undefined } : { required })} /></span></label>
          {!input.required && <label className="field-label"><span>Default</span>{defaultEditor(input, (value) => patchInput(index, { default: value }))}</label>}
          {binding && <div className="mt-2 flex items-center gap-1.5 rounded-md bg-[#f0f1ec] px-2 py-1.5 text-[10px] text-[#666a61]"><Link2 size={11} /><code>{binding.target.node_id}{binding.target.path}</code></div>}
        </article>;
      })}</div>
      <section className="mt-6 border-t pt-4">
        <h3 className="text-sm font-semibold">Input bindings</h3>
        <p className="mb-3 text-xs text-[#777b72]">같은 입력을 여러 설정에 연결하거나, 문자열 설정에 {"{{topic}}"} 형태의 템플릿을 사용하세요.</p>
        {contract.bindings.map((binding, index) => {
          const target = targets.find((item) => item.nodeId === binding.target.node_id && item.path === binding.target.path);
          const compatibleInputs = contract.inputs.filter((input) => input.type === target?.field["x-workflow-input"]?.type || (target?.field["x-workflow-input"]?.type === "number" && input.type === "integer"));
          const update = (value: typeof binding.value) => onChange({ ...contract, bindings: contract.bindings.map((item, i) => i === index ? { ...item, value } : item) });
          return <article key={`${binding.target.node_id}:${binding.target.path}`} className="mb-3 rounded-lg border bg-white p-3">
            <div className="flex items-center justify-between"><strong className="text-xs">{target?.label ?? `Missing target: ${binding.target.node_id}${binding.target.path}`}</strong><Button type="button" variant="ghost" size="icon-sm" aria-label="Remove binding" onClick={() => onChange({ ...contract, bindings: contract.bindings.filter((_, i) => i !== index) })}><Trash2 size={13} /></Button></div>
            <label className="field-label"><span>Binding mode</span><NativeSelect value={binding.value.kind} onChange={(event) => update(bindingValue(event.target.value as "input" | "template", event.target.value === "input" ? compatibleInputs[0]?.key ?? "" : `{{${compatibleInputs[0]?.key ?? "input_1"}}}`))}><option value="input">Input value</option>{target?.field.type === "string" && <option value="template">Prompt template</option>}</NativeSelect></label>
            {binding.value.kind === "input" ? <label className="field-label"><span>Workflow input</span><NativeSelect value={binding.value.key} onChange={(event) => update(bindingValue("input", event.target.value))}><option value="">Choose input</option>{compatibleInputs.map((input) => <option key={input.key} value={input.key}>{input.label} ({input.key})</option>)}</NativeSelect></label> : <label className="field-label"><span>Template</span><Textarea value={binding.value.template} onChange={(event) => update(bindingValue("template", event.target.value))} placeholder="A {{subject}} in {{location}}" /><small>Available: {contract.inputs.map((input) => `{{${input.key}}}`).join(", ") || "Add an input first"}</small>{binding.value.input_keys.some((key) => !contract.inputs.some((input) => input.key === key)) && <small className="text-red-700">템플릿에 선언되지 않은 입력이 있습니다.</small>}</label>}
          </article>;
        })}
        <label className="field-label"><span>Add binding target</span><NativeSelect value="" onChange={(event) => {
          const target = targets[Number(event.target.value)];
          if (!target) return;
          const input = contract.inputs.find((item) => item.type === target.field["x-workflow-input"]?.type);
          onChange({ ...contract, bindings: [...contract.bindings, { target: { node_id: target.nodeId, path: target.path }, value: bindingValue("input", input?.key ?? "") }] });
        }}><option value="">Choose Node setting</option>{targets.map((target, index) => contract.bindings.some((binding) => binding.target.node_id === target.nodeId && binding.target.path === target.path) ? null : <option key={`${target.nodeId}:${target.path}`} value={index}>{target.label}</option>)}</NativeSelect></label>
      </section>
      <section className="mt-6 border-t pt-4">
        <h3 className="text-sm font-semibold">Workflow outputs</h3>
        <p className="mb-3 text-xs text-[#777b72]">Primary 결과 하나와 필요한 Secondary 결과를 선택하세요. 이 결과로 이어지는 Node만 게시됩니다.</p>
        {contract.outputs.map((output, index) => <article className="mb-3 rounded-lg border bg-white p-3" key={index}>
          <div className="flex items-center justify-between"><label className="flex items-center gap-2 text-xs"><input type="radio" name="primary-output" checked={output.primary} onChange={() => onChange({ ...contract, outputs: contract.outputs.map((item, i) => ({ ...item, primary: i === index })) })} />Primary output</label><Button type="button" variant="ghost" size="icon-sm" aria-label="Remove output" onClick={() => { const outputs = contract.outputs.filter((_, i) => i !== index); onChange({ ...contract, outputs: output.primary ? outputs.map((item, i) => ({ ...item, primary: i === 0 })) : outputs }); }}><Trash2 size={13} /></Button></div>
          <label className="field-label"><span>Key</span><Input value={output.key} onChange={(event) => onChange({ ...contract, outputs: contract.outputs.map((item, i) => i === index ? { ...item, key: event.target.value } : item) })} /></label>
          <label className="field-label"><span>Label</span><Input value={output.label} onChange={(event) => onChange({ ...contract, outputs: contract.outputs.map((item, i) => i === index ? { ...item, label: event.target.value } : item) })} /></label>
          <p className="text-xs">{nodes.find((node) => node.id === output.node_id)?.data.label ?? "Missing Node"} · {output.port_key ?? output.port_type}</p>
        </article>)}
        <label className="field-label"><span>Add output</span><NativeSelect value="" onChange={(event) => {
          const option = outputOptions[Number(event.target.value)];
          if (!option) return;
          let index = 1;
          while (contract.outputs.some((output) => output.key === `output_${index}`)) index++;
          onChange({ ...contract, outputs: [...contract.outputs, { key: `output_${index}`, label: option.label, node_id: option.nodeId, port_key: option.portKey, port_type: option.portType, primary: !contract.outputs.length }] });
        }}><option value="">Choose Node result</option>{outputOptions.map((option, index) => <option key={`${option.nodeId}:${option.portKey}`} value={index}>{option.label}</option>)}</NativeSelect></label>
        {!!contract.outputs.length && <p className="text-xs text-[#777b72]">게시 제외: {excluded.length ? excluded.map((node) => node.data.label).join(", ") : "없음"}</p>}
      </section>
    </SheetContent>
  </Sheet>;
}
