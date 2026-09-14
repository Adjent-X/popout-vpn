"use client";

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import {
  Cable,
  Cpu,
  EthernetPort,
  HardDrive,
  MemoryStick,
  type LucideIcon,
} from "lucide-react";

import {
  ApiError,
  fetchAnalyticsOverview,
  fetchSiteSettings,
  updateSiteSettings,
  type AnalyticsOverview,
  type BandwidthToDate,
  type HostMetricsLatest,
  type MetricPoint,
  type MonthlyBandwidth,
} from "@/lib/api";
import { useTheme } from "@/components/theme-provider";

/** Soft rounded badge for resource / NIC icons. */
function MetricIcon({
  icon: Icon,
  label,
  tone = "accent",
}: {
  icon: LucideIcon;
  label: string;
  tone?: "accent" | "primary" | "amber" | "sky";
}) {
  const tones: Record<typeof tone, string> = {
    accent:
      "bg-[color-mix(in_oklab,var(--brand-accent)_18%,transparent)] text-[var(--brand-accent-bright)]",
    primary:
      "bg-[color-mix(in_oklab,var(--brand-primary)_18%,transparent)] text-[var(--brand-primary)]",
    amber: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
    sky: "bg-sky-500/15 text-sky-600 dark:text-sky-400",
  };
  return (
    <span
      className={
        "inline-flex size-6 shrink-0 items-center justify-center rounded-md " +
        tones[tone]
      }
      aria-hidden
      title={label}
    >
      <Icon className="size-3.5" strokeWidth={1.75} />
    </span>
  );
}

function MetricLabel({
  icon,
  children,
}: {
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex items-center gap-2">
      {icon}
      <div className="min-w-0 text-xs font-medium text-muted-foreground">
        {children}
      </div>
    </div>
  );
}

const SERIES_HOURS = 6;
const REFRESH_OPTIONS = [0.25, 0.5, 1, 2.5, 5, 10, 30] as const;
const REFRESH_STORAGE_KEY = "popout_analytics_refresh_seconds";
const RATE_UNIT_STORAGE_KEY = "popout_analytics_rate_unit";
/** Live scroll window (~30s at 250ms). New samples enter on the right. */
const LIVE_TRAIL_CAP = 120;
/** Historical charts downsample to this many points across full width. */
const HISTORY_SPARK_POINTS = 48;
/** Frames of lower demand before zooming Y back in (~1.5s at 250ms). */
const ZOOM_IN_QUIET_FRAMES = 6;

const BYTE_RATE_SCALE_STEPS = [
  512, // 0.5 KB/s — zoomed in for quiet links
  1 * 1024,
  2 * 1024,
  4 * 1024,
  8 * 1024,
  16 * 1024,
  32 * 1024,
  64 * 1024,
  128 * 1024,
  256 * 1024,
  512 * 1024,
  1 * 1024 * 1024,
  2 * 1024 * 1024,
  4 * 1024 * 1024,
  8 * 1024 * 1024,
  16 * 1024 * 1024,
  32 * 1024 * 1024,
  64 * 1024 * 1024,
  128 * 1024 * 1024,
  256 * 1024 * 1024,
  512 * 1024 * 1024,
  1024 * 1024 * 1024,
] as const;

const PPS_SCALE_STEPS = [
  5, 10, 25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000, 25_000, 50_000,
  100_000, 250_000, 500_000, 1_000_000, 2_500_000, 5_000_000,
] as const;

function niceScaleMax(peak: number, unit: "bytes" | "pps"): number {
  const steps = unit === "bytes" ? BYTE_RATE_SCALE_STEPS : PPS_SCALE_STEPS;
  const floor = steps[0]!;
  const need = Math.max(peak * 1.2, floor);
  for (const step of steps) {
    if (step >= need) return step;
  }
  return need;
}

/** Zoom out instantly on spikes; zoom back in after quiet frames (KB detail returns). */
function stepAutoZoom(
  held: number,
  peak: number,
  unit: "bytes" | "pps",
  quietFrames: { current: number },
): number {
  const target = niceScaleMax(peak, unit);
  if (target > held) {
    quietFrames.current = 0;
    return target;
  }
  if (target < held) {
    quietFrames.current += 1;
    if (quietFrames.current >= ZOOM_IN_QUIET_FRAMES) {
      quietFrames.current = 0;
      return target;
    }
    return held;
  }
  quietFrames.current = 0;
  return held;
}
type RefreshSeconds = (typeof REFRESH_OPTIONS)[number];
type RateUnit = "bytes" | "bits";

