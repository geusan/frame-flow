export interface ModelOption {
  value: string;
  label: string;
}

export const googleTextModelOptions: ModelOption[] = [
  { value: "text.3.6-flash", label: "Gemini 3.6 Flash · Latest" },
  { value: "text.3.5-flash", label: "Gemini 3.5 Flash" },
  { value: "text.3.5-flash-lite", label: "Gemini 3.5 Flash-Lite" },
  { value: "text.3.1-pro-preview", label: "Gemini 3.1 Pro · Preview" },
  { value: "text.3.1-flash-lite", label: "Gemini 3.1 Flash-Lite" },
  { value: "text.2.5-flash", label: "Gemini 2.5 Flash" },
  { value: "text.2.5-flash-lite", label: "Gemini 2.5 Flash-Lite" },
];

export const qualifiedGoogleTextModelOptions: ModelOption[] = googleTextModelOptions.map((option) => ({
  ...option,
  value: `google.${option.value}`,
}));

export function migrateLegacyGoogleTextModelAlias(value?: string): string | undefined {
  if (value === "text.fast" || value === "google.text.fast") return "text.3.6-flash";
  if (value === "text.quality" || value === "google.text.quality") return "text.3.1-pro-preview";
  return value;
}
