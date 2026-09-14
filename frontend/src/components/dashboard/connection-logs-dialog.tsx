"use client";

import { useEffect, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { PrivateWanIp } from "@/components/dashboard/private-wan-ip";
import {
  ApiError,
  fetchConnectionLogs,
  type ClientConfig,
  type ConnectionLogEntry,
} from "@/lib/api";

function formatDateTime(iso: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "medium",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function EventBadge({ event }: { event: string }) {
  const isConnect = event.toLowerCase().includes("connect") && !event.toLowerCase().includes("dis");
  return (
    <span
      className={
        "inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide " +
        (isConnect
          ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-300 dark:text-cyan-300 text-cyan-700"
          : "border-border bg-secondary/40 text-muted-foreground")
      }
    >
      {event}
    </span>
  );
}

type ConnectionLogsDialogProps = {
  config: ClientConfig | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function ConnectionLogsDialog({
  config,
  open,
  onOpenChange,
}: ConnectionLogsDialogProps) {
  const [logs, setLogs] = useState<ConnectionLogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !config) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const data = await fetchConnectionLogs(config.id);
        if (!cancelled) setLogs(data);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.message
              : "Could not load connection logs.",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, config]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" showCloseButton>
        <DialogHeader>
          <DialogTitle>Connection logs</DialogTitle>
          <DialogDescription>
            Recent connect/disconnect events for{" "}
            <strong>{config?.label ?? "this config"}</strong>.
          </DialogDescription>
        </DialogHeader>

        {error && (
          <p
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
          >
            {error}
          </p>
        )}

        <div className="max-h-[min(24rem,55dvh)] overflow-auto rounded-lg border border-border/70">
          <table className="w-full min-w-[360px] text-left text-xs">
            <thead className="border-b border-border bg-secondary/40">
              <tr>
                <th className="px-3 py-2 font-medium">Time</th>
                <th className="px-3 py-2 font-medium">Event</th>
                <th className="px-3 py-2 font-medium">WAN IP</th>
                <th className="px-3 py-2 font-medium">VPN IP</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td
                    colSpan={4}
                    className="px-3 py-8 text-center font-mono text-muted-foreground"
                  >
                    Loading…
                  </td>
                </tr>
              )}
              {!loading && logs.length === 0 && !error && (
                <tr>
                  <td
                    colSpan={4}
                    className="px-3 py-8 text-center text-muted-foreground"
                  >
                    No connection events recorded yet.
                  </td>
                </tr>
              )}
              {!loading &&
                logs.map((log) => (
                  <tr
                    key={log.id}
                    className="border-b border-border/60 last:border-0"
                  >
                    <td className="px-3 py-2 font-mono text-[11px] text-muted-foreground">
                      {formatDateTime(log.at)}
                    </td>
                    <td className="px-3 py-2">
                      <EventBadge event={log.event} />
                    </td>
                    <td className="px-3 py-2 font-mono text-[11px]">
                      <PrivateWanIp ip={log.wan_ip} />
                      {log.wan_ip && !log.wan_logged && (
                        <span
                          className="ml-1 text-muted-foreground"
                          title="Not persisted to long-term log"
                        >
                          (unlogged)
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono text-[11px]">
                      {log.vpn_ip ?? "—"}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>

        <DialogFooter showCloseButton />
      </DialogContent>
    </Dialog>
  );
}
