import assert from "node:assert/strict";
import { costPresentation, formatCostAmount } from "../src/lib/cost.ts";

const base = {version: 1, currency: "USD", known_cost_usd: "0", amount_usd: null, unresolved_calls: 1, call_count: 1};
assert.equal(costPresentation({...base, status:"unreported"}).label, "미확정");
assert.equal(costPresentation({...base, status:"pending"}).label, "확인 중");
assert.equal(costPresentation({...base, status:"legacy"}, 0).detail, "비용 근거 없음");
assert.equal(costPresentation({...base, status:"partial", known_cost_usd:"0.25"}).label, "$0.25 + 미확정");
assert.equal(costPresentation({...base, status:"calculated", amount_usd:"0.0037756"}).label, "$0.003776");
assert.equal(costPresentation({...base, status:"recorded", amount_usd:"0.0037756"}).detail, "공급사 확인 금액");
assert.equal(costPresentation({...base, status:"no_charge", amount_usd:"0", reason:"cache_hit"}).detail, "캐시 재사용");
assert.equal(formatCostAmount("0.00000001"), "<$0.000001");
assert.equal(formatCostAmount("NaN"), "미확정");
console.log("Cost states distinguish pending, unknown, partial, legacy, calculated and confirmed amounts.");
