import assert from "node:assert/strict";
import { stat } from "node:fs/promises";
import test from "node:test";
import { selectMusicScene } from "../app/audio/music-scene.ts";

const context = { hasSession: true, nightConversationOpen: false, broadcastOpen: false, endingOpen: false, endingId: "" };

test("uses separate tracks for a night conversation and a progress broadcast", () => {
  assert.equal(selectMusicScene(context), "main");
  assert.equal(selectMusicScene({ ...context, nightConversationOpen: true }), "night");
  assert.equal(selectMusicScene({ ...context, nightConversationOpen: true, broadcastOpen: true }), "broadcast");
  assert.equal(selectMusicScene({ ...context, hasSession: false }), "none");
});

test("classifies the two rounded endings as victories and other endings as defeats", () => {
  for (const endingId of ["ending_22", "ending_23"]) {
    assert.equal(selectMusicScene({ ...context, endingOpen: true, endingId }), "victory");
  }
  for (const endingId of ["ending_01", "ending_21", "ending_24"]) {
    assert.equal(selectMusicScene({ ...context, endingOpen: true, endingId }), "defeat");
  }
  assert.equal(selectMusicScene({ ...context, endingOpen: true, endingId: "ending_22", broadcastOpen: true }), "victory");
});

test("all five scene tracks are present in the public directory", async () => {
  for (const name of ["bgm-main.mp3", "bgm-night-dialogue.mp3", "bgm-progress-broadcast.mp3", "bgm-ending-victory.mp3", "bgm-ending-defeat.mp3"]) {
    const file = new URL(`../public/audio/${name}`, import.meta.url);
    const size = (await stat(file)).size;
    assert.ok(size > 100_000, `${name} is missing or empty`);
    assert.ok(size < 25 * 1024 * 1024, `${name} exceeds the static asset limit`);
  }
});
