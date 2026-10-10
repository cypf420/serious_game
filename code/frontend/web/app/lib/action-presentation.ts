type Action = Record<string, unknown> | null | undefined;

// Presentation follows the concrete variant; action_id only selects the API protocol.
const variants: Record<string, { title: string; noun: string; participants: string; topic: string; prompt: string; start: string; finish: string; result: string }> = {
  contract_negotiation: { title: "签约协商", noun: "协商", participants: "住户或代表", topic: "本次协商重点", prompt: "了解本户诉求，核对已保存合同与尚待办理事项", start: "开始协商", finish: "结束协商", result: "签约协商记录" },
  field_visit: { title: "现场走访", noun: "走访", participants: "走访对象", topic: "本次走访重点", prompt: "了解现场情况、对象诉求与需要核实的问题", start: "开始走访", finish: "结束走访", result: "走访记录" },
  interview_cadre: { title: "干部约谈", noun: "约谈", participants: "约谈干部", topic: "本次约谈重点", prompt: "核实职责、工作进展、现有材料与程序风险", start: "开始约谈", finish: "结束约谈", result: "约谈记录" },
  interview_enterprise: { title: "企业约谈", noun: "约谈", participants: "企业对象", topic: "企业约谈重点", prompt: "核实项目履约、资金安排与环境责任", start: "开始约谈", finish: "结束约谈", result: "企业约谈记录" },
  contact_media: { title: "媒体沟通", noun: "沟通", participants: "媒体沟通对象", topic: "本次沟通事项", prompt: "核对公开口径、材料来源与采访边界，区分事实与待核信息", start: "开始沟通", finish: "结束沟通", result: "媒体沟通记录" },
  convene_leadership_meeting: { title: "班子会议", noun: "会议", participants: "参会领导", topic: "本次会议要解决什么", prompt: "讨论议题、责任分工与执行安排", start: "发起会议", finish: "形成会议决议", result: "会议纪要" },
  public_hearing: { title: "公开听证", noun: "听证", participants: "听证参与人", topic: "本次听证议题", prompt: "明确争议事项，听取参与人意见并核对事实", start: "发起听证", finish: "形成听证结论", result: "听证记录" },
  clan_leader_campaign: { title: "宗族议事", noun: "议事", participants: "议事参与人", topic: "本次议事议题", prompt: "围绕宗族相关事项开展协商，明确意见与后续安排", start: "发起议事", finish: "形成议事结论", result: "议事记录" },
  consult_county_archives: { title: "查阅县级档案", noun: "查阅", participants: "待查阅档案", topic: "查阅材料", prompt: "选择一份当前可查阅的县级档案", start: "开始查阅", finish: "查看查阅结果", result: "查阅记录" },
  collect_blood_lead_report: { title: "调取血铅材料", noun: "调取", participants: "待调取材料", topic: "调取材料", prompt: "选择一份符合当前授权条件的医院材料", start: "调取材料", finish: "查看调取结果", result: "材料调取记录" },
};
const legacyVariants: Record<string, string> = {
  household_visit: "field_visit", cadre_interview: "interview_cadre", leadership_meeting: "convene_leadership_meeting", inspect_archives: "consult_county_archives",
};

export function actionPresentation(action: Action) {
  const actionId = String(action?.action_id || action?.action_kind || "");
  const variantId = String(action?.variant_id || legacyVariants[actionId] || "");
  const copy = variants[variantId] || { title: "治理行动", noun: "行动", participants: "参与对象", topic: "本次重点", prompt: "核对当前行动要求", start: "开始行动", finish: "结束行动", result: "行动记录" };
  const collective = actionId === "leadership_meeting" || ["convene_leadership_meeting", "public_hearing", "clan_leader_campaign"].includes(variantId);
  const leadership = collective && variantId === "convene_leadership_meeting";
  return {
    ...copy, collective, leadership,
    conclusion: leadership ? "会议决议" : collective ? `${copy.noun}结论` : copy.result,
    participantHelp: leadership ? "这里只列出当前已公开且符合参会条件的领导干部。"
      : variantId === "public_hearing" ? "这里只列出当前听证允许参与且已公开的人物，以本次名单为准。"
      : variantId === "clan_leader_campaign" ? "这里只列出当前议事允许参与的宗族相关人物，以本次名单为准。"
      : "只可选择当前行动允许且已公开的对象。",
    discussionLabel: leadership ? "向班子成员说明你的意见" : collective ? `向${copy.participants}说明你的意见` : copy.topic,
  };
}

export function participantCountLabel(minimum: number, maximum: number): string {
  return minimum === maximum ? `选择 ${minimum} 人` : `选择 ${minimum} 至 ${maximum} 人`;
}

export function meetingAction(meeting: Action, governance: Action): Record<string, unknown> {
  const actions = Array.isArray(governance?.governance_actions) ? governance.governance_actions : [];
  return actions.find(action => action.action_instance_id === meeting?.action_instance_id) || { action_kind: "leadership_meeting", ...meeting };
}
