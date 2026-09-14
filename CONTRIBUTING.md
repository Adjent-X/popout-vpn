# Contributing

Thanks for making Popout VPN less of a private ops tool and more of a product.

## Ways to help

- Bug reports with distro (`/etc/os-release`), installer log, and `popout-vpn version`
- Installer coverage on a distro Angristan supports but we mishandle
- UI copy, accessibility, and docs
- Features that match [ROADMAP.md](ROADMAP.md)

## Dev setup (Linux)

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
cp config/app.env.example config/app.env
# edit JWT, Mongo, OpenVPN paths
cd frontend && npm install
```

Run the API (`uvicorn`) and Next.js dev server against a local Mongo. Do not commit `config/app.env`, `.env`, or anything under `/etc/popout-vpn`.

## Shell

Installer scripts are `bash`. Keep them `set -euo pipefail` at the entry point. Prefer `install/*.sh` libraries over growing `install.sh`. Line endings are LF (`.gitattributes`).

## Pull requests

Small, reviewable, with a sentence of *why*. Match existing naming (`popout-vpn`, `ephemeral-ports`, `/opt/popout-vpn`). Do not add paid Cloudflare products as defaults.
