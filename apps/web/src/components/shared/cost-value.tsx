import type { CostSummary } from "@/lib/api";
import { costPresentation } from "@/lib/cost";

export function CostValue({ cost, legacyCost = 0 }: { cost?: CostSummary; legacyCost?: number }) {
  const value = costPresentation(cost, legacyCost);
  return <span className="inline-flex flex-col gap-1 text-left"><strong className="whitespace-nowrap">{value.label}</strong><small className="text-[var(--ink-faint)]">{value.detail}</small></span>;
}
