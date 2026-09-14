"use client";

import { cn } from "@/lib/utils";

type PrivateWanIpProps = {
  ip?: string | null;
  className?: string;
};

/**
 * Blurs a client WAN IP until hover/focus — for screen-share privacy.
 */
export function PrivateWanIp({ ip, className }: PrivateWanIpProps) {
  if (!ip) {
    return <span className={cn("text-muted-foreground", className)}>—</span>;
  }

  return (
    <span
      tabIndex={0}
      title="Hover or focus to reveal WAN IP"
      className={cn(
        "inline-block max-w-full cursor-default rounded-sm align-baseline outline-none",
        "blur-[6px] select-none transition-[filter] duration-150 ease-out",
        "hover:blur-none hover:select-text",
        "focus-visible:blur-none focus-visible:select-text focus-visible:ring-2 focus-visible:ring-ring/50",
        className,
      )}
    >
      {ip}
    </span>
  );
}
