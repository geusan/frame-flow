import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const projectRoot = resolve(import.meta.dirname, "..");
const sourceRoot = join(projectRoot, "src");

function sourceFiles(directory) {
  return readdirSync(directory).flatMap((entry) => {
    const fullPath = join(directory, entry);
    return statSync(fullPath).isDirectory() ? sourceFiles(fullPath) : /\.(?:ts|tsx)$/.test(entry) ? [fullPath] : [];
  });
}

const violations = [];
const forbidden = [
  ["window.confirm", /\bwindow\.confirm\s*\(/],
  ["manual dialog role", /role=["']dialog["']/],
  ["manual aria-modal", /aria-modal=/],
  ["legacy button class", /\b(?:primary|secondary|danger|ghost|icon)-button\b/],
];

for (const file of sourceFiles(sourceRoot)) {
  const text = readFileSync(file, "utf8");
  const displayPath = relative(projectRoot, file);
  for (const [label, pattern] of forbidden) {
    if (pattern.test(text)) violations.push(`${displayPath}: ${label}`);
  }
  if (!file.includes(`${join("components", "ui")}`) && /from ["']radix-ui["']/.test(text)) {
    violations.push(`${displayPath}: import Radix through components/ui`);
  }
}

const globalsPath = join(sourceRoot, "app", "globals.css");
if (readFileSync(globalsPath, "utf8").length > 2_000) violations.push("src/app/globals.css: keep the global entrypoint import-only");

if (violations.length) {
  console.error(`UI architecture check failed:\n${violations.map((item) => `- ${item}`).join("\n")}`);
  process.exit(1);
}

console.log("UI architecture check passed");
