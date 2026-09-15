#!/usr/bin/env bash
# Popout VPN post-install CLI (Pi-hole / Angristan style).
# Installed to /usr/local/bin/popout-vpn
set -euo pipefail

POPOUT_PANEL_ROOT="${POPOUT_PANEL_ROOT:-/opt/popout-vpn}"
# Sourced install helpers read POPOUT_SRC for the on-disk tree.
export POPOUT_SRC="${POPOUT_PANEL_ROOT}"

if [[ -f "${POPOUT_PANEL_ROOT}/install/common.sh" ]]; then
  # shellcheck source=install/common.sh
  source "${POPOUT_PANEL_ROOT}/install/common.sh"
  # shellcheck source=install/os.sh
  source "${POPOUT_PANEL_ROOT}/install/os.sh"
  # shellcheck source=install/cloudflare.sh
  source "${POPOUT_PANEL_ROOT}/install/cloudflare.sh"
  # shellcheck source=install/firewall-ephemeral.sh
  source "${POPOUT_PANEL_ROOT}/install/firewall-ephemeral.sh"
  # shellcheck source=install/openvpn.sh
  source "${POPOUT_PANEL_ROOT}/install/openvpn.sh"
  # shellcheck source=install/packages.sh
  source "${POPOUT_PANEL_ROOT}/install/packages.sh"
  # shellcheck source=install/panel.sh
  source "${POPOUT_PANEL_ROOT}/install/panel.sh"
  # shellcheck source=install/banner.sh
  source "${POPOUT_PANEL_ROOT}/install/banner.sh"
else
  echo "Popout VPN is not installed at ${POPOUT_PANEL_ROOT}" >&2
  exit 1
fi

git_describe() {
  if need_cmd git && [[ -d "${POPOUT_PANEL_ROOT}/.git" ]]; then
    git -C "${POPOUT_PANEL_ROOT}" describe --tags --always --dirty 2>/dev/null || true
  fi
}

cmd_version() {
  local ver slug commit health
  ver="$(popout_version)"
  slug="$(popout_github_slug)"
  commit="$(git_describe)"
  echo "Popout VPN ${ver}"
  echo "Repository : https://github.com/${slug}"
  if [[ -n "$commit" ]]; then
    echo "Git        : ${commit}"
  fi
  health="$(curl -fsS --max-time 2 http://127.0.0.1:8000/api/health 2>/dev/null || true)"
  if [[ -n "$health" ]]; then
    echo "API health : ${health}"
  else
    echo "API health : (backend not responding on 127.0.0.1:8000)"
  fi
}

cmd_env() {
  local show=0
  if [[ "${1:-}" == "--show-secrets" ]]; then
    show=1
    if [[ "${2:-}" != "--yes" ]]; then
      local yn
      yn="$(ask_yn "Print secrets from config/app.env in the clear? [y/N]" "n")"
      [[ "$yn" == "y" ]] || exit 0
    fi
  fi
  local file="${POPOUT_PANEL_ROOT}/config/app.env"
  [[ -f "$file" ]] || die "No ${file} — is Popout VPN installed?"
  echo "# ${file}"
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "$line" ]]; then
      echo "$line"
      continue
    fi
    local key="${line%%=*}"
    local val="${line#*=}"
    if [[ $show -eq 0 && "$key" =~ (PASSWORD|SECRET|TOKEN|KEY|WEBHOOK) ]]; then
      echo "${key}=$(mask_secret "$val")"
    else
      echo "$line"
    fi
  done <"$file"
}

