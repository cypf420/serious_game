import assert from "node:assert/strict";
import { readdir, stat } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { ENDING_SCENES, STORY_SCENES, blockIdFromContentInstance, resolveScene, resolveSceneForView } from "../app/lib/scene-resolver.ts";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("resolves identifiers in the required priority order and records matchedBy", () => {
  const resolved = resolveScene({
    contentInstanceId: "block:d01_arrival_drive",
    blockId: "d01_briefing_office",
    decisionId: "ev1_01_reception_bag",
    mainEndingId: "ending_24",
    beatId: "beat_d89_m2",
  });
  assert.equal(resolved.id, "C01_S01");
  assert.equal(resolved.matchedBy, "content_instance_id");
  assert.equal(resolved.matchedId, "d01_arrival_drive");

  assert.equal(resolveScene({ blockId: "d01_briefing_office", decisionId: "ev1_01_reception_bag" }).matchedBy, "block_id");
  assert.equal(resolveScene({ decisionId: "ev1_01_reception_bag", mainEndingId: "ending_24" }).matchedBy, "decision_id");
  assert.equal(resolveScene({ mainEndingId: "ending_24", beatId: "beat_d89_m2" }).matchedBy, "main_ending_id");
  assert.equal(resolveScene({ beatId: "beat_d89_m2" }).matchedBy, "beat_id");
  assert.equal(resolveScene({}).matchedBy, "fallback");
  assert.equal(blockIdFromContentInstance("block:d01_reception_scene"), "d01_reception_scene");
});

test("uses different camera shots for blocks inside the same beat", () => {
  const arrival = resolveScene({ contentInstanceId: "block:d01_arrival_drive", beatId: "beat_d01_arrival_and_reception" });
  const office = resolveScene({ contentInstanceId: "block:d01_briefing_office", beatId: "beat_d01_arrival_and_reception" });
  const reception = resolveScene({ contentInstanceId: "block:d01_reception_scene", beatId: "beat_d01_arrival_and_reception" });
  assert.deepEqual([arrival.id, office.id, reception.id], ["C01_S01", "C01_S02", "C01_S03"]);
  assert.equal(new Set([arrival.asset, office.asset, reception.asset]).size, 3);
});

test("keeps historical and current-state scene identifiers in separate time contexts", () => {
  const oldLine = { sceneId: "C02_S08", storyDay: 30 };
  assert.equal(resolveSceneForView({ line: oldLine, currentStoryDay: 31, decisionId: "dp3_01" }).id, "C02_S08");
  assert.equal(resolveSceneForView({ line: { sceneId: "C02_S02", storyDay: 18 }, currentStoryDay: 19 }).id, "C02_S02");
  assert.equal(resolveSceneForView({ currentStoryDay: 90, mainEndingId: "ending_24" }).id, "E24");
});

test("binds the D18 hostile phone and D25 work meeting to their matching scenes", () => {
  const phone = resolveScene({ contentInstanceId: "block:d18_phone_pressure", beatId: "beat_d18_m2" });
  assert.equal(phone.id, "C01_S02");
  assert.equal(phone.title, "县长办公室");
  assert.notEqual(phone.title, "晨间三张纸与茶叶盒");

  const meeting = resolveScene({ contentInstanceId: "block:d25_meeting", beatId: "beat_d25_m2" });
  assert.equal(meeting.id, "C01_S06");
  assert.equal(meeting.title, "渡口镇工作组例会");
  assert.notEqual(meeting.title, "吴秀英红圈名册");
});

test("lets the authoritative pending D74 scene replace the previous pediatric line", () => {
  const resolved = resolveSceneForView({
    line: { sceneId: "C05_S07", storyDay: 74 },
    currentStoryDay: 74,
    pendingSceneId: "C05_S02",
    decisionId: "dp5_09",
  });
  assert.equal(resolved.id, "C05_S02");
  assert.equal(resolved.title, "白日祠堂");
});

test("uses a neutral scene when the current record has no scene binding", () => {
  assert.equal(resolveSceneForView({ line: { storyDay: 1 }, currentStoryDay: 1 }).id, "N00");
});

test("free work days cannot inherit the rain-night beat, including restored daily cards", () => {
  for (const day of [39, 40]) {
    const base = { currentStoryDay: day, beatId: `beat_d${day}_m2` };
    assert.equal(resolveSceneForView(base).title, "县长办公室");
    for (const kind of ["day_intro", "morning_card"]) {
      assert.equal(resolveSceneForView({ ...base, line: { kind, storyDay: day, sceneId: "C03_S03", beatId: base.beatId } }).id, "N00");
    }
    assert.equal(resolveSceneForView({ ...base, pendingSceneId: "C06_S10" }).id, "C06_S10");
  }
});

test("D38 morning, petition and pending decision preserve their verified locations", () => {
  assert.equal(resolveSceneForView({ decisionId: "dp3_06", pendingSceneId: "C03_S03" }).id, "C04_S02");
  assert.equal(resolveSceneForView({ line: { blockId: "d38_hint", sceneId: "C03_S03" } }).id, "C01_S02");
  for (const blockId of ["d38_petition", "d38_setup"]) {
    assert.equal(resolveSceneForView({ line: { blockId, sceneId: "C03_S03" } }).id, "C04_S02");
  }
});

test("covers 50 story scenes and all 24 real main endings", async () => {
  assert.equal(STORY_SCENES.length, 50);
  assert.equal(ENDING_SCENES.length, 24);
  assert.equal(new Set(STORY_SCENES.map(item => item.id)).size, 50);
  assert.equal(new Set(ENDING_SCENES.map(item => item.id)).size, 24);
  assert.equal(new Set(STORY_SCENES.flatMap(item => item.blockIds)).size, STORY_SCENES.reduce((total, item) => total + item.blockIds.length, 0));
  assert.equal(new Set(STORY_SCENES.flatMap(item => item.decisionIds)).size, STORY_SCENES.reduce((total, item) => total + item.decisionIds.length, 0));

  for (let index = 1; index <= 24; index += 1) {
    const endingId = `ending_${String(index).padStart(2, "0")}`;
    assert.equal(resolveScene({ mainEndingId: endingId }).id, `E${String(index).padStart(2, "0")}`);
  }

  const files = (await readdir(path.join(projectRoot, "public", "scenes"))).sort();
  const expected = [...STORY_SCENES, ...ENDING_SCENES].map(item => path.basename(item.asset)).sort();
  assert.deepEqual(files, expected);
  for (const file of files) assert.ok((await stat(path.join(projectRoot, "public", "scenes", file))).size > 0);
  assert.equal(files.some(file => /rejected|qa|backup|prompt|source|overview|script|备份|提示词|源图|总览|处理脚本|\.png$|\.jpg$/i.test(file)), false);
});
