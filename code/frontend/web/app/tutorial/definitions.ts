import { actionPointLabel } from "../lib/player-ui.ts";
import { actionPresentation } from "../lib/action-presentation.ts";
import type { TutorialDefinition, TutorialRecord, TutorialStep } from "./types.ts";

const target = (id: string) => `[data-tutorial-id="${id}"]`;
const text = (value: unknown, fallback = "") => typeof value === "string" && value.trim() ? value.trim() : fallback;
const records = (value: unknown): TutorialRecord[] => Array.isArray(value)
  ? value.filter((item): item is TutorialRecord => Boolean(item) && typeof item === "object" && !Array.isArray(item))
  : [];

export const QUICK_START = [
  { title: "阅读并决定", body: "先读当前叙事，处理需要你决定的事项。" },
  { title: "安排工作与会谈", body: "从行动安排工作，或从人物进入会谈。推进签约需另行逐户办理，剧情不会自动完成签约。" },
  { title: "结束今天", body: "读完当前剧情并处理必须完成的事项后，自行结束一天，查看随后发生的事件与工作结果。" },
];

export const BASIC_TUTORIAL: TutorialDefinition = {
  id: "basic", revision: 5, title: "认识工作台",
  steps: [
    { id: "play-at-your-pace", title: "行动、剧情与存档", body: "自由行动与剧情决策相对独立。行动开放时，可以先自由行动再推进剧情，也可以完成剧情决策后再自由行动；必须当场处理的决定，请按现场提示完成。游戏进度会随每次行动与决定自动保存，无需手动保存。", target: target("today") },
    { id: "today", title: "今日案头", body: "这里汇总今日目标与现场情况。结合当前叙事和必须处理的事项，安排今天的工作。", target: target("today") },
    { id: "metrics", title: "日期、阶段与精力", body: "日期、阶段和各项指标反映当前局面。精力决定今天还能安排多少工作；以当前显示的消耗为准。", detail: "资源余额可用于兑换通晓币。通晓币不用于人物会谈或本局行动消耗，将用于后续“百晓生”网站兑换；开放时间、兑换范围和具体规则以百晓生网站公告为准。", target: target("metrics") },
    { id: "narrative-controls", title: "阅读与推进", body: "使用这里的阅读控制查看叙事。读完当前剧情并处理必须完成的事项后，才能结束今日；出现现场决定时先完成选择。", target: target("narrative-controls") },
    { id: "nav-actions", title: "行动：安排工作", body: "这里按办理方式列出当前公开的行动。每张卡片会说明用途、精力消耗和不可用原因；选择要办理的行动后，核对对象与条件，再由你确认发起。", target: target("nav-actions") },
    { id: "nav-opportunities", title: "人物：了解与会谈", body: "这里列出已公开的人物与当前会谈入口。先了解人物状态与说明，再选择当前可以进入的会谈。", target: target("nav-opportunities") },
    { id: "advance-signing", title: "主动推进签约", body: "推进签约是独立于剧情阅读和决策的自由行动，剧情推进不会自动完成签约。最终实际签约数直接影响结局，但不是唯一判定因素。", detail: "可以向代表询问其所代表的各户需求，例如向吴秀英询问本批次其他住户的情况。代表始终以本人身份交流，不扮演其他住户，也不能代签。会谈后准备逐户合同，每户接受并签署后才计入进度并结算本户资源。打开入口不会直接签约或扣除资源，会谈消耗以当前提示为准。", target: target("advance-signing") },
    { id: "nav-desk", title: "卷宗与线索", body: "卷宗页查看任务与政策；线索页整理事实与调查途径。治理页的档案统一查看已取得材料、会议听证记录和公文。", detail: "对话中输入 @ 选择允许引用的档案，核对名称与状态后随发言发送。NPC 会收到所选材料的正文、版本和状态。引用不会替你查档或完成行动。听证通知表示已安排，形成的听证记录才说明实际办理结果。合同仍只能应用会议形成且符合条件的红头文件。", target: target("nav-desk") },
  ],
};

type ActionCopy = { title: string; purpose: string; when: string; how: string; result: string };

