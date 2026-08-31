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

const generationCanvasPath = join(sourceRoot, "components", "views", "generation-canvas.tsx");
const generationCanvas = readFileSync(generationCanvasPath, "utf8");
if (/\[\.\.\.nodeTemplates,\s*\.\.\.registryTemplates\]/.test(generationCanvas)) {
  violations.push("src/components/views/generation-canvas.tsx: production Node Library must use Registry templates");
}
if (/definitions\.filter\(\(definition\) => definition\.editor\.kind === ["']generic["']\)/.test(generationCanvas)) {
  violations.push("src/components/views/generation-canvas.tsx: do not exclude legacy-editor manifests from the Registry Library");
}
if (/providerOptionsForNode|modelOptionsForNode|googleTextModelOptions/.test(generationCanvas)) {
  violations.push("src/components/views/generation-canvas.tsx: Provider/model choices must come from Manifest capabilities and the Model Registry");
}
if (/\bisConnectionCompatible\b/.test(generationCanvas)) {
  violations.push("src/components/views/generation-canvas.tsx: production connections must use versioned Registry Port contracts");
}
const inspectorStart = generationCanvas.indexOf('<div className="inspector-content">');
const inspectorEnd = generationCanvas.indexOf('<div className="inspector-edit-actions">', inspectorStart);
const inspectorSource = inspectorStart >= 0 && inspectorEnd > inspectorStart ? generationCanvas.slice(inspectorStart, inspectorEnd) : "";
if (/selectedNode\.data\.key\s*(?:===|!==)/.test(inspectorSource)) {
  violations.push("src/components/views/generation-canvas.tsx: Node-specific Inspector UI belongs in the versioned Custom Editor Registry");
}

const modelOptionsPath = join(sourceRoot, "features", "nodes", "model-options.ts");
const modelOptions = readFileSync(modelOptionsPath, "utf8");
if (/\bnodeKey\b|\bnode_key\b/.test(modelOptions)) {
  violations.push("src/features/nodes/model-options.ts: capability resolution must not branch on Node keys");
}

const portContractsPath = join(sourceRoot, "features", "nodes", "port-contracts.ts");
const portContracts = readFileSync(portContractsPath, "utf8");
if (/node\.data\.key\s*(?:===|!==)|\bnodeKey\b|\bnode_key\b/.test(portContracts)) {
  violations.push("src/features/nodes/port-contracts.ts: Port compatibility must resolve from Node Definitions, not Node keys");
}
if (/\.filter\(\(edge\) => isConnectionCompatible/.test(generationCanvas)) {
  violations.push("src/components/views/generation-canvas.tsx: Legacy or Unknown edges must be preserved during load");
}

const customEditorRegistryPath = join(sourceRoot, "features", "nodes", "custom-editors", "registry.tsx");
const customEditorRegistry = readFileSync(customEditorRegistryPath, "utf8");
const implementedEditorRefs = new Set([...customEditorRegistry.matchAll(/^\s*"([a-z][a-z0-9-]*)": \(props\) =>/gm)].map((match) => match[1]));
const legacyEditorMappings = [...customEditorRegistry.matchAll(/^\s*"([a-z][a-z0-9_.]*@[1-9][0-9]*)": "([a-z][a-z0-9-]*)",/gm)].map((match) => ({ contractId: match[1], ref: match[2] }));
const definitionsRoot = resolve(projectRoot, "..", "api", "app", "nodes", "definitions");
const definitions = readdirSync(definitionsRoot).filter((entry) => entry.endsWith(".json")).flatMap((entry) => {
  const document = JSON.parse(readFileSync(join(definitionsRoot, entry), "utf8"));
  return Array.isArray(document) ? document : [document];
});
const definitionIds = new Set(definitions.map((definition) => `${definition.type_key}@${definition.contract_version}`));
const editorCatalogPath = resolve(projectRoot, "..", "api", "app", "nodes", "editor_refs.v1.json");
const editorCatalog = JSON.parse(readFileSync(editorCatalogPath, "utf8"));
const catalogRefs = new Set(editorCatalog.refs);
for (const ref of catalogRefs) {
  if (!implementedEditorRefs.has(ref)) violations.push(`src/features/nodes/custom-editors/registry.tsx: missing implementation for editor ref ${ref}`);
}
for (const ref of implementedEditorRefs) {
  if (!catalogRefs.has(ref)) violations.push(`src/features/nodes/custom-editors/registry.tsx: unregistered editor ref ${ref}`);
}
for (const mapping of legacyEditorMappings) {
  if (!definitionIds.has(mapping.contractId)) violations.push(`src/features/nodes/custom-editors/registry.tsx: unknown Node contract ${mapping.contractId}`);
  if (!catalogRefs.has(mapping.ref)) violations.push(`src/features/nodes/custom-editors/registry.tsx: unknown legacy editor ref ${mapping.ref}`);
}
for (const definition of definitions.filter((item) => item.editor?.kind === "custom")) {
  if (!implementedEditorRefs.has(definition.editor.ref)) violations.push(`src/features/nodes/custom-editors/registry.tsx: missing Manifest editor ${definition.editor.ref}`);
}

if (violations.length) {
  console.error(`UI architecture check failed:\n${violations.map((item) => `- ${item}`).join("\n")}`);
  process.exit(1);
}

console.log("UI architecture check passed");
