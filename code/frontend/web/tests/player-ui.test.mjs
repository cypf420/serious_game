import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { actionPointCost, actionPointLabel, toPlayerText } from "../app/lib/player-ui.ts";
import * as playerUi from "../app/lib/player-ui.ts";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("selects a clicked NPC timeline entry through the existing speaker selection state", async () => {
  assert.equal(typeof playerUi.speakerSelectionForTimelineEntry, "function");
  assert.deepEqual(
    playerUi.speakerSelectionForTimelineEntry({ speaker_type: "npc", npc_id: "npc_sun_qiang" }, 7),
    { npcId: "npc_sun_qiang", timelineLength: 7 },
  );
  assert.equal(playerUi.speakerSelectionForTimelineEntry({ speaker_type: "player" }, 7), null);

  const shell = await readFile(path.join(projectRoot, "app", "GameShell.tsx"), "utf8");
  assert.match(shell, /setSpeakerSelection\(speakerSelectionForTimelineEntry\(entry, timeline\.length\)!\)/);
  assert.doesNotMatch(shell, /setSelectedNpcId/);
});

test("normalizes every supported action point cost shape including zero", () => {
  assert.equal(actionPointCost({ cost_action_points: 2 }), 2);
  assert.equal(actionPointCost({ action_point_cost: 3 }), 3);
  assert.equal(actionPointCost({ cost: { action_points: 4 } }), 4);
  assert.equal(actionPointCost({ cost: 5 }), 5);
  assert.equal(actionPointCost({ ap_cost: "6" }), 6);
  assert.equal(actionPointCost({ cost_action_points: 0, action_point_cost: 9 }), 0);
  assert.equal(actionPointCost({}), null);
  assert.equal(actionPointLabel({ cost_action_points: 0 }), "不消耗精力");
  assert.equal(actionPointLabel({ cost_action_points: 2 }), "消耗 2 点精力");
});

test("restores the configured AI mode from the authoritative response", () => {
  assert.equal(typeof playerUi.aiConfigurationMode, "function");
  assert.equal(playerUi.aiConfigurationMode({ active: true, mode: "server_default" }), "server_default");
  assert.equal(playerUi.aiConfigurationMode({ active: true, mode: "personal" }), "personal");
  assert.equal(playerUi.aiConfigurationMode({ active: false }), "personal");
});

test("routes a forced group conversation before a stale governance action", async () => {
  assert.equal(typeof playerUi.activeInteractionMode, "function");
  assert.equal(playerUi.activeInteractionMode({
    active_group_conversation: { conversation_id: "group-d2" },
    active_conversation: null,
  }, { action_instance_id: "gov-d2", status: "active" }), "group");
  const shell = await readFile(path.join(projectRoot, "app", "GameShell.tsx"), "utf8");
  assert.match(shell, /onSubmit=\{interactionMode === "governance" \? submitGovernanceTurn : submitConversation\}/);
});

test("keeps scene and interaction priority aligned for overlapping player states", () => {
  const overlapping = {
    has_session: true,
    active_group_conversation: { conversation_id: "group-priority" },
    active_conversation: { conversation_id: "ordinary-priority" },
    active_governance_action: { action_instance_id: "gov-priority", action_kind: "household_visit" },
  };
  assert.deepEqual(playerUi.primaryScenePlan(overlapping), ["forced_group_conversation"]);
  assert.equal(playerUi.activeInteractionMode(overlapping, overlapping.active_governance_action), "group");
  const conversationOnly = { ...overlapping, active_group_conversation: null };
  assert.deepEqual(playerUi.primaryScenePlan(conversationOnly), ["conversation"]);
  assert.equal(playerUi.activeInteractionMode(conversationOnly, conversationOnly.active_governance_action), "conversation");
});

test("shows unfinished contract work only during the matching representative conversation", () => {
  assert.equal(typeof playerUi.conversationContractWorkflow, "function");
  const batches = [
    { batch_id: "batch-a", representative_npc_id: "npc_a", status: "confirmed", contract_ids: ["contract-a"] },
    { batch_id: "batch-b", representative_npc_id: "npc_b", status: "pending_confirmation", contract_ids: [] },
  ];
  const contracts = [
    { contract_id: "contract-a", batch_id: "batch-a", signatory_npc_id: "npc_household_a", status: "draft" },
  ];
  assert.deepEqual(
    playerUi.conversationContractWorkflow(
      { action_kind: "household_visit", status: "active", target_ids: ["npc_a"] },
      batches,
      contracts,
    ),
    { proposal: null, contract: contracts[0] },
  );
  assert.equal(
    playerUi.conversationContractWorkflow(
      { action_kind: "cadre_interview", status: "active", target_ids: ["npc_a"] },
      batches,
      contracts,
    ),
    null,
  );
  assert.equal(
    playerUi.conversationContractWorkflow(
      { action_kind: "household_visit", status: "active", target_ids: ["npc_b"] },
      batches,
      contracts,
    )?.proposal?.batch_id,
    "batch-b",
  );
  assert.deepEqual(
    playerUi.conversationContractWorkflow(
      { action_kind: "household_visit", status: "active", target_ids: ["npc_household_a"] },
      batches,
      contracts,
    ),
    { proposal: null, contract: contracts[0] },
  );
  assert.equal(playerUi.conversationContractWorkflow(null, batches, contracts), null);
});

test("uses the pre-update scroll state when deciding whether to follow new dialogue", () => {
  assert.equal(typeof playerUi.conversationTimelineUpdate, "function");
  assert.deepEqual(
    playerUi.conversationTimelineUpdate(true, 2, 3),
    { followLatest: true, showNewDialogue: false },
  );
  assert.deepEqual(
    playerUi.conversationTimelineUpdate(false, 2, 3),
    { followLatest: false, showNewDialogue: true },
  );
  assert.deepEqual(
    playerUi.conversationTimelineUpdate(false, 3, 3),
    { followLatest: false, showNewDialogue: false },
  );
});

