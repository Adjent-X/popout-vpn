# Commands

The installer puts **`popout-vpn`** on `PATH` (`/usr/local/bin/popout-vpn`).

Run with no arguments for an interactive menu (Angristan-style).

| Command | What it does |
|---|---|
| `popout-vpn` / `popout-vpn menu` | Interactive menu |
| `popout-vpn version` | `VERSION` file, git describe (if `.git` exists), GitHub URL, `/api/health` |
| `popout-vpn env` | Print `/opt/popout-vpn/config/app.env` with `PASSWORD`/`SECRET`/`TOKEN`/`KEY` masked |
| `popout-vpn env --show-secrets` | Same, after a yes/no confirm |
| `popout-vpn settings` | Pretty-print live Server settings from Mongo (secrets redacted) |
| `popout-vpn status` | systemd `is-active` for panel, mongo, nginx, OpenVPN UDP/TCP, WireGuard, DNAT |
| `popout-vpn reinstall` | `install.sh reinstall` — packages, panel, firewall, Cloudflare; **keeps PKI and Mongo** |
| `popout-vpn restart` | Restart backend, frontend, attack monitor |
| `popout-vpn uninstall` | Stop units; optional delete of `/opt/popout-vpn` |

Version correlation:

- Repo root `VERSION` (currently `0.2.0-beta`)
- `APP_VERSION` / `GITHUB_REPO` in `config/app.env`
- `GET /api/health` → `{ "status", "version", "repository", "timestamp" }`
- GitHub release tags should match `VERSION` (v0.2.0-beta, …)

Installer entry points:

```bash
sudo bash install.sh            # full install
sudo bash install.sh reinstall
sudo bash install.sh uninstall
```
