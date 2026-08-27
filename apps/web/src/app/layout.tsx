import type { Metadata } from "next";
import { Inter, Manrope } from "next/font/google";
import "@xyflow/react/dist/style.css";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const manrope = Manrope({ subsets: ["latin"], variable: "--font-manrope" });

export const metadata: Metadata = {
  title: "Frameflow — Reference to Shorts",
  description: "Reference-aware, graph-based AI shorts production studio",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body className={`${inter.variable} ${manrope.variable}`}>{children}</body>
    </html>
  );
}

