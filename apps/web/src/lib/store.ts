import { create } from "zustand";
import type { StudioView } from "./types";

interface StudioState {
  view: StudioView;
  selectedNodeId: string | null;
  inspectorOpen: boolean;
  setView: (view: StudioView) => void;
  selectNode: (nodeId: string | null) => void;
  setInspectorOpen: (open: boolean) => void;
}

export const useStudioStore = create<StudioState>((set) => ({
  view: "canvas",
  selectedNodeId: "generation.resolve",
  inspectorOpen: true,
  setView: (view) => set({ view }),
  selectNode: (selectedNodeId) => set({ selectedNodeId, inspectorOpen: selectedNodeId !== null }),
  setInspectorOpen: (inspectorOpen) => set({ inspectorOpen }),
}));
