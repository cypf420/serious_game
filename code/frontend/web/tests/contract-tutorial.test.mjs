import assert from "node:assert/strict";
import test from "node:test";
import { contractTutorial } from "../app/tutorial/contract.ts";

test("contract stages are separate chapters with visible text and no answer checklist", () => {
  const stages = ["terms", "preview", "feedback", "signed", "legacy"];
  const chapters = stages.map(contractTutorial);
  assert.equal(new Set(chapters.map(c => c.id)).size, 5);
  for (const chapter of chapters) {
    assert.equal(chapter.finishLabel, "讲解完成，自主操作");
    for (const step of chapter.steps) {
      assert.equal(step.detail, undefined);
      assert.match(step.target, /data-tutorial-id="contract-/);
      assert.ok([...step.title].length <= 12);
      assert.ok([...step.body].length <= 90);
      assert.notEqual(step.interactive, true);
      assert.doesNotMatch(step.body, /吴国平|血铅复检|必须分配|全部条件|专业审校/);
    }
  }
  assert.match(chapters[0].steps.at(-1).body, /自动保存.*正在编辑/);
  assert.match(chapters[2].steps[0].body, /不等于条件已经满足/);
});
