#!/bin/bash
#
# GrowMate V2 - Automated Installation Script
# Raspberry Pi Zero W Installation
#
# This script installs the GrowMate V2 plant monitoring system on a fresh
# Raspberry Pi OS installation. It handles all dependencies, system
# configuration, and service setup.
#
# V2 changes:
# - Installs to /home/pi/growmate/ (runs as pi user, not root)
# - Keeps AP mode (hostapd + dnsmasq) for first-time WiFi setup and recovery
# - Adds Tailscale for day-to-day secure connectivity
# - Uses rpicam-vid (rpicam-apps) for live camera stream (no picamera2)
# - Secrets from env vars (DEVICE_API_KEY, DEVICE_ID), not config.yaml
# - Interactive config.yaml creation during install
#
# Usage:
#   sudo ./install.sh
#
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTALL_DIR="/home/pi/growmate"
SERVICE_FILE="/etc/systemd/system/growmate.service"
CONFIG_DIR="/etc/growmate"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

error_exit() { log_error "$1"; exit 1; }

print_banner() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║                                                            ║"
    echo "║            GrowMate V2 - Installation                      ║"
    echo "║      Raspberry Pi Zero W Plant Monitoring System           ║"
    echo "║                                                            ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
}

check_root() {
    log_info "Checking root privileges..."
    if [ "$EUID" -ne 0 ]; then
        error_exit "This script must be run as root. Use: sudo ./install.sh"
    fi
    log_success "Running as root"
}

check_platform() {
    log_info "Checking platform..."
    if [ ! -f /proc/device-tree/model ]; then
        log_warning "Cannot detect Raspberry Pi model"
    else
        MODEL=$(cat /proc/device-tree/model)
        log_info "Detected: $MODEL"
        if [[ ! "$MODEL" =~ "Raspberry Pi" ]]; then
            log_warning "This script is designed for Raspberry Pi. Continuing anyway..."
        fi
    fi
}

update_system() {
    log_info "Updating system packages..."
    apt-get update -qq || error_exit "Failed to update package lists"
    log_success "System package lists updated"
}

install_system_deps() {
    log_info "Installing system dependencies..."

    PACKAGES=(
        python3
        python3-pip
        python3-dev
        python3-venv

        i2c-tools

        libgpiod2
        python3-libgpiod

        rpicam-apps

        hostapd
        dnsmasq

        build-essential

        git
        curl
    )

    log_info "Installing: ${PACKAGES[*]}"
    apt-get install -y -qq "${PACKAGES[@]}" || error_exit "Failed to install system dependencies"
    log_success "System dependencies installed"
}

install_tailscale() {
    log_info "Installing Tailscale..."

    if command -v tailscale &>/dev/null; then
        log_success "Tailscale already installed ($(tailscale version 2>/dev/null | head -1))"
        return
    fi

    curl -fsSL https://tailscale.com/install.sh | sh || error_exit "Failed to install Tailscale"
    log_success "Tailscale installed"

    log_info "Bring up Tailscale (you'll need to authenticate)..."
    tailscale up || log_warning "Tailscale up failed. Run 'sudo tailscale up' manually after install."
}

enable_i2c() {
    log_info "Enabling I2C interface..."

    if lsmod | grep -q i2c_bcm2835; then
        log_success "I2C already enabled"
        return
    fi

    raspi-config nonint do_i2c 0 || log_warning "Failed to enable I2C via raspi-config"

    if ! grep -q "^i2c-dev" /etc/modules; then
        echo "i2c-dev" >> /etc/modules
    fi
    if ! grep -q "^i2c-bcm2835" /etc/modules; then
        echo "i2c-bcm2835" >> /etc/modules
    fi

    modprobe i2c-dev 2>/dev/null || true
    modprobe i2c-bcm2835 2>/dev/null || true

    log_success "I2C interface enabled"
}

create_install_dir() {
    log_info "Creating installation directory: $INSTALL_DIR"

    if [ -d "$INSTALL_DIR" ]; then
        BACKUP_DIR="${INSTALL_DIR}.backup.$(date +%Y%m%d_%H%M%S)"
        log_warning "Existing installation found. Backing up to: $BACKUP_DIR"
        mv "$INSTALL_DIR" "$BACKUP_DIR"
    fi

    mkdir -p "$INSTALL_DIR"
    log_success "Installation directory created"
}

