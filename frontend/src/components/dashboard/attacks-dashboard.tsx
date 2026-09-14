"use client";

import { ChartPie, Download, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { PcapAnalysisDialog } from "@/components/dashboard/pcap-analysis-dialog";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  deleteAttackPcap,
  downloadAttackPcap,
  listAttackPcaps,
  type AttackEventItem,
  type AttackPcapItem,
} from "@/lib/api";
import { cn } from "@/lib/utils";

function formatBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatRate(n: number, unit: string): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)} M${unit}`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(2)} K${unit}`;
  return `${n} ${unit}`;
}

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function severityClass(severity: string): string {
  const s = severity.toUpperCase();
  if (s === "CRITICAL")
    return "border-red-500/50 bg-red-500/15 text-red-300";
  if (s === "SEVERE")
    return "border-orange-500/50 bg-orange-500/15 text-orange-300";
  if (s === "ATTACK")
    return "border-amber-500/50 bg-amber-500/15 text-amber-200";
  if (s === "WARNING")
    return "border-yellow-500/40 bg-yellow-500/10 text-yellow-200";
  return "border-border bg-secondary/40 text-muted-foreground";
}

function PcapActions({
  name,
  busy,
  onAnalyze,
  onDownload,
  onDelete,
}: {
  name: string;
  busy: boolean;
  onAnalyze: () => void;
  onDownload: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="flex flex-wrap justify-end gap-1.5">
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="gap-1.5"
        onClick={onAnalyze}
      >
        <ChartPie className="size-3.5" />
        <span className="sm:inline">Analyze</span>
      </Button>
      <Button
        type="button"
        size="icon-sm"
        variant="outline"
        disabled={busy}
        aria-label="Download"
        onClick={onDownload}
      >
        <Download className="size-3.5" />
      </Button>
      <Button
        type="button"
        size="icon-sm"
        variant="destructive"
        disabled={busy}
        aria-label="Delete capture"
        onClick={onDelete}
      >
        <Trash2 className="size-3.5" />
      </Button>
    </div>
  );
}

function eventHasCapture(ev: AttackEventItem): boolean {
  return Boolean(ev.pcap_file) && ev.pcap_available !== false && ev.pcap_size_bytes != null;
}