test("projects player-safe investigation leads with concrete acquisition instructions", () => {
  assert.equal(typeof playerUi.investigationLeadView, "function");
  assert.deepEqual(playerUi.investigationLeadView([
    {
      fact_id: "fact-a",
      title: "资金去向疑点",
      category: "clue",
      methods: [
        {
          route_type: "archive",
          label: "查阅《财政索引》",
          instructions: "进入行动页选择“查阅档案”。",
          unlock_day: 3,
          source_id: "internal-archive-id",
        },
      ],
    },
    { fact_id: "fact-empty", title: "无路径", methods: [] },
  ]), [
    {
      factId: "fact-a",
      title: "资金去向疑点",
      category: "clue",
      methods: [
        {
          routeType: "archive",
          label: "查阅《财政索引》",
          instructions: "进入行动页选择“查阅档案”。",
          unlockDay: 3,
        },
      ],
    },
  ]);
});

test("sanitizes player copy", async () => {
  assert.equal(toPlayerText("[BEAT_C01] NPC与玩家对应剧情节点"), "人物与你后续事态");
});

test("projects every authoritative resource pool with usable inventory totals", () => {
  assert.equal(typeof playerUi.resourceInventoryView, "function");
  assert.deepEqual(playerUi.resourceInventoryView([
    {
      resource_id: "lead_recheck_slot",
      name: "血铅复检名额",
      category: "medical",
      capacity: 10,
      available_to_reserve: 7,
      blocked_total: 3,
      available_day: 1,
    },
    {
      resource_id: "grave_relocation_service",
      name: "迁坟事务服务户次",
      category: "grave",
      capacity: 5,
      available: 5,
      attributes: { unit: "household_case" },
      available_day: 30,
    },
    {
      resource_id: "startup_interest_slot",
      name: "创业贴息名额",
      category: "business",
      capacity: 4,
      available: 4,
    },
    {
      resource_id: "legal_review_slot",
      name: "合法性审查工时",
      category: "administrative_capacity",
      capacity: 8,
      available: 8,
      attributes: { unit: "case" },
    },
  ]), [
    {
      resourceId: "lead_recheck_slot",
      name: "血铅复检名额",
      category: "medical",
      capacity: 10,
      available: 7,
      used: 3,
      unit: "名额",
      availableDay: 1,
      allocatableScope: "contract",
    },
    {
      resourceId: "grave_relocation_service",
      name: "迁坟事务服务户次",
      category: "grave",
      capacity: 5,
      available: 5,
      used: 0,
      unit: "户次",
      availableDay: 30,
      allocatableScope: "contract",
    },
    {
      resourceId: "startup_interest_slot",
      name: "创业贴息名额",
      category: "business",
      capacity: 4,
      available: 4,
      used: 0,
      unit: "名额",
      availableDay: 1,
      allocatableScope: "contract",
    },
    {
      resourceId: "legal_review_slot",
      name: "合法性审查工时",
      category: "administrative_capacity",
      capacity: 8,
      available: 8,
      used: 0,
      unit: "工时",
      availableDay: 1,
      allocatableScope: "contract",
    },
  ]);
});

test("announces an AI operation before work and always clears it afterward", async () => {
  assert.equal(typeof playerUi.withAIActivity, "function");
  const activity = [];
  let release;
  const pending = playerUi.withAIActivity(
    value => activity.push(value),
    "正在生成并审校合同",
    () => new Promise(resolve => { release = resolve; }),
  );
  assert.deepEqual(activity, [{ label: "正在生成并审校合同" }]);
  release("完成");
  assert.equal(await pending, "完成");
  assert.deepEqual(activity, [{ label: "正在生成并审校合同" }, null]);

  await assert.rejects(() => playerUi.withAIActivity(
    value => activity.push(value),
    "正在进行夜间结算",
    async () => { throw new Error("供应商暂时不可用"); },
  ));
  assert.deepEqual(activity.slice(-2), [{ label: "正在进行夜间结算" }, null]);
});

test("groups archive investigations and exposes only read meeting evidence", () => {
  const archives = [
    {
      archive_id: "archive_unread",
      title: "三年度环保报告版本",
      read_status: "unread",
      first_read_cost_action_points: 2,
      result_fact_count: 1,
      strategic_uses: ["申请独立环境复核"],
    },
    {
      archive_id: "archive_read",
      title: "36户基础底账",
      read_status: "read",
      read_at_days: [2],
      evidence_level: "E2",
      strategic_uses: ["核对签约分母"],
    },
    {
      archive_id: "archive_legacy_read",
      title: "项目简报",
      read_at_days: [1],
      evidence_level: "E1",
    },
  ];

  assert.deepEqual(playerUi.archiveInvestigationGroups(archives), {
    unread: [archives[0]],
    read: [archives[1], archives[2]],
    unreadCount: 1,
  });
  assert.deepEqual(
    playerUi.meetingEvidenceArchives(archives).map(item => item.archive_id),
    ["archive_read", "archive_legacy_read"],
  );
});

test("projects safe decision unlock requirements and archive read gains", () => {
  assert.deepEqual(
    playerUi.decisionUnlockRequirements({
      unlock_requirements: [
        { archive_name: "血铅普查原始总表", reason: "公开结果需要完整依据。" },
        { archive_name: "", reason: "隐藏内部信息" },
      ],
    }),
    [{ archiveName: "血铅普查原始总表", reason: "公开结果需要完整依据。" }],
  );
  assert.deepEqual(
    playerUi.archiveReadGains({
      newly_learned_facts: [{ fact_id: "fact_lead_census", title: "血铅普查总表" }],
      strategic_uses: ["推动完整医疗处置", "纳入巡察材料"],
    }),
    {
      facts: [{ fact_id: "fact_lead_census", title: "血铅普查总表" }],
      strategicUses: ["推动完整医疗处置", "纳入巡察材料"],
    },
  );
});

test("connects archive investigation state to the visible player workflow", async () => {
  const source = await readFile(path.join(projectRoot, "app", "GameShell.tsx"), "utf8");
  assert.match(source, /新到未读/);
  assert.match(source, /已读可重读/);
  assert.match(source, /每次选择一份/);
  assert.match(source, /meetingEvidenceArchives/);
  assert.match(source, /decisionUnlockRequirements/);
  assert.match(source, /前往查档/);
  assert.match(source, /新掌握线索/);
  assert.match(source, /可用于什么/);
  assert.match(source, /只能引用已经查阅且证据等级足够的材料/);
});

