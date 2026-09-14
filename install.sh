#!/usr/bin/env bash
# Popout VPN installer — Angristan-class Linux support, Pi-hole-style finish.
#
#   curl -fsSL https://raw.githubusercontent.com/<you>/popout-vpn/main/install.sh -o popout-vpn-install.sh
#   sudo bash popout-vpn-install.sh
#
# Or clone the repo and run ./install.sh as root.
set -euo pipefail

# Resolve this script even when invoked via `sh install.sh` or curl|bash
_POPOUT_SELF="${BASH_SOURCE[0]:-$0}"
if [[ "${_POPOUT_SELF}" != /* ]]; then
  _POPOUT_SELF="$(pwd)/${_POPOUT_SELF}"
fi
_POPOUT_SELF="$(cd "$(dirname "${_POPOUT_SELF}")" && pwd)/$(basename "${_POPOUT_SELF}")"
POPOUT_SRC="$(cd "$(dirname "${_POPOUT_SELF}")" && pwd)"

# If this file was curled alone, clone the repo and re-exec.
ensure_full_tree() {
  if [[ -d "${POPOUT_SRC}/install" && -f "${POPOUT_SRC}/install/common.sh" ]]; then
    return
  fi
  echo "This copy of install.sh is missing the install/ library."
  echo "Cloning the Popout VPN repository…"
  local slug="${POPOUT_GITHUB_SLUG:-Adjent-X/popout-vpn}"
  local dest="${POPOUT_PANEL_ROOT:-/opt/popout-vpn}"
  mkdir -p "$(dirname "$dest")"
  if [[ -d "$dest/.git" ]]; then
    git -C "$dest" pull --ff-only || true
  else
    git clone "https://github.com/${slug}.git" "$dest"
  fi
  exec bash "${dest}/install.sh" "$@"
}

ensure_full_tree "$@"

# shellcheck source=install/common.sh
source "${POPOUT_SRC}/install/common.sh"
# shellcheck source=install/os.sh
source "${POPOUT_SRC}/install/os.sh"
# shellcheck source=install/packages.sh
source "${POPOUT_SRC}/install/packages.sh"
# shellcheck source=install/openvpn.sh
source "${POPOUT_SRC}/install/openvpn.sh"
# shellcheck source=install/cloudflare.sh
source "${POPOUT_SRC}/install/cloudflare.sh"
# shellcheck source=install/firewall-ephemeral.sh
source "${POPOUT_SRC}/install/firewall-ephemeral.sh"
# shellcheck source=install/panel.sh
source "${POPOUT_SRC}/install/panel.sh"
# shellcheck source=install/banner.sh
source "${POPOUT_SRC}/install/banner.sh"

usage() {
  cat <<EOF
Popout VPN $(popout_version) installer

Usage: sudo bash install.sh [command]

  (no args)    Full install: OpenVPN (Angristan) → Cloudflare prompt → stack
  reinstall    Repair panel, firewall, and optional Cloudflare (keep PKI/Mongo)
  uninstall    Stop services and remove the panel (asks before wiping PKI)
  help         This message

After install, use the popout-vpn command (see popout-vpn --help).
EOF
}

uninstall_stack() {
  check_root
  echo "This stops Popout VPN services and removes ${POPOUT_PANEL_ROOT}."
  echo "OpenVPN PKI under /etc/openvpn is left alone unless you confirm."
  local yn
  yn="$(ask_yn "Uninstall the Popout panel? [y/N]" "n")"
  [[ "$yn" == "y" ]] || exit 0
  systemctl disable --now popout-backend popout-frontend popout-attacks popout-ephemeral-ports 2>/dev/null || true
  rm -f /etc/systemd/system/popout-backend.service \
        /etc/systemd/system/popout-frontend.service \
        /etc/systemd/system/popout-attacks.service \
        /etc/systemd/system/popout-ephemeral-ports.service
  systemctl daemon-reload
  rm -f /usr/local/bin/popout-vpn /etc/nginx/conf.d/popout-vpn.conf
  nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
  yn="$(ask_yn "Also delete ${POPOUT_PANEL_ROOT}? [y/N]" "n")"
  if [[ "$yn" == "y" ]]; then
    rm -rf "${POPOUT_PANEL_ROOT}"
  fi
  ok "Panel uninstalled. OpenVPN was not removed (use Angristan's script for that)."
}

reinstall_stack() {
  check_root
  check_not_windows
  check_os
  load_state
  load_cloudflare_env 2>/dev/null || true
  info "Reinstall / repair (OpenVPN PKI and Mongo data are kept)"
  install_base_packages
  install_node20
  install_mongodb
  ensure_openvpn
  install_openvpn_hooks
  deploy_panel_stack
  setup_ephemeral_ports
  if [[ "${CF_ENABLED:-n}" == "y" ]]; then
    apply_cloudflare_zone
    seed_cloudflare_into_app
  fi
  print_install_banner
}

full_install() {
  check_root
  check_not_windows
  check_tun
  check_os
  ensure_dirs

  echo
  echo "${C_BOLD}Popout VPN $(popout_version)${C_RESET}"
  echo "All-in-one OpenVPN suite — same OS coverage as Angristan,"
  echo "then a web admin, optional Cloudflare, and ephemeral-port redirect."
  echo

  info "Step 1/6 — base packages"
  install_base_packages
  install_node20
  install_mongodb

  info "Step 2/6 — OpenVPN (Angristan)"
  ensure_openvpn
  install_openvpn_hooks

  info "Step 3/6 — Cloudflare"
  prompt_cloudflare

  info "Step 4/6 — control plane"
  deploy_panel_stack

  info "Step 5/6 — ephemeral-ports ipset + NAT REDIRECT"
  setup_ephemeral_ports

  info "Step 6/6 — Cloudflare zone (if enabled) + origin lock"
  if [[ "${CF_ENABLED:-n}" == "y" ]]; then
    apply_cloudflare_zone
    seed_cloudflare_into_app
    maybe_install_cf_nft
  fi

  print_install_banner
}

cmd="${1:-install}"
case "$cmd" in
  -h|--help|help) usage ;;
  uninstall) uninstall_stack ;;
  reinstall) reinstall_stack ;;
  install|"") full_install ;;
  *) usage; exit 1 ;;
esac
