"use client";
import { useStudioRuntime } from "../../runtime/studio-runtime";


import { useEffect, useState } from "react";
import { type ProviderCostRecord } from "../../lib/api";
import { formatCostAmount } from "../../lib/cost";
import { Button } from "../ui/button";

export function RunCostDetails({ ownerId }: { ownerId: string }) {
  const { frameflowApi } = useStudioRuntime();
  const [receipts, setReceipts] = useState<ProviderCostRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  useEffect(() => {
    let active = true;
    frameflowApi.listCosts(ownerId).then((rows) => { if (active) { setReceipts(rows); setHasMore(rows.length === 100); } })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "비용 기록을 불러오지 못했습니다."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [ownerId, frameflowApi]);
  const loadMore = async () => {
    setLoading(true);
    setError(null);
    try { const rows = await frameflowApi.listCosts(ownerId, receipts.length); setReceipts((current) => [...current, ...rows]); setHasMore(rows.length === 100); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "비용 기록을 불러오지 못했습니다."); }
    finally { setLoading(false); }
  };
  return <div className="flex flex-col gap-3 p-4" aria-label="비용 기록 상세">
    <p className="text-sm text-[var(--ink-soft)]">공급사 호출별 사용량과 단가입니다. 요금표 계산에는 계정 할인·세금이 반영되지 않으며, 미확정 항목은 금액 합계에서 제외합니다.</p>
    {error && <p role="alert">{error}</p>}
    {!loading && !receipts.length && !error && <p>이 실행에 연결된 공급사 호출 기록이 없습니다. 로컬 처리·재사용이거나 비용 원장 도입 전 기록입니다.</p>}
    {receipts.map((receipt) => <article key={receipt.id} className="rounded-lg border border-[var(--line)] bg-white p-3">
      <div className="flex flex-wrap items-start justify-between gap-3"><span><strong>{receipt.provider} · {receipt.model}</strong><small className="mt-1 block text-[var(--ink-faint)]">{receipt.operation} · {new Date(receipt.created_at).toLocaleString("ko-KR")}</small></span><span className="text-right"><strong>{receipt.amount_usd === null ? "미확정" : formatCostAmount(receipt.amount_usd)}</strong><small className="mt-1 block text-[var(--ink-faint)]">{receipt.status === "calculated" ? "사용량 × 요금표" : receipt.status === "recorded" ? "공급사 확인 금액" : receipt.status === "no_charge" ? "추가 과금 없음" : "금액 확인 필요"}</small></span></div>
      <p className="mt-2 break-all text-xs text-[var(--ink-soft)]">Request: {receipt.provider_request_id ?? "공급사 요청 ID 미수신"}</p>
      <details className="mt-2 text-xs"><summary className="cursor-pointer">사용량·단가 근거 보기</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all rounded bg-[var(--panel-muted)] p-3">{JSON.stringify({ usage: receipt.usage, pricing: receipt.pricing, reason: receipt.reason }, null, 2)}</pre></details>
    </article>)}
    {loading && <p role="status">비용 기록을 불러오는 중…</p>}
    {hasMore && <Button variant="secondary" disabled={loading} onClick={() => void loadMore()}>더 보기</Button>}
  </div>;
}