cmd_settings() {
  local py="${POPOUT_PANEL_ROOT}/backend/.venv/bin/python"
  [[ -x "$py" ]] || die "Backend venv missing"
  (
    cd "${POPOUT_PANEL_ROOT}/backend"
    set -a
    # shellcheck disable=SC1091
    source "${POPOUT_PANEL_ROOT}/config/app.env"
    set +a
    "$py" - <<'PY'
import asyncio, json
from app.db import connect_db, close_db
from app.services.site_settings import get_site_settings

SECRET_KEYS = {
    "turnstile_secret_key",
    "cloudflare_api_token",
    "public_gate_password_hash",
    "attack_discord_webhook_url",
}

async def main():
    await connect_db(retries=5, delay_seconds=0.5)
    data, source = await get_site_settings(use_cache=False)
    payload = data.model_dump(mode="json")
    for k in SECRET_KEYS:
        if payload.get(k):
            payload[k] = "(configured)"
    payload["_source"] = source
    print(json.dumps(payload, indent=2, default=str))
    await close_db()

asyncio.run(main())
PY
  )
}

cmd_status() {
  echo "Popout VPN $(popout_version) — service status"
  echo
  for unit in popout-backend popout-frontend popout-attacks popout-ephemeral-ports mongod nginx openvpn-server@server; do
    if systemctl list-unit-files "${unit}.service" >/dev/null 2>&1 \
      || systemctl status "${unit}" >/dev/null 2>&1; then
      local state
      state="$(systemctl is-active "${unit}" 2>/dev/null || echo unknown)"
      printf "  %-28s %s\n" "$unit" "$state"
    fi
  done
  echo
  echo "Health: $(curl -fsS --max-time 2 http://127.0.0.1:8000/api/health 2>/dev/null || echo down)"
}

cmd_reinstall() {
  check_root
  exec bash "${POPOUT_PANEL_ROOT}/install.sh" reinstall
}

cmd_uninstall() {
  check_root
  exec bash "${POPOUT_PANEL_ROOT}/install.sh" uninstall
}

print_menu() {
  echo
  echo "${C_BOLD}Popout VPN $(popout_version)${C_RESET}  $(popout_github_url)"
  echo
  echo "  1) Status"
  echo "  2) Show version"
  echo "  3) View current .env (secrets masked)"
  echo "  4) View live app settings"
  echo "  5) Reinstall / repair"
  echo "  6) Restart services"
  echo "  7) Uninstall panel"
  echo "  8) Exit"
  echo
}

cmd_restart() {
  check_root
  systemctl restart popout-backend popout-frontend popout-attacks
  ok "Services restarted"
}

cmd_menu() {
  while true; do
    print_menu
    local choice
    choice="$(_ask_tty "Select an option [1-8]: ")"
    echo
    case "$choice" in
      1) cmd_status ;;
      2) cmd_version ;;
      3) cmd_env ;;
      4) cmd_settings ;;
      5) cmd_reinstall ;;
      6) cmd_restart ;;
      7) cmd_uninstall ;;
      8|q|Q) exit 0 ;;
      *) echo "Unknown option" ;;
    esac
    echo
  done
}

usage() {
  cat <<EOF
popout-vpn — manage a Popout VPN installation

Usage: popout-vpn [command]

  menu          Interactive menu (default)
  version       Version, git describe, GitHub URL, API health
  env           Print config/app.env (secrets masked)
  env --show-secrets
                Print env with secrets (confirms first)
  settings      Dump live Server settings from Mongo
  status        systemd unit health
  reinstall     Repair panel + firewall + Cloudflare
  restart       Restart panel services
  uninstall     Remove the panel (keeps OpenVPN by default)
  help          This message

Repo: $(popout_github_url)
EOF
}

main() {
  local cmd="${1:-menu}"
  shift || true
  case "$cmd" in
    -h|--help|help) usage ;;
    menu) cmd_menu ;;
    version|-v|--version) cmd_version ;;
    env) cmd_env "$@" ;;
    settings) cmd_settings ;;
    status) cmd_status ;;
    reinstall) cmd_reinstall ;;
    restart) cmd_restart ;;
    uninstall) cmd_uninstall ;;
    *) usage; exit 1 ;;
  esac
}

main "$@"
