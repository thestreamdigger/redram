#!/bin/bash

set -e

# configuration
VENV_DIR="venv"
REQUIREMENTS_FILE="requirements.txt"
PYTHON_CMD="python3"
BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
DEFAULT_USER="pi"
RAM_PATH="/mnt/cdram"
RAM_SIZE="1G"

# options
QUIET_MODE=false
SKIP_TMPFS=false
INSTALL_SUPERDRIVE_UDEV=false

# parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    -q|--quiet)
      QUIET_MODE=true
      shift
      ;;
    --skip-tmpfs)
      SKIP_TMPFS=true
      shift
      ;;
    --install-superdrive-udev)
      INSTALL_SUPERDRIVE_UDEV=true
      shift
      ;;
    -h|--help)
      echo ""
      echo "  redram installation"
      echo ""
      echo "  usage: sudo $0 [options]"
      echo ""
      echo "  options:"
      echo "    -q, --quiet                  quiet mode"
      echo "    --skip-tmpfs                 skip tmpfs ram configuration"
      echo "    --install-superdrive-udev    install udev rule for apple superdrive"
      echo "    -h, --help                   show this help"
      echo ""
      exit 0
      ;;
    *)
      echo "✗ unknown option: $1"
      exit 1
      ;;
  esac
done

# logging functions
log_info() {
  if [ "$QUIET_MODE" != "true" ]; then
    echo "  → $1"
  fi
}
log_error(){
  echo "  ✗ $1"
  exit 1
}
log_ok()   {
  if [ "$QUIET_MODE" != "true" ]; then
    echo "  ✓ $1"
  fi
}
log_warn() {
  if [ "$QUIET_MODE" != "true" ]; then
    echo "  ~ $1"
  fi
}

# check root
check_root() {
  if [ "$EUID" -ne 0 ]; then
    echo ""
    echo "  ✗ run as root"
    echo ""
    echo "    sudo $0"
    echo ""
    exit 1
  fi
}

execute_cmd() {
  local desc=$1; shift
  local cmd="$@"
  if [ "$QUIET_MODE" = "true" ]; then
    if eval "$cmd" &> /dev/null; then return 0; else log_error "$desc failed"; fi
  else
    log_info "$desc"
    if eval "$cmd"; then return 0; else log_error "$desc failed"; fi
  fi
}

# check system
check_system() {
  log_info "checking system"

  if ! command -v python3 &> /dev/null; then
    log_error "python3 not found"
  fi

  if ! command -v pip3 &> /dev/null; then
    log_error "pip3 not found"
  fi

  if [ ! -f /etc/rpi-issue ]; then
    log_warn "not raspberry pi os (may work anyway)"
  fi

  log_ok "system check passed"
}

# install system dependencies
install_system_deps() {
  log_info "updating packages"
  apt-get update -qq

  log_info "installing dependencies"
  apt-get install -y \
    cdparanoia \
    cdda2wav \
    sg3-utils \
    libcdio-utils \
    python3-pip \
    python3-dev \
    libasound2-dev \
    alsa-utils \
    i2c-tools \
    python3-smbus >/dev/null 2>&1

  apt-get install -y python3-alsaaudio >/dev/null 2>&1 || {
    log_warn "python3-alsaaudio not available"
  }

  log_ok "dependencies installed"
}

# setup python environment
setup_python_env() {
  TARGET_USER=${SUDO_USER:-$DEFAULT_USER}
  if [ "$TARGET_USER" = "root" ]; then TARGET_USER=$DEFAULT_USER; fi

  if [ -d "$BASE_DIR/$VENV_DIR" ]; then
    log_info "removing old venv"
    rm -rf "$BASE_DIR/$VENV_DIR"
  fi

  log_info "creating venv"
  if [ -n "$SUDO_USER" ]; then
    sudo -u $SUDO_USER $PYTHON_CMD -m venv --system-site-packages $BASE_DIR/$VENV_DIR >/dev/null 2>&1
  else
    $PYTHON_CMD -m venv --system-site-packages $BASE_DIR/$VENV_DIR >/dev/null 2>&1
  fi

  log_info "upgrading pip"
  if [ -n "$SUDO_USER" ]; then
    sudo -u "$SUDO_USER" "$BASE_DIR/$VENV_DIR/bin/pip" install --upgrade pip wheel >/dev/null 2>&1 || true
  else
    "$BASE_DIR/$VENV_DIR/bin/pip" install --upgrade pip wheel >/dev/null 2>&1 || true
  fi

  if [ -f "$BASE_DIR/$REQUIREMENTS_FILE" ]; then
    log_info "installing python packages"
    if [ -n "$SUDO_USER" ]; then
      sudo -u "$SUDO_USER" "$BASE_DIR/$VENV_DIR/bin/pip" install -r "$BASE_DIR/$REQUIREMENTS_FILE" >/dev/null 2>&1 || {
        log_warn "some optional packages failed"
      }
    else
      "$BASE_DIR/$VENV_DIR/bin/pip" install -r "$BASE_DIR/$REQUIREMENTS_FILE" >/dev/null 2>&1 || {
        log_warn "some optional packages failed"
      }
    fi
  fi

  log_ok "python environment ready"
}