test("closes the public signing reward after day 75", () => {
  assert.equal(typeof playerUi.publicWindowRewardAvailable, "function");
  assert.equal(playerUi.publicWindowRewardAvailable(75), true);
  assert.equal(playerUi.publicWindowRewardAvailable(76), false);
  assert.equal(playerUi.publicWindowRewardAvailable("77"), false);
});

test("projects the completed ending for the review panel", () => {
  assert.equal(typeof playerUi.reviewEndingView, "function");
  const ending = playerUi.reviewEndingView({
    status: "ended",
    ending: {
      main_ending_id: "ending_21",
      main_ending_name: "揭而未治",
      sub_ending_id: "ending_21a",
      sub_ending_title: "背书",
      main_text: "你把它说出来了。",
      sub_text: "决议下面没有钱，也没有人。",
      axes: { A: "宽裕", T: "揭而未治" },
      appendices: [{ appendix_id: "a1", title: "血铅名册的去向", text: "最终见了报。" }],
    },
  });
  assert.deepEqual(ending, {
    mainId: "ending_21",
    mainName: "揭而未治",
    subId: "ending_21a",
    subTitle: "背书",
    mainText: "你把它说出来了。",
    subText: "决议下面没有钱，也没有人。",
    axes: [{ key: "A", value: "宽裕" }, { key: "T", value: "揭而未治" }],
    appendices: [{ appendix_id: "a1", title: "血铅名册的去向", text: "最终见了报。" }],
  });
  assert.equal(playerUi.reviewEndingView({ status: "active" }), null);
});

test("explains whether cancelling an active governance action spends energy", () => {
  assert.equal(typeof playerUi.governanceCancelMessage, "function");
  assert.equal(
    playerUi.governanceCancelMessage({ cost_status: "pending" }),
    "确认终止当前行动？尚未形成有效交流，不会消耗精力。",
  );
  assert.equal(
    playerUi.governanceCancelMessage({ cost_status: "committed" }),
    "确认终止当前行动？已经消耗的精力不会返还。",
  );
});

test("describes an unfinished governance action without claiming completion", () => {
  assert.equal(typeof playerUi.governanceFinishMessage, "function");
  assert.equal(
    playerUi.governanceFinishMessage({ cost_status: "pending" }),
    "本次行动未形成有效交流，未消耗精力，也未产生完成效果。",
  );
  assert.equal(
    playerUi.governanceFinishMessage({ cost_status: "committed" }),
    "本次行动已经收束，取得的材料已收入案头。",
  );
});

test("projects exactly the four canonical action families and keeps backend variants", () => {
  assert.equal(typeof playerUi.canonicalActionFamilies, "function");
  const projected = playerUi.canonicalActionFamilies([
    { action_id: "cadre_interview", name: "干部访谈", variants: [{ variant_id: "interview_cadre", target_choices: [{ target_id: "npc_a" }] }] },
    { action_id: "legacy_tool", name: "旧工具" },
    { action_id: "inspect_archives", name: "查阅档案", variants: [] },
    { action_id: "household_visit", name: "入户走访", variants: [{ variant_id: "field_visit", preselected_location_id: "loc_a" }] },
    { action_id: "leadership_meeting", name: "班子会议", variants: [{ variant_id: "public_hearing" }] },
  ]);
  assert.deepEqual(projected.map(item => item.action_id), [
    "household_visit", "cadre_interview", "leadership_meeting", "inspect_archives",
  ]);
  assert.equal(projected[0].variants[0].preselected_location_id, "loc_a");
  assert.equal(projected[1].variants[0].target_choices[0].target_id, "npc_a");
});

test("builds a safe people and revealed-relationship view without internal fields", () => {
  assert.equal(typeof playerUi.peopleRelationshipView, "function");
  const result = playerUi.peopleRelationshipView({
    people: [
      { npc_id: "mentioned", name: "卷宗人物", contact_state: "known", discovery_state: "mentioned", trust_band: "not_assessed", attitude_band: "not_assessed", anxiety_band: "not_assessed", relationship_reasons: { trust: "尚未直接接触", attitude: "尚未直接接触", anxiety: "尚未直接接触" }, recent_change_reasons: [] },
      { npc_id: "known", name: "甲", contact_state: "known", discovery_state: "encountered", trust_band: "working", attitude_band: "neutral", anxiety_band: "uneasy", relationship_reasons: { trust: "按公开履约记录判断", attitude: "尚未公开表态", anxiety: "仍担忧后续安置" }, recent_change_reasons: ["一", "二", "三", "四"], trust_score: 61, personality: { openness: 99 }, hidden_demands: ["秘密"] },
      { npc_id: "contact", name: "乙", contact_state: "contactable", discovery_state: "contactable", trust_band: "trusted", attitude_band: "supportive", anxiety_band: "calm", recent_change_reasons: [] },
      { npc_id: "unknown", name: "未知", contact_state: "unknown", trust_score: 50 },
    ],
    relationship_edges: [
      { edge_id: "shown", source_npc_id: "known", target_npc_id: "contact", visibility: "confirmed", channel: "同事", discovery_reason: "公开材料" },
      { edge_id: "suspected", source_npc_id: "known", target_npc_id: "contact", visibility: "suspected", channel: "同事", discovery_reason: "待进入线索" },
      { edge_id: "hidden", source_npc_id: "known", target_npc_id: "unknown", visibility: "hidden", private_audit: { prompt: "secret" } },
    ],
  });
  assert.deepEqual(result.people.map(item => [item.npc_id, item.discovery_state]), [["mentioned", "mentioned"], ["known", "encountered"], ["contact", "contactable"]]);
  assert.deepEqual(result.people[1].recent_change_reasons, ["一", "二", "三"]);
  assert.deepEqual(result.people[1].relationship_reasons, {
    trust: "按公开履约记录判断",
    attitude: "尚未公开表态",
    anxiety: "仍担忧后续安置",
  });
  assert.deepEqual(result.edges.map(item => item.edge_id), ["shown"]);
  const serialized = JSON.stringify(result);
  for (const forbidden of ["trust_score", "personality", "hidden_demands", "private_audit", "prompt", "unknown"]) {
    assert.doesNotMatch(serialized, new RegExp(forbidden));
  }
});

