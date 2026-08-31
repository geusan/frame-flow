"use client";

import { Braces, Link2, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import type { WorkflowBindingDefinition, WorkflowDraftContract, WorkflowInputDefinition } from "@/lib/api";

function updateBindingKey(binding: WorkflowBindingDefinition, previous: string, next: string): WorkflowBindingDefinition {
  if (binding.value.kind === "input") return binding.value.key === previous ? { ...binding, value: { ...binding.value, key: next } } : binding;
  return binding.value.input_keys.includes(previous) ? { ...binding, value: { ...binding.value, input_keys: binding.value.input_keys.map((key) => key === previous ? next : key) } } : binding;
}

function defaultEditor(input: WorkflowInputDefinition, onChange: (value: unknown) => void) {
  if (input.type === "boolean") return <NativeSelect value={String(Boolean(input.default))} onChange={(event) => onChange(event.target.value === "true")}><option value="true">On</option><option value="false">Off</option></NativeSelect>;
  if ((input.type === "enum" || input.type === "model_alias") && input.options?.length) return <NativeSelect value={String(input.default ?? "")} onChange={(event) => onChange(event.target.value)}>{input.options.map((option) => <option value={String(option)} key={String(option)}>{String(option)}</option>)}</NativeSelect>;
  return <Input type={input.type === "integer" || input.type === "number" ? "number" : "text"} value={String(input.default ?? "")} onChange={(event) => onChange(input.type === "integer" || input.type === "number" ? Number(event.target.value) : event.target.value)} placeholder={input.type === "artifact" ? "Artifact ID" : input.type === "character" ? "Character Artifact ID" : "Default value"} />;
}

export function WorkflowInputsPanel({ open, contract, onOpenChange, onChange }: {
  open: boolean;
  contract: WorkflowDraftContract;
  onOpenChange: (open: boolean) => void;
  onChange: (contract: WorkflowDraftContract) => void;
}) {
  const patchInput = (index: number, patch: Partial<WorkflowInputDefinition>) => {
    const previous = contract.inputs[index];
    const nextInput = { ...previous, ...patch };
    onChange({
      ...contract,
      inputs: contract.inputs.map((item, itemIndex) => itemIndex === index ? nextInput : item),
      bindings: patch.key && patch.key !== previous.key ? contract.bindings.map((binding) => updateBindingKey(binding, previous.key, patch.key!)) : contract.bindings,
    });
  };
  const removeInput = (input: WorkflowInputDefinition) => onChange({
    ...contract,
    inputs: contract.inputs.filter((item) => item.key !== input.key),
    bindings: contract.bindings.filter((binding) => binding.value.kind === "input" ? binding.value.key !== input.key : !binding.value.input_keys.includes(input.key)),
  });

  return <Sheet open={open} onOpenChange={onOpenChange}>
    <SheetContent className="w-[420px] max-w-[92vw] overflow-y-auto border-l border-[#d8dad3] bg-[#f7f7f3] p-5 shadow-[-18px_0_44px_rgba(30,32,29,.12)]">
      <div className="mb-5 flex items-start justify-between gap-3"><div><SheetTitle className="text-lg font-bold text-[#252722]">Workflow inputs</SheetTitle><SheetDescription className="mt-1 text-xs text-[#777b72]">게시된 Version의 실행 Form과 Node Config binding을 정의합니다.</SheetDescription></div><SheetClose asChild><Button type="button" variant="ghost" size="icon-sm"><X size={16} /></Button></SheetClose></div>
      {!contract.inputs.length && <div className="rounded-xl border border-dashed border-[#cfd1ca] bg-white p-5 text-center"><Braces className="mx-auto mb-2 text-[#858980]" size={22} /><strong className="block text-sm text-[#3f423c]">No exposed inputs</strong><p className="mt-1 text-xs text-[#777b72]">Node Inspector에서 변수화 가능한 설정을 선택하세요.</p></div>}
      <div className="flex flex-col gap-3">{contract.inputs.map((input, index) => {
        const binding = contract.bindings.find((item) => item.value.kind === "input" ? item.value.key === input.key : item.value.input_keys.includes(input.key));
        return <article className="rounded-xl border border-[#d8dad3] bg-white p-3" key={`${input.key}-${index}`}>
          <div className="mb-3 flex items-center justify-between"><span><small className="block text-[10px] uppercase tracking-[.08em] text-[#888c83]">{input.type}</small><strong className="text-sm text-[#30332d]">{input.label}</strong></span><Button type="button" variant="ghost" size="icon-sm" onClick={() => removeInput(input)}><Trash2 size={13} /></Button></div>
          <div className="grid grid-cols-2 gap-2"><label className="field-label"><span>Key</span><Input value={input.key} onChange={(event) => patchInput(index, { key: event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })} /></label><label className="field-label"><span>Label</span><Input value={input.label} onChange={(event) => patchInput(index, { label: event.target.value })} /></label></div>
          <label className="field-label"><span className="flex items-center justify-between">Required <Switch checked={Boolean(input.required)} onCheckedChange={(required) => patchInput(index, required ? { required, default: undefined } : { required })} /></span></label>
          {!input.required && <label className="field-label"><span>Default</span>{defaultEditor(input, (value) => patchInput(index, { default: value }))}</label>}
          {binding && <div className="mt-2 flex items-center gap-1.5 rounded-md bg-[#f0f1ec] px-2 py-1.5 text-[10px] text-[#666a61]"><Link2 size={11} /><code>{binding.target.node_id}{binding.target.path}</code></div>}
        </article>;
      })}</div>
    </SheetContent>
  </Sheet>;
}