# setup tmpfs for ram cache
setup_tmpfs() {
  if [ "$SKIP_TMPFS" = "true" ]; then
    log_warn "skipping tmpfs"
    return 0
  fi

  log_info "configuring tmpfs"

  if [ ! -d "$RAM_PATH" ]; then
    mkdir -p "$RAM_PATH"
  fi

  if ! grep -q "$RAM_PATH" /etc/fstab 2>/dev/null; then
    echo "tmpfs $RAM_PATH tmpfs defaults,size=${RAM_SIZE},mode=1777 0 0" >> /etc/fstab
  fi

  mount "$RAM_PATH" 2>/dev/null || log_warn "tmpfs already mounted"

  log_ok "tmpfs ready"
}

# setup permissions
setup_permissions() {
  log_info "setting permissions"

  TARGET_USER=${SUDO_USER:-$DEFAULT_USER}
  if [ "$TARGET_USER" = "root" ]; then TARGET_USER=$DEFAULT_USER; fi

  find "$BASE_DIR" -type f ! -path "*/__pycache__/*" ! -path "*/venv/*" ! -name "*.pyc" \
    -exec chown "$TARGET_USER:$TARGET_USER" {} \; 2>/dev/null || true
  find "$BASE_DIR" -type d ! -path "*/__pycache__" ! -path "*/venv" \
    -exec chown "$TARGET_USER:$TARGET_USER" {} \; 2>/dev/null || true

  find "$BASE_DIR" -type d ! -path "*/venv" -exec chmod 755 {} \; 2>/dev/null || true
  find "$BASE_DIR" -type f -name "*.py" ! -path "*/venv/*" -exec chmod 644 {} \; 2>/dev/null || true

  chmod 755 "$BASE_DIR/install.sh" 2>/dev/null || true
  chmod 755 "$BASE_DIR/run.sh" 2>/dev/null || true
  chmod 755 "$BASE_DIR/src/main.py" 2>/dev/null || true
  chmod 755 "$BASE_DIR/src/superdrive.py" 2>/dev/null || true

  if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    usermod -a -G audio "$SUDO_USER" 2>/dev/null || true
    usermod -a -G dialout "$SUDO_USER" 2>/dev/null || true
  fi

  log_ok "permissions set"
}

# install superdrive udev rule
install_superdrive_udev() {
  if [ "$INSTALL_SUPERDRIVE_UDEV" != "true" ]; then
    return 0
  fi

  local UDEV_RULE_FILE="/etc/udev/rules.d/99-apple-superdrive.rules"

  if [ -f "$UDEV_RULE_FILE" ]; then
    log_warn "superdrive udev rule already exists"
    return 0
  fi

  if ! command -v sg_raw &> /dev/null; then
    log_error "sg_raw not found"
  fi

  log_info "installing superdrive udev rule"

  cat > "$UDEV_RULE_FILE" << 'UDEV_EOF'
# apple superdrive auto-init
ACTION=="add", ATTRS{idProduct}=="1500", ATTRS{idVendor}=="05ac", DRIVERS=="usb", RUN+="/usr/bin/sg_raw --cmdset=1 /dev/$kernel EA 00 00 00 00 00 01"
UDEV_EOF

  udevadm control --reload-rules 2>/dev/null || true
  udevadm trigger 2>/dev/null || true

  log_ok "superdrive udev installed"
}

# verify alsa
verify_alsa() {
  log_info "checking alsa"

  if ! command -v aplay &> /dev/null; then
    log_warn "aplay not found"
    return 1
  fi

  if ! aplay -l 2>/dev/null | grep -q "^card"; then
    log_warn "no alsa cards detected"
    return 1
  fi

  if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    if ! groups "$SUDO_USER" 2>/dev/null | grep -q "\baudio\b"; then
      log_warn "user not in audio group (logout/login required)"
    fi
  fi

  log_ok "alsa ready"
}

# show system info
show_system_info() {
  if [ "$QUIET_MODE" = "true" ]; then
    return 0
  fi

  echo ""
  echo "  system info"
  echo ""

  if command -v aplay &> /dev/null; then
    echo "    alsa devices:"
    aplay -l 2>/dev/null | grep -E "^card" | sed 's/^/      /' || echo "      none"
  fi

  if ls -d /dev/sr* 2>/dev/null | head -1 > /dev/null; then
    echo ""
    echo "    cd drives:"
    ls -l /dev/sr* 2>/dev/null | awk '{print "      " $NF}' || echo "      none"

    if lsusb 2>/dev/null | grep -qi "05ac:1500\|apple.*superdrive"; then
      echo "      ✓ apple superdrive detected"
    fi
  fi

  echo ""
}

# main
echo ""
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  redram installation"
echo ""
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

check_root
check_system
install_system_deps
setup_python_env
setup_tmpfs
setup_permissions
install_superdrive_udev
verify_alsa
show_system_info

echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  ✓ installation complete"
echo ""
echo "  start:"
echo "    ./run.sh"
echo ""
echo "  configuration:"
echo "    edit src/config.py"
echo ""
if [ "$INSTALL_SUPERDRIVE_UDEV" = "true" ]; then
  echo "  superdrive:"
  echo "    ✓ udev rule installed"
  echo ""
else
  echo "  superdrive users:"
  echo "    sudo ./install.sh --install-superdrive-udev"
  echo ""
fi
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

exit 0