test("presents dossier mentions without pretending the player has met them", () => {
  assert.equal(typeof playerUi.personDiscoveryPresentation, "function");
  assert.deepEqual(playerUi.personDiscoveryPresentation({
    discovery_state: "mentioned",
    contact_state: "known",
  }), {
    statusLabel: "卷宗提及 · 尚未接触",
    showRelationship: false,
    allowProfile: false,
  });
  assert.deepEqual(playerUi.personDiscoveryPresentation({
    discovery_state: "contactable",
    contact_state: "contactable",
  }), {
    statusLabel: "当前可联系",
    showRelationship: true,
    allowProfile: true,
  });
});

test("renders relationship bands as useful qualitative Chinese labels", () => {
  assert.equal(typeof playerUi.qualitativeRelationshipLabel, "function");
  assert.equal(playerUi.qualitativeRelationshipLabel("working"), "可协作");
  assert.equal(playerUi.qualitativeRelationshipLabel("resistant"), "抵触");
  assert.equal(playerUi.qualitativeRelationshipLabel("worried"), "担忧");
  assert.equal(playerUi.qualitativeRelationshipLabel("not_assessed"), "尚待观察");
  assert.notEqual(playerUi.qualitativeRelationshipLabel("working"), "已记录");
});

test("consumes only player-safe archive sections and ignores raw structured content", () => {
  assert.equal(typeof playerUi.archivePlayerSections, "function");
  const sections = playerUi.archivePlayerSections({
    content: JSON.stringify({ title: "内部标题", key: "deadline", value: "90天", detail: "内部细节" }),
    private_audit: "SECRET_ROOT_AUDIT",
    prompt: "SECRET_PROMPT",
    debug_notes: { summary: "SECRET_DEBUG" },
    player_sections: [
      { heading: "期限", body: "90天，到期按真实状态验收。" },
      { heading: "财政授权", body: "当前可安排7800万元。" },
    ],
  });
  assert.deepEqual(sections, [
    { heading: "期限", body: "90天，到期按真实状态验收。" },
    { heading: "财政授权", body: "当前可安排7800万元。" },
  ]);
  const rendered = JSON.stringify(sections);
  for (const forbidden of ["内部标题", "deadline", "内部细节", '"key"', '"value"', '"detail"', "SECRET_ROOT_AUDIT", "SECRET_PROMPT", "SECRET_DEBUG"]) {
    assert.doesNotMatch(rendered, new RegExp(forbidden));
  }
});

test("preserves only the safe household layout hint for archive sections", () => {
  const sections = playerUi.archivePlayerSections({
    player_sections: [
      {
        heading: "1. 周大山（户号 ZDS-01）",
        body: "登记4人，安置4人。",
        kind: "household",
      },
      {
        heading: "审计说明",
        body: "这段仍按普通正文展示。",
        kind: "private_debug_layout",
      },
    ],
  });

  assert.deepEqual(sections, [
    {
      heading: "1. 周大山（户号 ZDS-01）",
      body: "登记4人，安置4人。",
      kind: "household",
    },
    {
      heading: "审计说明",
      body: "这段仍按普通正文展示。",
    },
  ]);
});

test("labels canonical and legacy conversation speakers for player review", () => {
  assert.equal(typeof playerUi.conversationSpeakerLabel, "function");
  assert.equal(playerUi.conversationSpeakerLabel({ speaker_type: "player" }, "吴秀英"), "你");
  assert.equal(playerUi.conversationSpeakerLabel({ speaker: "player" }, "吴秀英"), "你");
  assert.equal(playerUi.conversationSpeakerLabel({ speaker_type: "npc" }, "吴秀英"), "吴秀英");
});

test("uses authoritative budget-envelope labels while retaining IDs only as form values", () => {
  assert.equal(typeof playerUi.budgetEnvelopeChoices, "function");
  const choices = playerUi.budgetEnvelopeChoices({
    property_land: { label: "房屋与土地补偿", capacity: 3200, available: 2800 },
    risk_reserve: { label: "风险预备金", capacity: 500, available: 500 },
  });
  assert.deepEqual(choices.map(item => item.name), ["房屋与土地补偿", "风险预备金"]);
  assert.deepEqual(choices.map(item => item.envelope_id), ["property_land", "risk_reserve"]);
  assert.ok(choices.every(item => !item.name.includes(item.envelope_id)));
});

test("prevents overlapping confirmation submissions while preserving retries after failure", async () => {
  assert.equal(typeof playerUi.createSingleFlight, "function");
  let releases;
  let calls = 0;
  const submit = playerUi.createSingleFlight(async () => {
    calls += 1;
    await new Promise(resolve => { releases = resolve; });
    if (calls === 1) throw new Error("retryable");
    return "done";
  });
  const first = submit();
  const duplicate = submit();
  assert.strictEqual(first, duplicate);
  await Promise.resolve();
  releases();
  await assert.rejects(first, /retryable/);
  const retry = submit();
  await Promise.resolve();
  releases();
  assert.equal(await retry, "done");
  assert.equal(calls, 2);
});

test("contract batch tabs immediately reflect the authoritative open contract", () => {
  assert.equal(typeof playerUi.contractBatchTabs, "function");
  const staleOverview = [
    { contract_id: "contract-1", batch_id: "batch-a", household_id: "ZDS-01", status: "awaiting_terms" },
    { contract_id: "contract-2", batch_id: "batch-a", household_id: "ZDS-02", status: "awaiting_terms" },
  ];
  const signedDetail = {
    contract_id: "contract-1",
    batch_id: "batch-a",
    household_id: "ZDS-01",
    status: "signed",
    signed_hash: "sha256:signed",
  };
  assert.deepEqual(playerUi.contractBatchTabs(staleOverview, signedDetail), [
    { ...staleOverview[0], ...signedDetail },
    staleOverview[1],
  ]);
});