function normalizeRefresh(value: number | null | undefined): RefreshSeconds {
  const n = Number(value);
  if (REFRESH_OPTIONS.includes(n as RefreshSeconds)) return n as RefreshSeconds;
  return 10;
}

function normalizeRateUnit(value: string | null | undefined): RateUnit {
  return value === "bits" ? "bits" : "bytes";
}

function refreshLabel(seconds: RefreshSeconds): string {
  if (seconds === 0.25) return "Live (250 ms)";
  if (seconds === 0.5) return "500 ms";
  if (seconds === 1) return "1 second";
  if (seconds === 2.5) return "2.5 seconds";
  return `${seconds} seconds`;
}

function latestToPoint(latest: HostMetricsLatest): MetricPoint {
  return {
    ts: latest.ts,
    cpu_percent: latest.cpu_percent,
    mem_percent: latest.mem_percent,
    disk_percent: latest.disk_percent,
    net_bytes_sent_rate: latest.net_bytes_sent_rate,
    net_bytes_recv_rate: latest.net_bytes_recv_rate,
    net_packets_sent_rate: latest.net_packets_sent_rate ?? null,
    net_packets_recv_rate: latest.net_packets_recv_rate ?? null,
    eth0_bytes_sent_rate: latest.eth0_bytes_sent_rate ?? null,
    eth0_bytes_recv_rate: latest.eth0_bytes_recv_rate ?? null,
    eth0_packets_sent_rate: latest.eth0_packets_sent_rate ?? null,
    eth0_packets_recv_rate: latest.eth0_packets_recv_rate ?? null,
    tun0_bytes_sent_rate: latest.tun0_bytes_sent_rate ?? null,
    tun0_bytes_recv_rate: latest.tun0_bytes_recv_rate ?? null,
    tun0_packets_sent_rate: latest.tun0_packets_sent_rate ?? null,
    tun0_packets_recv_rate: latest.tun0_packets_recv_rate ?? null,
  };
}

function readLocalRefresh(): RefreshSeconds | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(REFRESH_STORAGE_KEY);
    if (!raw) return null;
    return normalizeRefresh(Number(raw));
  } catch {
    return null;
  }
}

function writeLocalRefresh(value: RefreshSeconds) {
  try {
    sessionStorage.setItem(REFRESH_STORAGE_KEY, String(value));
  } catch {
    /* ignore */
  }
}

function readLocalRateUnit(): RateUnit | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(RATE_UNIT_STORAGE_KEY);
    if (!raw) return null;
    return normalizeRateUnit(raw);
  } catch {
    return null;
  }
}

function writeLocalRateUnit(value: RateUnit) {
  try {
    sessionStorage.setItem(RATE_UNIT_STORAGE_KEY, value);
  } catch {
    /* ignore */
  }
}

function formatBytesPerSec(value: number | null | undefined): string {
  const n = value ?? 0;
  if (n <= 0) return "0 B/s";
  const units = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"];
  let idx = 0;
  let v = n;
  while (v >= 1024 && idx < units.length - 1) {
    v /= 1024;
    idx += 1;
  }
  return `${v.toFixed(v < 10 && idx > 0 ? 1 : 0)} ${units[idx]}`;
}

/** Bits per second from a bytes/sec rate. */
function formatBitsPerSec(bytesPerSec: number | null | undefined): string {
  const n = (bytesPerSec ?? 0) * 8;
  if (n <= 0) return "0 bps";
  const units = ["bps", "Kbps", "Mbps", "Gbps", "Tbps"];
  let idx = 0;
  let v = n;
  while (v >= 1000 && idx < units.length - 1) {
    v /= 1000;
    idx += 1;
  }
  return `${v.toFixed(v < 10 && idx > 0 ? 1 : 0)} ${units[idx]}`;
}

