"use client";

import { useEffect, useMemo, useState } from "react";

import { useBrand } from "@/components/brand-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ApiError,
  fetchSiteSettings,
  testAttackWebhook,
  updateSiteSettings,
  validateAttackBpf,
  type OvpnBindMode,
  type OvpnRemoteMode,
  type SiteSettingsAdmin,
} from "@/lib/api";

function ColorField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          aria-label={label}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-10 w-12 cursor-pointer rounded border border-input bg-transparent p-1"
        />
        <Input
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 font-mono text-sm"
          spellCheck={false}
        />
      </div>
    </div>
  );
}

const selectClassName =
  "flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

function buildClientPreview(opts: {
  remoteHost: string;
  remoteMode: OvpnRemoteMode;
  remotePort: number;
  remotePortMin: number;
  remotePortMax: number;
  proto: string;
  tunMtu: string;
  mssfix: string;
  tcpNodelay: boolean;
  bindMode: OvpnBindMode;
  lport: number;
  auth: string;
  verb: number;
  extra: string;
}): string {
  const lines: string[] = ["client", "dev tun"];
  const mtu = Number(opts.tunMtu);
  if (opts.tunMtu.trim() && Number.isFinite(mtu) && mtu > 0) {
    lines.push(`tun-mtu ${mtu}`);
  }
  const mss = Number(opts.mssfix);
  if (opts.mssfix.trim() && Number.isFinite(mss) && mss > 0) {
    lines.push(`mssfix ${mss}`);
  }
  if (opts.tcpNodelay) lines.push("tcp-nodelay");
  lines.push(`proto ${opts.proto.trim() || "tcp4"}`);
  const host = opts.remoteHost.trim() || "vpn.example.com";
  if (opts.remoteMode === "remote_random") {
    const lo = Math.min(opts.remotePortMin, opts.remotePortMax);
    const hi = Math.max(opts.remotePortMin, opts.remotePortMax);
    lines.push("remote-random");
    const count = hi - lo + 1;
    if (count <= 8) {
      for (let port = lo; port <= hi; port += 1) {
        lines.push(`remote ${host} ${port}`);
      }
    } else {
      for (let port = lo; port <= lo + 2; port += 1) {
        lines.push(`remote ${host} ${port}`);
      }
      lines.push(`# … ${count - 4} more remote lines …`);
      for (let port = hi - 1; port <= hi; port += 1) {
        lines.push(`remote ${host} ${port}`);
      }
    }
  } else {
    lines.push(`remote ${host} ${opts.remotePort || 1194}`);
  }
  lines.push("resolv-retry infinite");
  if (opts.bindMode === "nobind") lines.push("nobind");
  else lines.push(`lport ${opts.lport}`);
  lines.push(
    "",
    "persist-key",
    "persist-tun",
    "remote-cert-tls server",
    `auth ${opts.auth.trim() || "SHA512"}`,
    "ignore-unknown-option block-outside-dns",
    `verb ${opts.verb}`,
  );
  const extra = opts.extra.trim();
  if (extra) {
    lines.push("");
    lines.push(...extra.split(/\r?\n/));
  }
  return lines.join("\n").replace(/\n+$/, "") + "\n";
}

