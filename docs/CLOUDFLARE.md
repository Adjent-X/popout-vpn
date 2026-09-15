# Cloudflare and Popout VPN

The installer asks **one yes/no question**:

```text
Put the admin portal behind Cloudflare? [y/N]
```

If you say **no**, the admin UI is only reachable from connected VPN clients (typically `http://10.8.0.1/`). Nothing is published on the WAN.

If you say **yes**, you will be asked for:

1. **Apex domain** — the zone in your Cloudflare account, e.g. `example.com`
2. **Admin hostname** — default `admin.example.com`
3. **API token** (recommended) **or** Global API Key + account email

The installer then **auto-tunes that zone** so the hostname works for this app: DNS, SSL, cache, WAF, and optional origin lock. It also generates a **public access code** (printed in the finish banner) so the hostname is not an open login page. VPN clients on `10.8.0.1` skip that gate.

> **The OpenVPN tunnel is never sent through Cloudflare.** UDP/TCP 1194 (and the ephemeral redirect ports) stay direct to your VPS. Cloudflare only sits in front of nginx for the **web portal**.

---

## Credential: API token (recommended)

Create a token at [https://dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens) → **Create Token** → Custom token.

| Scope | Permission | Why |
|---|---|---|
| Zone — DNS | Edit | Proxied A/AAAA for `admin.<domain>` |
| Zone — Zone Settings | Edit | SSL Full, Always HTTPS, HTTP/3, Brotli, security level |
| Zone — Zone | Read | Resolve the zone id from the domain |
| Zone — Cache Rules | Edit | Bypass `/api`, `/login`, `/dashboard`; cache `/_next/static` |
| Zone — Cache Purge | Purge | Future “clear cache” from the panel |
| Zone — Firewall Services | Edit | Popout WAF custom rules + `/api/v1` API-key allowlist |

Include **Zone Resources → Include → Specific zone → your domain**.

Paste that token when the installer asks. The panel stores it encrypted-at-rest in site settings (the raw token is also in `/etc/popout-vpn/cloudflare.env`, mode `600`).

---

## Credential: Global API Key (“zone API key”)

Cloudflare’s account **Global API Key** plus login email still works. This is what many people mean by “zone API key.” It is broader than a token — prefer a scoped token if you can.

When the installer asks `token or key?`, choose `key`, then enter:

- Cloudflare account email
- Global API Key from [API Tokens](https://dash.cloudflare.com/profile/api-tokens) (bottom of the page)

---

## What auto-tune does

| Change | Value |
|---|---|
| DNS A (and AAAA if the box has IPv6) | `admin.<domain>` → this server, **proxied** (orange cloud) |
| SSL/TLS | **Full** (self-signed origin cert is enough) |
| Always Use HTTPS | on |
| Minimum TLS | 1.2, TLS 1.3 on |
| Brotli, HTTP/3, WebSockets | on |
| Rocket Loader | off (breaks some SPAs) |
| Security level | medium + browser integrity check |
| Cache rules | Bypass HTML/API/dashboard; cache `/_next/static` for ~31 days |
| WAF | Popout-prefixed custom rules (scanners, threat score, hosting ASNs, `/api/v1` key gate) |
| Optional | nftables: WAN :80/:443 only from [Cloudflare IP ranges](https://www.cloudflare.com/ips/) |

No paid add-ons are enabled (Argo, Bot Fight, Cache Reserve). Those surprise people on the bill.

**Full (strict)** needs a certificate Cloudflare trusts. The installer ships a self-signed origin cert for **Full**. You can later upload a Cloudflare Origin CA cert and switch the zone to Full (strict) in the dashboard, or re-run zone sync from **Server settings → Cloudflare**.

---

## Re-applying from the panel

After login (full admin):

- **Server settings** stores the token, zone id, and host list
- `POST /api/site-settings/cloudflare-waf-sync` — WAF + API-key allowlist
- `POST /api/site-settings/cloudflare-zone-sync` — DNS + SSL + cache + WAF

CLI: `popout-vpn reinstall` re-runs zone tune if Cloudflare was enabled at install time.

---

## What not to put on Cloudflare

- OpenVPN `port` / `proto` (1194/udp, 443/tcp, etc.)
- The `ephemeral-ports` range (45000–45099) used for `remote-random`
- SSH

Those must hit the VPS directly. Only nginx 80/443 for the admin hostname should be orange-clouded.
