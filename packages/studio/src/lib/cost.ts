import type { CostSummary } from "./api";

export function formatCostAmount(value: string | number): string {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount < 0) return "미확정";
  if (amount > 0 && amount < 0.000001) return "<$0.000001";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 6 }).format(amount);
}

export function costPresentation(cost?: CostSummary, legacyCost = 0): { label: string; detail: string } {
  if (!cost || cost.status === "legacy") return { label: "과거 기록", detail: legacyCost > 0 ? `${formatCostAmount(legacyCost)} · 산정 근거 미확인` : "비용 근거 없음" };
  if (cost.status === "pending") return { label: "확인 중", detail: "사용량 수집 중" };
  if (cost.status === "unreported") return { label: "미확정", detail: "사용량 또는 단가 확인 필요" };
  if (cost.status === "partial") return { label: `${formatCostAmount(cost.known_cost_usd)} + 미확정`, detail: "확인된 금액만 합산" };
  if (cost.status === "no_charge") return { label: "$0.00", detail: cost.reason === "cache_hit" ? "캐시 재사용" : "추가 API 과금 없음" };
  return { label: formatCostAmount(cost.amount_usd ?? cost.known_cost_usd), detail: cost.status === "recorded" ? "공급사 확인 금액" : "사용량 × 요금표" };
}
