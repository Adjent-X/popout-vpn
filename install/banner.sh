#!/usr/bin/env bash
# Pi-hole style completion banner.
# shellcheck shell=bash

print_install_banner() {
  load_state
  load_cloudflare_env 2>/dev/null || true
  local ver url tun cf
  ver="$(popout_version)"
  url="$(popout_github_url)"
  tun="${TUN_IP:-10.8.0.1}"
  cf="${CF_HOST:-}"

  echo
  echo "${C_CYAN}${C_BOLD}"
  cat <<'ART'
  ____                        _     __     ______  _   _
 |  _ \ ___  _ __   ___  _   _| |_   \ \   / /  _ \| \ | |
 | |_) / _ \| '_ \ / _ \| | | | __|   \ \ / /| |_) |  \| |
 |  __/ (_) | |_) | (_) | |_| | |_     \ V / |  __/| |\  |
 |_|   \___/| .__/ \___/ \__,_|\__|     \_/  |_|   |_| \_|
            |_|
ART
  echo "${C_RESET}"
  echo "  ${C_BOLD}Popout VPN${C_RESET}  —  all-in-one OpenVPN suite"
  echo "  ${C_DIM}Open-source control plane + Angristan OpenVPN + optional Cloudflare edge${C_RESET}"
  echo
  echo "  ${C_GREEN}[✓] Installation complete${C_RESET}"
  echo
  echo "  Version     : ${ver}"
  echo "  Repository  : ${url}"
  echo
  echo "  ${C_BOLD}What you just installed${C_RESET}"
  echo "    An OpenVPN server (Angristan) plus a web admin that issues client"
  echo "    configs, shows live connections, optional attack capture, and"
  echo "    multiport NAT redirect (ipset ${EPHEMERAL_SET:-ephemeral-ports})."
  echo
  echo "  ${C_BOLD}Admin portal${C_RESET}"
  echo "    VPN clients : ${C_CYAN}http://${tun}/${C_RESET}"
  if [[ -n "$cf" && "${CF_ENABLED:-n}" == "y" ]]; then
    echo "    Cloudflare  : ${C_CYAN}https://${cf}/${C_RESET}"
  fi
  echo
  echo "  ${C_BOLD}Default login${C_RESET}  ${C_DIM}(change this immediately)${C_RESET}"
  echo "    Email       : ${C_YELLOW}${ADMIN_EMAIL}${C_RESET}"
  echo "    Password    : ${C_YELLOW}${ADMIN_PASSWORD}${C_RESET}"
  echo "    Saved at    : ${POPOUT_CRED_FILE}"
  echo
  echo "  ${C_BOLD}Useful commands${C_RESET}"
  echo "    popout-vpn              Interactive menu"
  echo "    popout-vpn version      Version + git + GitHub URL"
  echo "    popout-vpn env          Show config/app.env (secrets masked)"
  echo "    popout-vpn settings     Show live Server settings"
  echo "    popout-vpn reinstall    Repair / upgrade this stack"
  echo "    popout-vpn status       systemd health"
  echo
  echo "  Connect a client, then open the portal over the tunnel at the VPN URL."
  echo "  Docs: ${url}#readme"
  echo
}
