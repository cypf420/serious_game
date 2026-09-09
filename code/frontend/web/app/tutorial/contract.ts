import type { ContractTutorialStage, TutorialDefinition, TutorialStep } from "./types";

const step = (id: string, title: string, body: string): TutorialStep => ({ id, title, body, target: `[data-tutorial-id="contract-${id}"]` });

export function contractTutorial(stage: ContractTutorialStage): TutorialDefinition {
  const chapters = {
    terms: { title: "填写合同方案", focus: "save", steps: [
      step("household", "先确认这一户", "核对当前家庭与签约人。同一代表可以协商多户，但每户合同独立，签署后才计入这一户的进度。"),
      step("fields", "安排补偿与时间", "现金按本户政策标准填写，可结合诉求和可用预算调整。搬离日与过渡月份也属于方案；超过授权的补偿按页面提示办理。"),
      step("housing", "选择住房安排", "选择住房后填写交房日，并核对房源与搬离时间。晚交房需要过渡安排；不采用实物安置时无需填写交房日。"),
      step("services", "分配配套服务", "结合会谈和本户情况安排服务。名额由各户共用，草案不占库存；提交签约时再次核验剩余资源。"),
      step("save", "保存并预览", "保存方案会核验并生成合同，此时尚未签约或扣款。游戏自动保存已完成的操作；正在编辑的修改仍需点击这里保存。"),
    ] },
    preview: { title: "核对并提交合同", focus: "submit", steps: [
      step("preview", "核对合同正文", "正文由已保存的方案生成。需要调整时使用“修改方案”，不能在正文里另写承诺。"),
      step("deduction", "确认签署后扣除", "这里列出当前方案签署时扣除的现金、住房和服务名额。预览不会扣除资源。"),
      step("submit", "自主提交签约", "提交后按本户实际条件办理。满足条件即签署并结算；尚未满足时不扣款。是否提交由你决定，教程不会替你操作。"),
    ] },
    feedback: { title: "阅读签约答复", focus: "feedback", steps: [
      step("feedback", "了解当前顾虑", "先读本户对当前方案的回应，可继续会谈了解情况。调整方案或实际事项变化后再提交；重复说几句话不等于条件已经满足。"),
    ] },
    signed: { title: "查看已签合同", focus: "signed", steps: [
      step("signed", "本户已签署", "本户合同已生效，约定现金与名额已结算。同批次其他家庭仍需逐户办理；可保存并查看本户合同记录。"),
    ] },
    legacy: { title: "核对旧版草案", focus: "legacy", steps: [
      step("legacy", "核对旧约定", "先查看旧版正文，核对需要保留的安排。确认并保存当前方案后再提交；旧正文存档不会因此丢失。"),
    ] },
  };
  const chapter = chapters[stage];
  return { id: `scene:contract:${stage}`, revision: 1, title: chapter.title, steps: chapter.steps,
    finishLabel: "讲解完成，自主操作", finishFocusTarget: `[data-tutorial-id="contract-${chapter.focus}"]` };
}
