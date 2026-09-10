import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { resourceInventoryView } from "../app/lib/player-ui.ts";

const shell = await readFile(new URL("../app/GameShell.tsx", import.meta.url), "utf8");

test("hides decision forecasts and exact thresholds without revealing NPC demand checklists", () => {
  assert.doesNotMatch(shell, /data-testid="decision-tradeoff-preview"/);
  assert.doesNotMatch(shell, /data-testid="threshold-alerts"/);
  assert.doesNotMatch(shell, /data-testid="npc-demand-card"/);
  assert.match(shell, /data-testid="resource-pool-summary"/);
  assert.doesNotMatch(shell, /tradeoff_preview/);
  assert.equal(resourceInventoryView([{
    resource_id: "hearing_slot",
    name: "公开听证场次",
    category: "administrative_capacity",
    capacity: 3,
    available_to_reserve: 2,
    blocked_total: 1,
  }])[0].available, 2);
});

test("removes resource commitment controls and client asserted facts", () => {
  assert.doesNotMatch(shell, /governance\/npc-demands|onDisposeDemand|name="(?:authorization_confirmed|real_unit_viewed|ledger_disclosed|old_case_resolved|prior_payment_verified|payment_day)"/);
  assert.doesNotMatch(shell, /JSON.stringify\(contract.counteroffer/);
  assert.match(shell, /当前方案扣除预览/);
  assert.match(shell, /contract-submit/);
  assert.match(shell, /提交签约/);
});