copy_files() {
    log_info "Copying project files to $INSTALL_DIR..."

    cp -r "$PROJECT_ROOT/src" "$INSTALL_DIR/"
    cp -r "$PROJECT_ROOT/templates" "$INSTALL_DIR/"
    cp -r "$PROJECT_ROOT/static" "$INSTALL_DIR/"
    cp "$PROJECT_ROOT/requirements.txt" "$INSTALL_DIR/"

    cp "$PROJECT_ROOT/scripts/start.sh" "$INSTALL_DIR/"

    [ -f "$PROJECT_ROOT/README.md" ] && cp "$PROJECT_ROOT/README.md" "$INSTALL_DIR/"

    log_success "Project files copied"
}

install_python_deps() {
    log_info "Installing Python dependencies..."

    pip3 install --upgrade pip -q || log_warning "Failed to upgrade pip"
    pip3 install -r "$INSTALL_DIR/requirements.txt" -q || error_exit "Failed to install Python dependencies"

    log_success "Python dependencies installed"
}

configure_ap_mode() {
    log_info "Configuring AP mode support (first-time setup and recovery)..."

    systemctl stop hostapd 2>/dev/null || true
    systemctl stop dnsmasq 2>/dev/null || true

    systemctl disable hostapd 2>/dev/null || true
    systemctl disable dnsmasq 2>/dev/null || true

    systemctl unmask hostapd 2>/dev/null || true

    mkdir -p "$INSTALL_DIR/config"
    cp "$PROJECT_ROOT/config/hostapd.conf.template" "$INSTALL_DIR/config/"
    cp "$PROJECT_ROOT/config/dnsmasq.conf.template" "$INSTALL_DIR/config/"

    log_success "AP mode support configured"
}

