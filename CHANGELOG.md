# Changelog

## 0.1.0 — 2026-09-14

Public preview.

- Automated installer with Angristan-class OS detection (Debian, Ubuntu, Fedora, Rocky/Alma/CentOS, Amazon Linux, Oracle Linux, Arch)
- OpenVPN installed first via [angristan/openvpn-install](https://github.com/angristan/openvpn-install) when missing
- Interactive Cloudflare yes/no; domain + API token or Global API Key; zone DNS, SSL, cache, and WAF auto-tune
- ipset `ephemeral-ports` and iptables NAT `REDIRECT` to the OpenVPN listen port
- Pi-hole-style finish banner with portal URL and generated admin login
- `popout-vpn` CLI: `version`, `env`, `settings`, `reinstall`, `status`
- FastAPI + Next.js admin, MongoDB, nginx, systemd
