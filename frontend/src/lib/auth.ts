import {
  apiFetch,
  type AdminPublic,
  type TokenResponse,
} from "@/lib/api";

const ACCESS_TOKEN_KEY = "popout_access_token";
const ADMIN_KEY = "popout_admin";
const PERSIST_KEY = "popout_session_persist";

export type LoginPayload = {
  email: string;
  password: string;
  turnstile_token: string;
  keep_signed_in?: boolean;
};

export type RegisterPayload = {
  email: string;
  password: string;
  registration_token: string;
  turnstile_token: string;
};

function storageForPersist(persist: boolean): Storage {
  return persist ? localStorage : sessionStorage;
}

function isPersistentSession(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(PERSIST_KEY) === "1";
}

export function saveSession(
  data: TokenResponse,
  options?: { persist?: boolean },
): void {
  const persist =
    options?.persist ??
    (data.admin.role === "admin" || isPersistentSession());
  // Always clear both, then write to the chosen store
  clearSession();
  if (persist) {
    localStorage.setItem(PERSIST_KEY, "1");
  }
  const store = storageForPersist(persist);
  store.setItem(ACCESS_TOKEN_KEY, data.access_token);
  store.setItem(ADMIN_KEY, JSON.stringify(data.admin));
}

export function updateStoredAdmin(admin: AdminPublic): void {
  const persist = isPersistentSession();
  const store = storageForPersist(persist);
  // Prefer whichever currently holds the session
  if (localStorage.getItem(ADMIN_KEY)) {
    localStorage.setItem(ADMIN_KEY, JSON.stringify(admin));
  }
  if (sessionStorage.getItem(ADMIN_KEY)) {
    sessionStorage.setItem(ADMIN_KEY, JSON.stringify(admin));
  }
  if (!localStorage.getItem(ADMIN_KEY) && !sessionStorage.getItem(ADMIN_KEY)) {
    store.setItem(ADMIN_KEY, JSON.stringify(admin));
  }
}

export function clearSession(): void {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  sessionStorage.removeItem(ADMIN_KEY);
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(ADMIN_KEY);
  localStorage.removeItem(PERSIST_KEY);
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return (
    localStorage.getItem(ACCESS_TOKEN_KEY) ??
    sessionStorage.getItem(ACCESS_TOKEN_KEY)
  );
}

export function getStoredAdmin(): AdminPublic | null {
  if (typeof window === "undefined") return null;
  const raw =
    localStorage.getItem(ADMIN_KEY) ?? sessionStorage.getItem(ADMIN_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AdminPublic;
  } catch {
    return null;
  }
}

export async function login(payload: LoginPayload): Promise<TokenResponse> {
  const keep = Boolean(payload.keep_signed_in);
  const data = await apiFetch<TokenResponse>(
    "/api/auth/login",
    {
      method: "POST",
      body: JSON.stringify({
        email: payload.email,
        password: payload.password,
        turnstile_token: payload.turnstile_token,
        keep_signed_in: keep,
      }),
    },
    { auth: false },
  );
  // Full admins always persist (localStorage). Others only with checkbox.
  saveSession(data, {
    persist: keep || data.admin.role === "admin",
  });
  return data;
}

export async function register(
  payload: RegisterPayload,
): Promise<TokenResponse> {
  const data = await apiFetch<TokenResponse>(
    "/api/auth/register",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    { auth: false },
  );
  saveSession(data, { persist: data.admin.role === "admin" });
  return data;
}

export async function refreshSession(): Promise<TokenResponse | null> {
  try {
    const data = await apiFetch<TokenResponse>(
      "/api/auth/refresh",
      { method: "POST" },
      { auth: false, skipAuthRedirect: true },
    );
    saveSession(data, {
      persist: isPersistentSession() || data.admin.role === "admin",
    });
    return data;
  } catch {
    return null;
  }
}

export async function logout(): Promise<void> {
  try {
    await apiFetch<void>(
      "/api/auth/logout",
      { method: "POST" },
      { auth: false, skipAuthRedirect: true },
    );
  } finally {
    clearSession();
  }
}
