import assert from "node:assert/strict";
import test from "node:test";
import { contractBatchTabs, firstMeetingHint } from "../app/lib/player-ui.ts";

test("batch display sorts household numbers without changing records or other batches", () => {
  const records = ["10", "2", "01"].map(id => ({ household_id: `WU-${id}`, batch_id: "wu", contract_id: `c${id}`, status: "draft" }));
  const before = structuredClone(records);
  const unrelated = { household_id: "YUAN-01", batch_id: "yuan", contract_id: "other" };
  const current = { ...records[1], status: "signed", current_version: 3 };
  const result = contractBatchTabs([...records, unrelated], current);
  assert.deepEqual(result.map(c => c.household_id), ["WU-01", "WU-2", "WU-10"]);
  assert.deepEqual(result[1], current);
  assert.deepEqual(records, before);
  assert.equal(result[0], records[2]);
});

test("Wu first meeting hint requires the current incomplete opportunity", () => {
  const state = { story: { day: 2 } };
  const required = { opportunity_id: "opp_d02_wu_xiuying_first_talk" };
  assert.match(firstMeetingHint(state, { required_opportunity: required }), /请寻找吴秀英进行谈话/);
  assert.equal(firstMeetingHint(state, {}), null);
  for (const change of [{ completed: true }, { satisfied: true }, { available: false }, { status: "completed" }, { status: "expired" }, { opportunity_id: "other" }]) {
    assert.equal(firstMeetingHint(state, { required_opportunity: { ...required, ...change } }), null);
  }
  assert.equal(firstMeetingHint({ story: { day: 10 } }, { required_opportunity: required }), null);
});
