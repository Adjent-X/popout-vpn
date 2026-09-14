# Security

Popout VPN is a network appliance. Treat reports as urgent.

## Please report privately

Email security issues to the maintainer listed on the GitHub repo (or open a **private** GitHub security advisory). Include:

- Popout version (`popout-vpn version`)
- Distro
- Whether Cloudflare is enabled
- Steps that do **not** require a live exploit against someone else’s box

Do not file a public issue for auth bypass, origin exposure, or PKI leakage until there is a fix or a coordinated disclosure date.

## What we consider in-scope

- Admin auth (JWT, bootstrap password, registration tokens)
- Cloudflare token storage
- Path traversal on pcap / backup download
- nginx / origin exposure when Cloudflare lock is enabled
- Privilege escalation via OpenVPN hooks or sudoers snippets we ship

## Out of scope

- “My VPS has no firewall”
- Weak passwords the operator generated and did not rotate
- OpenVPN protocol issues upstream of this repo
- Denial of service by saturating a small VPS

## Operator basics

Change the generated admin password immediately. Delete `BOOTSTRAP_ADMIN_PASSWORD` from `config/app.env`. Keep Mongo on localhost. Do not orange-cloud OpenVPN ports.