create_config() {
    log_info "Creating configuration file: $CONFIG_FILE"

    mkdir -p "$CONFIG_DIR"

    # Detect device ID from MAC
    DEVICE_ID="growmate-$(cat /sys/class/net/wlan0/address 2>/dev/null | tr -d ':' || echo 'unknown')"

    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║              Configuration Setup                          ║"
    echo "║ Press Enter to accept defaults in [brackets].             ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""

    # Device
    read -r -p "  Device ID [$DEVICE_ID]: " input_id
    DEVICE_ID="${input_id:-$DEVICE_ID}"

    # API
    read -r -p "  Sensor API URL [https://growmate.bond/api/v2/sensors]: " input_sensor_url
    SENSOR_URL="${input_sensor_url:-https://growmate.bond/api/v2/sensors}"

    read -r -p "  Stream Register URL [https://growmate.bond/api/v2/stream/register]: " input_stream_url
    STREAM_URL="${input_stream_url:-https://growmate.bond/api/v2/stream/register}"

    # Onboarding
    read -r -p "  AP mode password [growmate]: " input_ap_pass
    AP_PASS="${input_ap_pass:-growmate}"

    # Sensor interval
    read -r -p "  Sensor reading interval in seconds [60]: " input_interval
    SENSOR_INTERVAL="${input_interval:-60}"

    # DHT22
    read -r -p "  Enable DHT22 sensor? (y/n) [y]: " input_dht
    if [[ "${input_dht:-y}" =~ ^[Yy] ]]; then
        DHT22="true"
        read -r -p "  DHT22 GPIO pin [4]: " input_dht_pin
        DHT22_PIN="${input_dht_pin:-4}"
    else
        DHT22="false"
        DHT22_PIN="4"
    fi

    # ADC
    read -r -p "  ADC I2C address (hex, e.g. 0x48) [0x48]: " input_adc_addr
    ADC_ADDR="${input_adc_addr:-0x48}"

    read -r -p "  ADC gain [1]: " input_gain
    ADC_GAIN="${input_gain:-1}"

    # Relay pins
    read -r -p "  Pump relay GPIO [10]: " input_pump
    PUMP_PIN="${input_pump:-10}"

    read -r -p "  Fertilizer relay GPIO [17]: " input_fert
    FERT_PIN="${input_fert:-17}"

    read -r -p "  Pesticide relay GPIO [27]: " input_pest
    PEST_PIN="${input_pest:-27}"

    # Limit switches
    read -r -p "  Tank limit switch GPIO [20]: " input_tank
    TANK_PIN="${input_tank:-20}"

    read -r -p "  Drawer limit switch GPIO [21]: " input_drawer
    DRAWER_PIN="${input_drawer:-21}"

    # Camera
    read -r -p "  Enable rpicam-vid camera? (y/n) [y]: " input_cam
    if [[ "${input_cam:-y}" =~ ^[Yy] ]]; then
        CAM_ENABLED="true"
    else
        CAM_ENABLED="false"
    fi

    # Logging
    read -r -p "  Log level (DEBUG/INFO/WARNING/ERROR) [INFO]: " input_log
    LOG_LEVEL="${input_log:-INFO}"

    # Provisioned (fresh install = false)
    PROVISIONED="false"

    cat > "$CONFIG_FILE" <<YAMLEOF
# GrowMate Pods V2 Configuration
# Generated by install.sh on $(date)
# See /home/pi/growmate/config/config.yaml.example for full documentation
version: 9

device:
  id: "${DEVICE_ID}"

api:
  sensor_url: "${SENSOR_URL}"
  stream_register_url: "${STREAM_URL}"
  timeout_sensor: 30.0
  timeout_stream_register: 10.0

network:
  provisioned: ${PROVISIONED}
  wifi_ssid: ""
  wifi_password: ""
  wifi:
    interface: "wlan0"
    connect_timeout: 12
    connect_retries: 4

ap_mode:
  ssid: "GrowMate-A1B2C3"
  password: "${AP_PASS}"
  channel: 1
  ip_address: "192.168.4.1"
  netmask: "255.255.255.0"
  dhcp_range_start: "192.168.4.2"
  dhcp_range_end: "192.168.4.20"
  interface: "wlan0"

onboarding:
  host: "0.0.0.0"
  port: 80

intervals:
  sensor_reading: ${SENSOR_INTERVAL}
  failure_monitor: 30
  camera_watchdog: 30
  queue_cleanup: 3600
  queue_vacuum: 604800
  queue_stats: 300
  health_check: 300

queue:
  enabled: true
  db_path: "/var/lib/growmate/queue.db"
  max_age_hours: 24
  max_sensor_entries: 1440
  cleanup_interval: 3600
  max_retries: 5
  vacuum_interval: 604800

upload_processor:
  max_concurrent: 3
  delay: 0.5
  idle_sleep: 2.0
  batch_sleep: 0.1

retry:
  max_attempts: 6
  initial_delay: 1.0
  max_delay: 32.0
  jitter: 0.25

circuit_breaker:
  failure_threshold: 5
  recovery_timeout: 60
  success_threshold: 2

sensors:
  enable_dht22: ${DHT22}
  dht22_pin: ${DHT22_PIN}
  adc:
    i2c_bus: 1
    i2c_address: ${ADC_ADDR}
    gain: ${ADC_GAIN}
    samples: 8
    sample_delay: 0.01
    max_value: 65535
  channels:
    battery_current: 0
    light: 1
    water: 2
    soil: 3
  calibration:
    soil:
      min: 0
      max: 65535
    light:
      min: 0
      max: 65535
    water:
      min: 0
      max: 65535
  battery_current:
    midpoint_voltage: 2.5
    sensitivity: 0.185
  limit_switches:
    tank_gpio: ${TANK_PIN}
    drawer_gpio: ${DRAWER_PIN}
    pull_up_down: "PUD_UP"
    debounce_ms: 50
    debounce_samples: 5
    debounce_sample_interval: 0.01
  health:
    failure_threshold: 3

actuators:
  pins:
    pump: ${PUMP_PIN}
    fertilizer: ${FERT_PIN}
    pesticide: ${PEST_PIN}
  active_high: true
  initial_value: false
  journal_size: 1000
  journal_trim: 500

camera:
  enabled: ${CAM_ENABLED}
  port: 8554
  width: 640
  height: 480
  framerate: 15
  bitrate: 1000000
  profile: "baseline"
  level: "3.1"
  denoise: "cdn_off"
  restart_delay: 0.5

failure:
  consecutive_threshold: 5

health_monitor:
  history_size: 100
  camera_crash_threshold: 5

stream_registration:
  max_attempts: 10
  base_delay: 1.0
  max_delay: 60.0

logging:
  level: "${LOG_LEVEL}"
  file: "/var/log/growmate/growmate.log"
  format: "json"
  max_bytes: 10485760
  backup_count: 5
  modules: {}

features:
  offline_queue: true
  hot_reload: true
  circuit_breaker: true
YAMLEOF

    chmod 644 "$CONFIG_FILE"
    log_success "Configuration file created: $CONFIG_FILE"
    log_info "Review and edit: sudo nano $CONFIG_FILE"
}

