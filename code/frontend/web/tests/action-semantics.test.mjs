import assert from "node:assert/strict";
import test from "node:test";
import { governanceActionButtonLabel, governanceDisplayTitle } from "../app/lib/player-ui.ts";
import { formTutorial } from "../app/tutorial/definitions.ts";

test("hearing and clan entries use the named activity rather than meeting verbs", () => {
  assert.equal(governanceActionButtonLabel({ action_id: "leadership_meeting", variant_id: "public_hearing" }), "发起听证");
  assert.equal(governanceActionButtonLabel({ action_id: "leadership_meeting", variant_id: "clan_leader_campaign" }), "发起议事");
  assert.equal(governanceActionButtonLabel({ action_id: "inspect_archives", variant_id: "collect_blood_lead_report" }), "调取材料");
});

test("public variant name stays consistent across entry and active record", () => {
  const descriptor = { action_id: "cadre_interview", variant_id: "interview_enterprise", name: "企业约谈" };
  assert.equal(governanceDisplayTitle(descriptor), "企业约谈");
  assert.equal(governanceDisplayTitle({ ...descriptor, display_title: "约谈钱伟" }), "约谈钱伟");
});

test("non-leadership guides cannot offer a leader, official document or meeting evidence workflow", () => {
  for (const variant_id of ["public_hearing", "clan_leader_campaign"]) {
    const guide = formTutorial({ action_id: "leadership_meeting", variant_id });
    assert.equal(guide.steps.some(step => ["form-document", "form-evidence", "form-lead"].includes(step.id)), false);
    const topic = guide.steps.find(step => step.id === "form-topic");
    assert.match(topic.body, variant_id === "public_hearing" ? /听证/ : /协商|议事/);
  }
});
