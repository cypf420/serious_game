"use client";
import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { useTutorialOverlayActive } from "../tutorial/TutorialProvider";

export type SigningReward = { reward_id: string; threshold: number; title: string; earned: boolean; acknowledged: boolean; received_day: number | null };

const REWARD_IMAGES: Partial<Record<number, string>> = {
  1: "/achievements/signing-1.png",
  3: "/achievements/signing-3.png",
  10: "/achievements/signing-10.png",
  18: "/achievements/signing-18.png",
  30: "/achievements/signing-30.png",
  36: "/achievements/signing-36.png",
};

export function AutoSigningReward({ sessionId, threshold, stateVersion, blocked, onReceive }: {
  sessionId: string; threshold?: number; stateVersion: number; blocked: boolean;
  onReceive: (threshold: number, automatic: boolean) => Promise<void>;
}) {
  const tutorialActive = useTutorialOverlayActive();
  const attempt = useRef("");
  useEffect(() => {
    if (!sessionId || threshold === undefined || blocked || tutorialActive) return;
    const key = `${sessionId}:${threshold}:${stateVersion}`;
    if (attempt.current === key) return;
    attempt.current = key;
    void onReceive(threshold, true);
  }, [sessionId, threshold, stateVersion, blocked, tutorialActive, onReceive]);
  return null;
}

export function SigningRewardCard({ reward, playerName }: { reward: SigningReward; playerName: string }) {
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);
  const image = REWARD_IMAGES[reward.threshold];
  async function download() {
    setDownloading(true); setError("");
    try {
      await document.fonts.ready;
      if (!image) throw new Error("该成就图片暂不可用，请刷新后重试。");
      const canvas = document.createElement("canvas"); canvas.width = 1920; canvas.height = 1080;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("当前浏览器无法生成纪念图片，请更换浏览器后重试。");
      const artwork = new window.Image(); artwork.src = image;
      try { await artwork.decode(); }
      catch { throw new Error("成就图片加载失败，请检查连接后重试。"); }
      ctx.drawImage(artwork, 0, 0, canvas.width, canvas.height);
      // The supplied artwork leaves its bottom edge clear of the achievement.
      ctx.fillStyle = "rgba(18, 52, 41, .92)"; ctx.fillRect(0, 1008, 1920, 72);
      ctx.fillStyle = "#f4dfaa"; ctx.textAlign = "left";
      ctx.font = '28px "Microsoft YaHei", sans-serif'; ctx.fillText(`${playerName}县长 · ${reward.title}`, 48, 1054);
      ctx.textAlign = "right"; ctx.fillText(`2026年 · 游戏第 ${reward.received_day ?? "—"} 日领取`, 1872, 1054);
      const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(value => value ? resolve(value) : reject(new Error("图片生成失败，请重试。")), "image/png"));
      const url = URL.createObjectURL(blob); const link = document.createElement("a");
      link.href = url; link.download = `浊流之上-${playerName}-签约${reward.threshold}户纪念.png`;
      document.body.append(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (error) { setError(error instanceof Error ? error.message : "下载失败，请重试。"); }
    finally { setDownloading(false); }
  }
  return <div className="signing-reward-card">
    {image ? <Image className="signing-reward-art" src={image} alt={`${reward.threshold}户成就：${reward.title}`} width={1920} height={1080} unoptimized onError={() => setError("成就图片加载失败，请刷新后重试。")} /> : <p role="alert">该成就图片暂不可用，请刷新后重试。</p>}
    <p>{playerName}县长 · 累计签约 {reward.threshold} 户</p>
    <p>2026年 · 游戏第 {reward.received_day ?? "—"} 日领取</p>
    <button type="button" disabled={downloading} onClick={() => void download()}>{downloading ? "正在生成图片…" : "下载纪念图片（PNG）"}</button>
    {error && <p role="alert">{error}</p>}
  </div>;
}

export function SigningRewardAlbum({ rewards, busy, onOpen }: { rewards: SigningReward[]; busy: boolean; onOpen: (threshold: number) => void }) {
  return <div className="signing-reward-album"><p>按实际签约户数解锁六项成就，可随时再次查看和下载。</p><div>{rewards.map(reward => <button type="button" key={reward.reward_id} disabled={busy || (!reward.earned && !reward.acknowledged)} onClick={() => onOpen(reward.threshold)}><b>{reward.threshold} 户</b><span>{reward.title}</span><small>{reward.acknowledged ? "已领取 · 查看与下载" : reward.earned ? "已达到 · 领取成就" : "尚未达到"}</small></button>)}</div></div>;
}
