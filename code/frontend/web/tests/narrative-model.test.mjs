import assert from "node:assert/strict";
import test from "node:test";

import { dedupeNarrative, initialNarrativeState, narrativeItemFromFeed, narrativeReducer, narrativeReadingComplete, pendingDecisionIsReady } from "../app/lib/narrative-model.ts";
import { resolveSceneForView } from "../app/lib/scene-resolver.ts";

const line = (id, cursor, text = id, storyDay = 1) => ({ id, cursor, storyDay, kind: "narrative", text, contentInstanceId: `block:${id}` });

test("resolved generic decision questions disappear while pending choices and consequences remain", () => {
  const setup = line("yuan", 74, "袁桂兰担心安置和孩子就医。", 5);
  const gate = {...line("question", 76, "你准备如何处理？", 5), kind:"decision", presentationPhase:"decision", contentInstanceId:"decision:yuan"};
  const result = line("answer", 77, "你解释安置房和就医便利，她送你到了门口。", 5);
  let state = narrativeReducer(initialNarrativeState, {type:"SESSION_REBUILD",sessionId:"s",items:[setup,gate],storyDay:5,pendingDecisionEntryId:gate.contentInstanceId,position:"latest"});
  assert.equal(pendingDecisionIsReady(state.items[state.currentIndex], gate.contentInstanceId), true);
  state = narrativeReducer(state, {type:"FEED_MERGE",sessionId:"s",items:[result],storyDay:5,pendingDecisionEntryId:null,cursor:77});
  assert.deepEqual(state.items.map(x=>x.id), ["yuan","answer"]);
  assert.equal(state.items[state.currentIndex].id, "answer");
  const restored = narrativeReducer(initialNarrativeState, {type:"SESSION_REBUILD",sessionId:"s",items:[setup,gate,result],storyDay:5,pendingDecisionEntryId:null,position:2,cursor:77});
  assert.deepEqual(restored.items.map(x=>x.id), ["yuan","answer"]);
  assert.equal(restored.items[restored.currentIndex].id, "answer");
  assert.equal(restored.feedCursor,77);
  const nextGate = {...gate,id:"next",cursor:78,contentInstanceId:"decision:next"};
  state = narrativeReducer(state,{type:"FEED_MERGE",sessionId:"s",items:[nextGate],storyDay:5,pendingDecisionEntryId:nextGate.contentInstanceId});
  assert.equal(pendingDecisionIsReady(state.items[state.currentIndex],nextGate.contentInstanceId),true);
});

test("end-day reading readiness follows visible position and newly appended prose", () => {
  assert.equal(narrativeReadingComplete(initialNarrativeState), true);
  let state = narrativeReducer(initialNarrativeState, { type: "SESSION_REBUILD", sessionId: "s", items: [line("a", 1), line("b", 2)] });
  assert.equal(narrativeReadingComplete(state), false);
  state = narrativeReducer(state, { type: "NEXT" });
  assert.equal(narrativeReadingComplete(state), true);
  state = narrativeReducer(state, { type: "PREVIOUS" });
  assert.equal(narrativeReadingComplete(state), false);
  state = narrativeReducer(state, { type: "GO_LATEST" });
  state = narrativeReducer(state, { type: "FEED_MERGE", sessionId: "s", items: [line("c", 3), line("d", 4)] });
  assert.equal(state.items[state.currentIndex].id, "c");
  assert.equal(narrativeReadingComplete(state), false);
  state = narrativeReducer(state, { type: "NEXT" });
  assert.equal(narrativeReadingComplete(state), true);
});

test("story dates use Chinese numerals without rewriting dialogue or source documents", () => {
  const text = "第31天早晨六点四十，第 90 日归档，合同WU-02约定31万元，文号〔2026〕31号。";
  const converted = "第三十一天早晨六点四十，第九十日归档，合同WU-02约定31万元，文号〔2026〕31号。";
  for (const kind of ["narration", "narrative", "night", "morning_card"]) {
    assert.equal(narrativeItemFromFeed({ kind, text }, "test").text, converted);
  }
  for (const kind of ["dialogue", "document", "contract", "conversation_turn"]) {
    assert.equal(narrativeItemFromFeed({ kind, text }, "test").text, text);
  }
  for (const [number, written] of [[1, "一"], [10, "十"], [11, "十一"], [20, "二十"], [90, "九十"]]) {
    assert.equal(narrativeItemFromFeed({kind: "narration", text: `第${number}日早晨`}, "test").text, `第${written}日早晨`);
  }
});

