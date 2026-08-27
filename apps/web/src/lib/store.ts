import { create } from "zustand";
import type { NodeStatus, StudioView } from "./types";

interface StudioState {
  view: StudioView;
  selectedNodeId: string | null;
  runStatus: NodeStatus | "IDLE";
  runProgress: number;
  inspectorOpen: boolean;
  setView: (view: StudioView) => void;
  selectNode: (nodeId: string | null) => void;
  setInspectorOpen: (open: boolean) => void;
  startDemoRun: () => void;
  advanceDemoRun: () => void;
  resetRun: () => void;
}

export const useStudioStore = create<StudioState>((set, get) => ({
  view: "canvas",
  selectedNodeId: "generation.resolve",
  runStatus: "IDLE",
  runProgress: 0,
  inspectorOpen: true,
  setView: (view) => set({ view }),
  selectNode: (selectedNodeId) => set({ selectedNodeId, inspectorOpen: selectedNodeId !== null }),
  setInspectorOpen: (inspectorOpen) => set({ inspectorOpen }),
  startDemoRun: () => set({ runStatus: "RUNNING", runProgress: 12 }),
  advanceDemoRun: () => {
    const next = Math.min(100, get().runProgress + 17);
    set({ runProgress: next, runStatus: next >= 68 && next < 100 ? "WAITING_INPUT" : next === 100 ? "SUCCEEDED" : "RUNNING" });
  },
  resetRun: () => set({ runStatus: "IDLE", runProgress: 0 }),
}));

