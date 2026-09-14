# Roadmap

Popout VPN **0.1.0** is a public preview: one VPS, OpenVPN, a real admin, optional Cloudflare. This file is the advertised future — not a graveyard of ideas.

## Next (0.2)

- Refresh `ephemeral-ports` from Server settings when the remote-random range changes
- Cloudflare Origin CA issuance from the panel (Full Strict in one click)
- First-run wizard in the UI (password change, WAN IP, proto)
- Health checks and a prettier `popout-vpn status`

## Near term

- **WireGuard** peer admin next to OpenVPN (same panel, same users)
- Official **.deb / .rpm** so the curl installer is not the only path
- **Docker Compose** profile for labs (not a replacement for the bare-metal installer)
- Invite links and client download that work on a phone

## Later

- Multi-node / anycast-friendly config sync
- WebAuthn / passkeys for the admin
- Signed backup restore
- Prometheus endpoint
- IPv6-first installs

If you want a line moved up, open an issue with `roadmap` and a sentence of why.