export const ACTION_COPY: Record<string, ActionCopy> = {
  field_visit: { title: "现场走访", purpose: "进入现场，了解当事人的诉求与具体情况。", when: "需要核实现场情况、听取走访对象意见时。", how: "核对地点，选择当前可见的走访对象，写明重点后发起行动。", result: "形成现场走访记录和待办事项。" },
  interview_cadre: { title: "干部约谈", purpose: "向干部核实负责事项、现有材料和程序风险。", when: "需要明确责任分工或补充材料说明时。", how: "核对固定地点并选择可约谈干部，写明要核实的问题，再进入访谈。", result: "形成干部访谈记录和待核材料清单。" },
  interview_enterprise: { title: "企业约谈", purpose: "与企业负责人沟通项目履约、资金和环境责任。", when: "需要核实企业的说明与待办责任时。", how: "从当前企业对象中选择参与者，写明具体问题后发起约谈。", result: "形成企业约谈记录和待核事项。" },
  contact_media: { title: "媒体沟通", purpose: "核对公开口径、材料来源和采访边界。", when: "需要向当前可联系的媒体对象核实公开材料时。", how: "选择公开的媒体联系人并核对固定地点，明确沟通重点后发起。", result: "形成媒体沟通记录和公开材料核对清单。" },
  convene_leadership_meeting: { title: "班子会议", purpose: "围绕明确议题组织领导讨论并形成决议。", when: "需要集体讨论方案、分工或拟形成文件时。", how: "确定议题、参会人员和主要汇报人；如拟形成文件，再核对必要会签人与已读依据。", result: "形成会议记录及依法通过的决议或文件。" },
  public_hearing: { title: "公开听证", purpose: "围绕议题听取参与者意见并记录程序性结论。", when: "需要组织当前可参与对象进行公开讨论时。", how: "确定具体争议事项和相关参与人，核对表单后发起；讨论后形成结论。", result: "形成公开听证记录和程序性结论。发起或引用通知不等于完成听证，也不代替法审及其他处理。" },
  clan_leader_campaign: { title: "宗族议事", purpose: "就当前议题组织宗族相关人物讨论。", when: "该方式已开放，且需要听取相关人物意见时。", how: "选择当前允许的参与者，确定议题，核对方案后发起议事。", result: "形成宗族议事记录和后续事项。" },
  consult_county_archives: { title: "查阅县级档案", purpose: "阅读当前可调阅档案，核对事实与材料依据。", when: "需要补足书面依据或核实线索时。", how: "从当前未读档案中选择一份，核对首次查阅消耗后自行开始查阅。", result: "登记调阅并展示档案；新增事实和用途可在线索页回看，已读档案可在治理页免费重读。" },
  collect_blood_lead_report: { title: "调取血铅材料", purpose: "调阅符合当前授权条件的医院材料。", when: "该方式已开放，且需要核实相关书面材料时。", how: "查看当前允许调取的档案，选择一份并核对消耗后自行查阅。", result: "取得并登记符合授权条件的医院材料。" },
};

function costDetail(item: TutorialRecord): string {
  const budget = Number(item.direct_budget_cost);
  const resources = records(item.resource_costs).flatMap(cost => {
    const label = text(cost.label, text(cost.name, text(cost.resource_id)));
    const amount = Number(cost.amount ?? cost.quantity ?? cost.cost);
    return label && Number.isFinite(amount) && amount > 0 ? [`${label} ${amount}${text(cost.unit)}`] : [];
  });
  return [actionPointLabel(item), ...(Number.isFinite(budget) && budget > 0 ? [`预算 ${budget} 万元`] : []), ...resources].join("；");
}

