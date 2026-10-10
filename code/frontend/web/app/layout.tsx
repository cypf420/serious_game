import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "浊流之上",
  description: "一场关于基层治理、公共信任与政策执行的 90 天情境模拟。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
