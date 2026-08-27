import { Check, Clock3, LoaderCircle, ShieldAlert, Sparkles, TriangleAlert } from "lucide-react";
import type { NodeStatus } from "@/lib/types";

const labels: Partial<Record<NodeStatus, string>> = {
  BLOCKED: "Blocked",
  READY: "Ready",
  QUEUED: "Queued",
  SUBMITTED: "Submitted",
  RUNNING: "Running",
  WAITING_INPUT: "Needs review",
  RETRY_WAIT: "Retrying",
  SUCCEEDED: "Succeeded",
  FAILED: "Failed",
  CANCELED: "Canceled",
  STALE: "Stale",
};

export function StatusPill({ status, compact = false }: { status: NodeStatus; compact?: boolean }) {
  const Icon = status === "SUCCEEDED"
    ? Check
    : status === "RUNNING" || status === "SUBMITTED"
      ? LoaderCircle
      : status === "WAITING_INPUT"
        ? Sparkles
        : status === "FAILED"
          ? TriangleAlert
          : status === "BLOCKED"
            ? ShieldAlert
            : Clock3;
  return (
    <span className={`status-pill status-${status.toLowerCase()} ${compact ? "compact" : ""}`}>
      <Icon size={compact ? 11 : 12} className={status === "RUNNING" ? "spin" : ""} />
      {!compact && (labels[status] ?? status)}
    </span>
  );
}