export function AttacksDashboard() {
  const [events, setEvents] = useState<AttackEventItem[]>([]);
  const [captures, setCaptures] = useState<AttackPcapItem[]>([]);
  const [lifetime, setLifetime] = useState(0);
  const [last24h, setLast24h] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyName, setBusyName] = useState<string | null>(null);
  const [analysisOpen, setAnalysisOpen] = useState(false);
  const [analysisPcap, setAnalysisPcap] = useState<string | null>(null);
  const [analysisEvent, setAnalysisEvent] = useState<AttackEventItem | null>(
    null,
  );

  function openAnalysis(pcapName: string, event?: AttackEventItem | null) {
    setAnalysisPcap(pcapName);
    setAnalysisEvent(event ?? null);
    setAnalysisOpen(true);
  }

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const data = await listAttackPcaps();
      setEvents(data.events ?? []);
      setCaptures(data.captures ?? []);
      setLifetime(data.attacks_lifetime);
      setLast24h(data.attacks_24h);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not load attack events.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 15_000);
    return () => clearInterval(t);
  }, [refresh]);

  async function onDownload(name: string) {
    setBusyName(name);
    setError(null);
    try {
      await downloadAttackPcap(name);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Download failed.");
    } finally {
      setBusyName(null);
    }
  }

  async function onDelete(name: string) {
    if (
      !window.confirm(
        `Delete capture ${name}?\n\nAttack analytics for this detection will be kept.`,
      )
    ) {
      return;
    }
    setBusyName(name);
    setError(null);
    try {
      await deleteAttackPcap(name);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed.");
    } finally {
      setBusyName(null);
    }
  }

  return (
    <div className="dash-page">
      <div>
        <h1 className="dash-title">
          Attacks
        </h1>
        <p className="dash-sub">
          Detections are stored as analytics. Deleting a capture removes only
          the .pcap file — 24h / lifetime counts stay.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:gap-3">
        <div className="rounded-lg border border-border/70 bg-background/50 p-2.5 sm:p-3">
          <p className="text-xs text-muted-foreground">Attacks (24h)</p>
          <p className="mt-0.5 text-lg font-semibold sm:text-xl">{last24h}</p>
        </div>
        <div className="rounded-lg border border-border/70 bg-background/50 p-2.5 sm:p-3">
          <p className="text-xs text-muted-foreground">Attacks (lifetime)</p>
          <p className="mt-0.5 text-lg font-semibold sm:text-xl">{lifetime}</p>
        </div>
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
        >
          {error}
        </p>
      )}

      {/* Mobile event cards */}
      <div className="space-y-2 md:hidden">
        {loading && (
          <p className="py-5 text-center font-mono text-sm text-muted-foreground">
            Loading attacks…
          </p>
        )}
        {!loading && events.length === 0 && (
          <div className="dash-empty">
            No attack events yet.
          </div>
        )}
        {events.map((ev) => (
          <article
            key={ev.id}
            className="dash-card"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-mono text-xs">{formatWhen(ev.detected_at)}</p>
                <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                  {ev.kind}
                </p>
              </div>
              <span
                className={cn(
                  "shrink-0 rounded-md border px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide",
                  severityClass(ev.severity),
                )}
              >
                {ev.severity}
              </span>
            </div>
            <div className="font-mono text-xs text-muted-foreground">
              {formatRate(ev.pps, "pps")} · {formatRate(ev.bps, "B/s")}
            </div>
            {ev.pcap_file ? (
              <div className="flex items-center gap-2 min-w-0">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src="/pcap-icon.png"
                  alt=""
                  width={28}
                  height={28}
                  className="size-7 shrink-0 object-contain opacity-80"
                  aria-hidden
                />
                <div className="min-w-0">
                  <p className="truncate font-mono text-xs">{ev.pcap_file}</p>
                  <p className="font-mono text-[11px] text-muted-foreground">
                    {eventHasCapture(ev)
                      ? formatBytes(ev.pcap_size_bytes)
                      : "Capture removed"}
                  </p>
                </div>
              </div>
            ) : null}
            {eventHasCapture(ev) && ev.pcap_file && (
              <PcapActions
                name={ev.pcap_file}
                busy={busyName === ev.pcap_file}
                onAnalyze={() => openAnalysis(ev.pcap_file!, ev)}
                onDownload={() => void onDownload(ev.pcap_file!)}
                onDelete={() => void onDelete(ev.pcap_file!)}
              />
            )}
          </article>
        ))}
      </div>

      {/* Desktop event table */}
      <div className="auth-glow-border hidden overflow-hidden rounded-xl bg-card/90 md:block">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b border-border bg-secondary/40">
              <tr>
                <th className="px-4 py-3 font-medium">When</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Rates</th>
                <th className="px-4 py-3 font-medium">Capture</th>
                <th className="px-4 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-10 text-center font-mono text-sm text-muted-foreground"
                  >
                    Loading attacks…
                  </td>
                </tr>
              )}
              {!loading && events.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-10 text-center text-sm text-muted-foreground"
                  >
                    No attack events yet. Detections and captures appear here
                    when the monitor trips.
                  </td>
                </tr>
              )}
              {!loading &&
                events.map((ev) => (
                  <tr
                    key={ev.id}
                    className="border-b border-border/60 last:border-0"
                  >
                    <td className="px-4 py-3">
                      <div className="font-mono text-xs">
                        {formatWhen(ev.detected_at)}
                      </div>
                      <div className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                        {ev.kind}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          "inline-flex rounded-md border px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide",
                          severityClass(ev.severity),
                        )}
                      >
                        {ev.severity}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                      <div>{formatRate(ev.pps, "pps")}</div>
                      <div className="mt-0.5">{formatRate(ev.bps, "B/s")}</div>
                    </td>
                    <td className="px-4 py-3">
                      {ev.pcap_file ? (
                        <div className="flex min-w-0 items-center gap-2">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src="/pcap-icon.png"
                            alt=""
                            width={28}
                            height={28}
                            className="size-7 shrink-0 object-contain opacity-80"
                            aria-hidden
                          />
                          <div className="min-w-0">
                            <div className="truncate font-mono text-xs">
                              {ev.pcap_file}
                            </div>
                            <div className="font-mono text-[11px] text-muted-foreground">
                              {eventHasCapture(ev)
                                ? formatBytes(ev.pcap_size_bytes)
                                : "Capture removed"}
                            </div>
                          </div>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {eventHasCapture(ev) && ev.pcap_file ? (
                        <PcapActions
                          name={ev.pcap_file}
                          busy={busyName === ev.pcap_file}
                          onAnalyze={() => openAnalysis(ev.pcap_file!, ev)}
                          onDownload={() => void onDownload(ev.pcap_file!)}
                          onDelete={() => void onDelete(ev.pcap_file!)}
                        />
                      ) : (
                        <span className="block text-right text-xs text-muted-foreground">
                          —
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>

      <details className="dash-section space-y-3">
        <summary>Captures</summary>
        <p className="-mt-1 text-xs text-muted-foreground">
          Packet capture files on disk (.pcap). Deleting here only removes the
          file — detection analytics stay in the list above.
        </p>

      <div className="space-y-2 md:hidden">
        {!loading && captures.length === 0 && (
          <div className="dash-empty">
            No capture files yet.
          </div>
        )}
        {captures.map((cap) => (
          <article
            key={cap.name}
            className="dash-card"
          >
            <div className="flex items-center gap-2 min-w-0">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/pcap-icon.png"
                alt=""
                width={28}
                height={28}
                className="size-7 shrink-0 object-contain"
                aria-hidden
              />
              <div className="min-w-0">
                <p className="truncate font-mono text-xs">{cap.name}</p>
                <p className="font-mono text-[11px] text-muted-foreground">
                  {formatBytes(cap.size_bytes)} · {formatWhen(cap.modified_at)}
                </p>
              </div>
            </div>
            <PcapActions
              name={cap.name}
              busy={busyName === cap.name}
              onAnalyze={() => openAnalysis(cap.name)}
              onDownload={() => void onDownload(cap.name)}
              onDelete={() => void onDelete(cap.name)}
            />
          </article>
        ))}
      </div>

      <div className="auth-glow-border hidden overflow-hidden rounded-xl bg-card/90 md:block">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="border-b border-border bg-secondary/40">
              <tr>
                <th className="px-4 py-3 font-medium">File</th>
                <th className="px-4 py-3 font-medium">Size</th>
                <th className="px-4 py-3 font-medium">Modified</th>
                <th className="px-4 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {!loading && captures.length === 0 && (
                <tr>
                  <td
                    colSpan={4}
                    className="px-4 py-8 text-center text-sm text-muted-foreground"
                  >
                    No capture files yet.
                  </td>
                </tr>
              )}
              {captures.map((cap) => (
                <tr
                  key={cap.name}
                  className="border-b border-border/60 last:border-0"
                >
                  <td className="px-4 py-3">
                    <div className="flex min-w-0 items-center gap-2">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src="/pcap-icon.png"
                        alt=""
                        width={28}
                        height={28}
                        className="size-7 shrink-0 object-contain"
                        aria-hidden
                      />
                      <span className="truncate font-mono text-xs">
                        {cap.name}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                    {formatBytes(cap.size_bytes)}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                    {formatWhen(cap.modified_at)}
                  </td>
                  <td className="px-4 py-3">
                    <PcapActions
                      name={cap.name}
                      busy={busyName === cap.name}
                      onAnalyze={() => openAnalysis(cap.name)}
                      onDownload={() => void onDownload(cap.name)}
                      onDelete={() => void onDelete(cap.name)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      </details>

      <PcapAnalysisDialog
        open={analysisOpen}
        onOpenChange={setAnalysisOpen}
        pcapName={analysisPcap}
        event={analysisEvent}
      />
    </div>
  );
}
