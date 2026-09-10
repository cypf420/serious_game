import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { paginateText, pageForOffset } from "../app/reading/pagination.ts";

test("all shipped ending texts paginate without repeating or omitting source ranges", async () => {
  const source = JSON.parse(await readFile(new URL("../../../backend/content/packages/pkg_gameplay_v3/ending_rules.json", import.meta.url), "utf8"));
  assert.equal(source.main_endings.length, 24);
  assert.equal(source.sub_endings.length, 95);
  for (const ending of [...source.main_endings, ...source.sub_endings]) {
    const paragraphs = ending.text.split(/\n\s*\n/u).map(value => value.trim()).filter(value => value.length > 30);
    assert.equal(new Set(paragraphs).size, paragraphs.length, ending.ending_id || ending.sub_ending_id);
    for (const capacity of [120, 400, 900]) {
      const pages = paginateText(ending.text, text => text.length <= capacity);
      assert.equal(pages.map(page => page.text).join(""), ending.text);
      pages.forEach((page, index) => {
        assert.equal(page.start, index ? pages[index - 1].end : 0);
        assert.equal(page.text, ending.text.slice(page.start, page.end));
      });
    }
  }
  const fixture = JSON.parse(await readFile(new URL("../e2e/fixtures/ending-from-package.json", import.meta.url), "utf8"));
  assert.equal(fixture.main_text, source.main_endings.find(item => item.ending_id === fixture.main_ending_id).text);
  assert.equal(fixture.sub_text, source.sub_endings.find(item => item.sub_ending_id === fixture.sub_ending_id).text);
});

test("pagination preserves every character, punctuation and paragraph break", () => {
  for (const text of ["", "\n开头。\n\n第二段：‘您好！’\n末尾", "长句，".repeat(600), "你好。世界！真的吗？\n".repeat(400)]) {
    const pages = paginateText(text, value => value.length < 120);
    assert.equal(pages.map(page => page.text).join(""), text);
    for (const page of pages) {
      assert.equal(page.text, text.slice(page.start, page.end));
      assert.ok(page.text.trim().split(/\n+/).length <= 3);
    }
  }
});
test("natural paragraphs take priority, at most three per page", () => {
  assert.deepEqual(paginateText("甲。乙。\n\n丙。丁。\n\n戊。己。\n\n庚。", () => true).map(page => page.text), ["甲。乙。\n\n丙。丁。\n\n戊。己。\n\n", "庚。"]);
  assert.deepEqual(paginateText("甲。乙。\n丙。丁。", value => value.length <= 8).map(page => page.text), ["甲。乙。\n", "丙。丁。"]);
});
test("resize resolves the original offset instead of retaining an unrelated page number", () => {
  const text = "一段完整句子。".repeat(60);
  const small = paginateText(text, value => value.length <= 40);
  const large = paginateText(text, value => value.length <= 100);
  const offset = small[4].start;
  const selected = large[pageForOffset(large, offset)];
  assert.ok(selected.start <= offset && selected.end > offset);
});
