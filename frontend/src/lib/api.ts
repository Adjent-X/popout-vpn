/** Browser API base. Empty env = same-origin via nginx; direct :3000 → :8000. */
export function getApiUrl(): string {
  const fromEnv = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
  if (fromEnv) return fromEnv;
  if (typeof window !== "undefined") {
    const { protocol, hostname, port } = window.location;
    if (port === "3000") return `${protocol}//${hostname}:8000`;
  }
  return "";
}

/** @deprecated prefer getApiUrl(); kept empty for rare static imports */
const API_URL = "";
void API_URL;

export type HealthResponse = {
  status: string;
  service: string;
  environment: string;
  timestamp: string;
};

export type AdminRole = "admin" | "sub_admin";

export type AdminPublic = {
  id: string;
  email: string;
  role: AdminRole | string;
  theme: "dark" | "light";
  config_slot_limit?: number | null;
  config_slots_used?: number;
  locked?: boolean;
  last_login_at?: string | null;
  last_login_ip?: string | null;
  created_at?: string | null;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  admin: AdminPublic;
};

export type ConfigStatus =
  | "active"
  | "expiring_soon"
  | "expired"
  | "revoked";

export type ClientConfig = {
  id: string;
  label: string;
  client_name: string;
  owner_admin_id: string;
  created_at: string;
  expires_at: string;
  status: ConfigStatus;
  cert_serial: string;
  revoked_at: string | null;
  vpn_ip?: string | null;
  last_wan_ip?: string | null;
  last_connected_at?: string | null;
  is_online?: boolean;
  wan_ip_logging_enabled?: boolean | null;
  warp_routing_enabled?: boolean;
  session_count?: number;
  active_sessions?: ActiveSession[];
};

export type ActiveSession = {
  vpn_ip: string | null;
  wan_ip: string | null;
  connected_since: string | null;
  bytes_received: number;
  bytes_sent: number;
};

export type CreateConfigResponse = ClientConfig & {
  ovpn: string;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail
        .map((item) => {
          if (typeof item === "object" && item && "msg" in item) {
            return String((item as { msg: string }).msg);
          }
          return String(item);
        })
        .join(", ");
    }
  } catch {
    /* ignore */
  }
  return res.statusText || "Request failed";
}

/** Public Cloudflare site gate — blocks API until password unlock. */
let publicGateEnabled = false;
let publicGateUnlocked = true;
const publicGateWaiters: Array<() => void> = [];

export function syncPublicGateState(enabled: boolean, unlocked: boolean): void {
  publicGateEnabled = enabled;
  publicGateUnlocked = !enabled || unlocked;
  if (publicGateUnlocked) {
    while (publicGateWaiters.length) {
      publicGateWaiters.shift()?.();
    }
  }
}

export function markPublicGateUnlocked(): void {
  publicGateUnlocked = true;
  while (publicGateWaiters.length) {
    publicGateWaiters.shift()?.();
  }
}

function isPublicGateAllowlisted(path: string): boolean {
  return (
    path === "/api/public/config" ||
    path === "/api/public/gate/unlock" ||
    path === "/api/health" ||
    path.startsWith("/api/public/gate/")
  );
}

async function waitForPublicGate(path: string): Promise<void> {
  if (!publicGateEnabled || publicGateUnlocked || isPublicGateAllowlisted(path)) {
    return;
  }
  await new Promise<void>((resolve) => {
    publicGateWaiters.push(resolve);
  });
}

export async function unlockPublicGate(password: string): Promise<void> {
  await apiFetch<{ unlocked: boolean }>(
    "/api/public/gate/unlock",
    { method: "POST", body: JSON.stringify({ password }) },
    { auth: false },
  );
  markPublicGateUnlocked();
}

function getStoredAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return (
    localStorage.getItem("popout_access_token") ??
    sessionStorage.getItem("popout_access_token")
  );
}

function clearStoredSession(): void {
  sessionStorage.removeItem("popout_access_token");
  sessionStorage.removeItem("popout_admin");
  localStorage.removeItem("popout_access_token");
  localStorage.removeItem("popout_admin");
  localStorage.removeItem("popout_session_persist");
}

let refreshInFlight: Promise<boolean> | null = null;

