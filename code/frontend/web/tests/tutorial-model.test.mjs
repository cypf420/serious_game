import assert from "node:assert/strict";
import test from "node:test";
import { ACTION_COPY, BASIC_TUTORIAL, QUICK_START, actionTour, actionTutorial, formTutorial, sceneTutorial } from "../app/tutorial/definitions.ts";
import { emptyProgress, loadProgress, markChapter, saveProgress, shouldAutoShow } from "../app/tutorial/progress.ts";

const variantIds = ["field_visit", "interview_cadre", "interview_enterprise", "contact_media", "convene_leadership_meeting", "public_hearing", "clan_leader_campaign", "consult_county_archives", "collect_blood_lead_report"];
const fakeStorage = () => {
  const values = new Map();
  return { values, getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
};

test("basic guide has six distinct destinations and shared quick start", () => {
  assert.equal(BASIC_TUTORIAL.steps.length, 6);
  assert.equal(new Set(BASIC_TUTORIAL.steps.map(step => step.target)).size, 6);
  assert.ok(BASIC_TUTORIAL.steps.every(step => [...step.title].length <= 12 && [...step.body].length <= 90));
  assert.match(BASIC_TUTORIAL.steps.find(step => step.id === "nav-opportunities").title, /人物/);
  assert.match(BASIC_TUTORIAL.steps.find(step => step.id === "nav-desk").title, /卷宗/);
  assert.equal(BASIC_TUTORIAL.steps.some(step => step.id === "nav-manual-saves"), false);
  assert.match(BASIC_TUTORIAL.steps.find(step => step.id === "nav-desk").body, /线索/);
  assert.equal(QUICK_START.length, 3);
});

test("all nine action variants have distinct purpose, usage, and result guidance", () => {
  assert.deepEqual(Object.keys(ACTION_COPY), variantIds);
  assert.equal(new Set(Object.values(ACTION_COPY).map(copy => copy.purpose)).size, 9);
  for (const variant_id of variantIds) {
    const chapter = actionTutorial({ variant_id, available: true, cost_action_points: 3 });
    assert.equal(chapter.id, `action:${variant_id}`);
    assert.equal(chapter.steps.length, 1);
    assert.match(chapter.steps[0].target, /\.canonical-actions/);
    for (const label of ["用途：", "适用时机：", "操作：", "当前消耗：", "办理结果："]) assert.ok(chapter.steps[0].detail.includes(label));
  }
});

test("costs and public results always use the current descriptor", () => {
  const item = { variant_id: "interview_cadre", available: true, cost: { action_points: 7 }, direct_budget_cost: 12, visible_result: "本次公开结果" };
  const detail = actionTutorial(item).steps[0].detail;
  assert.match(detail, /消耗 7 点精力/);
  assert.match(detail, /预算 12 万元/);
  assert.match(detail, /本次公开结果/);
  assert.match(actionTutorial({ ...item, cost_action_points: 0 }).steps[0].detail, /不消耗精力/);
  assert.match(actionTutorial({ variant_id: "field_visit", available: true }).steps[0].detail, /消耗待确认/);
});

test("unknown disabled public variants only explain current unavailability", () => {
  const chapter = actionTutorial({ variant_id: "future_action", name: "未开放事项", available: false, unavailable_reason: "当前条件不允许", description: "不应介绍的功能", visible_result: "不应承诺的结果" });
  assert.match(chapter.steps[0].detail, /当前条件不允许/);
  assert.doesNotMatch(chapter.steps[0].detail, /不应介绍|不应承诺|操作：|适用时机/);
});

test("action tour only follows available public descriptors in their displayed order", () => {
  assert.deepEqual(actionTour([]).steps, []);
  const tour = actionTour([
    { action_id: "cadre_interview", variants: [
      { variant_id: "contact_media", available: true },
      { variant_id: "interview_cadre", available: false },
      { variant_id: "interview_enterprise", available: true, hidden: true },
    ] },
    { variant_id: "field_visit", available: true },
    { variant_id: "field_visit", available: true },
    { variant_id: "collect_blood_lead_report" },
  ]);
  assert.deepEqual(tour.steps.map(step => step.id), ["action:contact_media", "action:field_visit"]);
});

test("forms conditionally explain real inputs while keeping submission noninteractive", () => {
  const meeting = formTutorial({ action_id: "leadership_meeting", variant_id: "convene_leadership_meeting", location_choices: [{}, {}] });
  assert.deepEqual(meeting.steps.map(step => step.id), ["form-location", "form-topic", "form-targets", "form-lead", "form-document", "form-evidence", "form-submit"]);
  assert.equal(meeting.id, "form:convene_leadership_meeting");
  assert.ok(meeting.steps.slice(0, -1).every(step => step.optional && step.interactive));
  assert.equal(meeting.steps.at(-1).interactive, undefined);
  assert.equal(meeting.steps.at(-1).optional, undefined);
  assert.equal(meeting.finishLabel, "讲解完成，自主操作");
  assert.equal(meeting.finishFocusTarget, '[data-tutorial-id="form-submit"]');
  const hearing = formTutorial({ action_id: "leadership_meeting", variant_id: "public_hearing" });
  assert.ok(!hearing.steps.some(step => step.id === "form-lead"));
  const archive = formTutorial({ action_id: "inspect_archives", variant_id: "consult_county_archives" });
  assert.deepEqual(archive.steps.map(step => step.id), ["form-archives", "form-submit"]);
  const visit = formTutorial({ action_id: "household_visit", variant_id: "field_visit" });
  assert.deepEqual(visit.steps.map(step => step.id), ["form-topic", "form-targets", "form-submit"]);
});

test("all eleven scene guides are explanatory and unknown scenes have no guide", () => {
  const scenes = ["decision", "conversation", "group", "governance", "meeting", "document", "contract", "archive-result", "action-result", "end-day", "morning"];
  for (const scene of scenes) {
    const guide = sceneTutorial(scene);
    assert.equal(guide.id, `scene:${scene}`);
    assert.ok(guide.steps.every(step => !step.interactive));
    assert.ok(guide.steps.every(step => [...step.title].length <= 12 && [...step.body].length <= 90 && [...(step.detail || "")].length <= 120));
    assert.equal(guide.steps[0].target, `[data-tutorial-id="${scene}"]`);
    if (["conversation", "group", "governance", "meeting"].includes(scene)) {
      assert.equal(guide.steps.length, 3);
      assert.equal(guide.steps[1].target, '[data-tutorial-id="conversation-input"]');
      assert.equal(guide.steps[2].target, '[data-tutorial-id="conversation-send"]');
      assert.match(guide.steps[2].detail, /结束或返回/);
    }
  }
  assert.match(sceneTutorial("document").steps[0].detail, /审校通过后才能请其会签/);
  assert.match(sceneTutorial("contract").steps[0].detail, /直接签署并从对应资源项扣除/);
  assert.match(sceneTutorial("action-result").steps[0].body, /治理页.*线索页/);
  assert.equal(sceneTutorial("unrecognized"), null);
});

test("progress is isolated by account and versioned, including memory fallbacks", () => {
  const storage = fakeStorage();
  const progress = markChapter(emptyProgress(), BASIC_TUTORIAL, "completed", 6);
  saveProgress("tutorial-test-a", progress, storage);
  assert.deepEqual(loadProgress("tutorial-test-a", storage), progress);
  assert.deepEqual(loadProgress("tutorial-test-b", storage), emptyProgress());
  assert.match([...storage.values.keys()][0], /:v1:/);
  const broken = { getItem() { throw Error("denied"); }, setItem() { throw Error("quota"); } };
  saveProgress("tutorial-test-memory", progress, broken);
  assert.deepEqual(loadProgress("tutorial-test-memory", broken), progress);
  assert.deepEqual(loadProgress("tutorial-test-other-memory", broken), emptyProgress());
  const loaded = loadProgress("tutorial-test-memory", broken);
  loaded.chapters.basic.step = 0;
  assert.equal(loadProgress("tutorial-test-memory", broken).chapters.basic.step, BASIC_TUTORIAL.steps.length - 1);
});

test("corrupt storage and unsupported schemas safely fall back", () => {
  for (const [index, raw] of ["{bad", "null", '{"version":2,"auto":true,"chapters":{}}', '{"version":1,"auto":"yes","chapters":{}}'].entries()) {
    assert.deepEqual(loadProgress(`tutorial-corrupt-${index}`, { getItem: () => raw }), emptyProgress());
  }
  const raw = JSON.stringify({ version: 1, auto: false, chapters: { valid: { revision: 1, status: "seen", step: 2 }, bad: { revision: -1, status: "completed", step: -5 } }, paused: { id: "basic", step: -2 } });
  const progress = loadProgress("tutorial-sanitize", { getItem: () => raw });
  assert.equal(progress.auto, false);
  assert.deepEqual(Object.keys(progress.chapters), ["valid"]);
  assert.equal(progress.paused, undefined);
});

test("automatic chapters respect seen state, opt-out, revisions and safe resume steps", () => {
  const fresh = emptyProgress();
  assert.equal(shouldAutoShow(fresh, BASIC_TUTORIAL), true);
  const seen = markChapter(fresh, BASIC_TUTORIAL, "seen", 99);
  assert.equal(seen.chapters.basic.step, BASIC_TUTORIAL.steps.length - 1);
  assert.equal(shouldAutoShow(seen, BASIC_TUTORIAL), false);
  assert.equal(shouldAutoShow(seen, { ...BASIC_TUTORIAL, revision: 2 }), true);
  assert.equal(shouldAutoShow({ ...fresh, auto: false }, BASIC_TUTORIAL), false);
  assert.equal(shouldAutoShow(fresh, actionTour([])), false);
  const completed = markChapter(seen, BASIC_TUTORIAL, "completed", 6);
  assert.equal(markChapter(completed, BASIC_TUTORIAL, "seen", -1).chapters.basic.status, "completed");
  assert.equal(markChapter(completed, { ...BASIC_TUTORIAL, revision: 2 }, "seen", NaN).chapters.basic.status, "seen");
  assert.deepEqual(fresh, emptyProgress());
});
