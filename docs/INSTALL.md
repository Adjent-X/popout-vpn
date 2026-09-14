# Install guide

Popout VPN targets a **Linux VPS** with root and TUN — the same platforms as [angristan/openvpn-install](https://github.com/angristan/openvpn-install):

- Debian 11–13
- Ubuntu 20.04, 22.04, 24.04
- Fedora
- Rocky Linux, AlmaLinux, CentOS Stream
- Amazon Linux 2
- Oracle Linux
- Arch Linux

**Not supported as the VPN server:** Windows, macOS, OpenVZ without TUN.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/Adjent-X/popout-vpn/main/install.sh \
  -o popout-vpn-install.sh
sudo bash popout-vpn-install.sh
```

From a clone:

```bash
sudo bash install.sh
```

Repair without wiping OpenVPN PKI or Mongo:

```bash
sudo bash install.sh reinstall
# or
sudo popout-vpn reinstall
```

## What happens

1. Root + TUN + OS detection (Angristan-style abort messages if the platform is wrong).
2. Packages: curl, nginx, Python 3 venv, Node 20, MongoDB, ipset, iptables, tcpdump.
3. **OpenVPN** — if `/etc/openvpn/server/server.conf` is missing, Angristan’s script is downloaded and run **interactively**. Finish that wizard (protocol, port, DNS, first client) before expecting Popout to continue.
4. **Cloudflare?** `[y/N]`. Yes → domain + API token or Global API Key. See [CLOUDFLARE.md](CLOUDFLARE.md).
5. Secrets generated: JWT, Mongo password, first admin password.
6. Panel at `/opt/popout-vpn`, systemd `popout-backend` / `popout-frontend` / `popout-attacks`.
7. nginx: VPN-only on `10.8.0.1:80`; if Cloudflare, 443 on the WAN with a self-signed origin cert.
8. ipset `ephemeral-ports` + NAT `REDIRECT` to the OpenVPN listen port.
9. Zone auto-tune (if enabled).
10. Pi-hole-style banner with URLs and the default login. Copy is also in `/root/popout-vpn-credentials.txt` (mode 600).

## After install

1. Import the `.ovpn` Angristan (or Popout) issued onto your laptop.
2. Connect.
3. Open `http://10.8.0.1/` (or the Cloudflare hostname).
4. Sign in with the generated email/password.
5. **Change the password**, then remove `BOOTSTRAP_ADMIN_PASSWORD` from `/opt/popout-vpn/config/app.env`.

## Firewall notes

- Allow OpenVPN (the port you chose in Angristan) and the ephemeral range **45000–45099** from the internet if you use `remote-random`.
- Allow 80/443 from the world (or from Cloudflare only) if you enabled the public portal.
- Keep SSH on a known port; the installer does not close it.

## Uninstall

```bash
sudo popout-vpn uninstall
```

Removes systemd units and optionally `/opt/popout-vpn`. OpenVPN is left installed — use Angristan’s script if you want that gone too.
