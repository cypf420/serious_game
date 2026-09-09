import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { toPlayerText } from "../app/lib/player-ui.ts";

test("day-nine source dialogue displays curly quotes without changing its words", async () => {
  const beats = JSON.parse(await readFile(new URL("../../../backend/content/packages/pkg_gameplay_v3/story_beats.json", import.meta.url), "utf8"));
  const text = JSON.stringify(beats);
  for (const phrase of ["晚上老赵约你了吧", "冶炼厂那点老皇历"]) assert.ok(text.includes(phrase));
  const walk = value => typeof value === "string" ? [value] : value && typeof value === "object" ? Object.values(value).flatMap(walk) : [];
  for (const source of walk(beats).filter(value => /晚上老赵约你了吧|冶炼厂那点老皇历/.test(value))) {
    assert.equal(toPlayerText(source), source.replaceAll("「", "“").replaceAll("」", "”"));
    assert.doesNotMatch(toPlayerText(source), /[「」『』]/);
  }
});

test("nested dialogue uses outer double and inner single quotes and is idempotent", () => {
  for (const source of ["他说：「她说『明天办』，请核实。」", "他说：「所谓“办妥”，还需要核实。」"]) {
    const result = toPlayerText(source);
    assert.doesNotMatch(result, /[「」『』]/);
    assert.match(result, /“.*‘.*’.*”/);
    assert.equal(toPlayerText(result), result);
  }
});

test("streaming partial quotes do not invent closing marks", () => {
  assert.equal(toPlayerText("他说：「先核实"), "他说：“先核实");
  assert.equal(toPlayerText("他说：「先核实。」"), "他说：“先核实。”");
});

test("old saved narration removes only redundant full stops after completed quotations", () => {
  for (const [source, expected] of [
    ["周满仓：「不算我这一房的。」。", "周满仓：“不算我这一房的。”"],
    ["周满仓：「我要看的是原始的单子。」。", "周满仓：“我要看的是原始的单子。”"],
    ["周满仓：「对不上，你说什么我都不信。」。", "周满仓：“对不上，你说什么我都不信。”"],
    ["他说，“我能替他们说话的，只有这六户。”。", "他说，“我能替他们说话的，只有这六户。”"],
    ["老人说，“我周大山这辈子没替人做过主。”。", "老人说，“我周大山这辈子没替人做过主。”"],
    ["他说：“她问‘核实了吗？’”。", "他说：“她问‘核实了吗？’”"],
    ["他说：“等等！” 。随后起身。", "他说：“等等！”随后起身。"],
    ["这叫“先核实”。", "这叫“先核实”。"],
    ["他说：“我想……”。", "他说：“我想……”"],
  ]) {
    assert.equal(toPlayerText(source), expected);
    assert.equal(toPlayerText(expected), expected);
  }
});

test("numbers, links, apostrophes, title marks and ordinary punctuation stay intact", () => {
  const source = "《安置办法》：3.5万元，2026-09-09；https://example.test/a?q=1.5，O'Brien。";
  assert.equal(toPlayerText(source), source);
  assert.equal(toPlayerText("他说：「O’Brien会来。」"), "他说：“O’Brien会来。”");
});
