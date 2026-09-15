# Architecture

Popout VPN is a **control plane** for an OpenVPN server on the same machine. It does not replace OpenVPN; it manages PKI, clients, and operations around it.

```
Internet
   │
   ├─ OpenVPN (Angristan or existing Nyr)
   │     tun0 10.8.0.0/24
   │     ipset ephemeral-ports → iptables NAT REDIRECT → real listen port
   │
   └─ HTTPS 80/443 (optional Cloudflare orange-cloud)
         nginx
           ├─ /api/  → uvicorn 127.0.0.1:8000  (FastAPI)
           └─ /      → next start 127.0.0.1:3000
         MongoDB 127.0.0.1:27017
```

## Components

| Path | Role |
|---|---|
| `backend/` | FastAPI, Motor/MongoDB, easy-rsa, Cloudflare WAF/zone, backups |
| `frontend/` | Next.js 16 admin UI |
| `monitor/` | pps + pcap daemon (`popout-attacks`) |
| `install/` | Distro packages, Angristan, Cloudflare, firewall, panel |
| `config/` | nginx snippets, mongod template, OpenVPN hooks |

Canonical install root: **`/opt/popout-vpn`**. Config: `/etc/popout-vpn`. Logs: `/var/log/popout-vpn`.

## OpenVPN flavors

`OPENVPN_FLAVOR=auto` looks at `/etc/openvpn/server/` for Angristan (`client-template.txt`, `tls-crypt-v2.key`) vs Nyr (`client-common.txt`, `tc.key`). Client `.ovpn` assembly lives in `backend/app/services/openvpn.py`.

## Multiport

Site settings `ovpn_remote_mode=remote_random` emits `remote-random` plus one `remote` per port in `45000–45099`. The installer creates ipset **`ephemeral-ports`** (bitmap:port) and:

```text
iptables -t nat -A PREROUTING -p tcp -m set --match-set ephemeral-ports dst \
  -j REDIRECT --to-ports <openvpn>
```

(same for UDP). Persisted by `popout-ephemeral-ports.service` and `ipset-restore.service`.

## Attack monitor

`monitor/attacks.sh` watches WAN pps thresholds and writes events + optional pcaps under `/var/log/popout-vpn/`. Panel **Analyze** calls `backend/app/services/pcap_analysis.py`: `tshark` line-by-line stats scored with **heuristics** (UDP flood, SYN flood, amplification ports, GRE, distributed sources, etc.) plus confidence %, protocol pie, and source geo — not a static signature / IOC database.

## Auth

First admin is seeded from `BOOTSTRAP_ADMIN_*` only when the `admins` collection is empty. JWT access + refresh; optional Cloudflare Turnstile; optional public access code for the Cloudflare hostname (generated at install when Cloudflare is enabled).