test("keeps player actions busy until every nested refresh scope finishes", async () => {
  assert.equal(typeof playerUi.createActivityLatch, "function");
  const busyStates = [];
  const activity = playerUi.createActivityLatch(value => busyStates.push(value));
  const releaseAction = activity.acquire();
  const releaseRefresh = activity.acquire();

  releaseRefresh();
  assert.deepEqual(busyStates, [true]);
  releaseAction();
  assert.deepEqual(busyStates, [true, false]);
});

test("routes people and map entries through the same canonical governance request", async () => {
  assert.equal(typeof playerUi.canonicalActionEntry, "function");
  assert.equal(typeof playerUi.submitGovernanceAction, "function");
  const descriptor = {
    action_id: "household_visit",
    variant_id: "field_visit",
    opportunity_id: "opp-d2-wu",
    participant_rules: { minimum: 1, maximum: 1 },
    location_choices: [{ location_id: "loc_village", label: "入村走访" }],
    target_choices: [{ target_id: "npc_household", label: "住户代表" }],
    canonical_topic: "听取吴秀英对搬迁安排的真实诉求",
  };
  const peopleEntry = playerUi.canonicalActionEntry({
    npc_id: "npc_household",
    canonical_action_descriptor: {
      ...descriptor,
      preselected_npc_ids: ["npc_household"],
      preselected_location_id: "loc_village",
    },
  });
  const mapEntry = playerUi.canonicalActionEntry({
    ...descriptor,
    preselected_npc_ids: ["npc_household"],
    preselected_location_id: "loc_village",
  });
  assert.deepEqual(peopleEntry, mapEntry);

  const calls = [];
  let release;
  const api = { write: (...args) => {
    calls.push(args);
    return new Promise(resolve => { release = () => resolve({ state_version: 8 }); });
  } };
  const submit = playerUi.createSingleFlight(() => playerUi.submitGovernanceAction(api, "session-1", {
    state_version: 7,
    descriptor: peopleEntry,
    location_id: "loc_tampered",
    target_ids: ["npc_tampered"],
    topic: "表单中的通用默认主题",
    archive_ids: ["archive_tampered"],
    proposed_document_type: "tampered_document",
    lead_npc_id: "npc_tampered",
  }));
  const first = submit();
  const doubleConfirm = submit();
  assert.strictEqual(first, doubleConfirm);
  await Promise.resolve();
  assert.equal(calls.length, 1);
  release();
  await first;
  const mapSubmit = playerUi.submitGovernanceAction(api, "session-1", {
    state_version: 7,
    descriptor: mapEntry,
    location_id: "loc_tampered_again",
    target_ids: ["npc_tampered_again"],
    topic: "另一个表单默认主题",
    archive_ids: ["archive_tampered_again"],
    proposed_document_type: "tampered_document",
    lead_npc_id: "npc_tampered_again",
  });
  await Promise.resolve();
  release();
  await mapSubmit;
  const canonicalRequest = ["session-1", "/governance/actions", "POST", {
    state_version: 7,
    action_kind: "household_visit",
    variant_id: "field_visit",
    location_id: "loc_village",
    opportunity_id: "opp-d2-wu",
    target_ids: ["npc_household"],
    topic: "听取吴秀英对搬迁安排的真实诉求",
    archive_ids: [],
    proposed_document_type: null,
    lead_npc_id: null,
  }];
  assert.deepEqual(calls, [canonicalRequest, canonicalRequest]);
});

test("locks every map-launched action to its authoritative location", async () => {
  assert.equal(typeof playerUi.governanceLocationLocked, "function");
  assert.equal(playerUi.governanceLocationLocked({ location_locked: true }), true);
  assert.equal(playerUi.governanceLocationLocked({ opportunity_id: "opp-1" }), true);
  assert.equal(playerUi.governanceLocationLocked({ variant_id: "field_visit" }), false);
  assert.equal(
    playerUi.governanceLocationLockMessage({ location_locked: true }),
    "地图入口已锁定本次办理地点。",
  );
  assert.equal(
    playerUi.governanceLocationLockMessage({ opportunity_id: "opp-1" }),
    "人物会谈机会已锁定本次办理地点。",
  );
  assert.equal(playerUi.governanceLocationLockMessage({ variant_id: "field_visit" }), "");
  assert.equal(
    playerUi.governanceActionTitle(
      { display_title: "化工厂现场核查", action_kind: "household_visit" },
      "入户走访",
    ),
    "化工厂现场核查",
  );
  assert.deepEqual(
    playerUi.governanceActionProgressLabels(
      { display_title: "化工厂现场核查" },
      "入户走访",
    ),
    {
      footer: "化工厂现场核查进行中",
      task: "完成正在进行的化工厂现场核查",
    },
  );
  const entry = playerUi.canonicalActionEntry({
    action_id: "household_visit",
    variant_id: "field_visit",
    map_entry_id: "map:loc_hongda_factory:field_visit",
    location_locked: true,
    preselected_location_id: "loc_hongda_factory",
    preselected_npc_ids: [],
    participant_rules: { minimum: 1, maximum: 1 },
    location_choices: [
      { location_id: "loc_liulin_village", label: "入村走访" },
      { location_id: "loc_hongda_factory", label: "化工厂现场核查" },
    ],
    target_choices: [{ target_id: "npc_household", label: "住户代表" }],
  });
  assert.equal(entry.location_locked, true);
  assert.equal(entry.map_entry_id, "map:loc_hongda_factory:field_visit");

  const calls = [];
  const api = { write: (...args) => { calls.push(args); return Promise.resolve({}); } };
  await playerUi.submitGovernanceAction(api, "session-map", {
    state_version: 11,
    descriptor: entry,
    location_id: "loc_liulin_village",
    target_ids: ["npc_household"],
    topic: "核查化工厂周边的搬迁与环境情况",
    archive_ids: [],
    proposed_document_type: null,
    lead_npc_id: null,
  });
  assert.deepEqual(calls[0][3], {
    state_version: 11,
    action_kind: "household_visit",
    variant_id: "field_visit",
    location_id: "loc_hongda_factory",
    map_entry_id: "map:loc_hongda_factory:field_visit",
    opportunity_id: null,
    target_ids: ["npc_household"],
    topic: "核查化工厂周边的搬迁与环境情况",
    archive_ids: [],
    proposed_document_type: null,
    lead_npc_id: null,
  });
});

