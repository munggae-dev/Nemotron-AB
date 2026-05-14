import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Nemotron-AB — 단문·이미지 A/B 평가",
  description: "Nemotron 페르소나 기반 단문·이미지 A/B 평가",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body className={`${inter.className} app-root`}>
        <Sidebar />
        <TopBar />
        <div className="main-area">
          <div className="main-inner">{children}</div>
        </div>
      </body>
    </html>
  );
}
