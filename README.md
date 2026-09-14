# Popout VPN

<p align="center">
  <img src="docs/assets/logo.svg" alt="Popout VPN" width="480" />
</p>

<p align="center">
  <strong>The all-in-one OpenVPN suite.</strong><br/>
  One installer. A real control plane. Optional Cloudflare edge.<br/>
  Open source, self-hosted, built to stay out of your way.
</p>

<p align="center">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-1e3a8a" />
  <img alt="Version" src="https://img.shields.io/badge/version-0.1.0-06b6d4" />
  <img alt="Platforms" src="https://img.shields.io/badge/OS-Debian%20%7C%20Ubuntu%20%7C%20Fedora%20%7C%20RHEL%20%7C%20Arch-0a0e14" />
  <img alt="Status" src="https://img.shields.io/badge/status-public%20preview-67e8f9" />
</p>

Popout VPN is a self-hosted **OpenVPN control plane**: client configs, live connections, analytics, attack capture, traffic shaping, and a dark admin UI. The installer has the **same Linux coverage as [Angristan OpenVPN](https://github.com/angristan/openvpn-install)** — it runs that installer first, then brings up the rest of the stack and prints your login like Pi-hole.

This is **v0.1.0** — a public start. The [roadmap](ROADMAP.md) is real: WireGuard admin, packages, Docker, multi-node. Star the repo if you want that work to stay loud.

---

## What you get

| | |
|---|---|
| **OpenVPN that already works** | Angristan’s installer on Debian, Ubuntu, Fedora, Rocky / Alma / CentOS Stream, Amazon Linux, Oracle Linux, and Arch. Nyr layouts are detected if you already have one. |
| **Admin portal** | Next.js + FastAPI. Issue and revoke `.ovpn` files, invite sub-admins, API keys, live sessions. |
| **Optional Cloudflare** | Yes/no during install. Domain + zone API token (or Global API Key). We create DNS, set SSL Full, Always HTTPS, cache rules, and WAF. **The tunnel is never proxied.** |
| **Multiport / knock-style remotes** | ipset `ephemeral-ports` (45000–45099) plus iptables `REDIRECT` to the real OpenVPN port. Client configs can advertise `remote-random`. |
| **Ops extras** | CAKE shaping on `tun0`, attack monitor + pcap, zip backups, VPN-only admin on `10.8.0.1`. |

After install you get a boxed summary: **admin URL(s), generated email/password, version, and commands** — same idea as Pi-hole’s finish screen.

---

## Install

You need a Linux VPS with a public IPv4, root, and `/dev/net/tun`. **Not Windows. Not macOS.** Same rule as Angristan.

```bash
curl -fsSL https://raw.githubusercontent.com/Adjent-X/popout-vpn/main/install.sh -o popout-vpn-install.sh
sudo bash popout-vpn-install.sh
```

Or clone and run from the tree:

```bash
git clone https://github.com/Adjent-X/popout-vpn.git
cd popout-vpn
sudo bash install.sh
```

The installer will:

1. Detect your distro and install packages (nginx, Node 20, MongoDB, Python, ipset, iptables).
2. **Install OpenVPN via Angristan** if it is not already there (interactive — pick protocol, port, DNS, first client).
3. Ask: **Put the admin portal behind Cloudflare? [y/N]**  
   If yes: apex domain + API token (or Global API Key + email). See [docs/CLOUDFLARE.md](docs/CLOUDFLARE.md).
4. Generate JWT, Mongo password, and the first admin login.
5. Create ipset `ephemeral-ports` and NAT `REDIRECT` to OpenVPN.
6. If Cloudflare was enabled, auto-tune the zone (DNS, SSL, cache, WAF).
7. Print the portal URL and default login.

Connect a client, then open the admin over the tunnel (typically `http://10.8.0.1/`). If you enabled Cloudflare, `https://admin.yourdomain.com` is the public gateway.

Full walkthrough: [docs/INSTALL.md](docs/INSTALL.md).

---

## Cloudflare (yes or no)

Cloudflare fronts the **web UI**, not OpenVPN.

- **Yes** — orange-cloud `admin.<your-domain>`, SSL Full, cache bypass for `/api` and `/dashboard`, long cache for `/_next/static`, WAF rules for scanners and `/api/v1` API keys. Optional: lock origin :80/:443 to Cloudflare IP ranges.
- **No** — admin stays on the VPN (`10.8.0.1`). Nothing is published on the WAN.

You will be asked for:

- Apex **domain** (the zone, e.g. `example.com`)
- **API token** with Zone DNS Edit, Zone Settings Edit, Zone Read, Cache Rules Edit, Firewall Services Edit  
  or a **Global API Key** + account email (Cloudflare still calls this an API key)

Token setup is spelled out in [docs/CLOUDFLARE.md](docs/CLOUDFLARE.md). The panel can re-apply the zone later from **Server settings**.

---

## Commands

After install, `popout-vpn` is on your PATH (Angristan-style menu if you run it with no args):

```text
popout-vpn                 Interactive menu
popout-vpn version         0.1.0 + git describe + GitHub URL + API health
popout-vpn env             Current config/app.env (secrets masked)
popout-vpn env --show-secrets
popout-vpn settings        Live Server settings from Mongo
popout-vpn reinstall       Repair panel + firewall + Cloudflare (keeps PKI)
popout-vpn status
popout-vpn uninstall
```

Version tracks the repo `VERSION` file (`0.1.0` today) and `GET /api/health`. Details: [docs/COMMANDS.md](docs/COMMANDS.md).

---

## Architecture

```
                    .ovpn clients
                          |
              +-----------+-----------+
              |  ports 45000-45099    |
              |  ipset ephemeral-ports|
              |  NAT REDIRECT ----+   |
              +-------------------|---+
                                  v
                           OpenVPN :1194
                           tun0 10.8.0.1
                                  |
        browser --(+ Cloudflare)-- nginx --+-- Next.js :3000
                                           +-- FastAPI :8000
                                                    |
                                                 MongoDB
```

More: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## What’s next

v0.1.0 is the public preview. Coming up (see [ROADMAP.md](ROADMAP.md)):

- WireGuard peer admin beside OpenVPN
- Official `.deb` / `.rpm` and a Docker Compose path
- Multi-node / failover
- WebAuthn and passkeys
- Mobile-friendly client download flow

Issues and PRs are welcome. This is meant to be a product, not a private ops dump.

---

## Credits

- [Angristan/openvpn-install](https://github.com/angristan/openvpn-install) — GPL-3.0. We **download and run** that installer; we do not relicense it. Popout VPN itself is MIT.
- Inspired by the Pi-hole installer finish screen (clear URLs, one default password, “you’re done”).

## License

[MIT](LICENSE)

## Security

Please see [SECURITY.md](SECURITY.md). Do not open public issues for unpatched origin or auth bugs.