test("gives governance variants distinct player-facing titles and actions", () => {
  assert.equal(typeof playerUi.governanceDisplayTitle, "function");
  assert.equal(typeof playerUi.governanceActionButtonLabel, "function");
  assert.equal(
    playerUi.governanceDisplayTitle({ action_id: "cadre_interview", variant_id: "interview_enterprise", target_ids: ["npc_qian_wei"] }, "干部访谈"),
    "约谈钱伟",
  );
  assert.equal(
    playerUi.governanceDisplayTitle({ action_id: "cadre_interview", variant_id: "contact_media" }, "干部访谈"),
    "媒体沟通",
  );
  assert.equal(
    playerUi.governanceDisplayTitle({ action_id: "household_visit", variant_id: "field_visit", map_entry_id: "map:factory", title: "化工厂现场核查" }, "入户走访"),
    "化工厂现场核查",
  );
  assert.equal(playerUi.governanceDisplayTitle({ action_id: "cadre_interview" }, "干部访谈"), "政务沟通");
  assert.equal(playerUi.governanceActionButtonLabel({ action_id: "inspect_archives" }), "开始查阅");
  assert.equal(playerUi.governanceActionButtonLabel({ action_id: "cadre_interview", variant_id: "interview_enterprise" }), "开始约谈");
  assert.equal(playerUi.governanceActionButtonLabel({ action_id: "household_visit" }), "开始走访");
});

test("merges committed and streaming governance replies without losing speakers or duplicating a turn", () => {
  assert.equal(typeof playerUi.mergeGovernanceTimeline, "function");
  const committed = [
    { speaker_type: "player", conversation_id: "action-1", turn_id: "turn-1", text: "请说明诉求" },
    { speaker_type: "npc", npc_id: "npc-a", npc_name: "甲", conversation_id: "action-1", turn_id: "turn-1", text: "我要一份书面答复" },
    { speaker_type: "npc", npc_id: "npc-b", npc_name: "乙", conversation_id: "action-1", turn_id: "turn-1", text: "我也要一份书面答复" },
  ];
  const result = playerUi.mergeGovernanceTimeline(committed, [
    { stream_id: "npc:0", npc_id: "npc-a", npc_name: "甲", conversation_id: "action-1", turn_id: "turn-1", text: "我要一份书面答复", complete: true },
    { stream_id: "npc:1", npc_id: "npc-c", npc_name: "丙", conversation_id: "action-1", turn_id: "turn-2", text: "我会补充材料", complete: false },
  ]);
  assert.equal(result.length, 4);
  assert.equal(result.filter(item => item.npc_id === "npc-a").length, 1);
  assert.equal(result.find(item => item.npc_id === "npc-a")?.live, false);
  assert.equal(result.find(item => item.npc_id === "npc-c")?.live, true);

  const sameText = playerUi.mergeGovernanceTimeline(
    [{ speaker_type: "npc", npc_id: "npc-a", text: "共同答复" }],
    [{ stream_id: "npc:0", npc_id: "npc-a", text: "共同答复", complete: true }],
  );
  assert.equal(sameText.length, 1);
});

test("keeps the multi-NPC governance surface and ordinary action location read-only", async () => {
  const source = await readFile(path.join(projectRoot, "app", "GameShell.tsx"), "utf8");
  assert.match(source, /mergeGovernanceTimeline\(transcript, streamingReplies\)/);
  assert.match(source, /className="governance-action-timeline"/);
  assert.match(source, /className="new-dialogue-button governance-new-dialogue"/);
  assert.match(source, /className="archive-unread-status"/);
  assert.match(source, /requiredOpportunityPending/);
  const form = source.slice(source.indexOf("function GovernanceActionForm"), source.indexOf("function Empty", source.indexOf("function GovernanceActionForm")));
  assert.match(form, /className="action-location-readonly"/);
  assert.doesNotMatch(form, /governanceLocationLocked\(item\)/);
});

test("selects exactly one dedicated primary scene for an active leadership meeting", () => {
  assert.equal(typeof playerUi.primaryScenePlan, "function");
  assert.deepEqual(playerUi.primaryScenePlan({
    has_session: true,
    active_governance_action: { action_kind: "leadership_meeting" },
    active_meeting: { meeting_id: "meeting-1" },
    active_group_conversation: null,
    active_conversation: null,
  }), ["leadership_meeting"]);
  assert.deepEqual(playerUi.primaryScenePlan({
    has_session: true,
    active_governance_action: null,
    active_meeting: null,
    active_group_conversation: null,
    active_conversation: { conversation_id: "conversation-1" },
  }), ["conversation"]);
});

test("routes retired sessions to review and never offers continue", () => {
  assert.equal(typeof playerUi.sessionEntry, "function");
  assert.deepEqual(playerUi.sessionEntry({ session_id: "old", package_status: "retired", loadable: false }), {
    session_id: "old", mode: "review", label: "仅可复盘", canContinue: false, openKind: "review", unavailableReason: "",
  });
  assert.deepEqual(playerUi.sessionEntry({ session_id: "v3", package_status: "published", loadable: true }), {
    session_id: "v3", mode: "continue", label: "继续游戏", canContinue: true, openKind: "load", unavailableReason: "",
  });
});

test("keeps unavailable content disabled and never maps it to a review request", () => {
  assert.deepEqual(playerUi.sessionEntry({
    session_id: "mismatch",
    mode: "content_unavailable",
    content_available: false,
    review_available: false,
    loadable: false,
    unavailable_reason: "该进度锁定的剧本内容已不在当前版本中，暂时无法打开。",
  }), {
    session_id: "mismatch",
    mode: "unavailable",
    label: "内容不可用",
    canContinue: false,
    openKind: null,
    unavailableReason: "该进度锁定的剧本内容已不在当前版本中，暂时无法打开。",
  });
});

