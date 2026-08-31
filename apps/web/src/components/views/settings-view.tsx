"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  Bot,
  Check,
  ChevronDown,
  CircleAlert,
  Cloud,
  Copy,
  Database,
  ExternalLink,
  Film,
  KeyRound,
  RefreshCw,
  Save,
  ServerCog,
  Sparkles,
  SquareTerminal,
  Trash2,
  Video,
  Volume2,
  WandSparkles,
  Zap,
} from "lucide-react";

import { ConfirmAction } from "@/components/shared/confirm-action";
import { PageHeader } from "@/components/shared/page-header";
import { Accordion, AccordionContent, AccordionHeader, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { frameflowApi, type ProviderAuthMethod, type ProviderSetting } from "@/lib/api";

interface ProviderDraft {
  enabled: boolean;
  authMethod: string;
  values: Record<string, string>;
}

function draftFor(provider: ProviderSetting): ProviderDraft {
  return {
    enabled: provider.enabled,
    authMethod: provider.auth_method,
    values: Object.fromEntries(provider.fields.map((field) => [field.key, field.secret ? "" : field.value])),
  };
}

function sourceLabel(source: ProviderSetting["source"]): string {
  if (source === "environment") return "Imported from .env";
  if (source === "database") return "Managed in database";
  return "Provider defaults";
}

function providerIcon(provider: ProviderSetting["provider"]): ReactNode {
  if (provider === "openai") return <KeyRound size={19} />;
  if (provider === "google") return <Sparkles size={19} />;
  if (provider === "claude") return <Bot size={19} />;
  if (provider === "elevenlabs") return <Volume2 size={19} />;
  if (provider === "seedance") return <Film size={19} />;
  if (provider === "kling") return <WandSparkles size={19} />;
  if (provider === "minimax") return <Video size={19} />;
  if (provider === "fal") return <Zap size={19} />;
  if (provider === "r2") return <Cloud size={19} />;
  return <ServerCog size={19} />;
}

function authCommand(provider: ProviderSetting["provider"], method: ProviderAuthMethod): string | null {
  if (provider === "openai" && method.key === "chatgpt_oauth") return "codex login --device-auth";
  if (provider === "claude" && method.key === "setup_token") return "claude setup-token";
  return null;
}

export function SettingsView() {
  const [providers, setProviders] = useState<ProviderSetting[]>([]);
  const [drafts, setDrafts] = useState<Record<string, ProviderDraft>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [providerErrors, setProviderErrors] = useState<Record<string, string>>({});
  const [savedProvider, setSavedProvider] = useState<string | null>(null);
  const [copiedCommand, setCopiedCommand] = useState<string | null>(null);
  const [selectedSecretFiles, setSelectedSecretFiles] = useState<Record<string, string>>({});
  const [expandedProvider, setExpandedProvider] = useState<string | null>("openai");

  const loadProviders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const records = await frameflowApi.listProviderSettings();
      setProviders(records);
      setDrafts(Object.fromEntries(records.map((provider) => [provider.provider, draftFor(provider)])));
      setExpandedProvider((current) => current && records.some((provider) => provider.provider === current) ? current : records[0]?.provider ?? null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Provider settings loading failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadProviders(); }, [loadProviders]);

  const updateRecord = (record: ProviderSetting) => {
    setProviders((current) => current.map((provider) => provider.provider === record.provider ? record : provider));
    setDrafts((current) => ({ ...current, [record.provider]: draftFor(record) }));
    setSelectedSecretFiles((current) => {
      const next = { ...current };
      delete next[record.provider];
      return next;
    });
    window.dispatchEvent(new Event("frameflow:provider-settings-changed"));
  };

  const saveProvider = async (provider: ProviderSetting) => {
    const draft = drafts[provider.provider] ?? draftFor(provider);
    const visibleFields = provider.fields.filter((field) => !field.auth_methods.length || field.auth_methods.includes(draft.authMethod));
    setSaving(provider.provider);
    setSavedProvider(null);
    setProviderErrors((current) => ({ ...current, [provider.provider]: "" }));
    try {
      const values = Object.fromEntries(visibleFields
        .filter((field) => !field.secret || Boolean(draft.values[field.key]?.trim()))
        .map((field) => [field.key, draft.values[field.key] ?? ""]));
      const updated = await frameflowApi.updateProviderSettings(provider.provider, {
        enabled: draft.enabled,
        auth_method: draft.authMethod,
        values,
      });
      updateRecord(updated);
      setSavedProvider(provider.provider);
      window.setTimeout(() => setSavedProvider((current) => current === provider.provider ? null : current), 2200);
    } catch (saveError) {
      setProviderErrors((current) => ({ ...current, [provider.provider]: saveError instanceof Error ? saveError.message : "Provider settings save failed" }));
    } finally {
      setSaving(null);
    }
  };

  const removeSecret = async (provider: ProviderSetting, fieldKey: string) => {
    const draft = drafts[provider.provider] ?? draftFor(provider);
    setSaving(provider.provider);
    setProviderErrors((current) => ({ ...current, [provider.provider]: "" }));
    try {
      const updated = await frameflowApi.updateProviderSettings(provider.provider, {
        enabled: draft.enabled,
        auth_method: draft.authMethod,
        values: {},
        clear_fields: [fieldKey],
      });
      updateRecord(updated);
    } catch (removeError) {
      setProviderErrors((current) => ({ ...current, [provider.provider]: removeError instanceof Error ? removeError.message : "Credential removal failed" }));
    } finally {
      setSaving(null);
    }
  };

  const copyCommand = async (provider: string, command: string) => {
    try {
      await navigator.clipboard.writeText(command);
      setCopiedCommand(provider);
      window.setTimeout(() => setCopiedCommand((current) => current === provider ? null : current), 1800);
    } catch {
      setProviderErrors((current) => ({ ...current, [provider]: "Could not copy the command. Copy it from the code block instead." }));
    }
  };

  return (
    <div className="view-page settings-page">
      <PageHeader
        title="Provider connections"
        description="생성과 에이전트 실행에 사용할 모델 프로바이더와 인증 방식을 관리합니다."
        actions={<><Button variant="secondary" asChild><Link className="settings-model-link" href="/settings/models">Model registry <ExternalLink size={13} /></Link></Button><Button type="button" variant="secondary" onClick={() => void loadProviders()} disabled={loading}><RefreshCw size={14} className={loading ? "spin" : ""} /> Refresh</Button></>}
      />

      <Card className="settings-callout">
        <span><Database size={18} /></span>
        <div><strong>Credentials stay on the server</strong><p>저장한 secret은 이 화면에서 다시 읽을 수 없습니다. `.env` 값은 프로바이더가 처음 생성될 때만 가져오며 이후에는 DB 설정이 우선합니다.</p></div>
      </Card>

      {error && <p className="experiment-history-state error">{error}</p>}
      {!error && loading && <p className="experiment-history-state">Loading provider connections…</p>}

      <Accordion type="single" collapsible value={expandedProvider ?? ""} onValueChange={(value) => setExpandedProvider(value || null)} className="provider-settings-grid">
        {providers.map((provider) => {
          const draft = drafts[provider.provider] ?? draftFor(provider);
          const providerError = providerErrors[provider.provider];
          const selectedAuth = provider.auth_methods.find((method) => method.key === draft.authMethod) ?? provider.auth_methods[0];
          const visibleFields = provider.fields.filter((field) => !field.auth_methods.length || field.auth_methods.includes(draft.authMethod));
          const command = selectedAuth ? authCommand(provider.provider, selectedAuth) : null;
          const savedMethodIsSelected = provider.auth_method === draft.authMethod;
          const ready = draft.enabled && savedMethodIsSelected && provider.configured;
          const expanded = expandedProvider === provider.provider;
          return (
            <AccordionItem value={provider.provider} className={`provider-settings-card rounded-[11px] border border-[var(--line)] bg-[var(--panel)] shadow-[var(--shadow-sm)] ${expanded ? "expanded" : ""}`} key={provider.provider}>
              <AccordionHeader className="provider-settings-header">
                <AccordionTrigger
                  className="provider-accordion-trigger"
                >
                  <span className={`provider-logo ${provider.provider}`}>{providerIcon(provider.provider)}</span>
                  <span className="provider-accordion-copy"><strong>{provider.label}</strong><small>{provider.description}</small></span>
                  <span className={`provider-accordion-status ${ready ? "ready" : "incomplete"}`}>
                    {ready ? <Check size={12} /> : <CircleAlert size={12} />}
                    {ready ? "Ready" : "Setup required"}
                  </span>
                  <ChevronDown size={17} className={`provider-accordion-chevron ${expanded ? "expanded" : ""}`} />
                </AccordionTrigger>
                <div className="provider-toggle">
                  <Switch
                    id={`provider-enabled-${provider.provider}`}
                    checked={draft.enabled}
                    onCheckedChange={(checked) => setDrafts((current) => ({ ...current, [provider.provider]: { ...draft, enabled: checked } }))}
                  />
                  <label htmlFor={`provider-enabled-${provider.provider}`}><small>{draft.enabled ? "Enabled" : "Disabled"}</small></label>
                </div>
              </AccordionHeader>

              <AccordionContent className="provider-settings-content">
                <div className="provider-status-row">
                <span className={`provider-config-status ${ready ? "ready" : "incomplete"}`}>
                  {ready ? <Check size={12} /> : <CircleAlert size={12} />}
                  {ready ? "Ready" : selectedAuth?.external ? "Host sign-in required" : "Setup required"}
                </span>
                <span>{sourceLabel(provider.source)}</span>
                <span>Updated {new Date(provider.updated_at).toLocaleString("ko-KR")}</span>
              </div>

              {savedMethodIsSelected && provider.connection && (
                <p className={`provider-save-message ${provider.connection.ready ? "success" : "error"}`}>
                  {provider.connection.ready ? <Check size={13} /> : <CircleAlert size={13} />}
                  {provider.connection.message}
                  {provider.connection.plan && ` · ${provider.connection.plan}`}
                </p>
              )}

              {provider.auth_methods.length > 1 && (
                <div className="provider-auth-section">
                  <span>Authentication</span>
                  <ToggleGroup type="single" value={draft.authMethod} onValueChange={(value) => { if (value) setDrafts((current) => ({ ...current, [provider.provider]: { ...draft, authMethod: value } })); }} className="provider-auth-tabs" aria-label={`${provider.label} authentication method`}>
                    {provider.auth_methods.map((method) => (
                      <ToggleGroupItem
                        value={method.key}
                        className={draft.authMethod === method.key ? "active" : ""}
                        key={method.key}
                      >
                        {method.kind === "cloud" ? <Cloud size={13} /> : method.kind === "oauth" || method.kind === "setup_token" ? <SquareTerminal size={13} /> : <KeyRound size={13} />}
                        {method.label}
                      </ToggleGroupItem>
                    ))}
                  </ToggleGroup>
                  {selectedAuth && <p>{selectedAuth.description}</p>}
                </div>
              )}

              {command && (
                <div className={`provider-command-panel ${selectedAuth?.external ? "external" : ""}`}>
                  <span><SquareTerminal size={17} /></span>
                  <div>
                    <strong>{selectedAuth?.external ? "Sign in on the Codex execution host" : "Generate a setup token on the Claude Code host"}</strong>
                    <p>{selectedAuth?.external ? "브라우저 로그인을 완료한 호스트 세션은 토큰을 이 DB에 노출하지 않습니다." : "명령 실행 후 발급된 토큰을 아래 입력란에 붙여 넣으세요."}</p>
                    <code>{command}</code>
                  </div>
                  <Button type="button" variant="secondary" className="provider-copy-command" onClick={() => void copyCommand(provider.provider, command)}>
                    {copiedCommand === provider.provider ? <Check size={13} /> : <Copy size={13} />}
                    {copiedCommand === provider.provider ? "Copied" : "Copy"}
                  </Button>
                </div>
              )}

              {visibleFields.length > 0 && (
                <div className="provider-fields">
                  {visibleFields.map((field) => {
                    const required = selectedAuth?.required_fields.includes(field.key) ?? field.required;
                    if (field.input_kind === "service_account_json") {
                      const selectedFile = selectedSecretFiles[provider.provider];
                      return (
                        <Label className="provider-field provider-service-account-field" key={field.key} htmlFor={`${provider.provider}-${field.key}`}>
                          <span>{field.label}{required && <b>Required</b>}</span>
                          <div className="provider-service-account-input">
                            <Input
                              id={`${provider.provider}-${field.key}`}
                              type="file"
                              accept="application/json,.json"
                              autoComplete="off"
                              onChange={(event) => {
                                const file = event.target.files?.[0];
                                if (!file) return;
                                void file.text().then((value) => {
                                  setDrafts((current) => ({
                                    ...current,
                                    [provider.provider]: { ...draft, values: { ...draft.values, [field.key]: value } },
                                  }));
                                  setSelectedSecretFiles((current) => ({ ...current, [provider.provider]: file.name }));
                                }).catch(() => setProviderErrors((current) => ({ ...current, [provider.provider]: "Service Account JSON 파일을 읽지 못했습니다." })));
                              }}
                            />
                            <span>{selectedFile ? `${selectedFile} · 저장 준비됨` : field.has_value ? "Service Account가 저장되어 있습니다." : "다운로드한 JSON 키 파일을 선택하세요."}</span>
                            {field.has_value && <ConfirmAction trigger={<Button type="button" variant="danger" size="icon" className="provider-secret-remove" aria-label={`Remove ${field.label}`} disabled={saving === provider.provider}><Trash2 size={13} /></Button>} title={`Remove ${field.label}?`} description="저장된 Service Account 개인 키를 데이터베이스에서 제거합니다." confirmLabel="Remove credential" onConfirm={() => removeSecret(provider, field.key)} />}
                          </div>
                          <small><code>{field.env_var}</code>{field.help_text && ` · ${field.help_text}`}</small>
                        </Label>
                      );
                    }
                    return (
                      <Label className="provider-field" key={field.key} htmlFor={`${provider.provider}-${field.key}`}>
                        <span>{field.label}{required && <b>Required</b>}</span>
                        <div className="provider-input-row">
                          <Input
                            id={`${provider.provider}-${field.key}`}
                            className="flex-1"
                            type={field.secret ? "password" : "text"}
                            autoComplete="off"
                            value={draft.values[field.key] ?? ""}
                            placeholder={field.secret && field.has_value ? "Saved — enter a new value to replace" : field.placeholder}
                            onChange={(event) => setDrafts((current) => ({
                              ...current,
                              [provider.provider]: { ...draft, values: { ...draft.values, [field.key]: event.target.value } },
                            }))}
                          />
                          {field.secret && field.has_value && <ConfirmAction trigger={<Button type="button" variant="danger" size="icon" className="provider-secret-remove" aria-label={`Remove ${field.label}`} disabled={saving === provider.provider}><Trash2 size={13} /></Button>} title={`Remove ${field.label}?`} description="This saved credential will be removed from the database. You can add a new value later." confirmLabel="Remove credential" onConfirm={() => removeSecret(provider, field.key)} />}
                        </div>
                        <small><code>{field.env_var}</code>{field.help_text && ` · ${field.help_text}`}</small>
                      </Label>
                    );
                  })}
                </div>
              )}

              {providerError && <p className="provider-save-message error"><CircleAlert size={13} />{providerError}</p>}
              {savedProvider === provider.provider && <p className="provider-save-message success"><Check size={13} />Saved to database and applied</p>}
              <footer className="provider-settings-footer">
                <span>{selectedAuth?.external ? "OAuth credentials remain in the Codex host session." : "Secret values are write-only in this UI."}</span>
                <Button type="button" onClick={() => void saveProvider(provider)} disabled={saving === provider.provider}>
                  <Save size={14} /> {saving === provider.provider ? "Saving…" : "Save connection"}
                </Button>
              </footer>
              </AccordionContent>
            </AccordionItem>
          );
        })}
      </Accordion>
    </div>
  );
}
