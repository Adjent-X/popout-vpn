"use client";

import { cn } from "@/lib/utils";

export type PieSlice = {
  name: string;
  value: number;
  pct: number;
  color: string;
};

const DEFAULT_COLORS = [
  "#06b6d4",
  "#3b82f6",
  "#a855f7",
  "#f59e0b",
  "#ef4444",
  "#22c55e",
  "#eab308",
  "#94a3b8",
];

function polar(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function arcPath(
  cx: number,
  cy: number,
  r: number,
  startAngle: number,
  endAngle: number,
) {
  const start = polar(cx, cy, r, endAngle);
  const end = polar(cx, cy, r, startAngle);
  const large = endAngle - startAngle > 180 ? 1 : 0;
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${large} 0 ${end.x} ${end.y} L ${cx} ${cy} Z`;
}

type PercentagePieChartProps = {
  title: string;
  slices: PieSlice[];
  className?: string;
  size?: number;
};

export function PercentagePieChart({
  title,
  slices,
  className,
  size = 160,
}: PercentagePieChartProps) {
  const usable = slices.filter((s) => s.value > 0 && s.pct > 0);
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 4;
  let angle = 0;
  const paths = usable.map((slice, i) => {
    const sweep = Math.max(0.01, (slice.pct / 100) * 360);
    const start = angle;
    const end = angle + sweep;
    angle = end;
    return {
      ...slice,
      color: slice.color || DEFAULT_COLORS[i % DEFAULT_COLORS.length],
      d: arcPath(cx, cy, r, start, end),
    };
  });

  return (
    <div className={cn("space-y-3", className)}>
      <h3 className="text-sm font-medium">{title}</h3>
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start">
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          className="shrink-0"
          role="img"
          aria-label={title}
        >
          {paths.length === 0 ? (
            <circle
              cx={cx}
              cy={cy}
              r={r}
              className="fill-secondary/60"
            />
          ) : (
            paths.map((p) => (
              <path key={p.name} d={p.d} fill={p.color} stroke="transparent">
                <title>
                  {p.name}: {p.pct}% ({p.value})
                </title>
              </path>
            ))
          )}
        </svg>
        <ul className="min-w-0 flex-1 space-y-1.5 text-xs">
          {usable.length === 0 && (
            <li className="text-muted-foreground">No data</li>
          )}
          {usable.map((s, i) => (
            <li
              key={s.name}
              className="flex items-center justify-between gap-3"
            >
              <span className="flex min-w-0 items-center gap-2">
                <span
                  className="size-2.5 shrink-0 rounded-sm"
                  style={{
                    background:
                      s.color || DEFAULT_COLORS[i % DEFAULT_COLORS.length],
                  }}
                />
                <span className="truncate font-mono">{s.name}</span>
              </span>
              <span className="shrink-0 font-mono text-muted-foreground">
                {s.pct.toFixed(1)}%
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function pieColors(n: number): string[] {
  return Array.from(
    { length: n },
    (_, i) => DEFAULT_COLORS[i % DEFAULT_COLORS.length],
  );
}
