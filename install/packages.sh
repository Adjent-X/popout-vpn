#!/usr/bin/env bash
# Distro packages: nginx, Python, Node 20, MongoDB, ipset, iptables.
# shellcheck shell=bash

install_base_packages() {
  info "Installing base packages for ${OS}…"
  pkg_update
  case "$PKG_MGR" in
    apt)
      pkg_install \
        curl ca-certificates gnupg lsb-release openssl tmux \
        build-essential python3 python3-venv python3-pip python3-dev \
        nginx ipset iptables iptables-persistent nftables \
        psmisc net-tools iproute2 tcpdump dnsutils \
        git sudo cron gawk rsync unzip tar \
        apache2-utils iputils-ping
      ;;
    dnf|yum)
      pkg_install \
        curl ca-certificates gnupg2 openssl tmux \
        gcc gcc-c++ make python3 python3-pip python3-devel \
        nginx ipset iptables nftables \
        psmisc net-tools iproute tcpdump bind-utils \
        git sudo cronie gawk rsync unzip tar \
        httpd-tools iputils
      ;;
    pacman)
      pkg_install \
        curl ca-certificates gnupg openssl tmux \
        base-devel python python-pip \
        nginx ipset iptables nftables \
        psmisc net-tools iproute2 tcpdump bind \
        git sudo cronie gawk rsync unzip tar \
        apache iputils
      ;;
  esac
  ok "Base packages installed"
}

install_node20() {
  local major=0
  if need_cmd node; then
    major="$(node -p "process.versions.node.split('.')[0]" 2>/dev/null || echo 0)"
  fi
  if [[ "$major" -ge 20 ]]; then
    ok "Node.js $(node -v) (>= 20)"
    return
  fi
  info "Installing Node.js 20…"
  case "$PKG_MGR" in
    apt)
      curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
      pkg_install nodejs
      ;;
    dnf|yum)
      curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
      pkg_install nodejs
      ;;
    pacman)
      pkg_install nodejs npm
      ;;
  esac
  need_cmd node || die "Node.js install failed"
  major="$(node -p "process.versions.node.split('.')[0]" 2>/dev/null || echo 0)"
  [[ "$major" -ge 20 ]] || die "Node.js is still < 20 ($(node -v 2>/dev/null || echo none)). Next.js 16 needs Node 20+."
  ok "Node.js $(node -v)"
}

install_mongodb() {
  if need_cmd mongod; then
    ok "MongoDB already present ($(mongod --version 2>/dev/null | head -n1))"
    return
  fi
  info "Installing MongoDB…"
  case "$OS" in
    debian|ubuntu)
      curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc \
        | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg
      local repo_line=""
      if [[ "$OS" == "ubuntu" ]]; then
        local codename="${OS_CODENAME:-jammy}"
        case "$codename" in
          noble|jammy|focal) ;;
          *) codename="jammy" ;;
        esac
        repo_line="deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu ${codename}/mongodb-org/7.0 multiverse"
      else
        local codename="${OS_CODENAME:-bookworm}"
        case "$codename" in
          bookworm|bullseye) ;;
          trixie|*)
            if [[ "$codename" == "trixie" ]]; then
              warn "MongoDB 7 has no trixie repo yet — using bookworm packages."
              codename="bookworm"
            fi
            ;;
        esac
        repo_line="deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/debian ${codename}/mongodb-org/7.0 main"
      fi
      echo "$repo_line" > /etc/apt/sources.list.d/mongodb-org-7.0.list
      pkg_update
      pkg_install mongodb-org
      ;;
    fedora)
      cat > /etc/yum.repos.d/mongodb-org-7.0.repo <<'EOF'
[mongodb-org-7.0]
name=MongoDB Repository
baseurl=https://repo.mongodb.org/yum/redhat/9/mongodb-org/7.0/x86_64/
gpgcheck=1
enabled=1
gpgkey=https://www.mongodb.org/static/pgp/server-7.0.asc
EOF
      pkg_install mongodb-org || pkg_install mongodb
      ;;
    centos|oracle)
      cat > /etc/yum.repos.d/mongodb-org-7.0.repo <<'EOF'
[mongodb-org-7.0]
name=MongoDB Repository
baseurl=https://repo.mongodb.org/yum/redhat/$releasever/mongodb-org/7.0/x86_64/
gpgcheck=1
enabled=1
gpgkey=https://www.mongodb.org/static/pgp/server-7.0.asc
EOF
      pkg_install mongodb-org
      ;;
    amzn)
      cat > /etc/yum.repos.d/mongodb-org-7.0.repo <<'EOF'
[mongodb-org-7.0]
name=MongoDB Repository
baseurl=https://repo.mongodb.org/yum/amazon/2/mongodb-org/7.0/x86_64/
gpgcheck=1
enabled=1
gpgkey=https://www.mongodb.org/static/pgp/server-7.0.asc
EOF
      pkg_install mongodb-org
      ;;
    arch)
      if ! pkg_install mongodb; then
        warn "Official mongodb package missing on Arch. Install mongodb-bin from the AUR, then re-run."
      fi
      ;;
  esac
  need_cmd mongod || die "MongoDB install failed"
  if [[ -f "${POPOUT_SRC}/config/mongod.popout.conf" && -d /etc ]]; then
    if [[ -f /etc/mongod.conf ]]; then
      cp -a /etc/mongod.conf "/etc/mongod.conf.bak.$(date +%s)" || true
    fi
    # Keep distro dbPath; overlay bind + cache from our template when paths exist
    if [[ -d /var/lib/mongodb || -d /var/lib/mongo ]]; then
      install -m 644 "${POPOUT_SRC}/config/mongod.popout.conf" /etc/mongod.conf
      if [[ -d /var/lib/mongo && ! -d /var/lib/mongodb ]]; then
        sed -i 's|/var/lib/mongodb|/var/lib/mongo|' /etc/mongod.conf || true
      fi
    fi
  fi
  systemctl enable mongod 2>/dev/null || systemctl enable mongodb 2>/dev/null || true
  systemctl start mongod 2>/dev/null || systemctl start mongodb 2>/dev/null || true
  sleep 2
  ok "MongoDB running"
}
