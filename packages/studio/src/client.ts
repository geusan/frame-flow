"use client";

// Reusable views and explicit runtime ports, not a Next application or iframe.
export { StudioProvider } from "./runtime/studio-runtime";
export { createBrowserTransport } from "./lib/api-transport";
export { CanvasLibrary } from "./components/views/canvas-library";
export { GenerationCanvas } from "./components/views/generation-canvas";
export { WorkflowLibrary } from "./components/views/workflow-library";
export { WorkflowDetail } from "./components/views/workflow-detail";
export { WorkflowVersionView } from "./components/views/workflow-version-view";
export { RunsView } from "./components/views/runs-view";
export type { ApiTransport } from "./lib/api-transport";