export function SiteSettingsForm() {
  const { refresh } = useBrand();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [meta, setMeta] = useState<{
    source: string;
    secretConfigured: boolean;
    gatePasswordConfigured: boolean;
  }>({
    source: "environment",
    secretConfigured: false,
    gatePasswordConfigured: false,
  });

  const [turnstileEnabled, setTurnstileEnabled] = useState(false);
  const [turnstileSiteKey, setTurnstileSiteKey] = useState("");
  const [turnstileSecret, setTurnstileSecret] = useState("");
  const [publicGateEnabled, setPublicGateEnabled] = useState(true);
  const [publicGatePassword, setPublicGatePassword] = useState("");
  const [duplicateCnMode, setDuplicateCnMode] = useState(false);
  const [duplicateCnDetected, setDuplicateCnDetected] = useState(false);
  const [clientShapeEnabled, setClientShapeEnabled] = useState(true);
  const [clientShapeDownMbit, setClientShapeDownMbit] = useState(23);
  const [clientShapeUpMbit, setClientShapeUpMbit] = useState(23);
  const [clientShapeLiveDown, setClientShapeLiveDown] = useState<string | null>(
    null,
  );
  const [clientShapeLiveUp, setClientShapeLiveUp] = useState<string | null>(
    null,
  );
  const [brandName, setBrandName] = useState("Popout");
  const [brandProduct, setBrandProduct] = useState("VPN");
  const [siteTitle, setSiteTitle] = useState("Popout VPN Admin");
  const [colorBg, setColorBg] = useState("#0a0e14");
  const [colorPrimary, setColorPrimary] = useState("#1e3a8a");
  const [colorAccent, setColorAccent] = useState("#06b6d4");
  const [colorBright, setColorBright] = useState("#67e8f9");

  const [ovpnRemoteHost, setOvpnRemoteHost] = useState("vpn.example.com");
  const [ovpnRemoteMode, setOvpnRemoteMode] = useState<OvpnRemoteMode>("single");
  const [ovpnRemotePort, setOvpnRemotePort] = useState(1194);
  const [ovpnRemotePortMin, setOvpnRemotePortMin] = useState(45000);
  const [ovpnRemotePortMax, setOvpnRemotePortMax] = useState(45099);
  const [ovpnProto, setOvpnProto] = useState("tcp4");
  const [ovpnTunMtu, setOvpnTunMtu] = useState("1400");
  const [ovpnMssfix, setOvpnMssfix] = useState("1360");
  const [ovpnTcpNodelay, setOvpnTcpNodelay] = useState(true);
  const [ovpnBindMode, setOvpnBindMode] = useState<OvpnBindMode>("lport");
  const [ovpnLport, setOvpnLport] = useState(1);
  const [ovpnAuth, setOvpnAuth] = useState("SHA512");
  const [ovpnVerb, setOvpnVerb] = useState(3);
  const [ovpnExtra, setOvpnExtra] = useState("");

  const [wanIpLoggingEnabled, setWanIpLoggingEnabled] = useState(true);
  const [uniqueWanIpLimit, setUniqueWanIpLimit] = useState(3);
  const [uniqueWanIpWindowHours, setUniqueWanIpWindowHours] = useState(24);
  const [analyticsRefreshSeconds, setAnalyticsRefreshSeconds] = useState(10);
  const [attackRetentionDays, setAttackRetentionDays] = useState(7);
  const [attackPacketCount, setAttackPacketCount] = useState(4500);
  const [attackBpf, setAttackBpf] = useState("");
  const [bpfError, setBpfError] = useState<string | null>(null);
  const [bpfOk, setBpfOk] = useState<string | null>(null);
  const [bpfChecking, setBpfChecking] = useState(false);
  const [attackWebhookUrl, setAttackWebhookUrl] = useState("");
  const [attackEmbedJson, setAttackEmbedJson] = useState("");
  const [attackMaxAttachMb, setAttackMaxAttachMb] = useState(8);
  const [webhookTesting, setWebhookTesting] = useState(false);
  const [webhookTestMsg, setWebhookTestMsg] = useState<string | null>(null);
  const [webhookTestErr, setWebhookTestErr] = useState<string | null>(null);
  const [backupIntervalMinutes, setBackupIntervalMinutes] = useState(30);
  const [backupKeepCount, setBackupKeepCount] = useState(3);

  const livePreview = useMemo(
    () =>
      buildClientPreview({
        remoteHost: ovpnRemoteHost,
        remoteMode: ovpnRemoteMode,
        remotePort: ovpnRemotePort,
        remotePortMin: ovpnRemotePortMin,
        remotePortMax: ovpnRemotePortMax,
        proto: ovpnProto,
        tunMtu: ovpnTunMtu,
        mssfix: ovpnMssfix,
        tcpNodelay: ovpnTcpNodelay,
        bindMode: ovpnBindMode,
        lport: ovpnLport,
        auth: ovpnAuth,
        verb: ovpnVerb,
        extra: ovpnExtra,
      }),
    [
      ovpnRemoteHost,
      ovpnRemoteMode,
      ovpnRemotePort,
      ovpnRemotePortMin,
      ovpnRemotePortMax,
      ovpnProto,
      ovpnTunMtu,
      ovpnMssfix,
      ovpnTcpNodelay,
      ovpnBindMode,
      ovpnLport,
      ovpnAuth,
      ovpnVerb,
      ovpnExtra,
    ],
  );

  function applyFromApi(data: SiteSettingsAdmin) {
    setTurnstileEnabled(data.turnstile_enabled);
    setTurnstileSiteKey(data.turnstile_site_key);
    setTurnstileSecret("");
    setBrandName(data.brand_name);
    setBrandProduct(data.brand_product);
    setSiteTitle(data.site_title || "Popout VPN Admin");
    setColorBg(data.brand_color_bg);
    setColorPrimary(data.brand_color_primary);
    setColorAccent(data.brand_color_accent);
    setColorBright(data.brand_color_accent_bright);
    setOvpnRemoteHost(data.ovpn_remote_host);
    setOvpnRemoteMode(data.ovpn_remote_mode ?? "single");
    setOvpnRemotePort(data.ovpn_remote_port);
    setOvpnRemotePortMin(data.ovpn_remote_port_min ?? 45000);
    setOvpnRemotePortMax(data.ovpn_remote_port_max ?? 45099);
    setOvpnProto(data.ovpn_proto);
    setOvpnTunMtu(
      data.ovpn_tun_mtu != null && data.ovpn_tun_mtu > 0
        ? String(data.ovpn_tun_mtu)
        : "",
    );
    setOvpnMssfix(
      data.ovpn_mssfix != null && data.ovpn_mssfix > 0
        ? String(data.ovpn_mssfix)
        : "",
    );
    setOvpnTcpNodelay(data.ovpn_tcp_nodelay);
    setOvpnBindMode(data.ovpn_bind_mode);
    setOvpnLport(data.ovpn_lport);
    setOvpnAuth(data.ovpn_auth);
    setOvpnVerb(data.ovpn_verb);
    setOvpnExtra(data.ovpn_extra || "");
    setWanIpLoggingEnabled(data.wan_ip_logging_enabled);
    setUniqueWanIpLimit(data.unique_wan_ip_limit);
    setUniqueWanIpWindowHours(data.unique_wan_ip_window_hours);
    setAnalyticsRefreshSeconds(data.analytics_refresh_seconds ?? 10);
    setAttackRetentionDays(data.attack_pcap_retention_days ?? 7);
    setAttackPacketCount(data.attack_pcap_packet_count ?? 4500);
    setAttackBpf(data.attack_pcap_bpf ?? "");
    setBpfError(null);
    setBpfOk(null);
    setAttackWebhookUrl(data.attack_discord_webhook_url ?? "");
    setAttackEmbedJson(data.attack_discord_embed_json ?? "");
    setAttackMaxAttachMb(
      Math.max(
        0,
        Math.round((data.attack_discord_max_attach_bytes ?? 8_388_608) / (1024 * 1024)),
      ),
    );
    setBackupIntervalMinutes(data.backup_interval_minutes ?? 30);
    setBackupKeepCount(data.backup_keep_count ?? 3);
    setPublicGateEnabled(data.public_gate_enabled ?? true);
    setPublicGatePassword("");
    setDuplicateCnMode(Boolean(data.duplicate_cn_mode));
    setDuplicateCnDetected(Boolean(data.duplicate_cn_detected));
    setClientShapeEnabled(data.client_shape_enabled ?? true);
    setClientShapeDownMbit(data.client_shape_down_mbit ?? 23);
    setClientShapeUpMbit(data.client_shape_up_mbit ?? 23);
    setClientShapeLiveDown(data.client_shape_live_down ?? null);
    setClientShapeLiveUp(data.client_shape_live_up ?? null);
    setMeta({
      source: data.source,
      secretConfigured: data.turnstile_secret_configured,
      gatePasswordConfigured: data.public_gate_password_configured,
    });
  }

  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty("--brand-bg", colorBg);
    root.style.setProperty("--brand-primary", colorPrimary);
    root.style.setProperty("--brand-accent", colorAccent);
    root.style.setProperty("--brand-accent-bright", colorBright);
  }, [colorBg, colorPrimary, colorAccent, colorBright]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchSiteSettings();
        if (!cancelled) applyFromApi(data);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.message
              : "Could not load server settings.",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function checkBpf(expression: string): Promise<boolean> {
    setBpfChecking(true);
    setBpfError(null);
    setBpfOk(null);
    try {
      const result = await validateAttackBpf(expression);
      setBpfOk(result.message);
      return true;
    } catch (err) {
      setBpfError(
        err instanceof ApiError
          ? err.message
          : "Could not validate BPF filter syntax.",
      );
      return false;
    } finally {
      setBpfChecking(false);
    }
  }

  async function runWebhookTest() {
    setWebhookTesting(true);
    setWebhookTestMsg(null);
    setWebhookTestErr(null);
    try {
      const result = await testAttackWebhook({
        webhook_url: attackWebhookUrl.trim() || undefined,
        embed_json: attackEmbedJson || undefined,
      });
      setWebhookTestMsg(
        result.service
          ? `${result.message} (service: ${result.service})`
          : result.message,
      );
    } catch (err) {
      setWebhookTestErr(
        err instanceof ApiError
          ? err.message
          : "Webhook test failed.",
      );
    } finally {
      setWebhookTesting(false);
    }
  }

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const bpfValid = await checkBpf(attackBpf);
      if (!bpfValid) {
        setError("Fix the capture filter (BPF) before saving.");
        return;
      }
      const mtuRaw = ovpnTunMtu.trim();
      const mssRaw = ovpnMssfix.trim();
      const payload: Parameters<typeof updateSiteSettings>[0] = {
        turnstile_enabled: turnstileEnabled,
        turnstile_site_key: turnstileSiteKey.trim(),
        brand_name: brandName.trim(),
        brand_product: brandProduct.trim(),
        site_title: siteTitle.trim() || "Popout VPN Admin",
        brand_color_bg: colorBg.trim(),
        brand_color_primary: colorPrimary.trim(),
        brand_color_accent: colorAccent.trim(),
        brand_color_accent_bright: colorBright.trim(),
        ovpn_remote_host: ovpnRemoteHost.trim(),
        ovpn_remote_mode: ovpnRemoteMode,
        ovpn_remote_port: ovpnRemotePort,
        ovpn_remote_port_min: ovpnRemotePortMin,
        ovpn_remote_port_max: ovpnRemotePortMax,
        ovpn_proto: ovpnProto.trim(),
        ovpn_tun_mtu: mtuRaw ? Number(mtuRaw) : 0,
        ovpn_mssfix: mssRaw ? Number(mssRaw) : 0,
        ovpn_tcp_nodelay: ovpnTcpNodelay,
        ovpn_bind_mode: ovpnBindMode,
        ovpn_lport: ovpnLport,
        ovpn_auth: ovpnAuth.trim(),
        ovpn_verb: ovpnVerb,
        ovpn_extra: ovpnExtra,
        wan_ip_logging_enabled: wanIpLoggingEnabled,
        unique_wan_ip_limit: uniqueWanIpLimit,
        unique_wan_ip_window_hours: uniqueWanIpWindowHours,
        analytics_refresh_seconds: analyticsRefreshSeconds,
        attack_pcap_retention_days: attackRetentionDays,
        attack_pcap_packet_count: attackPacketCount,
        attack_pcap_bpf: attackBpf,
        attack_discord_webhook_url: attackWebhookUrl.trim(),
        attack_discord_embed_json: attackEmbedJson,
        attack_discord_max_attach_bytes: Math.round(
          attackMaxAttachMb * 1024 * 1024,
        ),
        backup_interval_minutes: backupIntervalMinutes,
        backup_keep_count: backupKeepCount,
        public_gate_enabled: publicGateEnabled,
        duplicate_cn_mode: duplicateCnMode,
        client_shape_enabled: clientShapeEnabled,
        client_shape_down_mbit: clientShapeDownMbit,
        client_shape_up_mbit: clientShapeUpMbit,
      };
      if (turnstileSecret.trim()) {
        payload.turnstile_secret_key = turnstileSecret.trim();
      }
      if (publicGatePassword.trim()) {
        payload.public_gate_password = publicGatePassword.trim();
      }
      const updated = await updateSiteSettings(payload);
      applyFromApi(updated);
      await refresh();
      const shapeNote =
        updated.client_shape_enabled &&
        (updated.client_shape_live_down || updated.client_shape_live_up)
          ? ` Shaping live: ${updated.client_shape_live_down ?? "—"} down / ${updated.client_shape_live_up ?? "—"} up.`
          : updated.client_shape_enabled === false
            ? " Client shaping disabled."
            : "";
      setMessage(
        `Server settings saved. New and re-downloaded .ovpn files use this client template.${shapeNote}`,
      );
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not save server settings.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <p className="font-mono text-sm text-muted-foreground">
        Loading server settings…
      </p>
    );
  }

  return (
    <div className="dash-page">
      <div>
        <h1 className="dash-title">
          Server settings
        </h1>
        <p className="dash-sub">
          Branding, captcha, and the OpenVPN client template for .ovpn files.
        </p>
        <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
          Source: {meta.source}
          {meta.secretConfigured ? " · Turnstile secret on file" : ""}
          {meta.gatePasswordConfigured ? " · Public gate password on file" : ""}
        </p>
      </div>

      <form
        onSubmit={onSave}
        className="auth-glow-border relative max-w-3xl space-y-4 rounded-xl bg-card/90 p-3 pb-20 sm:space-y-5 sm:p-5 sm:pb-5"
      >
        <section className="space-y-3">
          <h2 className="text-sm font-semibold tracking-wide text-foreground">
            Branding
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="brand_name">Brand name</Label>
              <Input
                id="brand_name"
                value={brandName}
                onChange={(e) => setBrandName(e.target.value)}
                className="h-9"
                placeholder="Popout"
              />
              <p className="font-mono text-[11px] text-muted-foreground">
                Shown in the gradient (before the product word)
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="brand_product">Product word</Label>
              <Input
                id="brand_product"
                value={brandProduct}
                onChange={(e) => setBrandProduct(e.target.value)}
                className="h-9"
                placeholder="VPN"
              />
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="site_title">Site title</Label>
              <Input
                id="site_title"
                value={siteTitle}
                onChange={(e) => setSiteTitle(e.target.value)}
                className="h-9"
                placeholder="Popout VPN Admin"
              />
              <p className="font-mono text-[11px] text-muted-foreground">
                Browser tab title (e.g. “Analytics · Popout VPN Admin”)
              </p>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <ColorField
              id="color_bg"
              label="Background"
              value={colorBg}
              onChange={setColorBg}
            />
            <ColorField
              id="color_primary"
              label="Primary"
              value={colorPrimary}
              onChange={setColorPrimary}
            />
            <ColorField
              id="color_accent"
              label="Accent"
              value={colorAccent}
              onChange={setColorAccent}
            />
            <ColorField
              id="color_bright"
              label="Accent bright"
              value={colorBright}
              onChange={setColorBright}
            />
          </div>
          <div className="rounded-lg border border-border/70 bg-background/50 p-4">
            <p className="mb-2 text-xs text-muted-foreground">Preview</p>
            <p className="font-heading text-xl font-semibold tracking-tight sm:text-2xl">
              <span className="brand-text-gradient">{brandName || "Popout"}</span>
              <span className="text-foreground/90">
                {" "}
                {brandProduct || "VPN"}
              </span>
            </p>
            <p className="mt-2 font-mono text-xs text-muted-foreground">
              Tab: Analytics · {siteTitle.trim() || "Popout VPN Admin"}
            </p>
          </div>
        </section>

        <details className="dash-section space-y-3">
          <summary>Client config template</summary>
          <p className="text-xs text-muted-foreground">Static header written into every issued .ovpn (before certs). Maps
              to Nyr&apos;s{" "}
              <span className="font-mono text-xs">client-common.txt</span> or
              Angristan&apos;s{" "}
              <span className="font-mono text-xs">client-template.txt</span>{" "}
              when the portal can write that file.</p>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="ovpn_remote">Remote host / IP</Label>
              <Input
                id="ovpn_remote"
                value={ovpnRemoteHost}
                onChange={(e) => setOvpnRemoteHost(e.target.value)}
                className="h-9 font-mono text-sm"
                placeholder="vpn.example.com"
                required
              />
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="ovpn_remote_mode">Remote connection mode</Label>
              <select
                id="ovpn_remote_mode"
                value={ovpnRemoteMode}
                onChange={(e) =>
                  setOvpnRemoteMode(e.target.value as OvpnRemoteMode)
                }
                className={selectClassName}
              >
                <option value="single">Single port</option>
                <option value="remote_random">
                  remote-random (knocked port range)
                </option>
              </select>
              <p className="font-mono text-[11px] text-muted-foreground">
                {ovpnRemoteMode === "remote_random"
                  ? "Emits remote-random plus one remote line per port in the range (for ephemeral knocked listeners)."
                  : "Single remote host:port line in each issued .ovpn file."}
              </p>
            </div>
            {ovpnRemoteMode === "single" ? (
              <div className="space-y-2">
                <Label htmlFor="ovpn_port">Remote port</Label>
                <Input
                  id="ovpn_port"
                  type="number"
                  min={1}
                  max={65535}
                  value={ovpnRemotePort}
                  onChange={(e) =>
                    setOvpnRemotePort(Number(e.target.value) || 1)
                  }
                  className="h-9 font-mono text-sm"
                  required
                />
              </div>
            ) : (
              <>
                <div className="space-y-2">
                  <Label htmlFor="ovpn_port_min">Port range start</Label>
                  <Input
                    id="ovpn_port_min"
                    type="number"
                    min={1}
                    max={65535}
                    value={ovpnRemotePortMin}
                    onChange={(e) =>
                      setOvpnRemotePortMin(Number(e.target.value) || 1)
                    }
                    className="h-9 font-mono text-sm"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="ovpn_port_max">Port range end</Label>
                  <Input
                    id="ovpn_port_max"
                    type="number"
                    min={1}
                    max={65535}
                    value={ovpnRemotePortMax}
                    onChange={(e) =>
                      setOvpnRemotePortMax(Number(e.target.value) || 1)
                    }
                    className="h-9 font-mono text-sm"
                    required
                  />
                  <p className="font-mono text-[11px] text-muted-foreground">
                    {Math.max(
                      0,
                      Math.max(ovpnRemotePortMin, ovpnRemotePortMax) -
                        Math.min(ovpnRemotePortMin, ovpnRemotePortMax) +
                        1,
                    ).toLocaleString()}{" "}
                    remote lines will be written (max 4,096).
                  </p>
                </div>
              </>
            )}
            <div className="space-y-2">
              <Label htmlFor="ovpn_proto">Protocol</Label>
              <select
                id="ovpn_proto"
                value={ovpnProto}
                onChange={(e) => setOvpnProto(e.target.value)}
                className={selectClassName}
              >
                <option value="tcp4">tcp4</option>
                <option value="tcp6">tcp6</option>
                <option value="tcp">tcp</option>
                <option value="tcp-client">tcp-client (Angristan)</option>
                <option value="tcp6-client">tcp6-client (Angristan)</option>
                <option value="udp4">udp4</option>
                <option value="udp6">udp6</option>
                <option value="udp">udp</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="ovpn_mtu">tun-mtu (blank to omit)</Label>
              <Input
                id="ovpn_mtu"
                type="number"
                min={0}
                max={9000}
                value={ovpnTunMtu}
                onChange={(e) => setOvpnTunMtu(e.target.value)}
                className="h-9 font-mono text-sm"
                placeholder="1400"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ovpn_mss">mssfix (blank to omit)</Label>
              <Input
                id="ovpn_mss"
                type="number"
                min={0}
                max={9000}
                value={ovpnMssfix}
                onChange={(e) => setOvpnMssfix(e.target.value)}
                className="h-9 font-mono text-sm"
                placeholder="1360"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ovpn_bind">Local bind</Label>
              <select
                id="ovpn_bind"
                value={ovpnBindMode}
                onChange={(e) =>
                  setOvpnBindMode(e.target.value as OvpnBindMode)
                }
                className={selectClassName}
              >
                <option value="lport">lport (fixed local port)</option>
                <option value="nobind">nobind</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="ovpn_lport">lport</Label>
              <Input
                id="ovpn_lport"
                type="number"
                min={0}
                max={65535}
                value={ovpnLport}
                onChange={(e) => setOvpnLport(Number(e.target.value) || 0)}
                className="h-9 font-mono text-sm"
                disabled={ovpnBindMode !== "lport"}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ovpn_auth">auth</Label>
              <Input
                id="ovpn_auth"
                value={ovpnAuth}
                onChange={(e) => setOvpnAuth(e.target.value)}
                className="h-9 font-mono text-sm"
                placeholder="SHA512"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ovpn_verb">verb</Label>
              <Input
                id="ovpn_verb"
                type="number"
                min={0}
                max={11}
                value={ovpnVerb}
                onChange={(e) => setOvpnVerb(Number(e.target.value) || 0)}
                className="h-9 font-mono text-sm"
              />
            </div>
          </div>

          <label className="flex items-center gap-3 text-sm">
            <input
              type="checkbox"
              checked={ovpnTcpNodelay}
              onChange={(e) => setOvpnTcpNodelay(e.target.checked)}
              className="size-4 rounded border-input"
            />
            Include <span className="font-mono text-xs">tcp-nodelay</span>
          </label>

          <div className="space-y-2">
            <Label htmlFor="ovpn_extra">Extra directives</Label>
            <textarea
              id="ovpn_extra"
              value={ovpnExtra}
              onChange={(e) => setOvpnExtra(e.target.value)}
              rows={4}
              spellCheck={false}
              placeholder={"# Optional lines appended after verb\n# e.g. pull-filter ignore redirect-gateway"}
              className="flex min-h-[72px] sm:min-h-[96px] w-full rounded-lg border border-input bg-transparent px-3 py-2 font-mono text-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            />
          </div>

          <div className="rounded-lg border border-border/70 bg-background/50 p-4">
            <p className="mb-2 text-xs text-muted-foreground">
              Live preview (certs are appended at issue time)
            </p>
            <pre className="max-h-40 sm:max-h-64 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-foreground/90">
              {livePreview}
              {"\n"}
              {"# … <cert> <key> <ca> <tls-crypt> …"}
            </pre>
          </div>
        </details>

        <details className="dash-section space-y-3">
          <summary>Connection security</summary>
          <p className="text-xs text-muted-foreground">Auto-revoke a config when it connects from more unique WAN IPs
              than the limit allows within the time window — a sign a .ovpn
              file may have been shared or leaked.</p>
          <label className="flex items-center gap-3 text-sm">
            <input
              type="checkbox"
              checked={wanIpLoggingEnabled}
              onChange={(e) => setWanIpLoggingEnabled(e.target.checked)}
              className="size-4 rounded border-input"
            />
            Log client WAN IPs on connect (default for configs without a
            per-config override)
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="unique_wan_ip_limit">Unique WAN IP limit</Label>
              <Input
                id="unique_wan_ip_limit"
                type="number"
                min={1}
                max={1000}
                value={uniqueWanIpLimit}
                onChange={(e) =>
                  setUniqueWanIpLimit(Number(e.target.value) || 1)
                }
                className="h-9 font-mono text-sm"
                disabled={!wanIpLoggingEnabled}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="unique_wan_ip_window_hours">
                Window (hours)
              </Label>
              <Input
                id="unique_wan_ip_window_hours"
                type="number"
                min={1}
                max={24 * 30}
                value={uniqueWanIpWindowHours}
                onChange={(e) =>
                  setUniqueWanIpWindowHours(Number(e.target.value) || 1)
                }
                className="h-9 font-mono text-sm"
                disabled={!wanIpLoggingEnabled}
              />
            </div>
          </div>
          <p className="font-mono text-[11px] text-muted-foreground">
            Example: limit 3, window 24h — a config seen from more than 3
            distinct WAN IPs in 24 hours is revoked automatically.
          </p>
          <div className="space-y-2">
            <Label htmlFor="analytics_refresh_seconds">
              Analytics refresh interval
            </Label>
            <select
              id="analytics_refresh_seconds"
              value={String(analyticsRefreshSeconds)}
              onChange={(e) =>
                setAnalyticsRefreshSeconds(Number(e.target.value))
              }
              className={selectClassName}
            >
              <option value="0.25">Live (250 ms)</option>
              <option value="0.5">500 ms</option>
              <option value="1">1 second</option>
              <option value="2.5">2.5 seconds</option>
              <option value="5">5 seconds</option>
              <option value="10">10 seconds</option>
              <option value="30">30 seconds</option>
            </select>
            <p className="text-xs text-muted-foreground">
              Default Analytics tab cadence. Live / sub-second modes sample in
              memory on demand; Mongo history and OpenVPN sync stay ≥2.5s to
              limit load.
            </p>
          </div>
        </details>

        <details className="dash-section space-y-3">
          <summary>Attack capture</summary>
          <p className="text-xs text-muted-foreground">Controls the WAN attack monitor daemon (`popout-attacks`): how
              many packets to capture, how long to keep `.pcap` files, and an
              optional BPF filter (empty = capture all).</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="attack_pcap_retention_days">
                Pcap retention (days)
              </Label>
              <Input
                id="attack_pcap_retention_days"
                type="number"
                min={1}
                max={365}
                value={attackRetentionDays}
                onChange={(e) =>
                  setAttackRetentionDays(Number(e.target.value) || 1)
                }
                className="h-9 font-mono text-sm"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="attack_pcap_packet_count">
                Packets per capture
              </Label>
              <Input
                id="attack_pcap_packet_count"
                type="number"
                min={100}
                max={1000000}
                value={attackPacketCount}
                onChange={(e) =>
                  setAttackPacketCount(Number(e.target.value) || 100)
                }
                className="h-9 font-mono text-sm"
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="attack_pcap_bpf">
              Capture filter (BPF, optional)
            </Label>
            <Input
              id="attack_pcap_bpf"
              value={attackBpf}
              onChange={(e) => {
                setAttackBpf(e.target.value);
                setBpfError(null);
                setBpfOk(null);
              }}
              onBlur={() => {
                void checkBpf(attackBpf);
              }}
              placeholder='e.g. tcp or udp port 53 — leave blank for all traffic'
              className="h-9 font-mono text-sm"
              aria-invalid={Boolean(bpfError)}
            />
            <p className="text-xs text-muted-foreground">
              Standard tcpdump/libpcap expression. Blank captures everything on
              eth0. Syntax is checked with tcpdump before the filter is applied.
            </p>
            {bpfChecking && (
              <p className="font-mono text-xs text-muted-foreground">
                Checking BPF syntax…
              </p>
            )}
            {bpfError && (
              <p
                role="alert"
                className="font-mono text-xs text-destructive"
              >
                {bpfError}
              </p>
            )}
            {!bpfError && bpfOk && (
              <p className="font-mono text-xs text-emerald-400/90">{bpfOk}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="attack_discord_webhook_url">
              Discord webhook URL
            </Label>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Input
                id="attack_discord_webhook_url"
                value={attackWebhookUrl}
                onChange={(e) => {
                  setAttackWebhookUrl(e.target.value);
                  setWebhookTestMsg(null);
                  setWebhookTestErr(null);
                }}
                placeholder="https://discord.com/api/webhooks/…"
                className="h-9 font-mono text-sm"
              />
              <Button
                type="button"
                variant="outline"
                className="h-9 shrink-0"
                disabled={webhookTesting || !attackWebhookUrl.trim()}
                onClick={() => {
                  void runWebhookTest();
                }}
              >
                {webhookTesting ? "Sending…" : "Test webhook"}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Test sends the detection embed with NA placeholders and attaches a
              fake empty <span className="font-mono">.pcap</span> (0 packets).
              Uses the URL/JSON above even if not saved yet.
            </p>
            {webhookTestErr && (
              <p role="alert" className="font-mono text-xs text-destructive">
                {webhookTestErr}
              </p>
            )}
            {!webhookTestErr && webhookTestMsg && (
              <p className="font-mono text-xs text-emerald-400/90">
                {webhookTestMsg}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="attack_discord_max_attach_mb">
              Max pcap attach size (MB)
            </Label>
            <Input
              id="attack_discord_max_attach_mb"
              type="number"
              min={0}
              max={25}
              value={attackMaxAttachMb}
              onChange={(e) =>
                setAttackMaxAttachMb(Number(e.target.value) || 0)
              }
              className="h-9 max-w-[10rem] font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">
              If the capture is larger than this, the embed is still sent
              without the file (Discord webhook limit is typically 8–25 MB).
              Use 0 to never attach.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="attack_discord_embed_json">
              Discord embed JSON
            </Label>
            <textarea
              id="attack_discord_embed_json"
              value={attackEmbedJson}
              onChange={(e) => setAttackEmbedJson(e.target.value)}
              rows={12}
              spellCheck={false}
              className="flex min-h-[110px] sm:min-h-[150px] w-full rounded-lg border border-input bg-transparent px-3 py-2 font-mono text-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            />
            <p className="text-xs text-muted-foreground">
              Placeholders:{" "}
              <span className="font-mono">
                {"{{severity}} {{pps}} {{bps}} {{pcap_name}} {{pcap_size}} {{pcap_attached}} {{unique_srcs}} {{bpf}} {{kind}} {{service}} {{color}} {{detected_at}}"}
              </span>
            </p>
          </div>
        </details>

        <details className="dash-section space-y-3">
          <summary>Panel backups</summary>
          <p className="text-xs text-muted-foreground">Zip snapshots into{" "}
              <span className="font-mono text-xs">/root/backups</span>: panel,
              monitor, OpenVPN PKI, and MongoDB collections (admins,
              configs, settings, bandwidth). Older copies beyond the keep limit
              are removed automatically. Host metrics history is not included
              (regenerable).</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="backup_interval_minutes">
                Backup every (minutes)
              </Label>
              <Input
                id="backup_interval_minutes"
                type="number"
                min={5}
                max={1440}
                value={backupIntervalMinutes}
                onChange={(e) =>
                  setBackupIntervalMinutes(Number(e.target.value) || 5)
                }
                className="h-9 font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Minimum 5 minutes. Default 30.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="backup_keep_count">Copies to keep</Label>
              <Input
                id="backup_keep_count"
                type="number"
                min={1}
                max={50}
                value={backupKeepCount}
                onChange={(e) =>
                  setBackupKeepCount(Number(e.target.value) || 1)
                }
                className="h-9 font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Only the newest N zips are retained (default 3).
              </p>
            </div>
          </div>
        </details>

        <details className="dash-section space-y-3">
          <summary>Public Cloudflare gate</summary>
          <p className="text-xs text-muted-foreground">
            Client-side password modal on the public admin site. Visitors must
            enter this password (no username) before the UI can talk to the API.
            VPN / localhost access is unchanged when the panel is private.
          </p>
          <label className="flex items-center gap-3 text-sm">
            <input
              type="checkbox"
              checked={publicGateEnabled}
              onChange={(e) => setPublicGateEnabled(e.target.checked)}
              className="size-4 rounded border-input"
            />
            Require gate password on the public admin site
          </label>
          <div className="space-y-2">
            <Label htmlFor="public_gate_password">
              Gate password
              {meta.gatePasswordConfigured ? " (leave blank to keep)" : ""}
            </Label>
            <Input
              id="public_gate_password"
              type="password"
              autoComplete="new-password"
              value={publicGatePassword}
              onChange={(e) => setPublicGatePassword(e.target.value)}
              className="h-9 font-mono text-sm"
              placeholder={
                meta.gatePasswordConfigured
                  ? "••••••••"
                  : "Set a password (min 8 chars)"
              }
            />
          </div>
        </details>

        <details className="dash-section space-y-3" open>
          <summary>Per-client bandwidth (CAKE)</summary>
          <p className="text-xs text-muted-foreground">
            Soft per-client limits on{" "}
            <span className="font-mono text-xs">tun0</span> (10.8.0.0/24).
            Over-limit traffic is queued with CAKE — not hard-dropped — so
            ICE/STUN/TURN stay happier. Changes apply live on save.
          </p>
          <label className="flex items-center gap-3 text-sm">
            <input
              type="checkbox"
              checked={clientShapeEnabled}
              onChange={(e) => setClientShapeEnabled(e.target.checked)}
              className="size-4 rounded border-input"
            />
            Enable per-client shaping
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="client_shape_down_mbit">Download Mbps / client</Label>
              <Input
                id="client_shape_down_mbit"
                type="number"
                min={1}
                max={10000}
                value={clientShapeDownMbit}
                onChange={(e) =>
                  setClientShapeDownMbit(Number(e.target.value) || 1)
                }
                disabled={!clientShapeEnabled}
                className="h-9 font-mono text-sm"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="client_shape_up_mbit">Upload Mbps / client</Label>
              <Input
                id="client_shape_up_mbit"
                type="number"
                min={1}
                max={10000}
                value={clientShapeUpMbit}
                onChange={(e) =>
                  setClientShapeUpMbit(Number(e.target.value) || 1)
                }
                disabled={!clientShapeEnabled}
                className="h-9 font-mono text-sm"
              />
            </div>
          </div>
          {(clientShapeLiveDown || clientShapeLiveUp) && (
            <p className="font-mono text-[11px] text-emerald-600 dark:text-emerald-400">
              Live tc: down={clientShapeLiveDown ?? "—"} up=
              {clientShapeLiveUp ?? "—"}
            </p>
          )}
        </details>

        <details className="dash-section space-y-3">
          <summary>Duplicate-CN mode</summary>
          <p className="text-xs text-muted-foreground">When OpenVPN has <span className="font-mono text-xs">duplicate-cn</span>{" "}
            enabled, many users share one client certificate. The panel then
            treats that shared config as the only manageable profile and lists
            every live session (private VPN IP + public WAN) on that row.</p>{duplicateCnDetected && (
            <p className="font-mono text-[11px] text-emerald-600 dark:text-emerald-400">
              Detected in /etc/openvpn/server/server.conf
            </p>
          )}
          <label className="flex items-center gap-3 text-sm">
            <input
              type="checkbox"
              checked={duplicateCnMode}
              onChange={(e) => setDuplicateCnMode(e.target.checked)}
              className="size-4 rounded border-input"
            />
            Enable duplicate-CN panel behavior (block extra configs)
          </label>
        </details>

        <details className="dash-section space-y-3">
          <summary>Cloudflare Turnstile</summary>
          <p className="text-xs text-muted-foreground">Turn captcha off for VPN-only access (for example tun0 / 10.8.0.1).
            Turn it on when this portal is reachable over the public internet.</p><label className="flex items-center gap-3 text-sm">
            <input
              type="checkbox"
              checked={turnstileEnabled}
              onChange={(e) => setTurnstileEnabled(e.target.checked)}
              className="size-4 rounded border-input"
            />
            Require Cloudflare Turnstile on login and register
          </label>
          <div className="space-y-2">
            <Label htmlFor="ts_site">Turnstile site key (public)</Label>
            <Input
              id="ts_site"
              value={turnstileSiteKey}
              onChange={(e) => setTurnstileSiteKey(e.target.value)}
              className="h-9 font-mono text-sm"
              disabled={!turnstileEnabled}
              autoComplete="off"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="ts_secret">Turnstile secret key</Label>
            <Input
              id="ts_secret"
              type="password"
              value={turnstileSecret}
              onChange={(e) => setTurnstileSecret(e.target.value)}
              className="h-9 font-mono text-sm"
              disabled={!turnstileEnabled}
              autoComplete="new-password"
              placeholder={
                meta.secretConfigured
                  ? "Leave blank to keep the current secret"
                  : "Paste secret key"
              }
            />
          </div>
        </details>

        {error && (
          <p
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
          >
            {error}
          </p>
        )}
        {message && (
          <p className="font-mono text-xs text-cyan-600 dark:text-cyan-300">
            {message}
          </p>
        )}

        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border/70 bg-background/95 p-3 backdrop-blur-md sm:static sm:border-0 sm:bg-transparent sm:p-0 sm:backdrop-blur-none">
          <Button
            type="submit"
            disabled={saving}
            className="brand-btn-gradient h-9 w-full px-5 sm:h-10 sm:w-auto"
          >
            {saving ? "Saving…" : "Save server settings"}
          </Button>
        </div>
      </form>
    </div>
  );
}
