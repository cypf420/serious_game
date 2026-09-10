import { expect, test, type Page, type Locator } from "@playwright/test";
import { mkdir, readFile } from "node:fs/promises";
import { resolve } from "node:path";

const account = "sandbox_web_ending_qa";
// Produced by EndingService.finalize against pkg_gameplay_v3 in an isolated test session.
const ending = JSON.parse(await readFile(resolve("e2e/fixtures/ending-from-package.json"), "utf8")) as {
  main_ending_id: string; main_ending_name: string; sub_ending_id: string; sub_ending_title: string;
  main_text: string; sub_text: string; signed_households: number; total_households: number;
  target_signed_households: number; appendices: Array<{ title: string; text: string }>;
};
const chosenTitle = ending.main_ending_name;
const chosenSubtitle = ending.sub_ending_title;

async function fixture(page: Page) {
  let selectedSession = "ending-session-a";
  let viewFails = false;
  const errors: string[] = [];
  const writes: string[] = [];
  await page.addInitScript(({ accountId }) => {
    if (!localStorage.getItem("qingjiang-sandbox-account")) localStorage.setItem("qingjiang-sandbox-account", accountId);
    const currentAccount = localStorage.getItem("qingjiang-sandbox-account");
    localStorage.setItem(`qingjiang:tutorial:v1:${currentAccount}`, JSON.stringify({ version: 1, auto: false, chapters: {} }));
  }, { accountId: account });
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/backend/**", async route => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api\/backend/, "");
    if (viewFails && path.endsWith("/view")) {
      await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ message: "存档状态读取失败" }) });
      return;
    }
    if (route.request().method() !== "GET") writes.push(path);
    const state = {
      session_id: selectedSession, status: "completed", state_version: 1, story: { day: 30 },
      ending_result: ending,
      ledger: { action_points: { remaining: 0, daily_cap: 8 }, budget: { available: 2400 }, relocation: { signed: 30, total: 36 } },
    };
    let body: Record<string, unknown> = {};
    if (path === "/health/ready") body = { authentication_required: false, model_consent_required: false };
    else if (path === "/api/ai/config") body = { active: true, mode: "personal", endpoint: "https://fixture.invalid/v1", model: "fixture-model" };
    else if (path === "/api/game/sessions") body = { sessions: [{ session_id: selectedSession, story_day: 30, status: "completed", review_only: true }] };
    else if (path === "/api/game/session" || path === `/api/game/session/${selectedSession}`) body = { session_id: selectedSession };
    else if (path.endsWith("/view")) body = { state, commands: {}, feed: { items: [{ id: "ending-line", story_day: 30, text: "本次治理工作已告一段落。" }], cursor: 1 } };
    else if (path.endsWith("/review")) body = { ending, summary: "本次签约30户。" };
    else if (path.endsWith("/actions")) body = { actions: [] };
    else if (path.endsWith("/governance")) body = { governance_actions: [], meetings: [], archives: [], document_types: [] };
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });
  return { errors, writes, selectSession: (id: string) => { selectedSession = id; }, failView: () => { viewFails = true; } };
}

async function enter(page: Page) {
  await page.goto("/");
  await expect(page.getByText("游戏已就绪", { exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /查看已有进度/ }).click();
  await page.locator(".saved-session-list button").click();
  await expect(page.getByRole("button", { name: "查看结局", exact: true })).toBeAttached();
}

const card = (page: Page) => page.getByRole("dialog", { name: chosenTitle, exact: true });
async function withinViewport(page: Page, element: Locator) {
  await expect(element).toBeVisible();
  const box = await element.boundingBox();
  const viewport = page.viewportSize()!;
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width + 1);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height + 1);
}

test("ending opens once, Escape closes, manual reopens at saved page, reload stays dismissed", async ({ page }) => {
  const result = await fixture(page);
  await enter(page);
  await expect(card(page)).toBeVisible();
  await card(page).getByRole("button", { name: "下一页", exact: true }).click();
  const pageText = await card(page).locator(".reading-viewport").innerText();
  await page.keyboard.press("Escape");
  await expect(card(page)).toHaveCount(0);
  const manual = page.getByRole("button", { name: "查看结局", exact: true });
  await manual.click();
  await expect(card(page).locator(".reading-viewport")).toHaveText(pageText);
  await card(page).getByRole("button", { name: "关闭结局弹窗", exact: true }).click();
  await expect(manual).toBeFocused();
  await enter(page);
  await expect(card(page)).toHaveCount(0);
  await manual.click();
  await expect(card(page).locator(".reading-viewport")).toHaveText(pageText);
  expect(result.errors).toEqual([]);
  expect(result.writes).toEqual([]);
});

test("ending dismissal is isolated by save and account", async ({ page }) => {
  const result = await fixture(page);
  await enter(page);
  await expect(card(page)).toBeVisible();
  await page.keyboard.press("Escape");
  result.selectSession("ending-session-b");
  await enter(page);
  await expect(card(page)).toBeVisible();
  await page.keyboard.press("Escape");
  result.selectSession("ending-session-a");
  await enter(page);
  await expect(card(page)).toHaveCount(0);
  await page.evaluate(() => localStorage.setItem("qingjiang-sandbox-account", "sandbox_web_ending_other"));
  await enter(page);
  await expect(card(page)).toBeVisible();
  expect(result.errors).toEqual([]);
});

test("failed save switch cannot show the previous save ending under the new identity", async ({ page }) => {
  const result = await fixture(page);
  await enter(page);
  await expect(card(page)).toBeVisible();
  await page.keyboard.press("Escape");
  result.selectSession("ending-session-failed");
  result.failView();
  // Switch inside the running app: a reload would discard the stale state this regression guards.
  const progress = page.getByRole("button", { name: /游戏进度/ });
  await progress.click();
  await page.getByRole("button", { name: /查看已有进度/ }).click();
  const failedResponse = page.waitForResponse(response => response.url().includes("ending-session-failed") && new URL(response.url()).pathname.endsWith("/view") && response.status() === 500);
  await page.locator(".saved-session-list button").click();
  await failedResponse;
  await expect(progress).toBeEnabled();
  await expect(card(page)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "查看结局", exact: true })).toHaveCount(0);
  const wrongKeys = await page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith("serious-game:ending:") && key.includes("ending-session-failed")));
  expect(wrongKeys).toEqual([]);
  expect(result.errors).toEqual([]);
});

test("resizing ending pages retains the original source position and focused control", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await fixture(page);
  await enter(page);
  const next = card(page).getByRole("button", { name: "下一页", exact: true });
  await next.click();
  await next.click();
  const reading = card(page).locator(".paged-reading");
  const originalOffset = Number(await reading.getAttribute("data-reading-offset"));
  expect(originalOffset).toBeGreaterThan(0);
  await next.focus();
  for (const size of [{ width: 390, height: 844 }, { width: 1920, height: 1080 }]) {
    await page.setViewportSize(size);
    await expect(async () => {
      const start = Number(await reading.getAttribute("data-reading-offset"));
      const visibleText = await reading.locator(".reading-viewport").textContent() || "";
      expect(start).toBeLessThanOrEqual(originalOffset);
      expect(start + visibleText.length).toBeGreaterThan(originalOffset);
      expect(ending.main_text.slice(start, start + visibleText.length)).toBe(visibleText);
    }).toPass();
    await expect(next).toBeFocused();
  }
});

for (const viewport of [{ width: 1920, height: 1080 }, { width: 1366, height: 768 }, { width: 390, height: 844 }]) {
  test(`ending selected title, metrics and controls fit ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const result = await fixture(page);
    await enter(page);
    await expect(card(page).getByRole("heading", { name: chosenTitle, exact: true })).toBeVisible();
    await expect(card(page).getByRole("heading", { name: chosenSubtitle, exact: true })).toBeVisible();
    await expect(card(page)).not.toContainText("未选结局不得展示");
    await expect(card(page).locator(".ending-metrics")).toHaveText("实际签约 30 / 36 户达标要求 30 / 36 户");
    await withinViewport(page, card(page));
    for (const name of ["关闭结局弹窗", "关闭结局", "查看复盘", "下一页", "上一页"]) {
      await withinViewport(page, card(page).getByRole("button", { name, exact: true }));
    }
    await mkdir("E:/严肃游戏/output", { recursive: true });
    await page.screenshot({ path: `E:/严肃游戏/output/ending-ui-${viewport.width}.png` });
    expect(result.errors).toEqual([]);
  });
}

test("long ending pages preserve main, sub and appendix order without leaking rule keys", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await fixture(page);
  await enter(page);
  await expect(card(page)).toBeVisible();
  const observed: string[] = [];
  const next = card(page).getByRole("button", { name: "下一页", exact: true });
  for (let index = 0; index < 100; index++) {
    observed.push(await card(page).locator(".reading-viewport").innerText());
    if (await next.isDisabled()) break;
    await next.click();
  }
  expect(await next.isDisabled()).toBe(true);
  const allText = observed.join("");
  const expectedText = [ending.main_text, ending.sub_text, `结局附记\n\n${ending.appendices.map(item => `${item.title}\n\n${item.text}`).join("\n\n")}`].join("\n\n");
  expect(allText).toBe(expectedText);
  expect(allText).not.toContain("DO_NOT_RENDER_INTERNAL_RULE");
});