test("collapses adjacent duplicate prose while preserving its canonical scene and aliases", () => {
  const text = "这是同一场景中重复出现的一段完整叙述。".repeat(4);
  const first = { ...line("a", 1, text), sceneId: "C03_S01", beatId: "beat_d31_m2", presentationPhase: "scene", readGate: "advance" };
  const second = { ...first, id: "b", cursor: 2, contentInstanceId: "block:b" };
  const result = dedupeNarrative([first, second]);
  assert.equal(result.length, 1);
  assert.equal(result[0].contentInstanceId, first.contentInstanceId);
  assert.equal(result[0].sceneId, first.sceneId);
  assert.deepEqual(result[0].mergedKeys, ["content:block:b"]);
  assert.deepEqual(dedupeNarrative([...result, second]), result);
  for (const change of [
    { kind: "dialogue", speaker: "吴秀英" }, { decisionId: "dp3_01" }, { mainEndingId: "ending_01" },
    { presentationPhase: "decision" }, { presentationPhase: "decision_setup" }, { readGate: "decision" },
    { readGate: "free_action" }, { sceneId: "C03_S02" }, { beatId: "other" }, { storyDay: 2 },
  ]) assert.equal(dedupeNarrative([first, { ...second, ...change }]).length, 2, JSON.stringify(change));
  assert.equal(dedupeNarrative([first, line("middle", 3), second]).length, 3);
});

test("night is read on its own day and is archived when the clock advances", () => {
  const items = [
    { ...line("night", 1, "第三十日夜里，你合上卷宗。", 30), kind: "night", presentationPhase: "night", sceneId: "C02_S08" },
    { ...line("morning", 2, "第三十一日早晨，巡察组进城。", 31), sceneId: "C03_S01" },
  ];
  let state = narrativeReducer(initialNarrativeState, { type: "SESSION_REBUILD", sessionId: "s", items: [items[0]], storyDay: 30, position: "start" });
  const view = () => resolveSceneForView({ line: state.items[state.currentIndex], currentStoryDay: 31, currentIndex: state.currentIndex, itemCount: state.items.length, decisionId: "dp3_01" });
  assert.equal(state.items[state.currentIndex].storyDay, 30);
  assert.equal(view().id, "C02_S08");
  assert.equal(narrativeReadingComplete(state), true);
  state = narrativeReducer(state, { type: "FEED_MERGE", sessionId: "s", items: [items[1]], storyDay: 31 });
  assert.equal(state.items[state.currentIndex].storyDay, 31);
  assert.equal(view().id, "C03_S01");
  assert.equal(narrativeReadingComplete(state), true);
  assert.deepEqual(state.historyItems.map(item => item.id), ["night"]);
  const restored = narrativeReducer(initialNarrativeState, { type: "SESSION_REBUILD", sessionId: "s", items, storyDay: 31 });
  assert.equal(restored.items[restored.currentIndex].storyDay, 31);
  assert.deepEqual(restored.historyItems.map(item => item.id), ["night"]);
});

test("all 89 day transitions keep night on its own day, including empty next-day feeds", () => {
  for (let day = 1; day < 90; day++) {
    const daytime = line(`day-${day}`, 1, "今日工作", day);
    const nights = [1, 2].map(n => ({ ...line(`night-${n}`, n + 1, `夜间收尾${n}`, day), kind: "night", presentationPhase: "night" }));
    let state = narrativeReducer(initialNarrativeState, { type: "SESSION_REBUILD", sessionId: "s", items: [daytime], storyDay: day });
    state = narrativeReducer(state, { type: "FEED_MERGE", sessionId: "s", items: nights, storyDay: day });
    assert.equal(state.items[state.currentIndex].id, "night-1");
    assert.equal(narrativeReadingComplete(state), false);
    state = narrativeReducer(state, { type: "NEXT" });
    assert.equal(narrativeReadingComplete(state), true);
    state = narrativeReducer(state, { type: "FEED_MERGE", sessionId: "s", items: [], storyDay: day + 1 });
    assert.deepEqual(state.items, []);
    assert.equal(state.historyItems.length, 3);
    const restored = narrativeReducer(initialNarrativeState, { type: "SESSION_REBUILD", sessionId: "s", items: [daytime, ...nights], storyDay: day + 1 });
    assert.deepEqual(restored.items, []);
  }
});

