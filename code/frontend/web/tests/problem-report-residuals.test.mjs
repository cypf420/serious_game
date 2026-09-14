import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { BASIC_TUTORIAL } from "../app/tutorial/definitions.ts";

const shell = await readFile(new URL("../app/GameShell.tsx", import.meta.url), "utf8");

test("cover and inline guide use the exact approved currency copy", () => {
  const copy = '剩余的财政余额能兑换百晓智能“通晓币”，详情xxx';
  assert.equal(shell.match(/<p className="currency-notice" role="note">(.*?)<\/p>/s)?.[1], copy);
  const step = BASIC_TUTORIAL.steps.find(step => step.id === "metrics");
  assert.ok(step.body.endsWith(copy));
  assert.equal(step.detail, undefined);
  assert.doesNotMatch(shell, /百晓生|财政余额兑换通晓币的功能目前尚未开放/);
});
