"use client";

import { cn } from "@/lib/utils";

const PAGE_SIZE = 8;

export function pageCountFor(total: number, pageSize = PAGE_SIZE): number {
  return Math.max(1, Math.ceil(Math.max(0, total) / pageSize));
}

export function slicePage<T>(
  items: T[],
  page: number,
  pageSize = PAGE_SIZE,
): T[] {
  const safePage = Math.min(Math.max(1, page), pageCountFor(items.length, pageSize));
  const start = (safePage - 1) * pageSize;
  return items.slice(start, start + pageSize);
}

/** Google-style page tabs: 1 2 3 … N with a sliding window around current. */
export function PaginationTabs({
  page,
  totalItems,
  pageSize = PAGE_SIZE,
  onPageChange,
  className,
}: {
  page: number;
  totalItems: number;
  pageSize?: number;
  onPageChange: (page: number) => void;
  className?: string;
}) {
  const totalPages = pageCountFor(totalItems, pageSize);
  if (totalItems <= pageSize) return null;

  const current = Math.min(Math.max(1, page), totalPages);
  const pages = buildPageList(current, totalPages);

  return (
    <nav
      aria-label="Pagination"
      className={cn(
        "flex flex-wrap items-center justify-center gap-1 border-t border-border/60 px-2 py-2 sm:px-3 sm:py-3",
        className,
      )}
    >
      <button
        type="button"
        disabled={current <= 1}
        onClick={() => onPageChange(current - 1)}
        className="rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
      >
        Prev
      </button>
      {pages.map((p, idx) =>
        p === "…" ? (
          <span
            key={`ellipsis-${idx}`}
            className="px-1.5 font-mono text-sm text-muted-foreground"
          >
            …
          </span>
        ) : (
          <button
            key={p}
            type="button"
            aria-current={p === current ? "page" : undefined}
            onClick={() => onPageChange(p)}
            className={cn(
              "min-w-8 rounded-md px-2.5 py-1.5 text-sm transition",
              p === current
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
            )}
          >
            {p}
          </button>
        ),
      )}
      <button
        type="button"
        disabled={current >= totalPages}
        onClick={() => onPageChange(current + 1)}
        className="rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
      >
        Next
      </button>
    </nav>
  );
}

function buildPageList(
  current: number,
  total: number,
): Array<number | "…"> {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const set = new Set<number>([1, total, current]);
  for (let d = 1; d <= 2; d += 1) {
    if (current - d >= 1) set.add(current - d);
    if (current + d <= total) set.add(current + d);
  }
  const sorted = [...set].sort((a, b) => a - b);
  const out: Array<number | "…"> = [];
  let prev = 0;
  for (const n of sorted) {
    if (prev && n - prev > 1) out.push("…");
    out.push(n);
    prev = n;
  }
  return out;
}

export { PAGE_SIZE };