async function tryRefreshAccessToken(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const res = await fetch(`${getApiUrl()}/api/auth/refresh`, {
        method: "POST",
        credentials: "include",
        cache: "no-store",
      });
      if (!res.ok) return false;
      const data = (await res.json()) as TokenResponse;
      const persist =
        localStorage.getItem("popout_session_persist") === "1" ||
        data.admin.role === "admin";
      const store = persist ? localStorage : sessionStorage;
      if (persist) localStorage.setItem("popout_session_persist", "1");
      sessionStorage.removeItem("popout_access_token");
      sessionStorage.removeItem("popout_admin");
      if (!persist) {
        localStorage.removeItem("popout_access_token");
        localStorage.removeItem("popout_admin");
        localStorage.removeItem("popout_session_persist");
      }
      store.setItem("popout_access_token", data.access_token);
      store.setItem("popout_admin", JSON.stringify(data.admin));
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  options?: { auth?: boolean; raw?: boolean; skipAuthRedirect?: boolean },
): Promise<T> {
  await waitForPublicGate(path);

  const headers = new Headers(init.headers);
  const useAuth = options?.auth !== false;

  if (init.body && !headers.has("Content-Type") && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  if (useAuth) {
    const token = getStoredAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(`${getApiUrl()}${path}`, {
    ...init,
    headers,
    credentials: "include",
    cache: "no-store",
  });

  if (
    res.status === 401 &&
    res.headers.get("X-Popout-Gate") === "required" &&
    typeof window !== "undefined"
  ) {
    syncPublicGateState(true, false);
    await waitForPublicGate(path);
    const retry = await fetch(`${getApiUrl()}${path}`, {
      ...init,
      headers,
      credentials: "include",
      cache: "no-store",
    });
    if (!retry.ok) {
      throw new ApiError(retry.status, await parseError(retry));
    }
    if (options?.raw) return retry as T;
    if (retry.status === 204) return undefined as T;
    return retry.json() as Promise<T>;
  }

  if (
    !res.ok &&
    useAuth &&
    res.status === 401 &&
    typeof window !== "undefined" &&
    !options?.skipAuthRedirect
  ) {
    const refreshed = await tryRefreshAccessToken();
    if (refreshed) {
      const retryHeaders = new Headers(init.headers);
      if (
        init.body &&
        !retryHeaders.has("Content-Type") &&
        !(init.body instanceof FormData)
      ) {
        retryHeaders.set("Content-Type", "application/json");
      }
      const token = getStoredAccessToken();
      if (token) retryHeaders.set("Authorization", `Bearer ${token}`);
      const retry = await fetch(`${getApiUrl()}${path}`, {
        ...init,
        headers: retryHeaders,
        credentials: "include",
        cache: "no-store",
      });
      if (retry.ok) {
        if (options?.raw) return retry as T;
        if (retry.status === 204) return undefined as T;
        return retry.json() as Promise<T>;
      }
    }
    clearStoredSession();
    const pathName = window.location.pathname;
    if (!pathName.startsWith("/login") && !pathName.startsWith("/register")) {
      window.location.replace("/login?reason=expired");
    }
    throw new ApiError(401, await parseError(res));
  }

  if (!res.ok) {
    const message = await parseError(res);
    throw new ApiError(res.status, message);
  }

  if (options?.raw) {
    return res as T;
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

export async function fetchHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/api/health", {}, { auth: false });
}

export async function listConfigs(): Promise<ClientConfig[]> {
  return apiFetch<ClientConfig[]>("/api/configs");
}

export type OrphanPkiClient = {
  client_name: string;
  cert_serial: string;
  revoked: boolean;
  has_key: boolean;
  vpn_ip: string | null;
};

export type ImportConfigsResponse = {
  imported: ClientConfig[];
  skipped: string[];
  errors: Record<string, string>;
};

/** Full admin: list CLI/installer clients not yet in the panel. */
export async function listOrphanConfigs(): Promise<OrphanPkiClient[]> {
  return apiFetch<OrphanPkiClient[]>("/api/configs/orphans");
}

/** Full admin: import existing PKI clients into the panel (no new certs). */
export async function importConfigs(body?: {
  client_names?: string[];
  expiry_days?: number;
}): Promise<ImportConfigsResponse> {
  return apiFetch<ImportConfigsResponse>("/api/configs/import", {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });
}

export async function createConfig(body: {
  label: string;
  expiry_days?: 7 | 30 | 90 | 365;
  expires_at?: string;
}): Promise<CreateConfigResponse> {
  return apiFetch<CreateConfigResponse>("/api/configs", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Revoke an active config, or permanently remove a revoked one. */
export async function deleteConfig(
  id: string,
): Promise<ClientConfig | null> {
  const res = await apiFetch<Response>(
    `/api/configs/${id}`,
    { method: "DELETE" },
    { raw: true },
  );
  if (res.status === 204) return null;
  return res.json() as Promise<ClientConfig>;
}

/** Mint a new cert for a revoked row and restore it as active. */
export async function reissueConfig(id: string): Promise<CreateConfigResponse> {
  return apiFetch<CreateConfigResponse>(`/api/configs/${id}/reissue`, {
    method: "POST",
  });
}

export async function downloadConfigFile(
  id: string,
  filename: string,
): Promise<void> {
  const res = await apiFetch<Response>(
    `/api/configs/${id}/download`,
    {},
    { raw: true },
  );
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".ovpn") ? filename : `${filename}.ovpn`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function downloadOvpnText(filename: string, content: string): void {
  const blob = new Blob([content], { type: "application/x-openvpn-profile" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".ovpn") ? filename : `${filename}.ovpn`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function fetchMe(): Promise<AdminPublic> {
  return apiFetch<AdminPublic>("/api/me");
}

export async function updateTheme(
  theme: "dark" | "light",
): Promise<AdminPublic> {
  return apiFetch<AdminPublic>("/api/me/theme", {
    method: "PATCH",
    body: JSON.stringify({ theme }),
  });
}

export async function updateCredentials(body: {
  current_password: string;
  new_email?: string;
  new_password?: string;
}): Promise<AdminPublic> {
  return apiFetch<AdminPublic>("/api/me/credentials", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export type RegistrationToken = {
  id: string;
  token: string;
  role: AdminRole | string;
  config_slot_limit: number | null;
  note: string | null;
  used: boolean;
  used_by: string | null;
  created_by: string | null;
  expires_at: string;
  created_at: string;
};

export async function listRegistrationTokens(): Promise<RegistrationToken[]> {
  return apiFetch<RegistrationToken[]>("/api/admin/tokens");
}

export async function createRegistrationToken(body: {
  role: AdminRole;
  config_slot_limit?: number;
  note?: string;
  expires_in_hours?: number;
}): Promise<RegistrationToken> {
  return apiFetch<RegistrationToken>("/api/admin/tokens", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function deleteRegistrationToken(id: string): Promise<void> {
  return apiFetch<void>(`/api/admin/tokens/${id}`, { method: "DELETE" });
}

export type ApiScope =
  | "configs:create"
  | "configs:revoke"
  | "configs:logs"
  | "analytics:read"
  | "settings:write";

export type ApiKeyPolicy = {
  sub_admin_scopes: ApiScope[];
  admin_scopes: ApiScope[];
  default_rate_limit_per_minute: number;
  max_rate_limit_per_minute: number;
  analytics_min_interval_seconds: number;
  max_keys_per_admin: number;
};

export type ApiKey = {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  rate_limit_per_minute: number;
  analytics_min_interval_seconds: number;
  enabled: boolean;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
};

export type CreateApiKeyResponse = ApiKey & { api_key: string };

export async function fetchApiKeyPolicy(): Promise<ApiKeyPolicy> {
  return apiFetch<ApiKeyPolicy>("/api/api-keys/policy");
}

export async function fetchMyApiScopes(): Promise<string[]> {
  return apiFetch<string[]>("/api/api-keys/policy/allowed-scopes");
}

export async function updateApiKeyPolicy(
  body: Partial<ApiKeyPolicy>,
): Promise<ApiKeyPolicy> {
  return apiFetch<ApiKeyPolicy>("/api/api-keys/policy", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function listApiKeys(): Promise<ApiKey[]> {
  return apiFetch<ApiKey[]>("/api/api-keys");
}

export async function createApiKey(body: {
  name: string;
  scopes: ApiScope[];
  rate_limit_per_minute?: number;
  analytics_min_interval_seconds?: number;
  expires_in_days?: number;
}): Promise<CreateApiKeyResponse> {
  return apiFetch<CreateApiKeyResponse>("/api/api-keys", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function deleteApiKey(id: string): Promise<void> {
  return apiFetch<void>(`/api/api-keys/${id}`, { method: "DELETE" });
}

export type OvpnBindMode = "lport" | "nobind";
export type OvpnRemoteMode = "single" | "remote_random";

export type SiteSettingsAdmin = {
  turnstile_enabled: boolean;
  turnstile_site_key: string;
  turnstile_secret_configured: boolean;
  brand_name: string;
  brand_product: string;
  site_title: string;
  brand_color_bg: string;
  brand_color_primary: string;
  brand_color_accent: string;
  brand_color_accent_bright: string;
  ovpn_remote_host: string;
  ovpn_remote_mode: OvpnRemoteMode;
  ovpn_remote_port: number;
  ovpn_remote_port_min: number;
  ovpn_remote_port_max: number;
  ovpn_proto: string;
  ovpn_tun_mtu: number | null;
  ovpn_mssfix: number | null;
  ovpn_tcp_nodelay: boolean;
  ovpn_bind_mode: OvpnBindMode;
  ovpn_lport: number;
  ovpn_auth: string;
  ovpn_verb: number;
  ovpn_extra: string;
  wan_ip_logging_enabled: boolean;
  unique_wan_ip_limit: number;
  unique_wan_ip_window_hours: number;
  analytics_refresh_seconds: number;
  attack_pcap_retention_days: number;
  attack_pcap_packet_count: number;
  attack_pcap_bpf: string;
  attack_discord_webhook_url: string;
  attack_discord_embed_json: string;
  attack_discord_max_attach_bytes: number;
  backup_interval_minutes: number;
  backup_keep_count: number;
  public_gate_enabled: boolean;
  public_gate_password_configured: boolean;
  public_gate_username: string;
  duplicate_cn_mode: boolean;
  duplicate_cn_detected: boolean;
  client_shape_enabled: boolean;
  client_shape_down_mbit: number;
  client_shape_up_mbit: number;
  client_shape_live_down: string | null;
  client_shape_live_up: string | null;
  client_config_preview: string;
  updated_at: string | null;
  source: string;
};

export type UpdateSiteSettingsPayload = {
  turnstile_enabled?: boolean;
  turnstile_site_key?: string;
  turnstile_secret_key?: string;
  brand_name?: string;
  brand_product?: string;
  site_title?: string;
  brand_color_bg?: string;
  brand_color_primary?: string;
  brand_color_accent?: string;
  brand_color_accent_bright?: string;
  ovpn_remote_host?: string;
  ovpn_remote_mode?: OvpnRemoteMode;
  ovpn_remote_port?: number;
  ovpn_remote_port_min?: number;
  ovpn_remote_port_max?: number;
  ovpn_proto?: string;
  ovpn_tun_mtu?: number | null;
  ovpn_mssfix?: number | null;
  ovpn_tcp_nodelay?: boolean;
  ovpn_bind_mode?: OvpnBindMode;
  ovpn_lport?: number;
  ovpn_auth?: string;
  ovpn_verb?: number;
  ovpn_extra?: string;
  wan_ip_logging_enabled?: boolean;
  unique_wan_ip_limit?: number;
  unique_wan_ip_window_hours?: number;
  analytics_refresh_seconds?: number;
  attack_pcap_retention_days?: number;
  attack_pcap_packet_count?: number;
  attack_pcap_bpf?: string;
  attack_discord_webhook_url?: string;
  attack_discord_embed_json?: string;
  attack_discord_max_attach_bytes?: number;
  backup_interval_minutes?: number;
  backup_keep_count?: number;
  public_gate_enabled?: boolean;
  public_gate_password?: string;
  duplicate_cn_mode?: boolean;
  client_shape_enabled?: boolean;
  client_shape_down_mbit?: number;
  client_shape_up_mbit?: number;
};

export async function fetchSiteSettings(): Promise<SiteSettingsAdmin> {
  return apiFetch<SiteSettingsAdmin>("/api/site-settings");
}

export async function updateSiteSettings(
  body: UpdateSiteSettingsPayload,
): Promise<SiteSettingsAdmin> {
  return apiFetch<SiteSettingsAdmin>("/api/site-settings", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function validateAttackBpf(
  bpf: string,
): Promise<{ ok: boolean; message: string }> {
  return apiFetch<{ ok: boolean; message: string }>(
    "/api/site-settings/validate-bpf",
    {
      method: "POST",
      body: JSON.stringify({ bpf }),
    },
  );
}

export async function testAttackWebhook(opts?: {
  webhook_url?: string;
  embed_json?: string;
}): Promise<{ ok: boolean; message: string; service: string }> {
  return apiFetch<{ ok: boolean; message: string; service: string }>(
    "/api/site-settings/test-attack-webhook",
    {
      method: "POST",
      body: JSON.stringify({
        webhook_url: opts?.webhook_url,
        embed_json: opts?.embed_json,
      }),
    },
  );
}

export type HostMetricsLatest = {
  ts: string;
  cpu_percent: number;
  mem_total: number;
  mem_used: number;
  mem_percent: number;
  disk_total: number;
  disk_used: number;
  disk_percent: number;
  net_bytes_sent: number;
  net_bytes_recv: number;
  net_bytes_sent_rate: number;
  net_bytes_recv_rate: number;
  net_packets_sent?: number;
  net_packets_recv?: number;
  net_packets_sent_rate?: number;
  net_packets_recv_rate?: number;
  eth0_bytes_sent?: number;
  eth0_bytes_recv?: number;
  eth0_packets_sent?: number;
  eth0_packets_recv?: number;
  eth0_bytes_sent_rate?: number;
  eth0_bytes_recv_rate?: number;
  eth0_packets_sent_rate?: number;
  eth0_packets_recv_rate?: number;
  tun0_bytes_sent?: number;
  tun0_bytes_recv?: number;
  tun0_packets_sent?: number;
  tun0_packets_recv?: number;
  tun0_bytes_sent_rate?: number;
  tun0_bytes_recv_rate?: number;
  tun0_packets_sent_rate?: number;
  tun0_packets_recv_rate?: number;
  load_avg: number[] | null;
};

export type MetricPoint = {
  ts: string;
  cpu_percent: number | null;
  mem_percent: number | null;
  disk_percent: number | null;
  net_bytes_sent_rate: number | null;
  net_bytes_recv_rate: number | null;
  net_packets_sent_rate?: number | null;
  net_packets_recv_rate?: number | null;
  eth0_bytes_sent_rate?: number | null;
  eth0_bytes_recv_rate?: number | null;
  eth0_packets_sent_rate?: number | null;
  eth0_packets_recv_rate?: number | null;
  tun0_bytes_sent_rate?: number | null;
  tun0_bytes_recv_rate?: number | null;
  tun0_packets_sent_rate?: number | null;
  tun0_packets_recv_rate?: number | null;
};

export type BandwidthToDate = {
  eth0_bytes_sent: number;
  eth0_bytes_recv: number;
  tun0_bytes_sent: number;
  tun0_bytes_recv: number;
  total_bytes: number;
  sample_seconds: number;
  avg_bps: number;
  started_at: string | null;
  updated_at: string | null;
};

export type MonthlyBandwidth = {
  id: string;
  year: number;
  month: number;
  eth0_bytes_sent: number;
  eth0_bytes_recv: number;
  tun0_bytes_sent: number;
  tun0_bytes_recv: number;
  total_bytes: number;
  sample_seconds: number;
  avg_bps: number;
};

export type AnalyticsOverview = {
  latest: HostMetricsLatest | null;
  series: MetricPoint[];
  clients_online: number;
  clients_total_active: number;
  configs_total: number;
  configs_revoked: number;
  attacks_lifetime?: number;
  attacks_24h?: number;
  bandwidth_to_date?: BandwidthToDate | null;
  bandwidth_monthly?: MonthlyBandwidth[];
};

export async function fetchAnalyticsOverview(
  hours?: number,
  maxAgeSeconds?: number,
  options?: { includeSeries?: boolean },
): Promise<AnalyticsOverview> {
  const params = new URLSearchParams();
  if (hours) params.set("hours", String(hours));
  if (maxAgeSeconds != null) params.set("max_age", String(maxAgeSeconds));
  if (options?.includeSeries === false) params.set("include_series", "false");
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<AnalyticsOverview>(`/api/analytics/overview${query}`);
}

export type ConnectionLogEntry = {
  id: string;
  at: string;
  event: string;
  client_name: string;
  wan_ip: string | null;
  vpn_ip: string | null;
  wan_logged: boolean;
};

export async function fetchConnectionLogs(
  configId: string,
): Promise<ConnectionLogEntry[]> {
  return apiFetch<ConnectionLogEntry[]>(
    `/api/configs/${configId}/connection-logs`,
  );
}

export async function updateConfigWanLogging(
  id: string,
  wan_ip_logging_enabled: boolean | null,
): Promise<ClientConfig> {
  return apiFetch<ClientConfig>(`/api/configs/${id}/wan-logging`, {
    method: "PATCH",
    body: JSON.stringify({ wan_ip_logging_enabled }),
  });
}

export async function updateConfigWarpRouting(
  id: string,
  warp_routing_enabled: boolean,
): Promise<ClientConfig> {
  return apiFetch<ClientConfig>(`/api/configs/${id}/warp-routing`, {
    method: "PATCH",
    body: JSON.stringify({ warp_routing_enabled }),
  });
}

export async function listAdmins(): Promise<AdminPublic[]> {
  return apiFetch<AdminPublic[]>("/api/admins");
}

export type UpdateAdminAccountPayload = {
  email?: string;
  password?: string;
  config_slot_limit?: number | null;
  clear_slot_limit?: boolean;
  locked?: boolean;
};

export async function updateAdminAccount(
  id: string,
  body: UpdateAdminAccountPayload,
): Promise<AdminPublic> {
  return apiFetch<AdminPublic>(`/api/admins/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteAdminAccount(id: string): Promise<void> {
  await apiFetch<void>(`/api/admins/${id}`, { method: "DELETE" });
}

export type AttackPcapItem = {
  name: string;
  size_bytes: number;
  modified_at: string;
};

export type AttackEventItem = {
  id: string;
  detected_at: string | null;
  severity: string;
  kind: string;
  pps: number;
  bps: number;
  interface: string;
  pcap_file: string | null;
  pcap_available?: boolean;
  pcap_size_bytes: number | null;
  pcap_modified_at: string | null;
  bpf: string;
  discord_sent: boolean;
};

export type AttackPcapList = {
  captures: AttackPcapItem[];
  events: AttackEventItem[];
  attacks_lifetime: number;
  attacks_24h: number;
};

export type PcapAnalysisHeuristic = {
  id: string;
  label: string;
  confidence: number;
};

export type PcapAnalysis = {
  name: string;
  size_bytes: number;
  packet_count: number;
  analyzed_packets: number;
  truncated: boolean;
  duration_sec: number | null;
  avg_packet_bytes: number;
  min_packet_bytes: number;
  max_packet_bytes: number;
  unique_sources: number;
  gre_packets?: number;
  gre_ratio_pct?: number;
  syn_ratio_pct: number;
  synack_ratio_pct?: number;
  ack_ratio_pct?: number;
  heuristics: PcapAnalysisHeuristic[];
  protocols: Array<{
    name: string;
    packets: number;
    bytes: number;
    pct_packets: number;
    pct_bytes: number;
  }>;
  services: Array<{ name: string; packets: number; pct_packets: number }>;
  top_ports: Array<{
    port: number;
    direction?: string;
    label: string | null;
    packets: number;
    pct_packets: number;
  }>;
  top_sources: Array<{
    ip: string;
    packets: number;
    bytes: number;
    pct_packets: number;
    country_code: string | null;
    region: string | null;
    region_name: string | null;
    city: string | null;
  }>;
  countries: Array<{
    code: string;
    label: string;
    packets: number;
    pct_packets: number;
  }>;
  us_states: Array<{
    code: string;
    label: string;
    packets: number;
    pct_packets: number;
    pct_of_us: number;
  }>;
  analyzed_at: string;
};

export async function listAttackPcaps(): Promise<AttackPcapList> {
  return apiFetch<AttackPcapList>("/api/attacks");
}

export async function fetchPcapAnalysis(
  name: string,
  force = false,
): Promise<PcapAnalysis> {
  const q = force ? "?force=true" : "";
  return apiFetch<PcapAnalysis>(
    `/api/attacks/${encodeURIComponent(name)}/analysis${q}`,
  );
}

export async function deleteAttackPcap(name: string): Promise<void> {
  await apiFetch<void>(`/api/attacks/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

export async function downloadAttackPcap(name: string): Promise<void> {
  const res = await apiFetch<Response>(
    `/api/attacks/${encodeURIComponent(name)}/download`,
    {},
    { raw: true },
  );
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