function formatPps(value: number | null | undefined): string {
  const n = value ?? 0;
  if (n <= 0) return "0 pps";
  if (n < 1000) return `${n.toFixed(n < 10 ? 1 : 0)} pps`;
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)} Kpps`;
  return `${(n / 1_000_000).toFixed(1)} Mpps`;
}

function formatBytes(value: number | null | undefined): string {
  const n = value ?? 0;
  if (n <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let idx = 0;
  let v = n;
  while (v >= 1024 && idx < units.length - 1) {
    v /= 1024;
    idx += 1;
  }
  return `${v.toFixed(v < 10 && idx > 0 ? 1 : 0)} ${units[idx]}`;
}

function formatPercent(value: number | null | undefined): string {
  return `${(value ?? 0).toFixed(1)}%`;
}

/** Format a bytes/sec sample as B/s or bit/s depending on unit preference. */
function formatRate(
  bytesPerSec: number | null | undefined,
  unit: RateUnit,
): string {
  return unit === "bits"
    ? formatBitsPerSec(bytesPerSec)
    : formatBytesPerSec(bytesPerSec);
}

function formatBitsPerSecAbsolute(bitsPerSec: number | null | undefined): string {
  const n = bitsPerSec ?? 0;
  if (n <= 0) return "0 bps";
  const units = ["bps", "Kbps", "Mbps", "Gbps", "Tbps"];
  let idx = 0;
  let v = n;
  while (v >= 1000 && idx < units.length - 1) {
    v /= 1000;
    idx += 1;
  }
  return `${v.toFixed(v < 10 && idx > 0 ? 1 : 0)} ${units[idx]}`;
}

/** Format an absolute bit/s value (e.g. monthly avg) for the chosen unit. */
function formatAbsoluteRate(
  bitsPerSec: number | null | undefined,
  unit: RateUnit,
): string {
  const bps = bitsPerSec ?? 0;
  if (unit === "bits") return formatBitsPerSecAbsolute(bps);
  return formatBytesPerSec(bps / 8);
}

function monthLabel(year: number, month: number): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      year: "numeric",
    }).format(new Date(year, month - 1, 1));
  } catch {
    return `${year}-${String(month).padStart(2, "0")}`;
  }
}

/** Windows-style disk usage meter (label → bar → free of total). */
function DiskStorageCard({
  used,
  total,
  percent,
}: {
  used: number;
  total: number;
  percent: number;
}) {
  const free = Math.max(0, total - used);
  const pct = Math.min(100, Math.max(0, percent));
  const warn = pct >= 90;
  return (
    <div className="rounded-lg border border-border/70 bg-card/90 p-2.5">
      <MetricLabel
        icon={
          <MetricIcon
            icon={HardDrive}
            label="Disk"
            tone="amber"
          />
        }
      >
        Disk
      </MetricLabel>
      <p className="mt-0.5 text-base font-semibold tracking-tight sm:text-lg">
        {formatPercent(percent)}
      </p>
      <div
        className="mt-1.5 h-1.5 w-full overflow-hidden rounded-sm bg-muted/70"
        role="meter"
        aria-label="Disk usage"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
      >
        <div
          className={
            "h-full rounded-sm transition-[width] duration-500 ease-out " +
            (warn
              ? "bg-amber-500"
              : "bg-[var(--brand-accent-bright)]")
          }
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-1 font-mono text-[10px] text-muted-foreground">
        {formatBytes(free)} free · {formatBytes(used)} used
      </p>
    </div>
  );
}

function formatStartedAt(iso: string | null | undefined): string {
  if (!iso) return "starting now";
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function MonthlyBandwidthSection({
  toDate,
  months,
  rateUnit,
}: {
  toDate: BandwidthToDate | null | undefined;
  months: MonthlyBandwidth[];
  rateUnit: RateUnit;
}) {
  const total = toDate?.total_bytes ?? 0;
  const avg = toDate?.avg_bps ?? 0;
  const maxBytes = Math.max(...months.map((m) => m.total_bytes), 1);
  return (
    <details className="rounded-lg border border-border/60 bg-background/40">
      <summary className="cursor-pointer list-none px-2.5 py-2 text-xs font-semibold tracking-wide [&::-webkit-details-marker]:hidden">
        <span className="text-muted-foreground">▸ </span>
        Bandwidth · {formatBytes(total)}
        <span className="ml-1.5 font-mono font-normal text-muted-foreground">
          · {formatAbsoluteRate(avg, rateUnit)} avg
        </span>
      </summary>
      <div className="space-y-2 border-t border-border/50 px-2.5 pb-2.5 pt-2">
        <div className="flex flex-wrap justify-between gap-x-3 gap-y-0.5 font-mono text-[10px] text-muted-foreground">
          <span>
            ↓ {formatBytes(toDate?.eth0_bytes_recv ?? 0)} · ↑{" "}
            {formatBytes(toDate?.eth0_bytes_sent ?? 0)}
          </span>
          <span>since {formatStartedAt(toDate?.started_at)}</span>
        </div>
        {months.length === 0 ? (
          <p className="font-mono text-[10px] text-muted-foreground">
            Counting from now — this month appears after the next sample.
          </p>
        ) : (
          <div className="space-y-2">
            {months.slice(0, 6).map((m) => {
              const widthPct = Math.max(
                2,
                Math.round((m.total_bytes / maxBytes) * 100),
              );
              return (
                <div key={m.id} className="space-y-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="text-xs font-medium">
                      {monthLabel(m.year, m.month)}
                    </p>
                    <p className="font-mono text-[10px] text-muted-foreground">
                      {formatBytes(m.total_bytes)} ·{" "}
                      {formatAbsoluteRate(m.avg_bps, rateUnit)}
                    </p>
                  </div>
                  <div
                    className="h-1.5 w-full overflow-hidden rounded-sm bg-muted/70"
                    role="meter"
                    aria-label={`Bandwidth ${monthLabel(m.year, m.month)}`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={widthPct}
                  >
                    <div
                      className="h-full rounded-sm bg-[var(--brand-accent)]"
                      style={{ width: `${widthPct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </details>
  );
}