install_service() {
    log_info "Installing systemd service..."

    if systemctl is-active --quiet growmate; then
        log_info "Stopping existing service..."
        systemctl stop growmate
    fi

    cp "$PROJECT_ROOT/systemd/growmate.service" "$SERVICE_FILE"

    systemctl daemon-reload
    log_success "Systemd service installed"
}

enable_service() {
    log_info "Enabling service to start on boot..."
    systemctl enable growmate
    log_success "Service enabled"

    log_info "Starting GrowMate service..."
    systemctl start growmate || log_warning "Service may need environment vars set; run: sudo systemctl edit growmate"
}

set_permissions() {
    log_info "Setting file permissions..."

    chown -R pi:pi "$INSTALL_DIR"
    chmod -R 755 "$INSTALL_DIR"
    chmod +x "$INSTALL_DIR/start.sh"

    log_success "Permissions set"
}

display_status() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║              Installation Complete!                       ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""

    log_info "Service Status:"
    systemctl status growmate --no-pager -l || true

    echo ""
    log_info "Installation Summary:"
    echo "  Installation directory: $INSTALL_DIR"
    echo "  Config file: $CONFIG_FILE"
    echo "  Service file: $SERVICE_FILE"
    echo "  Service status: $(systemctl is-active growmate)"
    echo "  Auto-start on boot: $(systemctl is-enabled growmate)"
    echo ""

    log_info "Next Steps:"
    echo ""
    echo "  1. Set required environment variables:"
    echo "     sudo systemctl edit growmate"
    echo ""
    echo "     Add:"
    echo "     [Service]"
    echo "     Environment=DEVICE_API_KEY=<your-api-key>"
    echo "     Environment=DEVICE_ID=<your-device-id>"
    echo ""
    echo "  2. Ensure Tailscale is connected:"
    echo "     sudo tailscale up"
    echo ""
    echo "  3. First-time setup (AP mode):"
    echo "     The device will enter AP mode automatically on boot."
    echo "     \u2022 Connect to WiFi network: $(grep 'ssid:' "$CONFIG_FILE" 2>/dev/null | head -1 | awk '{print $2}')"
    echo "     \u2022 Password: $(grep 'password:' "$CONFIG_FILE" 2>/dev/null | head -1 | awk '{print $2}')"
    echo "     \u2022 Channel: $(grep 'channel:' "$CONFIG_FILE" 2>/dev/null | head -1 | awk '{print $2}')"
    echo "     \u2022 Open browser: http://192.168.4.1"
    echo "     \u2022 Enter your WiFi credentials"
    echo "     \u2022 WiFi is saved to $CONFIG_FILE (network.wifi_ssid / network.wifi_password)"
    echo "     \u2022 The device connects and sets provisioned=true"
    echo ""
    echo "  4. Useful commands:"
    echo "     View logs:        journalctl -u growmate -f"
    echo "     Service status:   systemctl status growmate"
    echo "     Restart service:  systemctl restart growmate"
    echo "     Stop service:     systemctl stop growmate"
    echo "     Camera status:    ps aux | grep rpicam-vid"
    echo "     Tailscale IP:     tailscale ip -4"
    echo "     Edit config:      sudo nano $CONFIG_FILE"
    echo ""

    if ! lsmod | grep -q i2c_bcm2835; then
        log_warning "A reboot is recommended to fully enable I2C"
        echo ""
        echo "  ${YELLOW}Reboot now? (y/n)${NC}"
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            log_info "Rebooting in 5 seconds... (Ctrl+C to cancel)"
            sleep 5
            reboot
        fi
    fi
}

main() {
    print_banner
    log_info "Starting installation..."
    echo ""

    check_root
    check_platform

    update_system
    install_system_deps
    enable_i2c
    configure_ap_mode

    create_install_dir
    copy_files
    install_python_deps

    create_config

    set_permissions

    install_service

    install_tailscale

    enable_service

    display_status

    log_success "Installation completed successfully!"
}

main "$@"
