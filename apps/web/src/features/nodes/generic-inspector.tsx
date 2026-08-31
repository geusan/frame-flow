import type { NodeDefinitionRecord } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";

export function GenericNodeInspector({ definition, value, onChange, hiddenFields = [] }: {
  definition: NodeDefinitionRecord;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  hiddenFields?: string[];
}) {
  const fields = Object.entries(definition.config_schema.properties).filter(([key]) => !hiddenFields.includes(key));
  return <div className="generic-node-settings">
    <div className="editor-input-count connected">
      <span>Contract</span>
      <strong>{definition.type_key}@{definition.contract_version}</strong>
      <small>{definition.execution.provider} · {definition.execution.model_alias}</small>
    </div>
    {fields.map(([key, field]) => {
      const current = value[key] ?? field.default ?? "";
      const label = field.title ?? key.replaceAll("_", " ");
      const update = (next: string | number | boolean) => onChange({ ...value, [key]: next });
      if (field.enum?.length) {
        return <label className="field-label" key={key}><span>{label}</span><NativeSelect value={String(current)} onChange={(event) => update(field.type === "integer" || field.type === "number" ? Number(event.target.value) : event.target.value)}>
          {field.enum.map((option) => <option value={String(option)} key={String(option)}>{field["x-enum-labels"]?.[String(option)] ?? String(option)}</option>)}
        </NativeSelect>{field.description && <small>{field.description}</small>}</label>;
      }
      if (field.type === "boolean") {
        return <label className="field-label" key={key}><span>{label}</span><NativeSelect value={String(Boolean(current))} onChange={(event) => update(event.target.value === "true")}><option value="true">On</option><option value="false">Off</option></NativeSelect>{field.description && <small>{field.description}</small>}</label>;
      }
      return <label className="field-label" key={key}><span>{label}</span><Input
        type={field.type === "integer" || field.type === "number" ? "number" : "text"}
        min={field.minimum ?? field.exclusiveMinimum}
        max={field.maximum}
        step={field.type === "integer" ? 1 : field.type === "number" ? "any" : undefined}
        value={String(current)}
        onChange={(event) => update(field.type === "integer" || field.type === "number" ? Number(event.target.value) : event.target.value)}
      />{field.description && <small>{field.description}</small>}</label>;
    })}
    <p className="step-run-help">{definition.execution.provider === "local" ? "로컬 Executor가 연결된 Artifact를 처리합니다. 실행 전에 입력과 출력 설정을 확인하세요." : "외부 Provider 비용이 발생할 수 있습니다. 실행 전에 입력과 설정을 확인하세요."}</p>
  </div>;
}
