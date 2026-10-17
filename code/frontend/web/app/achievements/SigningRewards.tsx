"use client";
import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { useTutorialOverlayActive } from "../tutorial/TutorialProvider";

export type SigningReward = { reward_id: string; threshold: number; title: string; earned: boolean; acknowledged: boolean; received_day: number | null };

// Replace these same-origin image paths when the four approved banners arrive.
const REWARD_IMAGES: Partial<Record<number, string>> = {};

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
      const canvas = document.createElement("canvas"); canvas.width = 1080; canvas.height = 1440;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("当前浏览器无法生成纪念图片，请更换浏览器后重试。");
      ctx.fillStyle = "#f5ead0"; ctx.fillRect(0, 0, 1080, 1440);
      if (image) {
        const artwork = new window.Image(); artwork.src = image; await artwork.decode();
        const scale = Math.min(1000 / artwork.width, 1100 / artwork.height);
        ctx.drawImage(artwork, (1080 - artwork.width * scale) / 2, 40, artwork.width * scale, artwork.height * scale);
      } else {
        ctx.fillStyle = "#7b3028"; ctx.fillRect(80, 70, 920, 1060);
        ctx.strokeStyle = "#d8b775"; ctx.lineWidth = 8; ctx.strokeRect(105, 95, 870, 1010);
        ctx.fillStyle = "#f4dfaa"; ctx.textAlign = "center";
        ctx.font = '44px "Microsoft YaHei", sans-serif'; ctx.fillText("浊流之上 · 云溪县", 540, 240);
        ctx.font = 'bold 88px "Microsoft YaHei", sans-serif'; ctx.fillText("签约纪念", 540, 480);
        ctx.font = 'bold 132px "Microsoft YaHei", sans-serif'; ctx.fillText(`${reward.threshold} 户`, 540, 710);
        ctx.font = '32px "Microsoft YaHei", sans-serif'; ctx.fillText("临时样式 · 正式锦旗待替换", 540, 990);
      }
      ctx.textAlign = "center"; ctx.fillStyle = "#4a3424";
      ctx.font = 'bold 52px "Microsoft YaHei", sans-serif'; ctx.fillText(`${playerName}县长`, 540, 1230);
      ctx.font = '32px "Microsoft YaHei", sans-serif'; ctx.fillText(`2026年 · 游戏第 ${reward.received_day ?? "—"} 日领取`, 540, 1320);
      const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(value => value ? resolve(value) : reject(new Error("图片生成失败，请重试。")), "image/png"));
      const url = URL.createObjectURL(blob); const link = document.createElement("a");
      link.href = url; link.download = `浊流之上-${playerName}-签约${reward.threshold}户纪念.png`;
      document.body.append(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (error) { setError(error instanceof Error ? error.message : "下载失败，请重试。"); }
    finally { setDownloading(false); }
  }
  return <div className="signing-reward-card">
    {image ? <Image className="signing-reward-art" src={image} alt={reward.title} width={1080} height={1440} unoptimized /> : <figure className="signing-reward-banner" aria-label={`${reward.title}，临时样式`}><small>浊流之上 · 云溪县</small><h3>签约纪念</h3><strong>{reward.threshold}<span>户</span></strong><p>{playerName}县长</p><figcaption>临时样式 · 正式锦旗待替换</figcaption></figure>}
    <p>2026年 · 游戏第 {reward.received_day ?? "—"} 日领取</p>
    <button type="button" disabled={downloading} onClick={() => void download()}>{downloading ? "正在生成图片…" : "下载纪念图片（PNG）"}</button>
    {error && <p role="alert">{error}</p>}
  </div>;
}

export function SigningRewardAlbum({ rewards, busy, onOpen }: { rewards: SigningReward[]; busy: boolean; onOpen: (threshold: number) => void }) {
  return <div className="signing-reward-album"><p>按实际签约户数获得纪念，可随时再次查看和下载。</p><div>{rewards.map(reward => <button type="button" key={reward.reward_id} disabled={busy || (!reward.earned && !reward.acknowledged)} onClick={() => onOpen(reward.threshold)}><b>{reward.threshold} 户</b><span>{reward.title}</span><small>{reward.acknowledged ? "已领取 · 查看与下载" : reward.earned ? "已达到 · 领取纪念" : "尚未达到"}</small></button>)}</div><small>当前使用临时样式，正式锦旗素材到齐后更新。</small></div>;
}