test("day headings are hidden while free-day guidance remains", () => {
  for (let day = 1; day <= 90; day++) {
    const intro = narrativeItemFromFeed({ kind: "day_intro", story_day: day, text: `第${day}日，第三日·被截取的标题`, content_instance_id: `day:${day}:intro` }, "unused");
    assert.equal(intro.text, "");
    assert.equal(intro.contentInstanceId, `day:${day}:intro`);
  }
  const text = "第三日，他向你说明了完整的事情经过。";
  assert.equal(narrativeItemFromFeed({ kind: "narrative", story_day: 3, text }, "scene").text, text);
  const free = "第4日，今天没有必须处理的主线事项，可以自由安排行动。";
  assert.equal(narrativeItemFromFeed({ kind: "day_intro", story_day: 4, text: free }, "free").text, free.replace("第4日，", ""));
});

test("merges incremental feeds, de-duplicates content and stops at the first unread item", () => {
  let state = narrativeReducer(initialNarrativeState, { type: "SESSION_OPEN", sessionId: "s1" });
  state = narrativeReducer(state, { type: "FEED_MERGE", sessionId: "s1", items: [line("a", 1), line("b", 2)], cursor: 2 });
  assert.equal(state.items.length, 2);
  assert.equal(state.currentIndex, 0);
  assert.equal(state.unreadCount, 1);

  state = narrativeReducer(state, { type: "FEED_MERGE", sessionId: "s1", items: [line("b", 2), line("c", 3)], cursor: 3 });
  assert.deepEqual(state.items.map(item => item.id), ["a", "b", "c"]);
  assert.equal(state.currentIndex, 0);
  assert.equal(state.feedCursor, 3);
});

test("keeps navigation inside the current day and separates prior days", () => {
  let state = narrativeReducer(initialNarrativeState, { type: "SESSION_REBUILD", sessionId: "s1", items: [line("a", 1), line("b", 2)], cursor: 2 });
  state = narrativeReducer(state, { type: "PREVIOUS" });
  state = narrativeReducer(state, { type: "FEED_MERGE", sessionId: "s1", items: [line("c", 3, "c", 2), line("d", 4, "d", 2)], cursor: 4 });
  assert.equal(state.currentIndex, 0);
  assert.equal(state.unreadCount, 1);
  assert.deepEqual(state.items.map(item => item.id), ["c", "d"]);
  assert.deepEqual(state.historyItems.map(item => item.id), ["a", "b"]);
  state = narrativeReducer(state, { type: "NEXT" });
  assert.equal(state.currentIndex, 1);
  assert.equal(state.unreadCount, 0);
  state = narrativeReducer(state, { type: "GO_LATEST" });
  assert.equal(state.currentIndex, 1);
  assert.equal(state.unreadCount, 0);
});

test("resets for another save and rebuilds authoritative feed after a 409", () => {
  let state = narrativeReducer(initialNarrativeState, { type: "SESSION_REBUILD", sessionId: "save-a", items: [line("old", 7)], cursor: 7 });
  state = narrativeReducer(state, { type: "SESSION_OPEN", sessionId: "save-b" });
  assert.equal(state.sessionId, "save-b");
  assert.deepEqual(state.items, []);
  state = narrativeReducer(state, { type: "SESSION_REBUILD", sessionId: "save-b", items: [line("fresh", 1), line("fresh", 1)], cursor: 1 });
  assert.deepEqual(state.items.map(item => item.id), ["fresh"]);
  assert.equal(state.currentIndex, 0);
  assert.equal(state.rebuildCount, 1);
});

