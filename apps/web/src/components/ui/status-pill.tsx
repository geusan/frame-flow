import { Check, Clock3, LoaderCircle, ShieldAlert, Sparkles, TriangleAlert } from "lucide-react";
import { Badge, badgeVariants } from "@/components/ui/badge";
import type { NodeStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { VariantProps } from "class-variance-authority";

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

const statusVariants: Record<NodeStatus, NonNullable<VariantProps<typeof badgeVariants>["variant"]>> = {
  BLOCKED: "danger",
  READY: "default",
  QUEUED: "default",
  CLAIMED: "info",
  SUBMITTED: "info",
  RUNNING: "info",
  WAITING_INPUT: "warning",
  RETRY_WAIT: "default",
  SUCCEEDED: "success",
  FAILED: "danger",
  CANCELED: "default",
  STALE: "default",
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
    <Badge
      variant={statusVariants[status]}
      className={cn(
        "min-h-[23px] rounded-[10px] px-2 text-[length:var(--text-sm)]",
        compact && "size-[18px] min-h-[18px] justify-center rounded-full p-0",
      )}
    >
      <Icon size={compact ? 11 : 12} className={status === "RUNNING" ? "spin" : ""} />
      {!compact && (labels[status] ?? status)}
    </Badge>
  );
}
