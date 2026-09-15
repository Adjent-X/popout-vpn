from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    APP_NAME: str = "Popout VPN Admin API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # MongoDB
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "popout_vpn"
    # Optional SCRAM auth — leave blank for unauthenticated local Mongo
    MONGODB_USER: str = ""
    MONGODB_PASSWORD: str = ""
    # Auth DB where the user is defined (usually "admin")
    MONGODB_AUTH_SOURCE: str = "admin"

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Cloudflare Turnstile (disable for VPN-only / tun0 demos)
    TURNSTILE_ENABLED: bool = True
    TURNSTILE_SITE_KEY: str = ""
    TURNSTILE_SECRET_KEY: str = ""

    # Branding (also exposed via GET /api/public/config)
    BRAND_NAME: str = "Popout"
    BRAND_PRODUCT: str = "VPN"
    SITE_TITLE: str = "Popout VPN Admin"
    BRAND_COLOR_BG: str = "#0a0e14"
    BRAND_COLOR_PRIMARY: str = "#1e3a8a"
    BRAND_COLOR_ACCENT: str = "#06b6d4"
    BRAND_COLOR_ACCENT_BRIGHT: str = "#67e8f9"

    # CORS (comma-separated origins)
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Auth rate limiting (per IP, shared across /api/auth/*)
    AUTH_RATE_LIMIT_REQUESTS: int = 10
    AUTH_RATE_LIMIT_WINDOW_SECONDS: int = 60
    # Extra per-email cap on login/register (in addition to per-IP)
    AUTH_RATE_LIMIT_EMAIL_REQUESTS: int = 5
    AUTH_RATE_LIMIT_EMAIL_WINDOW_SECONDS: int = 300

    # Admin registration token
    REGISTRATION_TOKEN_TTL_HOURS: int = 24

    # First admin (created only when admins collection is empty)
    BOOTSTRAP_ADMIN_EMAIL: str = ""
    BOOTSTRAP_ADMIN_PASSWORD: str = ""

    # Public Cloudflare hostname gate (seeded once when the hash is empty)
    PUBLIC_GATE_PASSWORD: str = ""

    # OpenVPN / easy-rsa (Nyr or Angristan under /etc/openvpn/server/)
    # auto | nyr | angristan — auto detects from client-template.txt / tls-crypt-v2 / tc.key
    OPENVPN_FLAVOR: str = "auto"
    EASYRSA_PATH: str = "/etc/openvpn/server/easy-rsa"
    EASYRSA_BIN: str = "./easyrsa"
    # Nyr: client-common.txt · Angristan: client-template.txt (auto-resolved if missing)
    OPENVPN_CLIENT_COMMON_PATH: str = "/etc/openvpn/server/client-common.txt"
    OPENVPN_CA_CERT_PATH: str = "/etc/openvpn/server/ca.crt"
    # Nyr uses tc.key; Angristan shared tls-crypt uses tls-crypt.key
    OPENVPN_TLS_CRYPT_KEY_PATH: str = "/etc/openvpn/server/tc.key"
    # Angristan tls-crypt-v2 (per-client keys). Empty = auto-detect tls-crypt-v2.key
    OPENVPN_TLS_CRYPT_V2_KEY_PATH: str = ""
    # Hide / disable Cloudflare WARP routing UI + API (e.g. Chicago without Warp).
    WARP_ROUTING_ENABLED: bool = True
    OPENVPN_SERVER_HOST: str = "vpn.example.com"
    OPENVPN_SERVER_PORT: int = 1194
    OPENVPN_PROTO: str = "tcp4"
    # server.conf: crl-verify crl.pem  (relative to /etc/openvpn/server)
    OPENVPN_CRL_PATH: str = "/etc/openvpn/server/crl.pem"
    OPENVPN_CRL_OWNER: str = "nobody"
    OPENVPN_CRL_GROUP: str = "nogroup"
    # Nyr does not restart after revoke (CRL re-read on connect). Set if you want a bounce.
    OPENVPN_RELOAD_CMD: str = ""
    CONFIG_EXPIRING_SOON_DAYS: int = 7

    # OpenVPN live status / IP assignments / connect event log
    OPENVPN_STATUS_PATH: str = "/etc/openvpn/server/openvpn-status.log"
    OPENVPN_IPP_PATH: str = "/etc/openvpn/server/ipp.txt"
    OPENVPN_CLIENT_EVENTS_PATH: str = "/var/log/openvpn/client-events.log"

    # Host metrics + connection poll intervals (seconds)
    METRICS_POLL_SECONDS: int = 30
    CONNECTION_POLL_SECONDS: int = 15
    METRICS_RETENTION_HOURS: int = 24

    # Attack monitor pcap / events
    ATTACK_PCAP_DIR: str = "/var/log/popout-vpn/captures"
    ATTACK_EVENTS_DIR: str = "/var/log/popout-vpn/events"

    # Zip backups of panel + utilities
    BACKUP_DIR: str = "/root/backups"
    PANEL_ROOT: str = "/opt/popout-vpn"

    # Displayed by /api/health and the popout-vpn CLI
    APP_VERSION: str = "0.2.0-beta"
    GITHUB_REPO: str = ""

    # Scheduler
    CONFIG_EXPIRY_CHECK_INTERVAL_MINUTES: int = 15
    BACKUP_INTERVAL_MINUTES: int = 30
    BACKUP_KEEP_COUNT: int = 3

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production" or not self.DEBUG

    @property
    def mongodb_connection_uri(self) -> str:
        """
        Build the Motor/PyMongo URI for the self-hosted localhost MongoDB.

        Prefer host-only MONGODB_URI + MONGODB_USER / MONGODB_PASSWORD
        (password is percent-encoded with %20, not '+'). If MONGODB_URI already
        includes credentials, it is normalized when possible.
        """
        from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

        uri = (self.MONGODB_URI or "").strip()
        user = (self.MONGODB_USER or "").strip()
        password = self.MONGODB_PASSWORD or ""
        # Strip accidental surrounding quotes from EnvironmentFile / .env
        if len(password) >= 2 and password[0] == password[-1] and password[0] in "\"'":
            password = password[1:-1]

        parsed = urlparse(uri)
        auth_source = (self.MONGODB_AUTH_SOURCE or "admin").strip() or "admin"

        if user:
            # Always rebuild auth from discrete fields so spaces/special chars work
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 27017
            netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
        elif parsed.username is not None:
            # Credentials already in URI — keep host, re-encode userinfo safely
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 27017
            pw = parsed.password or ""
            netloc = (
                f"{quote(parsed.username, safe='')}:{quote(pw, safe='')}@{host}:{port}"
            )
        else:
            return uri

        query_pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query_pairs.setdefault("authSource", auth_source)
        # Keep local single-node snappy; avoid SRV discovery overhead
        query_pairs.setdefault("directConnection", "true")

        path = parsed.path if parsed.path not in ("", "/") else "/"
        return urlunparse(
            (
                parsed.scheme or "mongodb",
                netloc,
                path,
                parsed.params,
                urlencode(query_pairs),
                parsed.fragment,
            )
        )

@lru_cache
def get_settings() -> Settings:
    return Settings()
