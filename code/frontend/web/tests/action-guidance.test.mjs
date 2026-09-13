import assert from "node:assert/strict";
import test from "node:test";
import { actionForNextStep, nextSteps } from "../app/lib/action-guidance.ts";

const catalog = { actions: [{ action_id: "inspect_archives", variants: [{ variant_id: "consult_county_archives", available: true, target_choices: [{ archive_id: "original", title: "政策原件" }] }] }] };
test("server guidance opens the exact declared archive without deciding evidence state", () => {
  const [step] = nextSteps([{ label: "查阅政策原件", action_id: "inspect_archives", archive_id: "original" }]);
  assert.deepEqual(actionForNextStep(catalog, step).preselected_archive_ids, ["original"]);
  assert.equal(actionForNextStep(catalog, { ...step, archive_id: "not-in-current-catalog" }), null);
  assert.equal(actionForNextStep(catalog, { ...step, unavailable_reason: "此前已销毁" }), null);
});
test("multiple variants require an explicit route; unavailable operations remain unavailable", () => {
  const data = { actions: [{ action_id: "household_visit", variants: [
    { variant_id: "field_visit", available: true, target_choices: [{ target_id: "npc_yuan_guilan" }] },
    { variant_id: "public_hearing", available: false, unavailable_reason: "请先结束会谈" },
  ] }] };
  assert.equal(actionForNextStep(data, { label: "办理", action_id: "household_visit" }), null);
  assert.equal(actionForNextStep(data, { label: "听证", action_id: "household_visit", variant_id: "public_hearing" }).available, false);
  assert.deepEqual(actionForNextStep(data, { label: "入户", action_id: "household_visit", variant_id: "field_visit", target_ids: ["npc_yuan_guilan"] }).preselected_npc_ids, ["npc_yuan_guilan"]);
  assert.equal(actionForNextStep(data, { label: "入户", action_id: "household_visit", variant_id: "field_visit", target_ids: ["hidden_npc"] }), null);
});
