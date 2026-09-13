import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { primaryScenePlan } from "../app/lib/player-ui.ts";

const shellPath = new URL("../app/GameShell.tsx", import.meta.url);
const apiPath = new URL("../app/lib/api.ts", import.meta.url);

test("keeps every state-changing gameplay workflow connected to an API route", async () => {
  const [shell, api] = await Promise.all([
    readFile(shellPath, "utf8"),
    readFile(apiPath, "utf8"),
  ]);
  const source = `${shell}\n${api}`;
  for (const route of [
    "/action/stream",
    "/group-conversation/turn/stream",
    "/group-conversation/finish",
    "/governance/actions",
    "/governance/meetings/",
    "/governance/documents/",
    "/governance/contract-batches/",
    "/governance/contracts/",
    "/actions/quote",
    "/end-day",
    "/manual-saves",
    "/load-snapshot",
  ]) {
    assert.match(source, new RegExp(route.replaceAll("/", "\\/")));
  }
});

test("renders persuasion follow-ups as reviewable conversations without a turn quota", async () => {
  const [shell, styles] = await Promise.all([
    readFile(shellPath, "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);
  assert.doesNotMatch(shell, /group\.max_turns|conversation\.max_turns/);
  assert.match(shell, /conversation\.participant_states/);
  assert.match(shell, /在场人物已暂时接受，等待发起人确认收束/);
  assert.match(shell, /人仍在追问/);
  assert.match(shell, /item\.status !== "settled"/);
  assert.match(shell, /conversation\.phase === "resolved"/);
  assert.match(shell, /结束夜间会谈/);
  assert.match(shell, /有新发言/);
  assert.match(shell, /forced-group-timeline/);
  assert.match(shell, /leadership-meeting-room/);
  assert.match(styles, /\.ai-thinking-banner[^{]*\{[^}]*top:\s*50%/s);
  assert.match(styles, /\.ai-thinking-banner strong[^{]*\{[^}]*font-size:\s*2[2-4]px/s);
});

test("people cards show one compact metric projection and only confirmed relations", async () => {
  const [shell, playerUi] = await Promise.all([
    readFile(shellPath, "utf8"),
    readFile(new URL("../app/lib/player-ui.ts", import.meta.url), "utf8"),
  ]);
  const peoplePanel = shell.slice(shell.indexOf("function OpportunityPanel("), shell.indexOf("function ReviewPanel("));
  assert.doesNotMatch(peoplePanel, /关系待核实/);
  assert.match(peoplePanel, /近期关系变化依据/);
  assert.match(peoplePanel, /person\.recent_change_reasons/);
  assert.match(playerUi, /visibility !== "confirmed"/);
});

test("assigns attempt keys to every streamed group and governance turn", async () => {
  const shell = await readFile(shellPath, "utf8");
  for (const prefix of ["group-turn", "meeting-turn", "governance-turn"]) {
    assert.match(shell, new RegExp(`client_action_id: api\\.key\\("${prefix}"\\)`));
  }
});

test("signs an accepted household contract without a second confirmation step", async () => {
  const shell = await readFile(shellPath, "utf8");
  assert.match(shell, /ForcedGroupConversationScene/);
  assert.match(shell, /发起人：/);
  assert.match(shell, /participant_ids/);
  assert.match(shell, /contract_batch_proposal/);
  assert.match(shell, />继续办理合同</);
  assert.doesNotMatch(shell, /if \(result\.contract_batch_proposal\) setContractProposalOpen/);
  assert.match(shell, /activeContractWorkflow/);
  assert.match(shell, /openContractDetail\(activeContractWorkflow\.contract\)/);
  assert.match(shell, /确认逐户合同提议/);
  assert.match(shell, /保存方案并预览合同/);
  assert.doesNotMatch(shell, /保存正文并重新审校/);
  assert.match(shell, /提交签约/);
  assert.doesNotMatch(shell, /正式签署并入账/);
  assert.doesNotMatch(shell, /确认本人签署/);
  assert.match(shell, /group_conversation_timeline/);
  assert.doesNotMatch(shell, /contact_selections/);
  assert.doesNotMatch(shell, /contact_responses/);
  assert.doesNotMatch(shell, /agent_exchanges/);
});

test("renders the authoritative final ending in the review panel", async () => {
  const shell = await readFile(shellPath, "utf8");
  assert.match(shell, /reviewEndingView\(data\)/);
  assert.match(shell, /aria-label="最终结局"/);
  assert.match(shell, /ending\.mainText/);
  assert.match(shell, /ending\.subText/);
  assert.match(shell, /ending\.appendices/);
});

test("retired overtime and fatigue cannot be submitted from the frontend", async () => {
  const shell = await readFile(shellPath, "utf8");
  assert.doesNotMatch(shell, /input_mode: "overtime"|申请加班|fatigue\.label|chapter_overtime_remaining/);
});

test("surfaces required model consent before NPC gameplay", async () => {
  const [shell, api] = await Promise.all([
    readFile(shellPath, "utf8"),
    readFile(apiPath, "utf8"),
  ]);
  assert.match(api, /\/api\/consent\/current/);
  assert.match(api, /\/api\/consent"/);
  assert.match(api, /third_party_model/);
  assert.match(shell, /model_consent_required/);
  assert.match(shell, /同意必要授权并继续/);
  assert.match(shell, /撤回授权/);
});

test("day-end uses an in-game confirmation panel", async () => {
  const shell = await readFile(shellPath, "utf8");
  const endDay = shell.slice(shell.indexOf("function confirmEndDay"), shell.indexOf("function confirmEndDay") + 1000);
  assert.ok(endDay.includes("confirmLabel"));
  assert.doesNotMatch(endDay, /window\.confirm/);
  assert.match(shell, /结束今日工作/);
  assert.match(shell, /进入夜间结算/);
  assert.match(shell, /confirmLabel: "进入夜间结算"/);
});

test("routes retired saves to review and disables unavailable locked content", async () => {
  const [shell, api] = await Promise.all([readFile(shellPath, "utf8"), readFile(apiPath, "utf8")]);
  assert.match(api, /\/api\/game\/sessions/);
  assert.match(shell, /sessionEntry\(saved\)/);
  assert.match(shell, /entry\.mode === "review"/);
  assert.match(shell, /仅可复盘/);
  assert.match(shell, /disabled=\{entry\.openKind === null \|\| needsAI\}/);
  assert.match(shell, /if \(entry\.openKind && !needsAI\) openSession\(entry\.openKind/);
  assert.match(shell, /if \(kind !== "review" && modelConsentRequired && !consentGranted\)/);
  assert.match(shell, /entry\.unavailableReason/);
});

test("does not report rejected governance input as an NPC success", async () => {
  const shell = await readFile(shellPath, "utf8");
  assert.match(shell, /result\.input_rejected/);
  assert.match(shell, /这句话没有送达/);
  assert.match(shell, /typeof success === "function"/);
});

test("renders every non-meeting NPC exchange as a Galgame stage", async () => {
  const shell = await readFile(shellPath, "utf8");
  assert.deepEqual(primaryScenePlan({
    has_session: true,
    active_governance_action: { action_kind: "household_visit" },
    active_meeting: null,
  }), ["governance_action"]);
  assert.deepEqual(primaryScenePlan({
    has_session: true,
    active_governance_action: { action_kind: "leadership_meeting" },
    active_meeting: { meeting_id: "meeting-1" },
  }), ["leadership_meeting"]);
  assert.match(shell, /className="gal-stage governance-gal-stage conversation-mode"/);
  assert.match(shell, /data-testid="governance-gal-scene"/);
  assert.match(shell, /className="gal-portrait" aria-label=\{`\$\{targetName\}立绘`\}/);
  assert.match(shell, /className="forced-group-gal-stage leadership-meeting-room"/);
  assert.match(shell, /streamingReplies=\{streamingReplies\}/);
});
