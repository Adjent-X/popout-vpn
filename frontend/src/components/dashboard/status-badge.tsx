import type { ConfigStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const LABELS: Record<ConfigStatus, string> = {
  active: "Active",
  expiring_soon: "Expiring soon",
  expired: "Expired",
  revoked: "Revoked",
};

export function StatusBadge({ status }: { status: ConfigStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide",
        status === "active" &&
          "border-cyan-500/30 bg-cyan-500/10 text-cyan-300 dark:text-cyan-300 text-cyan-700",
        status === "expiring_soon" &&
          "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
        status === "expired" &&
          "border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-300",
        status === "revoked" &&
          "border-destructive/40 bg-destructive/10 text-destructive",
      )}
    >
      {LABELS[status]}
    </span>
  );
}
