"use client";

import { Menu } from "@base-ui/react/menu";
import {
  Download,
  FileClock,
  MoreVertical,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ConnectionLogsDialog } from "@/components/dashboard/connection-logs-dialog";
import { CreateConfigDialog } from "@/components/dashboard/create-config-dialog";
import {
  ConfigActionDialog,
  type ConfigActionMode,
} from "@/components/dashboard/delete-config-dialog";
import {
  PAGE_SIZE,
  PaginationTabs,
  slicePage,
} from "@/components/dashboard/pagination-tabs";
import { PrivateWanIp } from "@/components/dashboard/private-wan-ip";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { useBrand } from "@/components/brand-provider";
import { useTheme } from "@/components/theme-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ApiError,
  deleteConfig,
  downloadConfigFile,
  downloadOvpnText,
  fetchMe,
  importConfigs,
  listConfigs,
  reissueConfig,
  updateConfigWanLogging,
  updateConfigWarpRouting,
  type ClientConfig,
  type CreateConfigResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const LIST_POLL_MS = 20_000;

function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function formatRelativeSeen(iso: string | null | undefined): string {
  if (!iso) return "Never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "Never";
  const diffMs = Date.now() - then;
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function ActiveSessionsList({
  config,
}: {
  config: ClientConfig;
}) {
  const sessions = config.active_sessions ?? [];
  const count = config.session_count ?? sessions.length;
  if (!config.is_online && sessions.length === 0) {
    return (
      <p className="font-mono text-[11px] text-muted-foreground">No live sessions</p>
    );
  }
  return (
    <div className="space-y-1.5">
      <p className="font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
        Live sessions ({count})
      </p>
      <ul className="space-y-1.5">
        {sessions.map((s, idx) => (
          <li
            key={`${s.vpn_ip ?? "x"}-${s.wan_ip ?? "y"}-${idx}`}
            className="rounded-md border border-border/50 bg-secondary/20 px-2.5 py-1.5 font-mono text-[11px]"
          >
            <div className="flex flex-wrap gap-x-3 gap-y-0.5">
              <span>
                <span className="text-muted-foreground">VPN </span>
                <span className="text-foreground/90">{s.vpn_ip ?? "—"}</span>
              </span>
              <span>
                <span className="text-muted-foreground">WAN </span>
                <PrivateWanIp ip={s.wan_ip} />
              </span>
              <span className="text-muted-foreground">
                since {formatRelativeSeen(s.connected_since)}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function OnlineBadge({ online }: { online: boolean }) {
  return (
    <span
      className={
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide " +
        (online
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
          : "border-border bg-secondary/40 text-muted-foreground")
      }
    >
      <span
        className={
          "size-1.5 rounded-full " +
          (online ? "bg-emerald-500" : "bg-muted-foreground/50")
        }
      />
      {online ? "Online" : "Offline"}
    </span>
  );
}

type WanLoggingMode = "inherit" | "on" | "off";

function wanModeFromValue(value: boolean | null | undefined): WanLoggingMode {
  if (value === true) return "on";
  if (value === false) return "off";
  return "inherit";
}

function wanValueFromMode(mode: WanLoggingMode): boolean | null {
  if (mode === "on") return true;
  if (mode === "off") return false;
  return null;
}

/** Cloudflare WARP mark */
function WarpLogo({ className }: { className?: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/warp-logo.png"
      alt=""
      width={18}
      height={18}
      className={cn("size-[18px] shrink-0 object-contain", className)}
      aria-hidden
    />
  );
}

function SwitchToggle({
  checked,
  disabled,
  onChange,
  id,
  label,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
  id: string;
  label: string;
}) {
  return (
    <button
      type="button"
      id={id}
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors outline-none",
        "focus-visible:ring-3 focus-visible:ring-ring/50",
        disabled && "cursor-not-allowed opacity-50",
        checked
          ? "border-orange-500/50 bg-orange-500"
          : "border-border bg-muted/60",
      )}
    >
      <span
        className={cn(
          "pointer-events-none absolute top-0.5 left-0.5 size-3.5 rounded-full bg-white shadow-sm transition-transform",
          checked && "translate-x-4",
        )}
      />
    </button>
  );
}

const menuItemClass = cn(
  "flex w-full cursor-default items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm outline-none select-none",
  "data-highlighted:bg-accent data-highlighted:text-accent-foreground",
  "data-disabled:pointer-events-none data-disabled:opacity-40",
);

function ConfigActionsMenu({
  revoked,
  reissueDisabled,
  onLogs,
  onDownload,
  onReissue,
  onRevoke,
  onDelete,
}: {
  revoked: boolean;
  reissueDisabled: boolean;
  onLogs: () => void;
  onDownload: () => void;
  onReissue: () => void;
  onRevoke: () => void;
  onDelete: () => void;
}) {
  return (
    <Menu.Root>
      <Menu.Trigger
        className={cn(
          "inline-flex size-8 items-center justify-center rounded-lg border border-transparent text-muted-foreground outline-none transition-colors",
          "hover:border-border/80 hover:bg-secondary/70 hover:text-foreground",
          "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
          "data-popup-open:border-border/80 data-popup-open:bg-secondary/70 data-popup-open:text-foreground",
        )}
        aria-label="Config actions"
      >
        <MoreVertical className="size-4" />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner className="z-50 outline-none" sideOffset={6} align="end">
          <Menu.Popup
            className={cn(
              "min-w-44 origin-[var(--transform-origin)] rounded-xl border border-border/80 bg-popover p-1 text-popover-foreground shadow-lg outline-none",
              "transition-[transform,opacity] duration-100",
              "data-starting-style:scale-95 data-starting-style:opacity-0",
              "data-ending-style:scale-95 data-ending-style:opacity-0",
            )}
          >
            <Menu.Item className={menuItemClass} onClick={onLogs}>
              <FileClock className="size-3.5 opacity-70" />
              Connection logs
            </Menu.Item>
            {!revoked && (
              <Menu.Item className={menuItemClass} onClick={onDownload}>
                <Download className="size-3.5 opacity-70" />
                Download .ovpn
              </Menu.Item>
            )}
            <Menu.Separator className="my-1 h-px bg-border/70" />
            {revoked ? (
              <>
                <Menu.Item
                  className={menuItemClass}
                  disabled={reissueDisabled}
                  onClick={onReissue}
                >
                  <RefreshCw className="size-3.5 opacity-70" />
                  Reissue
                </Menu.Item>
                <Menu.Item
                  className={cn(menuItemClass, "text-destructive data-highlighted:text-destructive")}
                  onClick={onDelete}
                >
                  <Trash2 className="size-3.5 opacity-70" />
                  Delete
                </Menu.Item>
              </>
            ) : (
              <Menu.Item
                className={cn(menuItemClass, "text-destructive data-highlighted:text-destructive")}
                onClick={onRevoke}
              >
                <Trash2 className="size-3.5 opacity-70" />
                Revoke access
              </Menu.Item>
            )}
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

export function ConfigsDashboard() {
  const { admin, setAdmin } = useTheme();
  const { config: brandConfig } = useBrand();
  const [configs, setConfigs] = useState<ClientConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState<{
    config: ClientConfig;
    mode: ConfigActionMode;
  } | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionDialogError, setActionDialogError] = useState<string | null>(
    null,
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [logsConfig, setLogsConfig] = useState<ClientConfig | null>(null);
  const [wanBusyId, setWanBusyId] = useState<string | null>(null);
  const [warpBusyId, setWarpBusyId] = useState<string | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isFullAdmin = admin?.role !== "sub_admin";
  const duplicateCnMode = brandConfig.duplicate_cn_mode === true;
  const showWarp = isFullAdmin && brandConfig.warp_routing_enabled !== false;
  const slotLimit =
    admin?.role === "sub_admin" ? admin.config_slot_limit : null;
  const slotsUsed =
    admin?.role === "sub_admin" ? (admin.config_slots_used ?? 0) : null;
  const atSlotLimit =
    typeof slotLimit === "number" &&
    typeof slotsUsed === "number" &&
    slotsUsed >= slotLimit;
  const hasActiveSharedConfig = configs.some((c) => c.status !== "revoked");
  const blockNewConfigs = duplicateCnMode && hasActiveSharedConfig;
  const canCreateConfigs = !blockNewConfigs && !atSlotLimit;

  const filteredConfigs = configs.filter((c) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      c.client_name.toLowerCase().includes(q) ||
      c.label.toLowerCase().includes(q)
    );
  });
  const pageConfigs = slicePage(filteredConfigs, page, PAGE_SIZE);

  useEffect(() => {
    setPage(1);
  }, [search]);

  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(filteredConfigs.length / PAGE_SIZE));
    if (page > maxPage) setPage(maxPage);
  }, [filteredConfigs.length, page]);

  const refreshProfile = useCallback(async () => {
    try {
      const me = await fetchMe();
      setAdmin(me);
    } catch {
      /* ignore */
    }
  }, [setAdmin]);

  const refresh = useCallback(async () => {
    setListError(null);
    try {
      const data = await listConfigs();
      setConfigs(data);
      await refreshProfile();
    } catch (err) {
      setListError(
        err instanceof ApiError
          ? err.message
          : "Could not load VPN configs.",
      );
    } finally {
      setLoading(false);
    }
  }, [refreshProfile]);

  useEffect(() => {
    void refresh();
    pollRef.current = setInterval(() => void refresh(), LIST_POLL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refresh]);

  async function onWanLoggingChange(
    config: ClientConfig,
    mode: WanLoggingMode,
  ) {
    setWanBusyId(config.id);
    setActionError(null);
    try {
      const updated = await updateConfigWanLogging(
        config.id,
        wanValueFromMode(mode),
      );
      setConfigs((prev) =>
        prev.map((c) => (c.id === updated.id ? updated : c)),
      );
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? err.message
          : "Could not update WAN IP logging.",
      );
    } finally {
      setWanBusyId(null);
    }
  }

  async function onWarpRoutingChange(
    config: ClientConfig,
    enabled: boolean,
  ) {
    setWarpBusyId(config.id);
    setActionError(null);
    try {
      const updated = await updateConfigWarpRouting(config.id, enabled);
      setConfigs((prev) =>
        prev.map((c) => (c.id === updated.id ? updated : c)),
      );
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? err.message
          : "Could not update Warp routing.",
      );
    } finally {
      setWarpBusyId(null);
    }
  }

  function onCreated(created: CreateConfigResponse) {
    setConfigs((prev) => {
      const without = prev.filter((c) => c.id !== created.id);
      const { ovpn: _ovpn, ...row } = created;
      return [row, ...without];
    });
    void refreshProfile();
  }

  async function onDownload(config: ClientConfig) {
    setActionError(null);
    try {
      await downloadConfigFile(config.id, `${config.client_name}.ovpn`);
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? err.message
          : "Download failed. Try again.",
      );
    }
  }

  async function onImportFromServer() {
    if (!isFullAdmin) return;
    setImportBusy(true);
    setActionError(null);
    try {
      const result = await importConfigs({});
      if (result.imported.length === 0 && Object.keys(result.errors).length) {
        setActionError(
          `Import failed: ${Object.entries(result.errors)
            .map(([k, v]) => `${k}: ${v}`)
            .join("; ")}`,
        );
      } else if (result.imported.length === 0) {
        setActionError("No CLI clients left to import — all PKI certs are already listed.");
      }
      await refresh();
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? err.message
          : "Could not import existing OpenVPN clients.",
      );
    } finally {
      setImportBusy(false);
    }
  }

  async function confirmAction() {
    if (!pendingAction) return;
    const { config, mode } = pendingAction;
    setActionBusy(true);
    setActionDialogError(null);
    try {
      if (mode === "reissue") {
        const result = await reissueConfig(config.id);
        const { ovpn, ...row } = result;
        setConfigs((prev) => prev.map((c) => (c.id === row.id ? row : c)));
        downloadOvpnText(`${row.client_name}.ovpn`, ovpn);
        setPendingAction(null);
        await refreshProfile();
        return;
      }

      const updated = await deleteConfig(config.id);
      if (updated === null) {
        setConfigs((prev) => prev.filter((c) => c.id !== config.id));
      } else {
        setConfigs((prev) =>
          prev.map((c) => (c.id === updated.id ? updated : c)),
        );
      }
      setPendingAction(null);
      await refreshProfile();
    } catch (err) {
      setActionDialogError(
        err instanceof ApiError
          ? err.message
          : mode === "reissue"
            ? "Could not reissue this config."
            : mode === "delete"
              ? "Could not delete this config."
              : "Could not revoke this access.",
      );
    } finally {
      setActionBusy(false);
    }
  }

  return (
    <div className="dash-page">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="dash-title">
            VPN configs
          </h1>
          <p className="dash-sub">
            {admin?.role === "sub_admin"
              ? "Create and revoke VPN access files within your slot limit."
              : "Create and manage VPN access files for customers and staff."}
          </p>
          {(typeof slotLimit === "number" || duplicateCnMode) && (
            <div className="mt-1.5 flex max-w-3xl flex-col gap-1.5 sm:flex-row sm:items-start sm:gap-3">
              {typeof slotLimit === "number" && (
                <p className="shrink-0 font-mono text-[11px] text-muted-foreground sm:text-xs">
                  Slots used: {slotsUsed ?? 0}/{slotLimit}
                  {atSlotLimit
                    ? " · limit reached — revoke one to create another"
                    : ""}
                </p>
              )}
              {duplicateCnMode && (
                <p className="rounded-md border border-border/60 bg-secondary/30 px-2.5 py-1.5 text-xs text-muted-foreground sm:max-w-md">
                  <span className="font-medium text-foreground">
                    Duplicate-CN:
                  </span>{" "}
                  one shared cert for many users. Create / import / reissue stay
                  locked — live sessions list on that config.
                </p>
              )}
            </div>
          )}
        </div>
        <div className="flex w-full shrink-0 flex-col gap-1.5 sm:w-auto sm:flex-row">
          {isFullAdmin && (
            <Button
              type="button"
              variant="outline"
              disabled={importBusy || blockNewConfigs}
              onClick={() => void onImportFromServer()}
              className="h-9 w-full sm:w-auto"
              title={
                blockNewConfigs
                  ? "Disabled while duplicate-CN mode has a shared config"
                  : undefined
              }
            >
              {importBusy ? "Importing…" : "Import from server"}
            </Button>
          )}
          <Button
            onClick={() => setCreateOpen(true)}
            disabled={!canCreateConfigs || blockNewConfigs}
            className="brand-btn-gradient h-9 w-full shrink-0 px-4 shadow-[0_0_20px_color-mix(in_srgb,var(--brand-accent)_20%,transparent)] sm:w-auto"
            title={
              blockNewConfigs
                ? "Disabled while duplicate-CN mode has a shared config"
                : undefined
            }
          >
            Create config
          </Button>
        </div>
      </div>

      {(listError || actionError) && (
        <p
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
        >
          {listError || actionError}
        </p>
      )}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by client name or label…"
          className="h-9 max-w-md bg-background/60 font-mono text-sm"
          aria-label="Search VPN configs"
        />
        <p className="font-mono text-[11px] text-muted-foreground">
          {filteredConfigs.length === configs.length
            ? `${configs.length} config${configs.length === 1 ? "" : "s"}`
            : `${filteredConfigs.length} of ${configs.length} configs`}
        </p>
      </div>

      {/* Mobile cards */}
      <div className="space-y-2 md:hidden">
        {loading && (
          <p className="py-5 text-center font-mono text-sm text-muted-foreground">
            Loading configs…
          </p>
        )}
        {!loading && filteredConfigs.length === 0 && (
          <div className="dash-empty">
            {configs.length === 0 ? (
              <>
                No VPN configs yet.{" "}
                {blockNewConfigs ? (
                  <>Duplicate-CN mode blocks creating more configs.</>
                ) : isFullAdmin ? (
                  <>
                    Use <strong>Import from server</strong> for CLI clients, or{" "}
                    <strong>Create config</strong> for a new one.
                  </>
                ) : (
                  <>
                    Tap <strong>Create config</strong> to make the first one.
                  </>
                )}
              </>
            ) : (
              <>No configs match “{search.trim()}”.</>
            )}
          </div>
        )}
        {!loading &&
          pageConfigs.map((config) => {
            const revoked = config.status === "revoked";
            const hasVpnIp = Boolean(config.vpn_ip);
            const warpDisabled =
              revoked || !hasVpnIp || warpBusyId === config.id;
            const showSessions =
              duplicateCnMode ||
              (config.active_sessions?.length ?? 0) > 1 ||
              (config.session_count ?? 0) > 1;
            return (
              <article
                key={config.id}
                className="dash-card"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{config.label}</p>
                    <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">
                      {config.client_name}
                    </p>
                  </div>
                  <ConfigActionsMenu
                    revoked={revoked}
                    reissueDisabled={atSlotLimit || blockNewConfigs}
                    onLogs={() => setLogsConfig(config)}
                    onDownload={() => void onDownload(config)}
                    onReissue={() => {
                      setActionDialogError(null);
                      setPendingAction({ config, mode: "reissue" });
                    }}
                    onRevoke={() => {
                      setActionDialogError(null);
                      setPendingAction({ config, mode: "revoke" });
                    }}
                    onDelete={() => {
                      setActionDialogError(null);
                      setPendingAction({ config, mode: "delete" });
                    }}
                  />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <OnlineBadge online={Boolean(config.is_online)} />
                  <StatusBadge status={config.status} />
                </div>
                {showSessions ? (
                  <ActiveSessionsList config={config} />
                ) : (
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-2 font-mono text-[11px] text-muted-foreground">
                    <div>
                      <dt className="text-muted-foreground/80">VPN IP</dt>
                      <dd className="mt-0.5 text-foreground/90">
                        {config.vpn_ip ?? "—"}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground/80">Last seen</dt>
                      <dd className="mt-0.5 text-foreground/90">
                        {formatRelativeSeen(config.last_connected_at)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground/80">Expires</dt>
                      <dd className="mt-0.5 text-foreground/90">
                        {formatDate(config.expires_at)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground/80">WAN IP</dt>
                      <dd className="mt-0.5 text-foreground/90">
                        <PrivateWanIp ip={config.last_wan_ip} />
                      </dd>
                    </div>
                  </dl>
                )}
                {showSessions && (
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-2 font-mono text-[11px] text-muted-foreground">
                    <div>
                      <dt className="text-muted-foreground/80">Last seen</dt>
                      <dd className="mt-0.5 text-foreground/90">
                        {formatRelativeSeen(config.last_connected_at)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground/80">Expires</dt>
                      <dd className="mt-0.5 text-foreground/90">
                        {formatDate(config.expires_at)}
                      </dd>
                    </div>
                  </dl>
                )}
                <div className="space-y-1">
                  <label
                    htmlFor={`wan-m-${config.id}`}
                    className="text-[11px] text-muted-foreground"
                  >
                    WAN IP logging
                  </label>
                  <select
                    id={`wan-m-${config.id}`}
                    value={wanModeFromValue(config.wan_ip_logging_enabled)}
                    disabled={wanBusyId === config.id}
                    onChange={(e) =>
                      void onWanLoggingChange(
                        config,
                        e.target.value as WanLoggingMode,
                      )
                    }
                    className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 dark:bg-input/30"
                  >
                    <option value="inherit">Inherit</option>
                    <option value="on">On</option>
                    <option value="off">Off</option>
                  </select>
                </div>
                {showWarp && (
                  <div
                    className="flex items-center justify-between gap-3 border-t border-border/50 pt-3"
                    title={
                      hasVpnIp
                        ? "Route this client through Cloudflare WARP"
                        : "Connect once so a 10.8.0.x IP is assigned (ipp.txt)"
                    }
                  >
                    <span className="inline-flex items-center gap-1.5 text-xs">
                      <WarpLogo />
                      Warp{" "}
                      <span className="text-muted-foreground">(BETA)</span>
                    </span>
                    <div className="flex items-center gap-2">
                      <SwitchToggle
                        id={`warp-m-${config.id}`}
                        label={`Warp routing for ${config.label}`}
                        checked={Boolean(config.warp_routing_enabled)}
                        disabled={warpDisabled}
                        onChange={(enabled) =>
                          void onWarpRoutingChange(config, enabled)
                        }
                      />
                      <span
                        className={cn(
                          "text-[11px] font-medium tracking-wide",
                          config.warp_routing_enabled && !warpDisabled
                            ? "text-orange-500"
                            : "text-muted-foreground",
                        )}
                      >
                        {config.warp_routing_enabled ? "On" : "Off"}
                      </span>
                    </div>
                  </div>
                )}
              </article>
            );
          })}
        <PaginationTabs
          page={page}
          totalItems={filteredConfigs.length}
          onPageChange={setPage}
          className="rounded-xl border border-border/60 bg-card/50"
        />
      </div>

      {/* Desktop table */}
      <div className="auth-glow-border hidden overflow-hidden rounded-xl bg-card/90 md:block">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[800px] text-left text-sm">
            <thead className="border-b border-border bg-secondary/40">
              <tr>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">
                  {duplicateCnMode ? "Live sessions" : "VPN IP"}
                </th>
                <th className="px-4 py-3 font-medium">Last seen</th>
                <th className="px-4 py-3 font-medium">Online</th>
                <th className="px-4 py-3 font-medium">Expires</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">
                  Last WAN IP · logging
                </th>
                {showWarp && (
                  <th className="px-4 py-3 font-medium">
                    <span className="inline-flex items-center gap-1.5">
                      <WarpLogo />
                      <span>
                        Warp{" "}
                        <span className="font-normal text-muted-foreground">
                          (BETA)
                        </span>
                      </span>
                    </span>
                  </th>
                )}
                <th className="w-12 px-3 py-3 text-right font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td
                    colSpan={showWarp ? 9 : 8}
                    className="px-4 py-10 text-center font-mono text-sm text-muted-foreground"
                  >
                    Loading configs…
                  </td>
                </tr>
              )}
              {!loading && filteredConfigs.length === 0 && (
                <tr>
                  <td
                    colSpan={showWarp ? 9 : 8}
                    className="px-4 py-10 text-center text-sm text-muted-foreground"
                  >
                    {configs.length === 0 ? (
                      blockNewConfigs ? (
                        <>
                          No VPN configs yet. Duplicate-CN mode blocks creating
                          more configs.
                        </>
                      ) : (
                        <>
                          No VPN configs yet. Click{" "}
                          <strong>Create config</strong> to make the first one.
                        </>
                      )
                    ) : (
                      <>No configs match “{search.trim()}”.</>
                    )}
                  </td>
                </tr>
              )}
              {!loading &&
                pageConfigs.map((config) => {
                  const revoked = config.status === "revoked";
                  return (
                    <tr
                      key={config.id}
                      className="border-b border-border/60 last:border-0"
                    >
                      <td className="px-4 py-3">
                        <div className="font-medium">{config.label}</div>
                        <div className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                          {config.client_name}
                        </div>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                        {duplicateCnMode ||
                        (config.active_sessions?.length ?? 0) > 1 ||
                        (config.session_count ?? 0) > 1 ? (
                          <ActiveSessionsList config={config} />
                        ) : (
                          config.vpn_ip ?? "—"
                        )}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                        {formatRelativeSeen(config.last_connected_at)}
                      </td>
                      <td className="px-4 py-3">
                        <OnlineBadge online={Boolean(config.is_online)} />
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                        {formatDate(config.expires_at)}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={config.status} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-mono text-xs text-muted-foreground">
                          <PrivateWanIp ip={config.last_wan_ip} />
                        </div>
                        <select
                          value={wanModeFromValue(
                            config.wan_ip_logging_enabled,
                          )}
                          disabled={wanBusyId === config.id}
                          onChange={(e) =>
                            void onWanLoggingChange(
                              config,
                              e.target.value as WanLoggingMode,
                            )
                          }
                          className="mt-1 h-7 w-full rounded-md border border-input bg-transparent px-1.5 text-[11px] outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 dark:bg-input/30"
                          title="WAN IP logging for this config"
                        >
                          <option value="inherit">Inherit</option>
                          <option value="on">On</option>
                          <option value="off">Off</option>
                        </select>
                      </td>
                      {showWarp && (
                        <td className="px-4 py-3">
                          {(() => {
                            const hasVpnIp = Boolean(config.vpn_ip);
                            const disabled =
                              revoked ||
                              !hasVpnIp ||
                              warpBusyId === config.id;
                            return (
                              <div
                                className="flex items-center gap-2.5"
                                title={
                                  hasVpnIp
                                    ? "Route this client through Cloudflare WARP"
                                    : "Connect once so a 10.8.0.x IP is assigned (ipp.txt)"
                                }
                              >
                                <SwitchToggle
                                  id={`warp-${config.id}`}
                                  label={`Warp routing for ${config.label}`}
                                  checked={Boolean(config.warp_routing_enabled)}
                                  disabled={disabled}
                                  onChange={(enabled) =>
                                    void onWarpRoutingChange(config, enabled)
                                  }
                                />
                                <span
                                  className={cn(
                                    "text-[11px] font-medium tracking-wide",
                                    config.warp_routing_enabled && !disabled
                                      ? "text-orange-500"
                                      : "text-muted-foreground",
                                  )}
                                >
                                  {config.warp_routing_enabled ? "On" : "Off"}
                                </span>
                              </div>
                            );
                          })()}
                        </td>
                      )}
                      <td className="px-3 py-3 text-right">
                        <ConfigActionsMenu
                          revoked={revoked}
                          reissueDisabled={atSlotLimit || blockNewConfigs}
                          onLogs={() => setLogsConfig(config)}
                          onDownload={() => void onDownload(config)}
                          onReissue={() => {
                            setActionDialogError(null);
                            setPendingAction({ config, mode: "reissue" });
                          }}
                          onRevoke={() => {
                            setActionDialogError(null);
                            setPendingAction({ config, mode: "revoke" });
                          }}
                          onDelete={() => {
                            setActionDialogError(null);
                            setPendingAction({ config, mode: "delete" });
                          }}
                        />
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
        <PaginationTabs
          page={page}
          totalItems={filteredConfigs.length}
          onPageChange={setPage}
        />
      </div>

      <CreateConfigDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={onCreated}
      />

      <ConnectionLogsDialog
        config={logsConfig}
        open={Boolean(logsConfig)}
        onOpenChange={(open) => {
          if (!open) setLogsConfig(null);
        }}
      />

      <ConfigActionDialog
        config={pendingAction?.config ?? null}
        mode={pendingAction?.mode ?? "revoke"}
        open={Boolean(pendingAction)}
        onOpenChange={(open) => {
          if (!open) setPendingAction(null);
        }}
        onConfirm={() => void confirmAction()}
        busy={actionBusy}
        error={actionDialogError}
      />
    </div>
  );
}