test("starts a brand-new game at the first story entry while restores stay latest", () => {
  const items = [line("arrival", 1), line("office", 2), line("phone", 3)];
  const started = narrativeReducer(initialNarrativeState, { type: "SESSION_REBUILD", sessionId: "new-game", items, cursor: 3, position: "start" });
  const restored = narrativeReducer(initialNarrativeState, { type: "SESSION_REBUILD", sessionId: "saved-game", items, cursor: 3, position: "latest" });
  assert.equal(started.currentIndex, 0);
  assert.equal(started.items[started.currentIndex].id, "arrival");
  assert.equal(restored.currentIndex, 2);
  assert.equal(restored.items[restored.currentIndex].id, "phone");
});

test("reveals a pending decision only after its current narrative has been read", () => {
  const setup = { contentInstanceId: "block:setup", presentationPhase: "decision_setup" };
  const card = { contentInstanceId: "decision:event-1", presentationPhase: "decision" };
  assert.equal(pendingDecisionIsReady(setup, "decision:event-1"), false);
  assert.equal(pendingDecisionIsReady(card, "decision:event-1"), true);
  assert.equal(pendingDecisionIsReady(card, "decision:event-2"), false);
  assert.equal(pendingDecisionIsReady(null, "decision:event-1"), false);
});

test("keeps optional feed metadata for compatibility and stable scene matching", () => {
  const item = narrativeItemFromFeed({
    cursor: 4,
    story_day: 12,
    kind: "dialogue",
    speaker: "郑向东",
    text: "请看卷宗。",
    content_instance_id: "block:d01_briefing_files",
    block_id: "d01_briefing_files",
    decision_id: "dp1_01_taskforce_faction_map",
    beat_id: "beat_d01_arrival_and_reception",
    scene_id: "C01_S02",
    presentation_phase: "opening",
    day_sequence: 2,
    read_gate: "continue",
  }, "fallback");
  assert.equal(item.id, "block:d01_briefing_files");
  assert.equal(item.blockId, "d01_briefing_files");
  assert.equal(item.decisionId, "dp1_01_taskforce_faction_map");
  assert.equal(item.beatId, "beat_d01_arrival_and_reception");
  assert.equal(item.sceneId, "C01_S02");
  assert.equal(item.presentationPhase, "opening");
});


test("old empty morning cards are removed while free-day guidance survives reload and merge", () => {
  const morning = narrativeItemFromFeed({kind: "morning_card", story_day: 4, text: "D4 清晨，专班完成了昨日材料结转。", content_instance_id: "morning:4"}, "morning");
  const intro = narrativeItemFromFeed({kind: "day_intro", story_day: 4, text: "第4日，今天没有必须处理的主线事项，可以自由安排行动。", content_instance_id: "day:4:intro"}, "intro");
  let state = narrativeReducer(initialNarrativeState, {type: "SESSION_REBUILD", sessionId: "d4", items: [morning, intro], cursor: 2});
  assert.equal(state.items.length, 1);
  assert.equal(state.items[0].text, "今天没有必须处理的主线事项，可以自由安排行动。");
  state = narrativeReducer(state, {type: "FEED_MERGE", sessionId: "d4", items: [morning, intro], cursor: 2});
  assert.equal(state.items.length, 1);
  assert.equal(state.feedCursor, 2);
});

test("all 90 days omit boilerplate but preserve concrete news and decision gates", () => {
  for (let day = 1; day <= 90; day++) {
    for (const text of [`D${day} 清晨，专班完成了昨日材料结转。`, `第${day}日，清晨，专班完成了昨日材料结转。`, "县城昨夜无事。", "昨夜，与你白天接触有关的消息在熟人圈里传开了。"]) {
      assert.equal(narrativeItemFromFeed({kind:"morning_card",story_day:day,text}, "filler").text, "");
    }
  }
  const news = "夜间动向：吴秀英约好今天带两户村民来核对补偿。";
  assert.equal(narrativeItemFromFeed({kind:"morning_card",text:`D3 清晨，专班完成了昨日材料结转。\n${news}\n县城昨夜无事。`}, "mixed").text, news);
  for (const kind of ["dialogue", "document", "decision"]) {
    assert.equal(narrativeItemFromFeed({kind,text:"县城昨夜无事。"}, "keep").text, "县城昨夜无事。");
  }
  assert.equal(narrativeItemFromFeed({kind:"narration",presentation_phase:"decision",text:"县城昨夜无事。"}, "gate").text, "县城昨夜无事。");
});
