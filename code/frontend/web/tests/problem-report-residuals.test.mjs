import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const shell = await readFile(new URL("../app/GameShell.tsx", import.meta.url), "utf8");

test("explains the future currency purpose without promising an unavailable budget exchange", () => {
  assert.match(shell, /通晓币不用于人物会谈或本局行动消耗/);
  assert.match(shell, /财政余额兑换通晓币的功能目前尚未开放，当前没有兑换入口/);
  assert.match(shell, /比例和数量限制也尚未公布/);
  assert.match(shell, /后续“百晓生”网站用途及兑换规则以公告为准/);
  assert.doesNotMatch(shell, /通晓币用于需要模型参与的人物会谈/);
});
