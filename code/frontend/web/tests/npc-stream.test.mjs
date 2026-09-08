import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { GameApi } from "../app/lib/api.ts";
import * as playerUi from "../app/lib/player-ui.ts";

test("a complete event finishes even when a proxy leaves the connection open", async () => {
  const original = globalThis.fetch;
  let cancelled = false;
  globalThis.fetch = async () => new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('{"type":"complete","result":{"state_version":4}}\n'));
    },
    cancel() { cancelled = true; },
  }));
  try {
    const result = await new GameApi("").streamWrite("s", "/turn/stream", {}, () => {});
    assert.equal(result.state_version, 4);
    assert.equal(cancelled, true);
  } finally { globalThis.fetch = original; }
});

test("a silent response stream times out without resubmitting the player turn", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (_url, options) => {
    calls++;
    return new Response(new ReadableStream({
      start(controller) {
        options.signal.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")));
      },
    }));
  };
  try {
    const api = new GameApi("");
    api.streamIdleTimeoutMs = 20;
    await assert.rejects(api.streamWrite("s", "/turn/stream", {}, () => {}), error => error.code === "CLIENT_STREAM_TIMEOUT");
    assert.equal(calls, 1);
  } finally { globalThis.fetch = original; }
});

test("parses incremental NPC events and returns the authoritative result", async () => {
  const previousFetch = globalThis.fetch;
  const encoded = new TextEncoder();
  const chunks = [
    '{"type":"stream_start"}\n{"type":"npc_start","stream_id":"npc:0","npc_id":"npc"}\n',
    '{"type":"npc_delta","stream_id":"npc:0","delta":"逐字"}\n',
    '{"type":"npc_delta","stream_id":"npc:0","delta":"回应"}\n{"type":"npc_end","stream_id":"npc:0"}\n',
    '{"type":"complete","result":{"state_version":3}}\n',
  ];
  globalThis.fetch = async () => new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoded.encode(chunk));
      controller.close();
    },
  }), { status: 200, headers: { "Content-Type": "application/x-ndjson" } });

  try {
    const api = new GameApi("/api/backend");
    const events = [];
    const result = await api.streamWrite("session 1", "/action/stream", {
      player_text: "测试",
    }, event => events.push(event));
    assert.deepEqual(events.map(event => event.type), [
      "stream_start", "npc_start", "npc_delta", "npc_delta", "npc_end", "complete",
    ]);
    assert.equal(events.filter(event => event.type === "npc_delta").map(event => event.delta).join(""), "逐字回应");
    assert.deepEqual(result, { state_version: 3 });
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("tracks thinking per NPC, progressive answers, and safe error cleanup", () => {
  assert.equal(typeof playerUi.reduceNpcStream, "function");
  let state = playerUi.initialNpcStreamState();
  for (const event of [
    { type: "npc_thinking_start", stream_id: "a:0", npc_id: "a", npc_name: "甲" },
    { type: "npc_thinking_end", stream_id: "a:0", npc_id: "a", npc_name: "甲" },
    { type: "npc_start", stream_id: "a:0", npc_id: "a", npc_name: "甲" },
    { type: "npc_delta", stream_id: "a:0", delta: "答" },
    { type: "npc_delta", stream_id: "a:0", delta: "复" },
    { type: "npc_end", stream_id: "a:0", npc_id: "a" },
  ]) state = playerUi.reduceNpcStream(state, event);
  assert.deepEqual(state.thinking, {});
  assert.deepEqual(state.replies, [{ stream_id: "a:0", npc_id: "a", npc_name: "甲", text: "答复", complete: true }]);
  state = playerUi.reduceNpcStream(state, { type: "npc_thinking_start", stream_id: "b:0", npc_id: "b", npc_name: "乙" });
  state = playerUi.reduceNpcStream(state, { type: "error", code: "NPC_RESPONSE_UNAVAILABLE", message: "对方暂时无法回应，请稍后重试。" });
  assert.deepEqual(state.thinking, {});
  assert.equal(state.error, "对方暂时无法回应，请稍后重试。");
});

test("keeps repeated backend stream IDs separate across successive NPC replies", () => {
  let state = playerUi.initialNpcStreamState();
  state = playerUi.reduceNpcStream(state, { type: "npc_start", stream_id: "npc:0", npc_id: "npc-a", npc_name: "甲" });
  state = playerUi.reduceNpcStream(state, { type: "npc_delta", stream_id: "npc:0", delta: "第一轮" });
  state = playerUi.reduceNpcStream(state, { type: "npc_end", stream_id: "npc:0" });
  state = playerUi.reduceNpcStream(state, { type: "npc_start", stream_id: "npc:0", npc_id: "npc-b", npc_name: "乙" });
  state = playerUi.reduceNpcStream(state, { type: "npc_delta", stream_id: "npc:0", delta: "第二轮" });
  state = playerUi.reduceNpcStream(state, { type: "npc_end", stream_id: "npc:0" });

  assert.deepEqual(state.replies.map(reply => [reply.stream_id, reply.npc_id, reply.text, reply.complete]), [
    ["npc:0", "npc-a", "第一轮", true],
    ["npc:0#2", "npc-b", "第二轮", true],
  ]);
});

test("shows an immediate pending state until the first NPC response event", () => {
  let state = playerUi.initialNpcStreamState();
  state = playerUi.reduceNpcStream(state, { type: "request_started" });
  assert.equal(state.requestPending, true);

  state = playerUi.reduceNpcStream(state, { type: "stream_start" });
  assert.equal(state.requestPending, true, "transport startup is not yet an NPC response");

  state = playerUi.reduceNpcStream(state, {
    type: "npc_thinking_start",
    stream_id: "npc:0",
    npc_id: "npc",
    npc_name: "对方",
  });
  assert.equal(state.requestPending, true, "the request stays pending until reply text starts");
  assert.equal(state.thinking["npc:0"].npc_name, "对方");

  state = playerUi.reduceNpcStream(state, {
    type: "npc_start",
    stream_id: "npc:0",
    npc_id: "npc",
    npc_name: "对方",
  });
  assert.equal(state.requestPending, false);

  state = playerUi.reduceNpcStream(state, { type: "request_finished" });
  assert.equal(state.requestPending, false);
});

test("styles the central AI waiting layer used by streamed NPC replies", async () => {
  const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
  assert.match(css, /\.ai-thinking-banner\s*\{[^}]*top:\s*50%/s);
  assert.match(css, /\.ai-thinking-banner\s+strong\s*\{[^}]*font-size:\s*24px/s);
});

test("loads complete paginated conversation history with stable filters", async () => {
  const previousFetch = globalThis.fetch;
  const requested = [];
  globalThis.fetch = async url => {
    requested.push(String(url));
    const second = String(url).includes("cursor=next-page");
    return Response.json(second
      ? { items: [{ conversation_id: "c2", transcript: [{ speaker_type: "npc", text: "完整第二页" }] }], next_cursor: null }
      : { items: [{ conversation_id: "c1", transcript: [{ speaker_type: "player", text: "第一页" }] }], next_cursor: "next-page" });
  };
  try {
    const api = new GameApi("/api/backend");
    assert.equal(typeof api.completeConversationHistory, "function");
    const items = await api.completeConversationHistory("session 1", { npc_id: "npc a", story_day: 8, limit: 1 });
    assert.deepEqual(items.map(item => item.conversation_id), ["c1", "c2"]);
    assert.equal(requested.length, 2);
    assert.match(requested[0], /npc_id=npc\+a/);
    assert.match(requested[0], /story_day=8/);
    assert.match(requested[1], /cursor=next-page/);
  } finally {
    globalThis.fetch = previousFetch;
  }
});
