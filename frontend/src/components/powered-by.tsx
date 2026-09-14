export function PoweredByPopout({ className = "" }: { className?: string }) {
  return (
    <p
      className={`font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground/80 ${className}`}
    >
      Powered by{" "}
      <span className="text-muted-foreground">Popout VPN</span>
    </p>
  );
}

/** @deprecated Use PoweredByPopout */
export const PoweredByAdjentX = PoweredByPopout;
