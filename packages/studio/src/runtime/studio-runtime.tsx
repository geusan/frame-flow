"use client";

import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";
import { API_BASE, frameflowApi, createFrameflowApi } from "../lib/api";
import type { ApiTransport } from "../lib/api-transport";
import { draftBackups } from "../lib/draft-backups";
import { createStudioStore } from "../lib/studio-store";

type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export interface StudioRuntime {
  frameflowApi: ReturnType<typeof createFrameflowApi>;
  API_BASE: string;
  draftBackups: DraftStorage;
  uiStore: ReturnType<typeof createStudioStore>;
}

const noDraftStorage: DraftStorage = {
  getItem: () => null,
  setItem: () => undefined,
  removeItem: () => undefined,
};

// Compatibility for the public standalone app. Authenticated hosts supply a
// provider with an immutable transport and fresh state for every workspace.
const standaloneRuntime: StudioRuntime = { frameflowApi, API_BASE, draftBackups, uiStore: createStudioStore() };
const RuntimeContext = createContext<StudioRuntime | null>(null);

export function StudioProvider({ transport, children, onSessionExpired }: {
  transport: ApiTransport;
  children: ReactNode;
  onSessionExpired?: () => void;
}) {
  const mountedScopes = useRef(new Set<AbortController>());
  const scope = useMemo(() => {
    const controller = new AbortController();
    const scopedTransport: ApiTransport = {
      baseUrl: transport.baseUrl,
      async send(path, init) {
        const signal = init?.signal ? AbortSignal.any([controller.signal, init.signal]) : controller.signal;
        const response = await transport.send(path, { ...init, signal });
        if (response.status === 401) onSessionExpired?.();
        return response;
      },
    };
    return { controller, runtime: {
      frameflowApi: createFrameflowApi(scopedTransport), API_BASE: scopedTransport.baseUrl,
      draftBackups: noDraftStorage, uiStore: createStudioStore(),
    } satisfies StudioRuntime };
  }, [transport, onSessionExpired]);
  useEffect(() => {
    const mounted = mountedScopes.current;
    mounted.add(scope.controller);
    return () => {
      mounted.delete(scope.controller);
      // React Strict Mode repeats setup/cleanup in development. A real scope
      // replacement stays unmounted; its outstanding requests are canceled.
      queueMicrotask(() => { if (!mounted.has(scope.controller)) scope.controller.abort(); });
    };
  }, [scope]);
  return <RuntimeContext.Provider value={scope.runtime}>{children}</RuntimeContext.Provider>;
}

export function useStudioRuntime(): StudioRuntime {
  return useContext(RuntimeContext) ?? standaloneRuntime;
}