function formatClock(iso: string | undefined | null): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

/**
 * dstat-style live sparkline: fixed scroll window, right-aligned samples,
 * straight segments, no morph. History mode stretches a downsampled series.
 */
function Sparkline({
  values,
  color,
  max = 100,
  height = 40,
  live = false,
}: {
  values: number[];
  color: string;
  max?: number;
  height?: number;
  live?: boolean;
}) {
  const width = 320;
  const slots = live ? LIVE_TRAIL_CAP : HISTORY_SPARK_POINTS;
  const series = live
    ? rightAlignSeries(values, slots)
    : downsample(values.length > 0 ? values : [0], slots);
  const heldMaxRef = useRef(1);
  const gradId = useId().replace(/:/g, "");

  const peak = Math.max(
    0,
    ...series.filter((v): v is number => v != null),
  );
  const fixedScale = max != null && max > 0;
  if (fixedScale) {
    heldMaxRef.current = max;
  } else {
    heldMaxRef.current = Math.max(peak * 1.15, 1);
  }
  const clampedMax = Math.max(heldMaxRef.current, 1);

  const coords: [number, number][] = [];
  for (let i = 0; i < series.length; i += 1) {
    const v = series[i];
    if (v == null) continue;
    const x = slots > 1 ? (i / (slots - 1)) * width : 0;
    const clamped = Math.min(Math.max(v, 0), clampedMax);
    const y = height - (clamped / clampedMax) * (height - 4) - 2;
    coords.push([x, y]);
  }

  const path = live ? polylinePath(coords) : smoothPath(coords);
  const firstX = coords[0]?.[0] ?? 0;
  const lastX = coords[coords.length - 1]?.[0] ?? width;
  const areaPath =
    coords.length > 0
      ? `${path} L${lastX},${height} L${firstX},${height} Z`
      : "";
  const last = coords[coords.length - 1];

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="h-10 w-full"
      role="img"
      aria-label="Sparkline chart"
    >
      <defs>
        <linearGradient id={`g-${gradId}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={live ? 0.22 : 0.35} />
          <stop offset="100%" stopColor={color} stopOpacity={0.02} />
        </linearGradient>
      </defs>
      {areaPath ? (
        <path d={areaPath} fill={`url(#g-${gradId})`} stroke="none" />
      ) : null}
      {path ? (
        <path
          d={path}
          fill="none"
          stroke={color}
          strokeWidth={live ? 1.5 : 2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      ) : null}
      {last && !live ? (
        <circle cx={last[0]} cy={last[1]} r={2.6} fill={color} />
      ) : null}
      {last && live ? (
        <circle cx={last[0]} cy={last[1]} r={2} fill={color} />
      ) : null}
    </svg>
  );
}

function rightAlignSeries(
  values: number[],
  slots: number,
): (number | null)[] {
  const slice = values.slice(-slots);
  const pad = Math.max(0, slots - slice.length);
  return [...Array.from({ length: pad }, () => null), ...slice];
}

function polylinePath(coords: ReadonlyArray<readonly [number, number]>): string {
  if (coords.length === 0) return "";
  let d = `M${coords[0]![0].toFixed(1)},${coords[0]![1].toFixed(1)}`;
  for (let i = 1; i < coords.length; i += 1) {
    d += ` L${coords[i]![0].toFixed(1)},${coords[i]![1].toFixed(1)}`;
  }
  return d;
}

function downsample(values: number[], maxPoints: number): number[] {
  if (values.length <= maxPoints) return values;
  const out: number[] = [];
  const step = (values.length - 1) / (maxPoints - 1);
  for (let i = 0; i < maxPoints; i += 1) {
    const idx = Math.round(i * step);
    out.push(values[idx] ?? 0);
  }
  return out;
}

