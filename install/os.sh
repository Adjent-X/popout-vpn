#!/usr/bin/env bash
# OS detection — same families as angristan/openvpn-install.
# shellcheck shell=bash

check_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "This installer must run as root. Re-run with: sudo bash install.sh"
  fi
}

check_not_windows() {
  case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
      die "Popout VPN installs on a Linux VPS (same platforms as Angristan OpenVPN). Windows is not a supported server OS."
      ;;
    Darwin)
      die "macOS is not a supported VPN server. Install on Debian, Ubuntu, Fedora, Rocky, Alma, Amazon Linux, Oracle Linux, or Arch."
      ;;
  esac
}

check_tun() {
  if [[ ! -e /dev/net/tun ]]; then
    die "/dev/net/tun is missing. OpenVPN needs TUN. Enable it in your VPS panel (or load the tun module) and re-run."
  fi
  if ! grep -qE '^c .*tun' /proc/devices 2>/dev/null && [[ ! -c /dev/net/tun ]]; then
    warn "Could not confirm TUN character device — continuing, but OpenVPN may fail."
  fi
}

# Sets: OS, OS_ID, OS_VERSION_ID, OS_CODENAME, PKG_MGR
check_os() {
  if [[ ! -f /etc/os-release ]]; then
    die "Cannot detect OS (/etc/os-release missing)."
  fi
  # shellcheck disable=SC1091
  source /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_VERSION_ID="${VERSION_ID:-}"
  OS_CODENAME="${VERSION_CODENAME:-}"
  OS=""
  PKG_MGR=""

  if [[ -e /etc/debian_version ]]; then
    if [[ "$OS_ID" == "ubuntu" ]]; then
      OS="ubuntu"
      PKG_MGR="apt"
      local major
      major="$(echo "$OS_VERSION_ID" | cut -d. -f1)"
      if [[ -n "$major" && "$major" -lt 20 ]]; then
        die "Ubuntu ${OS_VERSION_ID} is too old. Use Ubuntu 20.04 or newer (same as Angristan)."
      fi
    else
      OS="debian"
      PKG_MGR="apt"
      local major
      major="$(echo "$OS_VERSION_ID" | cut -d. -f1)"
      if [[ -n "$major" && "$major" -lt 11 ]]; then
        die "Debian ${OS_VERSION_ID} is too old. Use Debian 11 or newer (same as Angristan)."
      fi
    fi
  elif [[ "$OS_ID" == "fedora" || "${ID_LIKE:-}" == *"fedora"* && "$OS_ID" == "fedora" ]]; then
    OS="fedora"
    PKG_MGR="dnf"
  elif [[ "$OS_ID" == "centos" || "$OS_ID" == "rocky" || "$OS_ID" == "almalinux" ]]; then
    OS="centos"
    if need_cmd dnf; then PKG_MGR="dnf"; else PKG_MGR="yum"; fi
  elif [[ "$OS_ID" == "ol" ]]; then
    OS="oracle"
    if need_cmd dnf; then PKG_MGR="dnf"; else PKG_MGR="yum"; fi
  elif [[ "$OS_ID" == "amzn" ]]; then
    OS="amzn"
    if need_cmd dnf; then PKG_MGR="dnf"; else PKG_MGR="yum"; fi
  elif [[ -e /etc/arch-release || "$OS_ID" == "arch" ]]; then
    OS="arch"
    PKG_MGR="pacman"
  else
    die "Unsupported OS '${OS_ID}'. Popout VPN supports the same platforms as Angristan OpenVPN: Debian, Ubuntu, Fedora, Rocky/Alma/CentOS Stream, Amazon Linux, Oracle Linux, and Arch."
  fi

  ok "Detected ${PRETTY_NAME:-$OS_ID $OS_VERSION_ID} (pkg=${PKG_MGR})"
}

pkg_update() {
  case "$PKG_MGR" in
    apt)
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -y
      ;;
    dnf) dnf -y makecache || true ;;
    yum) yum -y makecache || true ;;
    pacman) pacman -Sy --noconfirm ;;
  esac
}

pkg_install() {
  case "$PKG_MGR" in
    apt)
      export DEBIAN_FRONTEND=noninteractive
      apt-get install -y -qq "$@"
      ;;
    dnf) dnf install -y "$@" ;;
    yum) yum install -y "$@" ;;
    pacman) pacman -S --noconfirm --needed "$@" ;;
    *) die "Unknown package manager ${PKG_MGR}" ;;
  esac
}