test("keeps the visible conversation loop and removes the old terminal surface", async () => {
  const source = await readFile(path.join(projectRoot, "app", "GameShell.tsx"), "utf8");
  assert.match(source, />结束会谈</);
  assert.match(source, /input_mode: "conversation_end"/);
  assert.match(source, /"active-conversation-character"/);
  assert.match(source, /data-testid="active-conversation-compact"/);
  assert.match(source, /currentLine\?\.kind === "conversation_opening"/);
  assert.match(source, /currentLine\?\.speaker \? lineCharacter/);
  assert.match(source, /"gal-stage conversation-mode"/);
  assert.match(source, /className="conversation-bar gal-conversation-bar"/);
  assert.match(source, /compactCharacter\?\.role/);
  assert.match(source, /actionPointLabel\(item\)/);
  // Manual snapshot controls were removed at the player's request.
  assert.match(source, /refresh\(0, id, true, true, kind === "load" \? "latest" : "start"\)/);
  assert.match(source, /decisionReady && pending/);
  assert.match(source, /disabled=\{narrative\.currentIndex >= playerLines\.length - 1\}>下一段/);
  assert.match(source, /visibleHistoryLines\.map/);
  assert.match(source, />自定义会议主题</);
  assert.match(source, /meetingTopicMode === "custom"/);
  assert.match(source, /topic: isArchive \? "" : effectiveTopic/);
  assert.match(source, /apiError\?\.code === "STATE_VERSION_CONFLICT"/);
  assert.match(source, /required_countersign_ids/);
  assert.match(source, /chooseDocumentType/);
  assert.match(source, /会议依据（至少达到 \{requiredEvidenceLevel\}）/);
  assert.match(source, /archive_ids: isArchive \|\| \(isMeeting && Boolean\(documentType\)\) \? selectedArchives : \[\]/);
  assert.match(source, /已有一项治理行动正在进行，已为你切换到当前现场/);
  assert.match(source, /setMeetingResolutionOpen\(true\)/);
  assert.match(source, /data-testid="meeting-resolution-form"/);
  assert.match(source, /末位表态并形成决定/);
  assert.match(source, /指定分管或牵头领导/);
  assert.match(source, /lead_npc_id: requiresLead \? leadNpcId : null/);
  const { actionPresentation } = await import("../app/lib/action-presentation.ts");
  assert.match(actionPresentation({ variant_id: "convene_leadership_meeting" }).participantHelp, /领导干部/);
  assert.doesNotMatch(actionPresentation({ variant_id: "public_hearing" }).participantHelp, /只有领导|普通干部、村民和外部人员不能/);
  assert.match(source, /resource_mode: "authorization_ceiling"/);
  assert.match(source, /governance-inline-notice/);
  assert.match(source, /api\.archiveDetail\(sessionId, archiveId\)/);
  assert.match(source, /function ArchiveReading/);
  assert.match(source, /档案正文已经调出并记录查阅/);
  assert.match(source, /重读正文/);
  assert.match(source, /function clearAuthenticatedClientState\(\)/);
  assert.match(source, /if \(!restoredCsrf\) \{[\s\S]*?setAuthError\(""\)[\s\S]*?\} else \{/);
  assert.match(source, /const me = await api\.me\(\)/);
  assert.match(source, /if \(\(error as ApiError\)\?\.status !== 401\)/);
  assert.match(source, /clearAuthenticatedClientState\(\);[\s\S]*setAuthOpen\(true\)/);
  assert.match(source, /function GovernanceRecordDetail/);
  assert.equal(actionPresentation({ variant_id: "convene_leadership_meeting" }).result, "会议纪要");
  assert.equal(actionPresentation({ variant_id: "public_hearing" }).result, "听证记录");
  assert.equal(actionPresentation({ variant_id: "clan_leader_campaign" }).result, "议事记录");
  assert.match(source, /文书 Agent 审校/);
  assert.match(source, /自动修订记录/);
  assert.match(source, /文书审校通过后才能会签/);
  assert.match(source, /\["形成文本", "文书审校", "完成会签", "正式印发", "对外公示"\]/);
  assert.match(source, /\/countersign/);
  assert.match(source, /\/issue/);
  assert.match(source, /\/publish/);
  assert.doesNotMatch(source, /function NightConversationViewer/);
  assert.doesNotMatch(source, /agent_exchanges/);
  assert.match(source, /九十日治理周期已结束/);
  assert.match(source, /查看结局复盘/);
  assert.match(source, /治理周期完成/);
  assert.match(source, /私下联络仅汇入次晨简报/);
  assert.match(source, /function NpcStreamingReplies/);
  assert.match(source, /performNpcStream/);
  assert.match(source, /\/action\/stream/);
  assert.match(source, /group-conversation\/turn\/stream/);
  assert.equal((source.match(/new FormData\(event\.currentTarget as HTMLFormElement\)/g) || []).length, 2);
  assert.match(source, /name="player_text"/);
  assert.match(source, /data-state-version=\{state\.state_version\}/);
  assert.match(source, /governance\/meetings\/\$\{encodeURIComponent[\s\S]*\/turn\/stream/);
  assert.match(source, /governance\/actions\/\$\{encodeURIComponent[\s\S]*\/turn\/stream/);
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /item\.unavailable_reason/);
  assert.match(source, /: "填写方案"/);
  assert.doesNotMatch(source, />WORKSPACE</);
  assert.doesNotMatch(source, /state v\{/);
  assert.doesNotMatch(source, /\[ERR\]/);
  assert.doesNotMatch(source, /placeholder=.*输入命令/);
  assert.doesNotMatch(source, /aria-label="终端命令"/);
  assert.doesNotMatch(source, /item\.glyph/);
  assert.doesNotMatch(source, /<small>卷宗 \{chineseIndex\(index\)\}<\/small>/);
  const images = source.split("\n").filter(line => line.includes("<Image"));
  assert.equal(images.length, 2);
  for (const image of images) {
    assert.match(image, /\bunoptimized\b/);
    assert.match(image, /\balt=/);
    assert.match(image, /\bsizes=/);
  }
  const portraitImage = images.find(line => line.includes('className="character-portrait"'));
  const sceneImage = images.find(line => line.includes('className="scene-backdrop"'));
  assert.match(portraitImage || "", /style=\{\{ objectFit: "contain", objectPosition: "center bottom" \}\}/);
  assert.doesNotMatch(sceneImage || "", /objectFit: "contain"/);
});

test("reads the private backend address from the Cloudflare runtime binding", async () => {
  const source = await readFile(path.join(projectRoot, "app", "api", "backend", "[...path]", "route.ts"), "utf8");
  assert.match(source, /await import\("cloudflare:workers"\)/);
  assert.match(source, /runtimeUrl \|\| process\.env\.GAME_BACKEND_URL \|\| "http:\/\/127\.0\.0\.1:8100"/);
  assert.doesNotMatch(source, /NEXT_PUBLIC_GAME_BACKEND_URL/);
});

test("keeps narrow-screen auxiliary controls touch friendly without a manual refresh button", async () => {
  const source = await readFile(path.join(projectRoot, "app", "GameShell.tsx"), "utf8");
  const styles = await readFile(path.join(projectRoot, "app", "globals.css"), "utf8");
  assert.doesNotMatch(source, /className="refresh-button"/);
  assert.match(styles, /\.history-toggle/);
  assert.match(styles, /\.icon-button/);
});

test("uses the warm archival palette without the former green shell", async () => {
  const styles = await readFile(path.join(projectRoot, "app", "globals.css"), "utf8");
  const retiredGreenTokens = [
    "#10130f", "#161a17", "#20251f", "#2b3028", "#23261f",
    "#242821", "#1a1e19", "#34362d", "#292d27", "#171b17",
    "#607c50", "#8fac70", "--green",
  ];
  for (const token of retiredGreenTokens) assert.doesNotMatch(styles, new RegExp(token));
  assert.match(styles, /--charcoal: #1c1812/);
  assert.match(styles, /\.metric-strip \{[\s\S]*?background: #2a231a/);
  assert.match(styles, /\.context-panel \{[\s\S]*?background: var\(--paper-deep\)/);
  assert.match(styles, /\.context-panel \{[\s\S]*?background: #e3d1aa/);
  assert.match(styles, /\.panel-body \{ background: #e3d1aa/);
  assert.match(styles, /\.modal-backdrop \{[^}]*background: rgba\(18,13,8,\.72\);[^}]*backdrop-filter: none/);
  assert.match(styles, /\.night-stage-shade \{[^}]*background: rgba\(16,13,10,\.24\)/);
  assert.match(styles, /\.character-profile-stage::after \{ content: none; display: none; \}/);
  assert.match(styles, /\.scene-backdrop \{ animation: scene-enter \.18s ease-out; \}/);
});

test("decorative scene backdrops never intercept player controls", async () => {
  const styles = await readFile(path.join(projectRoot, "app", "globals.css"), "utf8");
  assert.match(styles, /\.scene-backdrop\s*\{[^}]*pointer-events:\s*none/s);
});

test("decision choices retain scroll clearance below the story heading", async () => {
  const styles = await readFile(path.join(projectRoot, "app", "globals.css"), "utf8");
  assert.match(styles, /\.decision-option\s*>\s*button\s*\{[^}]*scroll-margin-block:\s*76px\s+24px/s);
});

test("renders decisions in a document-flow stage instead of overflowing behind the story heading", async () => {
  const [source, styles] = await Promise.all([
    readFile(path.join(projectRoot, "app", "GameShell.tsx"), "utf8"),
    readFile(path.join(projectRoot, "app", "globals.css"), "utf8"),
  ]);
  assert.match(source, /decisionReady \? "gal-stage decision-mode"/);
  assert.match(styles, /\.gal-stage\.decision-mode\s*\{[^}]*display:\s*block;[^}]*height:\s*auto/s);
  assert.match(styles, /\.story-scroll\s*>\s*\.gal-stage\.decision-mode\s*\{[^}]*height:\s*auto/s);
});

test("does not open game entry while account and AI configuration restoration is still busy", async () => {
  const source = await readFile(path.join(projectRoot, "app", "GameShell.tsx"), "utf8");
  assert.match(source, /<button onClick=\{openGameEntry\} disabled=\{busy\}>\{sessionId/);
  assert.match(source, /className="welcome-action"><button onClick=\{openGameEntry\} disabled=\{busy\}>/);
});

test("exposes stable non-secret action and target identifiers for full browser acceptance", async () => {
  const source = await readFile(path.join(projectRoot, "app", "GameShell.tsx"), "utf8");
  assert.match(source, /data-action-id=\{String\(item\.action_id \|\| ""\)\}/);
  assert.match(source, /data-variant-id=\{String\(variant\.variant_id \|\| ""\)\}/);
  assert.match(source, /data-target-id=\{value\}/);
});

test("uses the authoritative Yunxi county name throughout the player shell", async () => {
  const source = await readFile(path.join(projectRoot, "app", "GameShell.tsx"), "utf8");
  assert.doesNotMatch(source, /清江县/);
  assert.match(source, /<small>云溪县政府<\/small>/);
  assert.match(source, /<small>云溪县政府 · 案头<\/small>/);
  assert.match(source, /<Modal title="进入云溪县"/);
});

test("refreshes the active side panel after every successful player write", async () => {
  const source = await readFile(path.join(projectRoot, "app", "GameShell.tsx"), "utf8");
  assert.match(source, /if \(panel !== "scene"\) \{\s*setPanel\(panel\);\s*setPanelData\(await api\.panel\(sessionId, panel\)\);/);
});

test("hides the retired day-four fatigue exposition from existing saves", async () => {
  const source = await readFile(path.join(projectRoot, "app", "GameShell.tsx"), "utf8");
  const storyBeats = await readFile(path.join(projectRoot, "..", "..", "backend", "content", "packages", "pkg_gameplay_v2", "story_beats.json"), "utf8");
  assert.match(source, /line\.blockId === "d04_source_opening"/);
  assert.doesNotMatch(storyBeats, /再补一条口径，免得和各章那句“连续满负荷降点”对不上/);
});
