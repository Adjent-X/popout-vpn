"use client";

import { useEffect, useState } from "react";

import {
  PercentagePieChart,
  pieColors,
} from "@/components/dashboard/percentage-pie-chart";
import { PrivateWanIp } from "@/components/dashboard/private-wan-ip";
import { WorldAttackMap } from "@/components/dashboard/world-attack-map";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  ApiError,
  fetchPcapAnalysis,
  type AttackEventItem,
  type PcapAnalysis,
} from "@/lib/api";

function formatBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

type PcapAnalysisDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pcapName: string | null;
  event?: AttackEventItem | null;
};

export function PcapAnalysisDialog({
  open,
  onOpenChange,
  pcapName,
  event,
}: PcapAnalysisDialogProps) {
  const [data, setData] = useState<PcapAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !pcapName) {
      setData(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const result = await fetchPcapAnalysis(pcapName);
        if (!cancelled) setData(result);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.message
              : "Could not analyze capture with tshark.",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, pcapName]);

  async function onRefresh() {
    if (!pcapName) return;
    setLoading(true);
    setError(null);
    try {
      const result = await fetchPcapAnalysis(pcapName, true);
      setData(result);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not analyze capture with tshark.",
      );
    } finally {
      setLoading(false);
    }
  }

  const protoColors = pieColors(data?.protocols.length ?? 0);
  const countryColors = pieColors(data?.countries.length ?? 0);
  const serviceColors = pieColors(data?.services.length ?? 0);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[min(90dvh,48rem)] overflow-y-auto sm:max-w-4xl"
        showCloseButton
      >
        <DialogHeader>
          <DialogTitle>Capture analysis</DialogTitle>
          <DialogDescription>
            tshark line-by-line heuristics for{" "}
            <span className="font-mono text-foreground">
              {pcapName ?? "—"}
            </span>
            {event?.severity ? (
              <>
                {" "}
                · event <span className="uppercase">{event.severity}</span>
              </>
            ) : null}
          </DialogDescription>
        </DialogHeader>

        {loading && (
          <p className="font-mono text-sm text-muted-foreground">
            Parsing packets with tshark…
          </p>
        )}
        {error && (
          <p
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
          >
            {error}
          </p>
        )}

        {data && !loading && (
          <div className="space-y-6">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Packets" value={data.packet_count.toLocaleString()} />
              <Stat label="Sources" value={String(data.unique_sources)} />
              <Stat label="Avg size" value={formatBytes(data.avg_packet_bytes)} />
              <Stat
                label="Duration"
                value={
                  data.duration_sec != null
                    ? `${data.duration_sec.toFixed(2)}s`
                    : "—"
                }
              />
            </div>

            {(data.gre_ratio_pct ?? 0) > 0 && (
              <p className="font-mono text-xs text-muted-foreground">
                GRE / tunnel encapsulation:{" "}
                {(data.gre_ratio_pct ?? 0).toFixed(1)}% of packets
                {data.gre_packets != null
                  ? ` (${data.gre_packets.toLocaleString()} pkts)`
                  : ""}
              </p>
            )}

            {data.truncated && (
              <p className="text-xs text-amber-300/90">
                Analysis capped at the first {data.analyzed_packets.toLocaleString()}{" "}
                packets for responsiveness.
              </p>
            )}

            <div className="space-y-2">
              <h3 className="text-sm font-medium">Heuristics</h3>
              <ul className="space-y-1.5">
                {data.heuristics.map((h) => (
                  <li
                    key={h.id}
                    className="flex items-center justify-between gap-3 rounded-md border border-border/60 bg-secondary/20 px-3 py-2 text-sm"
                  >
                    <span>{h.label}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {h.confidence.toFixed(0)}%
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <PercentagePieChart
                title="Protocol breakdown"
                slices={data.protocols.map((p, i) => ({
                  name: p.name,
                  value: p.packets,
                  pct: p.pct_packets,
                  color: protoColors[i],
                }))}
              />
              <PercentagePieChart
                title="Country breakdown (sources)"
                slices={data.countries.map((c, i) => ({
                  name: c.label || c.code,
                  value: c.packets,
                  pct: c.pct_packets,
                  color: countryColors[i],
                }))}
              />
            </div>

            {data.services.length > 0 && (
              <PercentagePieChart
                title="Service / amp hints (src-port)"
                slices={data.services.map((s, i) => ({
                  name: s.name,
                  value: s.packets,
                  pct: s.pct_packets,
                  color: serviceColors[i],
                }))}
              />
            )}

            <WorldAttackMap countries={data.countries} />

            <div className="space-y-2">
              <h3 className="text-sm font-medium">Top source IPs</h3>
              <div className="overflow-x-auto rounded-lg border border-border/60">
                <table className="w-full min-w-[280px] text-left text-xs sm:min-w-[480px]">
                  <thead className="border-b border-border bg-secondary/40">
                    <tr>
                      <th className="px-3 py-2 font-medium">IP</th>
                      <th className="px-3 py-2 font-medium">Geo</th>
                      <th className="px-3 py-2 font-medium">Packets</th>
                      <th className="px-3 py-2 font-medium">%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.top_sources.map((s) => (
                      <tr
                        key={s.ip}
                        className="border-b border-border/50 last:border-0"
                      >
                        <td className="px-3 py-2 font-mono">
                          <PrivateWanIp ip={s.ip} />
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {[s.city, s.region_name || s.region, s.country_code]
                            .filter(Boolean)
                            .join(", ") || "—"}
                        </td>
                        <td className="px-3 py-2 font-mono">
                          {s.packets.toLocaleString()}
                        </td>
                        <td className="px-3 py-2 font-mono">
                          {s.pct_packets.toFixed(1)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {data.top_ports.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-sm font-medium">
                  Top {data.top_ports[0]?.direction === "dst" ? "destination" : "source"}{" "}
                  ports
                </h3>
                <ul className="grid gap-1.5 sm:grid-cols-2">
                  {data.top_ports.map((p) => (
                    <li
                      key={p.port}
                      className="flex items-center justify-between gap-2 rounded-md border border-border/50 px-3 py-1.5 font-mono text-xs"
                    >
                      <span>
                        {p.port}
                        {p.label ? (
                          <span className="text-muted-foreground">
                            {" "}
                            ({p.label})
                          </span>
                        ) : null}
                      </span>
                      <span className="text-muted-foreground">
                        {p.pct_packets.toFixed(1)}%
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={!pcapName || loading}
            onClick={() => void onRefresh()}
          >
            Re-analyze
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border/60 bg-secondary/20 px-3 py-2">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 font-mono text-sm">{value}</p>
    </div>
  );
}
