import type { CSSProperties } from "react";
import type { RegisteredFont } from "@/lib/api";

const loadedFonts = new Map<string, Promise<FontFace>>();

export function loadRegisteredFont(font: RegisteredFont): Promise<FontFace> {
  const key = `${font.css_family}:${font.sha256}`;
  const current = loadedFonts.get(key);
  if (current) return current;
  const loading = new FontFace(
    font.css_family,
    `url("${font.url}")`,
    { style: font.style, weight: String(font.weight), display: "swap" },
  ).load().then((face) => {
    document.fonts.add(face);
    return face;
  }).catch((error: unknown) => {
    loadedFonts.delete(key);
    throw error;
  });
  loadedFonts.set(key, loading);
  return loading;
}

export function fontPreviewStyle(font: RegisteredFont): CSSProperties {
  return {
    fontFamily: `"${font.css_family}", "Noto Sans KR", sans-serif`,
    fontWeight: font.weight,
    fontStyle: font.style,
    fontSize: `${font.size_adjust}em`,
  };
}
