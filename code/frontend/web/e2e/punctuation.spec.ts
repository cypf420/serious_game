import { expect, test } from "@playwright/test";
import { readFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const packageData: unknown = JSON.parse(await readFile(resolve("../../backend/content/packages/pkg_gameplay_v3/story_beats.json"), "utf8"));
function strings(value: unknown): string[] {
  return typeof value === "string" ? [value] : value && typeof value === "object" ? Object.values(value).flatMap(strings) : [];
}
const qa = resolve("../../../../output/punctuation-20260909/qa");

for (const day of [9, 48, 52]) for (const width of [1440, 390]) test(`day-${day} punctuation in story, history and reloaded save at ${width}`, async ({ page }) => {
  const phrases = day === 9 ? /晚上老赵约你了吧|冶炼厂那点老皇历/
    : day === 48 ? /不算我这一房|原始的单子|对不上，你说什么/
    : /只有这六户|这辈子没替人做过主/;
  const source = strings(packageData).filter(text => phrases.test(text));
  expect(source).toHaveLength(day === 48 ? 3 : 2);
  const expected = source.map(text => text.replaceAll("「", "“").replaceAll("」", "”"));
  // Reproduce the old backend's persisted extra full stop, not just raw copy.
  const saved = source.map(text => /[。！？…][」”]$/.test(text) ? `${text}。` : text);
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
  const errors: string[] = [];
  const writes: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => {
    localStorage.setItem("qingjiang-sandbox-account", "sandbox_punctuation");
    localStorage.setItem("qingjiang:tutorial:v1:sandbox_punctuation", JSON.stringify({ version: 1, auto: false, chapters: {} }));
  });
  const state = { session_id: "punctuation-save", status: "active", state_version: 1, story: { day }, ledger: { action_points: { remaining: 4, daily_cap: 8 }, budget: { available: 7800 } } };
  await page.route("**/api/backend/**", async route => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api\/backend/, "");
    if (route.request().method() !== "GET") writes.push(path);
    let body: Record<string, unknown> = {};
    if (path === "/health/ready") body = { authentication_required: false, model_consent_required: false };
    else if (path === "/api/ai/config") body = { active: true, mode: "personal", endpoint: "https://fixture.invalid/v1", model: "fixture" };
    else if (path === "/api/game/sessions") body = { sessions: [{ session_id: state.session_id, story_day: day, status: "active" }] };
    else if (path === "/api/game/session" || path === `/api/game/session/${state.session_id}`) body = { session_id: state.session_id };
    else if (path.endsWith("/view")) body = { state, commands: {}, feed: { items: saved.map((text, index) => ({ id: `old-d${day}-${index}`, text, story_day: day, scene_id: day === 48 ? "C04_S02" : day === 52 ? "C04_S07" : "C01_S02" })), cursor: source.length } };
    else if (path.endsWith("/governance")) body = { governance_actions: [], meetings: [], documents: [] };
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/");
  await expect(page).toHaveTitle(/浊流之上/);
  await expect(page.locator(".top-status .online")).toHaveCount(1);
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /开始新游戏/ }).click();
  const paragraph = page.locator(".gal-dialogue .reading-viewport");
  for (let index = 0; index < expected.length; index++) {
    await expect(paragraph).toContainText(expected[index].slice(0, 12));
    let whole = await paragraph.innerText();
    while (whole.length < expected[index].length) {
      await page.getByRole("button", { name: "下一段", exact: true }).click();
      whole += await paragraph.innerText();
    }
    expect(whole).toBe(expected[index]);
    await expect(paragraph).not.toContainText(/[「」『』]|[。！？…]”\s*。/);
    if (index + 1 < expected.length) await page.getByRole("button", { name: "下一段", exact: true }).click();
  }
  await mkdir(qa, { recursive: true });
  await page.screenshot({ path: `${qa}/day${day}-narration-${width}.png`, fullPage: true });
  await page.getByRole("button", { name: "剧情回看", exact: true }).click();
  const history = page.locator(".history-drawer");
  for (const [index, line] of expected.entries()) {
    const article = history.locator("article").nth(index);
    const previous = article.getByRole("button", { name: "上一页", exact: true });
    while (await previous.isEnabled()) await previous.click();
    let whole = await article.locator(".reading-viewport").innerText();
    const next = article.getByRole("button", { name: "下一页", exact: true });
    while (await next.isEnabled()) { await next.click(); whole += await article.locator(".reading-viewport").innerText(); }
    expect(whole).toBe(line);
  }
  await mkdir(qa, { recursive: true });
  await page.screenshot({ path: `${qa}/day${day}-quotes-${width}.png`, fullPage: true });
  await page.reload();
  await expect(page.locator(".top-status .online")).toHaveCount(1);
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /查看已有进度/ }).click();
  await page.locator(".saved-session-list button").click();
  await expect.poll(async () => expected.at(-1)!.includes(await paragraph.innerText())).toBe(true);
  await expect(paragraph).not.toContainText(/[「」『』]|[。！？…]”\s*。/);
  await page.getByRole("button", { name: "剧情回看", exact: true }).click();
  for (const [index, line] of expected.entries()) {
    const article = history.locator("article").nth(index);
    const previous = article.getByRole("button", { name: "上一页", exact: true });
    while (await previous.isEnabled()) await previous.click();
    let whole = await article.locator(".reading-viewport").innerText();
    const next = article.getByRole("button", { name: "下一页", exact: true });
    while (await next.isEnabled()) { await next.click(); whole += await article.locator(".reading-viewport").innerText(); }
    expect(whole).toBe(line);
  }
  expect(writes.filter(path => path !== "/api/game/session")).toEqual([]);
  expect(errors).toEqual([]);
});
