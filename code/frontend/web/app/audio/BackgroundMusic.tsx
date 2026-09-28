"use client";

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { MusicScene } from "./music-scene";

const STORAGE_KEY = "serious-game:scene-music-enabled";
const MusicControls = createContext<{ enabled: boolean | null; toggle: () => void } | null>(null);
const TRACKS: Record<Exclude<MusicScene, "none">, { src: string; volume: number }> = {
  main: { src: "/audio/bgm-main.mp3", volume: 0.22 },
  night: { src: "/audio/bgm-night-dialogue.mp3", volume: 0.24 },
  broadcast: { src: "/audio/bgm-progress-broadcast.mp3", volume: 0.28 },
  victory: { src: "/audio/bgm-ending-victory.mp3", volume: 0.32 },
  defeat: { src: "/audio/bgm-ending-defeat.mp3", volume: 0.32 },
};

function playScene(audios: Partial<Record<Exclude<MusicScene, "none">, HTMLAudioElement>>, scene: Exclude<MusicScene, "none">) {
  const track = TRACKS[scene];
  let audio = audios[scene];
  if (!audio) {
    audio = new Audio();
    audio.preload = "none";
    audio.src = track.src;
    audio.loop = true;
    audio.volume = track.volume;
    audios[scene] = audio;
  }
  void audio.play().catch(() => {
    // The next player interaction retries when a browser blocks autoplay.
  });
}

export function BackgroundMusic({ scene, children }: { scene: MusicScene; children: ReactNode }) {
  const audiosRef = useRef<Partial<Record<Exclude<MusicScene, "none">, HTMLAudioElement>>>({});
  const [enabled, setEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    let disposed = false;
    queueMicrotask(() => {
      if (disposed) return;
      try { setEnabled(window.localStorage.getItem(STORAGE_KEY) !== "off"); }
      catch { setEnabled(true); }
    });
    return () => {
      disposed = true;
      Object.values(audiosRef.current).forEach(audio => {
        audio.pause();
        audio.removeAttribute("src");
      });
      audiosRef.current = {};
    };
  }, []);

  useEffect(() => {
    Object.entries(audiosRef.current).forEach(([name, audio]) => {
      if (name !== scene || !enabled) audio.pause();
    });
    if (enabled && scene !== "none") playScene(audiosRef.current, scene);
  }, [enabled, scene]);

  useEffect(() => {
    if (!enabled || scene === "none") return;
    const retry = () => {
      if (audiosRef.current[scene]?.paused) playScene(audiosRef.current, scene);
    };
    window.addEventListener("pointerdown", retry, { passive: true });
    window.addEventListener("keydown", retry);
    return () => {
      window.removeEventListener("pointerdown", retry);
      window.removeEventListener("keydown", retry);
    };
  }, [enabled, scene]);

  const toggle = () => {
    const next = enabled !== true;
    setEnabled(next);
    try { window.localStorage.setItem(STORAGE_KEY, next ? "on" : "off"); } catch { /* Keep the choice for this page. */ }
    if (next && scene !== "none") playScene(audiosRef.current, scene);
  };

  return <MusicControls.Provider value={{ enabled, toggle }}>{children}</MusicControls.Provider>;
}

export function MusicToggle() {
  const controls = useContext(MusicControls);
  if (!controls) return null;
  const { enabled, toggle } = controls;
  return <button type="button" className="scene-music-toggle" aria-label={enabled ? "关闭场景音乐" : "开启场景音乐"} aria-pressed={enabled === true} onClick={toggle}>
    <span className="scene-music-full">音乐：{enabled ? "开" : "关"}</span><span className="scene-music-short" aria-hidden="true">♫{enabled ? "开" : "关"}</span>
  </button>;
}
