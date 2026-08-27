import { create } from "zustand";
import type { StudioView } from "./types";

interface StudioState {
  view: StudioView;
  selectedNodeId: string | null;
  inspectorOpen: boolean;
  selectedCanvasId: string | null;
  setView: (view: StudioView) => void;
  selectNode: (nodeId: string | null) => void;
  setInspectorOpen: (open: boolean) => void;
  openCanvas: (canvasId: string) => void;
}

export const useStudioStore = create<StudioState>((set) => ({
  view: "canvas",
  selectedNodeId: "generation.resolve",
  inspectorOpen: true,
  selectedCanvasId: null,
  setView: (view) => set({ view }),
  selectNode: (selectedNodeId) => set({ selectedNodeId, inspectorOpen: selectedNodeId !== null }),
  setInspectorOpen: (inspectorOpen) => set({ inspectorOpen }),
  openCanvas: (selectedCanvasId) => set({ selectedCanvasId, view: "canvas-editor", selectedNodeId: null, inspectorOpen: false }),
}));