/** Catmull-Rom → cubic bezier smooth path (history charts). */
function smoothPath(coords: ReadonlyArray<readonly [number, number]>): string {
  if (coords.length === 0) return "";
  if (coords.length === 1) {
    const [x, y] = coords[0]!;
    return `M${x.toFixed(1)},${y.toFixed(1)}`;
  }
  let d = `M${coords[0]![0].toFixed(1)},${coords[0]![1].toFixed(1)}`;
  for (let i = 0; i < coords.length - 1; i += 1) {
    const p0 = coords[i - 1] ?? coords[i]!;
    const p1 = coords[i]!;
    const p2 = coords[i + 1]!;
    const p3 = coords[i + 2] ?? p2;
    const cp1x = p1[0] + (p2[0] - p0[0]) / 6;
    const cp1y = p1[1] + (p2[1] - p0[1]) / 6;
    const cp2x = p2[0] - (p3[0] - p1[0]) / 6;
    const cp2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C${cp1x.toFixed(1)},${cp1y.toFixed(1)} ${cp2x.toFixed(1)},${cp2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

function ResourceCard({
  label,
  value,
  sub,
  icon,
  iconTone,
  sparkValues,
  sparkColor,
  sparkMax,
  live,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: LucideIcon;
  iconTone?: "accent" | "primary" | "amber" | "sky";
  sparkValues?: number[];
  sparkColor?: string;
  sparkMax?: number;
  live?: boolean;
}) {
  return (
    <div className="rounded-lg border border-border/70 bg-card/90 p-2.5">
      <MetricLabel
        icon={<MetricIcon icon={icon} label={label} tone={iconTone} />}
      >
        {label}
      </MetricLabel>
      <p className="mt-0.5 text-base font-semibold tracking-tight sm:text-lg">
        {value}
      </p>
      {sub && (
        <p className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
          {sub}
        </p>
      )}
      {sparkValues && (
        <div className="mt-1.5">
          <Sparkline
            values={sparkValues}
            color={sparkColor ?? "var(--brand-accent)"}
            max={sparkMax}
            live={live}
          />
        </div>
      )}
    </div>
  );
}

function DualSparkline({
  inbound,
  outbound,
  inboundColor,
  outboundColor,
  max,
  height = 40,
  live = false,
  scaleUnit = "bytes",
  rateUnit = "bytes",
}: {
  inbound: number[];
  outbound: number[];
  inboundColor: string;
  outboundColor: string;
  max?: number;
  height?: number;
  live?: boolean;
  scaleUnit?: "bytes" | "pps";
  rateUnit?: RateUnit;
}) {
  const width = 320;
  const slots = live ? LIVE_TRAIL_CAP : HISTORY_SPARK_POINTS;
  const inSeries = live
    ? rightAlignSeries(inbound, slots)
    : downsample(inbound.length ? inbound : [0], slots);
  const outSeries = live
    ? rightAlignSeries(outbound, slots)
    : downsample(outbound.length ? outbound : [0], slots);

  const peak = Math.max(
    0,
    ...inSeries.filter((v): v is number => v != null),
    ...outSeries.filter((v): v is number => v != null),
  );
  const heldMaxRef = useRef(niceScaleMax(0, scaleUnit));
  const quietRef = useRef(0);

  if (live) {
    heldMaxRef.current = stepAutoZoom(
      heldMaxRef.current,
      peak,
      scaleUnit,
      quietRef,
    );
  } else {
    heldMaxRef.current =
      max != null && max > 0
        ? niceScaleMax(max / 1.15, scaleUnit)
        : niceScaleMax(peak, scaleUnit);
  }
  const clampedMax = Math.max(heldMaxRef.current, 1);

  const toCoords = (series: (number | null)[] | number[]) => {
    const coords: [number, number][] = [];
    for (let i = 0; i < series.length; i += 1) {
      const v = series[i];
      if (v == null) continue;
      const x = slots > 1 ? (i / (slots - 1)) * width : 0;
      const clamped = Math.min(Math.max(v, 0), clampedMax);
      const y = height - (clamped / clampedMax) * (height - 4) - 2;
      coords.push([x, y]);
    }
    return coords;
  };

  const inPath = live
    ? polylinePath(toCoords(inSeries))
    : smoothPath(toCoords(inSeries));
  const outPath = live
    ? polylinePath(toCoords(outSeries))
    : smoothPath(toCoords(outSeries));

  const scaleLabel =
    scaleUnit === "pps"
      ? formatPps(clampedMax)
      : formatRate(clampedMax, rateUnit);

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="h-10 w-full"
        role="img"
        aria-label="Inbound and outbound rate chart"
      >
        <path
          d={inPath}
          fill="none"
          stroke={inboundColor}
          strokeWidth={live ? 1.5 : 2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <path
          d={outPath}
          fill="none"
          stroke={outboundColor}
          strokeWidth={live ? 1.5 : 2}
          strokeLinejoin="round"
          strokeLinecap="round"
          strokeDasharray={live ? "3 2" : "4 3"}
        />
      </svg>
      <p className="mt-1 text-right font-mono text-[10px] text-muted-foreground/70">
        0 – {scaleLabel}
      </p>
    </div>
  );
}

function InOutLegend() {
  return (
    <div className="flex shrink-0 gap-2 font-mono text-[9px] text-muted-foreground">
      <span className="inline-flex items-center gap-1">
        <span className="size-1.5 rounded-full bg-[var(--brand-accent-bright)]" />
        in
      </span>
      <span className="inline-flex items-center gap-1">
        <span className="size-1.5 rounded-full bg-[var(--brand-primary)]" />
        out
      </span>
    </div>
  );
}

function ChipStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/60 bg-background/50 px-2 py-1.5">
      <p className="text-[10px] leading-none text-muted-foreground">{label}</p>
      <p className="mt-0.5 font-mono text-sm font-semibold tabular-nums">
        {value}
      </p>
    </div>
  );
}

function InterfaceSection({
  title,
  hint,
  nicIcon,
  nicTone = "sky",
  live,
  rateUnit,
  recvBytesRate,
  sentBytesRate,
  recvPps,
  sentPps,
  recvSeries,
  sentSeries,
}: {
  title: string;
  hint: string;
  nicIcon?: LucideIcon;
  nicTone?: "accent" | "primary" | "amber" | "sky";
  live?: boolean;
  rateUnit: RateUnit;
  recvBytesRate: number;
  sentBytesRate: number;
  recvPps: number;
  sentPps: number;
  recvSeries: number[];
  sentSeries: number[];
}) {
  const Nic = nicIcon ?? EthernetPort;
  return (
    <div className="rounded-lg border border-border/70 bg-card/90 p-2.5">
      <div className="flex items-center justify-between gap-2">
        <MetricLabel
          icon={<MetricIcon icon={Nic} label={title} tone={nicTone} />}
        >
          {title}
          <span className="ml-1.5 font-normal text-muted-foreground">
            · {hint}
          </span>
        </MetricLabel>
        <InOutLegend />
      </div>
      <div className="mt-2 grid grid-cols-4 gap-1.5 font-mono">
        <div>
          <p className="text-[10px] text-muted-foreground">↓ rate</p>
          <p className="text-xs font-semibold tracking-tight sm:text-sm">
            {formatRate(recvBytesRate, rateUnit)}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-muted-foreground">↑ rate</p>
          <p className="text-xs font-semibold tracking-tight sm:text-sm">
            {formatRate(sentBytesRate, rateUnit)}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-muted-foreground">↓ pps</p>
          <p className="text-xs font-semibold tracking-tight sm:text-sm">
            {formatPps(recvPps)}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-muted-foreground">↑ pps</p>
          <p className="text-xs font-semibold tracking-tight sm:text-sm">
            {formatPps(sentPps)}
          </p>
        </div>
      </div>
      <div className="mt-2">
        <DualSparkline
          inbound={recvSeries}
          outbound={sentSeries}
          inboundColor="var(--brand-accent-bright)"
          outboundColor="var(--brand-primary)"
          max={live ? undefined : maxOf([...recvSeries, ...sentSeries], 1024)}
          live={live}
          scaleUnit="bytes"
          rateUnit={rateUnit}
        />
      </div>
    </div>
  );
}

function seriesValues(
  series: MetricPoint[],
  key: keyof MetricPoint,
): number[] {
  return series.map((p) => Number(p[key] ?? 0));
}

function maxOf(values: number[], fallback: number): number {
  const m = Math.max(...values, 0);
  return m > 0 ? m * 1.15 : fallback;
}

export function AnalyticsDashboard() {
  const { admin } = useTheme();
  const isFullAdmin = admin?.role !== "sub_admin";
  const [data, setData] = useState<AnalyticsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshSeconds, setRefreshSeconds] = useState<RefreshSeconds>(10);
  const [rateUnit, setRateUnit] = useState<RateUnit>("bytes");
  const [savingRefresh, setSavingRefresh] = useState(false);
  const [liveTrail, setLiveTrail] = useState<MetricPoint[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isLive = refreshSeconds < 2.5;

  const refresh = useCallback(async () => {
    try {
      const live = refreshSeconds < 2.5;
      // Live charts use the client trail only — never pull 6h Mongo series on
      // the hot path (that was ~1s / 400KB and starved the whole panel).
      const includeSeries = !live;
      const overview = await fetchAnalyticsOverview(
        SERIES_HOURS,
        refreshSeconds,
        { includeSeries },
      );
      setData((prev) => {
        if (!includeSeries && prev?.series?.length) {
          return {
            ...overview,
            series: prev.series,
            bandwidth_monthly:
              overview.bandwidth_monthly?.length
                ? overview.bandwidth_monthly
                : prev.bandwidth_monthly,
            bandwidth_to_date:
              overview.bandwidth_to_date ?? prev.bandwidth_to_date,
          };
        }
        return overview;
      });

      if (live && overview.latest) {
        const point = latestToPoint(overview.latest);
        setLiveTrail((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.ts === point.ts) return prev;
          const next = [...prev, point];
          // Scroll window: drop oldest, newest enters on the right.
          return next.length > LIVE_TRAIL_CAP
            ? next.slice(next.length - LIVE_TRAIL_CAP)
            : next;
        });
      } else if (!live) {
        setLiveTrail([]);
      }
      setError(null);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not load analytics data.",
      );
    } finally {
      setLoading(false);
    }
  }, [refreshSeconds]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const local = readLocalRefresh();
      const localUnit = readLocalRateUnit();
      if (local && !cancelled) setRefreshSeconds(local);
      if (localUnit && !cancelled) setRateUnit(localUnit);
      if (!isFullAdmin) return;
      try {
        const settings = await fetchSiteSettings();
        if (!cancelled) {
          setRefreshSeconds(normalizeRefresh(settings.analytics_refresh_seconds));
        }
      } catch {
        /* keep default / local refresh */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isFullAdmin]);

  useEffect(() => {
    let cancelled = false;
    let timeout: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      await refresh();
      if (cancelled) return;
      // Chain after completion so Live polls never stack under load.
      timeout = setTimeout(
        () => void tick(),
        Math.max(50, Math.round(refreshSeconds * 1000)),
      );
    };
    void tick();

    return () => {
      cancelled = true;
      if (timeout) clearTimeout(timeout);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [refresh, refreshSeconds]);

  async function onRefreshChange(next: RefreshSeconds) {
    setRefreshSeconds(next);
    writeLocalRefresh(next);
    setLiveTrail([]);
    if (!isFullAdmin) return;
    setSavingRefresh(true);
    try {
      await updateSiteSettings({ analytics_refresh_seconds: next });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not save refresh interval.",
      );
    } finally {
      setSavingRefresh(false);
    }
  }

  if (loading) {
    return (
      <p className="font-mono text-sm text-muted-foreground">
        Loading analytics…
      </p>
    );
  }

  const latest = data?.latest ?? null;
  const series =
    isLive && liveTrail.length > 0 ? liveTrail : (data?.series ?? []);
  const cpuSeries = seriesValues(series, "cpu_percent");
  const memSeries = seriesValues(series, "mem_percent");
  const eth0Recv = seriesValues(series, "eth0_bytes_recv_rate");
  const eth0Sent = seriesValues(series, "eth0_bytes_sent_rate");
  const tun0Recv = seriesValues(series, "tun0_bytes_recv_rate");
  const tun0Sent = seriesValues(series, "tun0_bytes_sent_rate");

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="dash-title">Analytics</h1>
          <p className="dash-sub">
            Resources &amp; network · updated {formatClock(latest?.ts)}
            {savingRefresh ? " · saving…" : ""}
            {!isFullAdmin ? " · this session only" : ""}
            {refreshSeconds < 2.5 ? " · live ~30s" : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div
            className="inline-flex h-8 rounded-md border border-input bg-background p-0.5"
            role="group"
            aria-label="Throughput unit"
          >
            <button
              type="button"
              aria-pressed={rateUnit === "bytes"}
              onClick={() => {
                setRateUnit("bytes");
                writeLocalRateUnit("bytes");
              }}
              className={
                "rounded px-2.5 text-xs transition-colors " +
                (rateUnit === "bytes"
                  ? "bg-muted font-medium text-foreground"
                  : "text-muted-foreground hover:text-foreground")
              }
            >
              B/s
            </button>
            <button
              type="button"
              aria-pressed={rateUnit === "bits"}
              onClick={() => {
                setRateUnit("bits");
                writeLocalRateUnit("bits");
              }}
              className={
                "rounded px-2.5 text-xs transition-colors " +
                (rateUnit === "bits"
                  ? "bg-muted font-medium text-foreground"
                  : "text-muted-foreground hover:text-foreground")
              }
            >
              b/s
            </button>
          </div>
          <select
            id="analytics-refresh"
            aria-label="Sample and refresh interval"
            value={String(refreshSeconds)}
            disabled={savingRefresh}
            onChange={(e) =>
              void onRefreshChange(Number(e.target.value) as RefreshSeconds)
            }
            className="flex h-8 rounded-md border border-input bg-background px-2 text-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {REFRESH_OPTIONS.map((s) => (
              <option key={s} value={String(s)}>
                {refreshLabel(s)}
              </option>
            ))}
          </select>
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

      {!latest && !error && (
        <p className="rounded-md border border-border/70 bg-background/50 px-3 py-2 font-mono text-xs text-muted-foreground">
          No metrics yet — collector may still be starting.
        </p>
      )}

      <details open className="dash-section !space-y-2 !pt-3">
        <summary>Resources</summary>
        <div className="grid grid-cols-3 gap-1.5 sm:gap-2.5">
          <ResourceCard
            label="CPU"
            icon={Cpu}
            iconTone="accent"
            value={formatPercent(latest?.cpu_percent)}
            sub={
              latest?.load_avg
                ? latest.load_avg.map((n) => n.toFixed(2)).join(" / ")
                : undefined
            }
            sparkValues={cpuSeries}
            sparkColor="var(--brand-accent)"
            sparkMax={100}
            live={isLive}
          />
          <ResourceCard
            label="Mem"
            icon={MemoryStick}
            iconTone="primary"
            value={formatPercent(latest?.mem_percent)}
            sub={
              latest
                ? `${formatBytes(latest.mem_used)} / ${formatBytes(latest.mem_total)}`
                : undefined
            }
            sparkValues={memSeries}
            sparkColor="var(--brand-primary)"
            sparkMax={100}
            live={isLive}
          />
          <DiskStorageCard
            used={latest?.disk_used ?? 0}
            total={latest?.disk_total ?? 0}
            percent={latest?.disk_percent ?? 0}
          />
        </div>
      </details>

      <details open className="dash-section !space-y-2 !pt-3">
        <summary>Network</summary>
        <div className="grid gap-2 sm:grid-cols-2">
          <InterfaceSection
            title="eth0"
            hint="WAN"
            nicIcon={EthernetPort}
            nicTone="sky"
            live={isLive}
            rateUnit={rateUnit}
            recvBytesRate={latest?.eth0_bytes_recv_rate ?? 0}
            sentBytesRate={latest?.eth0_bytes_sent_rate ?? 0}
            recvPps={latest?.eth0_packets_recv_rate ?? 0}
            sentPps={latest?.eth0_packets_sent_rate ?? 0}
            recvSeries={eth0Recv}
            sentSeries={eth0Sent}
          />
          <InterfaceSection
            title="tun0"
            hint="VPN"
            nicIcon={Cable}
            nicTone="accent"
            live={isLive}
            rateUnit={rateUnit}
            recvBytesRate={latest?.tun0_bytes_recv_rate ?? 0}
            sentBytesRate={latest?.tun0_bytes_sent_rate ?? 0}
            recvPps={latest?.tun0_packets_recv_rate ?? 0}
            sentPps={latest?.tun0_packets_sent_rate ?? 0}
            recvSeries={tun0Recv}
            sentSeries={tun0Sent}
          />
        </div>
        <MonthlyBandwidthSection
          toDate={data?.bandwidth_to_date}
          months={data?.bandwidth_monthly ?? []}
          rateUnit={rateUnit}
        />
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
          <ChipStat
            label="Online"
            value={String(data?.clients_online ?? 0)}
          />
          <ChipStat
            label="Active"
            value={String(data?.clients_total_active ?? 0)}
          />
          <ChipStat
            label="Configs"
            value={String(data?.configs_total ?? 0)}
          />
          <ChipStat
            label="Revoked"
            value={String(data?.configs_revoked ?? 0)}
          />
        </div>
        {isFullAdmin && (
          <div className="grid grid-cols-2 gap-1.5">
            <ChipStat
              label="Attacks 24h"
              value={String(data?.attacks_24h ?? 0)}
            />
            <ChipStat
              label="Attacks life"
              value={String(data?.attacks_lifetime ?? 0)}
            />
          </div>
        )}
      </details>
    </div>
  );
}
