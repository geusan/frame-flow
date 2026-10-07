import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  basePath: process.env.CORE_WEB_BASE_PATH || "",
  distDir: process.env.CORE_WEB_DIST_DIR || ".next",
};

export default nextConfig;
