"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { frameflowApi, type CanvasRunRecord, type WorkflowRunRecord } from "@/lib/api";
import { isActiveRun, summaryFromRun } from "./run-model";

export function useWorkflowRuns(workflowId: string) {
  const [runs, setRuns] = useState<WorkflowRunRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<CanvasRunRecord>();
  const [error, setError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [canceling, setCanceling] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const mutation = useRef(0);
  const cancelLock = useRef(false);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const sequence = mutation.current;
      try {
        const rows = (await frameflowApi.listWorkflowRuns()).filter((run) => run.workflow_definition_id === workflowId);
        if (active && sequence === mutation.current) {
          setRuns(rows); setSelectedId((current) => current ?? rows[0]?.id ?? null); setPollError(null);
        }
      } catch (cause) { if (active) setPollError(cause instanceof Error ? cause.message : "실행 목록을 불러오지 못했습니다."); }
      finally { if (active) { setLoading(false); timer = setTimeout(poll, 3000); } }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [workflowId, revision]);

  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const sequence = mutation.current;
      try {
        const run = await frameflowApi.getCanvasRun(selectedId!);
        if (active && sequence === mutation.current) {
          setSelectedRun(run);
          if (isActiveRun(run.status)) timer = setTimeout(poll, 1500);
        }
      } catch (cause) {
        if (active) { setPollError(cause instanceof Error ? cause.message : "실행 상태를 불러오지 못했습니다."); timer = setTimeout(poll, 4000); }
      }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [selectedId, revision]);

  const addRun = useCallback((run: CanvasRunRecord) => {
    mutation.current += 1;
    setRuns((current) => [summaryFromRun(run), ...current.filter((item) => item.id !== run.id)]);
    setSelectedId(run.id); setSelectedRun(run); setRevision((current) => current + 1);
  }, []);
  const selectRun = (id: string) => { setSelectedId(id); setSelectedRun((current) => current?.id === id ? current : undefined); };
  const cancelRun = async (id: string) => {
    if (cancelLock.current) return;
    cancelLock.current = true; setCanceling(id); setError(null); mutation.current += 1;
    try {
      const current = await frameflowApi.getCanvasRun(id);
      const run = isActiveRun(current.status) ? await frameflowApi.cancelCanvasRun(id) : current;
      setRuns((rows) => rows.map((row) => row.id === id ? summaryFromRun(run) : row));
      if (id === selectedId) setSelectedRun(run);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "취소하지 못했습니다. 상태를 확인한 뒤 다시 시도해 주세요."); }
    finally { cancelLock.current = false; setCanceling(null); setRevision((current) => current + 1); }
  };
  return { runs, selectedId, selectedRun: selectedRun?.id === selectedId ? selectedRun : undefined, selectRun, addRun, cancelRun, canceling, error: error ?? pollError, loading, refresh: () => setRevision((current) => current + 1) };
}
