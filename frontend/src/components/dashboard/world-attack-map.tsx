"use client";

import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";

import { cn } from "@/lib/utils";

export type CountryStat = {
  code: string;
  label: string;
  packets: number;
  pct_packets: number;
};

type Feature = {
  type: "Feature";
  properties: { id: string; name: string };
  geometry:
    | { type: "Polygon"; coordinates: number[][][] }
    | { type: "MultiPolygon"; coordinates: number[][][][] };
};

type FeatureCollection = {
  type: "FeatureCollection";
  features: Feature[];
};

type WorldAttackMapProps = {
  countries: CountryStat[];
  className?: string;
};

const WIDTH = 960;
const HEIGHT = 480;

function project(lon: number, lat: number): [number, number] {
  const x = ((lon + 180) / 360) * WIDTH;
  const y = ((90 - lat) / 180) * HEIGHT;
  return [x, y];
}

function ringToPath(ring: number[][]): string {
  if (!ring.length) return "";
  const [x0, y0] = project(ring[0][0], ring[0][1]);
  let d = `M${x0.toFixed(1)},${y0.toFixed(1)}`;
  for (let i = 1; i < ring.length; i++) {
    const [x, y] = project(ring[i][0], ring[i][1]);
    d += `L${x.toFixed(1)},${y.toFixed(1)}`;
  }
  return `${d}Z`;
}

function geomToPath(geom: Feature["geometry"]): string {
  if (geom.type === "Polygon") {
    return geom.coordinates.map(ringToPath).join("");
  }
  return geom.coordinates
    .map((poly) => poly.map(ringToPath).join(""))
    .join("");
}

function heatColor(t: number): string {
  const x = Math.max(0, Math.min(1, t));
  if (x <= 0) return "color-mix(in oklab, var(--secondary) 55%, transparent)";
  if (x < 0.33) {
    const u = x / 0.33;
    return `color-mix(in oklab, #06b6d4 ${Math.round(35 + u * 45)}%, var(--secondary))`;
  }
  if (x < 0.66) {
    const u = (x - 0.33) / 0.33;
    return `color-mix(in oklab, #f59e0b ${Math.round(40 + u * 40)}%, #06b6d4)`;
  }
  const u = (x - 0.66) / 0.34;
  return `color-mix(in oklab, #ef4444 ${Math.round(50 + u * 50)}%, #f59e0b)`;
}

type HoverInfo = {
  code: string;
  name: string;
  packets: number;
  pct: number;
  x: number;
  y: number;
};

export function WorldAttackMap({ countries, className }: WorldAttackMapProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [world, setWorld] = useState<FeatureCollection | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [hover, setHover] = useState<HoverInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch("/geo/world-countries.min.json");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as FeatureCollection;
        if (!cancelled) setWorld(data);
      } catch (err) {
        if (!cancelled) {
          setLoadError(
            err instanceof Error ? err.message : "Could not load world map",
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const byCode = useMemo(() => {
    const m = new Map<string, CountryStat>();
    for (const c of countries) {
      if (!c.code || c.code === "ZZ") continue;
      m.set(c.code.toUpperCase(), c);
    }
    return m;
  }, [countries]);

  const maxPct = useMemo(() => {
    let max = 0.0001;
    for (const c of byCode.values()) {
      if (c.pct_packets > max) max = c.pct_packets;
    }
    return max;
  }, [byCode]);

  const knownPackets = useMemo(
    () =>
      countries
        .filter((c) => c.code !== "ZZ")
        .reduce((a, c) => a + c.packets, 0),
    [countries],
  );

  function setHoverFromEvent(
    e: MouseEvent<SVGPathElement>,
    code: string,
    name: string,
    stat: CountryStat | undefined,
  ) {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const rect = wrap.getBoundingClientRect();
    setHover({
      code,
      name,
      packets: stat?.packets ?? 0,
      pct: stat?.pct_packets ?? 0,
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    });
  }

  const tooltipStyle = (() => {
    if (!hover || !wrapRef.current) return undefined;
    const w = wrapRef.current.clientWidth;
    const tipW = 180;
    const left = Math.min(Math.max(8, hover.x + 14), Math.max(8, w - tipW - 8));
    const top = Math.max(8, hover.y - 12);
    return {
      left,
      top,
      transform: "translateY(-100%)" as const,
    };
  })();

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-medium">World source distribution</h3>
        <span className="font-mono text-[11px] text-muted-foreground">
          {knownPackets.toLocaleString()} pkts geolocated
        </span>
      </div>

      <div
        ref={wrapRef}
        className="relative overflow-hidden rounded-lg border border-border/60 bg-secondary/15"
        onMouseLeave={() => setHover(null)}
      >
        {loadError && (
          <p className="p-4 text-xs text-destructive">{loadError}</p>
        )}
        {!world && !loadError && (
          <p className="p-4 font-mono text-xs text-muted-foreground">
            Loading world map…
          </p>
        )}
        {world && (
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            className="h-auto w-full"
            role="img"
            aria-label="World attack source heat map by country"
          >
            {world.features.map((f) => {
              const code = (f.properties.id || "").toUpperCase();
              const stat = byCode.get(code);
              const intensity = stat ? stat.pct_packets / maxPct : 0;
              const name = f.properties.name || code;
              return (
                <path
                  key={`${code}-${name}`}
                  d={geomToPath(f.geometry)}
                  fill={heatColor(intensity)}
                  stroke="color-mix(in oklab, var(--border) 80%, transparent)"
                  strokeWidth={0.6}
                  className="cursor-default transition-[filter] duration-100 hover:brightness-110"
                  onMouseEnter={(e) => setHoverFromEvent(e, code, name, stat)}
                  onMouseMove={(e) => setHoverFromEvent(e, code, name, stat)}
                />
              );
            })}
          </svg>
        )}

        {hover && tooltipStyle && (
          <div
            className="pointer-events-none absolute z-10 w-[11.5rem] rounded-md border border-border/70 bg-popover/95 px-2.5 py-2 text-xs shadow-md backdrop-blur-sm"
            style={tooltipStyle}
          >
            <div className="font-medium">
              {hover.name}{" "}
              <span className="font-mono text-muted-foreground">
                ({hover.code})
              </span>
            </div>
            <div className="mt-1 space-y-0.5 font-mono text-[11px] text-muted-foreground">
              <div>{hover.packets.toLocaleString()} packets</div>
              <div>{hover.pct.toFixed(2)}% of capture</div>
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
        <span>Low</span>
        <div
          className="h-2 flex-1 rounded-full"
          style={{
            background:
              "linear-gradient(90deg, color-mix(in oklab, var(--secondary) 55%, transparent), #06b6d4, #f59e0b, #ef4444)",
          }}
        />
        <span>High</span>
      </div>
    </div>
  );
}