export function actionTutorial(item: TutorialRecord): TutorialDefinition {
  const variantId = text(item.variant_id);
  const copy = ACTION_COPY[variantId];
  const title = text(item.name, copy?.title || "当前办理方式");
  const unavailable = item.available === false;
  const escapedId = variantId.replace(/[\\"\n\r\f]/g, char => `\\${char.charCodeAt(0).toString(16)} `);
  const detail = unavailable
    ? `当前不可用：${text(item.unavailable_reason, "当前条件尚未满足")}。`
    : [`用途：${copy?.purpose || text(item.description, "请查看当前行动说明。")}`, `适用时机：${copy?.when || "以当前公开条件为准。"}`, `操作：${copy?.how || "核对当前表单要求后自行办理。"}`, `当前消耗：${costDetail(item)}。`, `办理结果：${text(item.visible_result, copy?.result || "以实际办理结果为准。")}`].join("\n");
  return {
    id: `action:${variantId}`, revision: 1, title,
    steps: [{ id: `action:${variantId}`, title, body: unavailable ? "此办理方式当前不能发起。" : copy?.purpose || text(item.description, "先查看当前公开说明。"), detail, target: `.canonical-actions [data-variant-id="${escapedId}"]` }],
  };
}

export function actionTour(items: TutorialRecord[]): TutorialDefinition {
  const seen = new Set<string>();
  const steps = items.flatMap(item => Array.isArray(item.variants)
    ? records(item.variants).map(variant => ({ ...item, ...variant }))
    : [item]).flatMap(item => {
    const id = text(item.variant_id);
    if (!id || seen.has(id) || item.available !== true || item.hidden === true || item.visibility === "hidden") return [];
    seen.add(id);
    return actionTutorial(item).steps;
  });
  return { id: "actions", revision: 1, title: "认识当前可用行动", steps };
}

export function formTutorial(item: TutorialRecord): TutorialDefinition {
  const variantId = text(item.variant_id);
  const isArchive = item.action_id === "inspect_archives";
  const isMeeting = actionPresentation(item).leadership;
  const steps: TutorialStep[] = [];
  const topicHelp: Record<string, string> = {
    field_visit: "写明本次要了解的现场情况与对象诉求。固定机会的重点可能已锁定，请核对页面说明。",
    interview_cadre: "写明需要核实的职责、工作进展、材料或程序问题。进入约谈后可针对回应继续追问。",
    interview_enterprise: "写明项目履约、资金或环境责任中的具体问题。进入约谈后，继续核实企业回应与待办责任。",
    contact_media: "明确要沟通的公开事项、材料来源和采访边界。将已核实事实与尚待核实的信息分开表述。",
    public_hearing: "写明本次听证要讨论的争议事项。参与对象和办理要求以当前表单为准。",
    clan_leader_campaign: "写明本次协商事项与需要了解的问题。发起后阅读各方意见，再核对记录与后续事项。",
  };
  const input = (id: string, title: string, body: string) => steps.push({ id, title, body, target: target(id), optional: true, interactive: true });
  if (records(item.location_choices).length > 1) input("form-location", "核对办理地点", "办理地点由当前行动或剧情机会确定，在此核对即可，无需选择。");
  if (!isArchive) {
    input("form-topic", isMeeting ? "明确会议议题" : "写明本次重点", isMeeting ? "选择预设议题或填写具体问题。会议讨论与最终决议将围绕这个议题展开。" : topicHelp[variantId] || "写下希望了解或核实的具体问题。固定机会的主题可能只读，以当前说明为准。");
    input("form-targets", "选择当前可参与对象", "按页面提示的人数范围选择对象。所选对象会参与本次行动；已锁定的对象按当前说明办理。是否满足要求，以表单校验为准。");
  }
  if (isMeeting && variantId === "convene_leadership_meeting") input("form-lead", "指定主要汇报人", "选择参会人员后，从中指定一名分管或牵头领导，由其首先汇报事实、依据、方案与风险。");
  if (isMeeting) {
    input("form-document", "选择是否拟形成文件", "可以仅形成会议纪要，也可选择当前允许的文件类型。拟形成文件时，请留意必要会签人与材料等级要求。");
    input("form-evidence", "核对会议依据", "选择拟形成文件后，这里会显示可引用的已读材料。按页面要求补足证据等级；教程不会代你判断或提交。");
  }
  if (isArchive) input("form-archives", "选择一份待查阅档案", "查看档案说明、证据等级和首次查阅消耗，再选择一份。实际开始查阅后才登记结果，已读档案可到治理页免费重读。");
  steps.push({ id: "form-submit", title: "确认前再核对一次", body: "讲解结束后，请自行核对行动安排与按钮状态。只有表单满足当前要求才可提交；点击实际办理按钮会推进游戏。", detail: `当前消耗：${costDetail(item)}。`, target: target("form-submit") });
  return { id: `form:${variantId}`, revision: 2, title: "核对行动安排", steps, finishLabel: "讲解完成，自主操作", finishFocusTarget: target("form-submit") };
}

const SCENES: Record<string, { title: string; body: string; detail?: string }> = {
  decision: { title: "处理当前决定", body: "先读各项选择与当前条件。不可选项会说明缺少的条件；讲解结束后，由你选择实际方案。" },
  conversation: { title: "与人物会谈", body: "按对话顺序阅读，留意对方的诉求与回应。可用的提问和结束方式以现场按钮为准。" },
  group: { title: "多人现场交流", body: "留意每段发言的说话人，结合现场问题阅读各方意见，再自行选择回应。" },
  governance: { title: "推进当前行动", body: "这里展示正在办理的行动与当前进展。先阅读记录和操作说明，再决定继续、结束或取消；消耗以现场提示为准。" },
  meeting: { title: "主持会议", body: "围绕已确定的议题阅读汇报与参会意见，再查看当前可形成的决议。实际发言、推进和确认由你操作。" },
  hearing: { title: "主持公开听证", body: "围绕争议事项听取当前参与人的意见，再按页面要求形成听证结论。发起、形成结果与中止是不同状态，听证也不能替代法审和旧案处理。" },
  clan: { title: "开展宗族议事", body: "围绕本次议题阅读相关人物的意见，核对协商记录与后续安排，再按页面要求形成议事结论。" },
  document: { title: "查看与办理文件", body: "先读正文、审校意见和必要会签状态，再看页面提示的下一步。", detail: "文书审校通过后才能请其会签；会签齐备后，按当前状态办理印发与公示。修订正文会重新开始会签。讲解结束后，请自行使用原有办理按钮。" },
  contract: { title: "核对合同", body: "填写补偿与安置方案，保存后核对合同预览，再提交本户签约。", detail: "每户独立签署。对方接受后合同立即生效，并扣除约定资源。有疑问可点击继续协商，回到入户会谈；调整约定请修改方案并保存。" },
  "archive-result": { title: "阅读查档结果", body: "这里展示本次调阅的正文、新获事实与用途。读完后可到线索页查看调查收获，到治理页重读已读档案。" },
  "action-result": { title: "回看行动结果", body: "核对本次反馈与待办事项。治理页查看办理记录与材料，线索页回看已获事实和证据，复盘页查看完整会谈记录。" },
  "end-day": { title: "结束今天", body: "结束一天会推进时间。先读完当前剧情，核对今日工作与剩余精力，处理必须完成的现场事项，再自行确认结束。" },
  morning: { title: "阅读新一天的简报", body: "先查看当天变化和新出现的事项，再根据当前条件安排工作。日期推进后，行动消耗与可用机会可能变化。" },
};

export function sceneTutorial(scene: string): TutorialDefinition | null {
  const copy = SCENES[scene];
  if (!copy) return null;
  const steps: TutorialStep[] = [{ id: scene, ...copy, target: target(scene) }];
  if (["conversation", "group", "governance", "meeting", "hearing", "clan"].includes(scene)) {
    steps.push(
      { id: `${scene}:input`, title: "准备你的发言", body: "这里填写具体问题或意见。支持引用的输入框可输入 @ 选择档案，核对材料状态后发送。NPC 会收到所选材料的正文、版本和状态。引用不代表事项已办妥，也不能代替实际行动。", target: target("conversation-input") },
      { id: `${scene}:send`, title: "发送与后续操作", body: "发送会将你的发言提交到当前现场。先核对内容与按钮状态，讲解结束后再由你发送。", detail: scene === "group" ? "继续阅读各方回应，按现场要求处理当前问题。是否可以结束或返回，以问题处理后的页面按钮为准。" : "收到回应后继续阅读记录。需要结束或返回时，先查看原有按钮的说明与当前条件，再自行操作。", target: target("conversation-send") },
    );
  }
  return { id: `scene:${scene}`, revision: 3, title: copy.title, steps };
}
