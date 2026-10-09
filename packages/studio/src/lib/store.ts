"use client";
import { useStore } from "zustand";
import { useStudioRuntime } from "../runtime/studio-runtime";
import type { StudioState } from "./studio-store";

export function useStudioStore<T>(selector: (state: StudioState) => T): T {
  return useStore(useStudioRuntime().uiStore, selector);
}
