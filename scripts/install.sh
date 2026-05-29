#!/bin/bash
#
# GrowMate Pods - Automated Installation Script
# For Raspberry Pi Zero W with Raspberry Pi OS
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Installation paths
INSTALL_DIR="/opt/growmate"
CONFIG_DIR="/etc/growmate"
SERVICE_FILE="/etc/systemd/system/growmate.service"

echo "============================================================"
echo "GrowMate Pods - Installation Script"
echo "============================================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Error: This script must be run as root${NC}"
    echo "Please run: sudo $0"
    exit 1
fi

echo -e "${GREEN}[1/10] Checking system...${NC}"
if [ ! -f /etc/os-release ]; then
    echo -e "${RED}Error: Cannot detect OS${NC}"
    exit 1
fi

# Check if Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo; then
    echo -e "${YELLOW}Warning: This doesn't appear to be a Raspberry Pi${NC}"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo -e "${GREEN}[2/10] Updating system packages...${NC}"
apt update
apt upgrade -y

echo -e "${GREEN}[3/10] Installing system dependencies...${NC}"
apt install -y \
    python3 \
    python3-pip \
    python3-dev \
    i2c-tools \
    libgpiod2 \
    libcamera-apps \
    hostapd \
    dnsmasq \
    git

echo -e "${GREEN}[4/10] Enabling I2C interface...${NC}"
if ! grep -q "^dtparam=i2c_arm=on" /boot/config.txt; then
    echo "dtparam=i2c_arm=on" >> /boot/config.txt
    echo "I2C enabled (reboot required)"
else
    echo "I2C already enabled"
fi

# Load I2C module now
modprobe i2c-dev || true

echo -e "${GREEN}[5/10] Enabling Camera interface...${NC}"
if ! grep -q "^start_x=1" /boot/config.txt; then
    echo "start_x=1" >> /boot/config.txt
    echo "gpu_mem=128" >> /boot/config.txt
    echo "Camera enabled (reboot required)"
else
    echo "Camera already enabled"
fi

echo -e "${GREEN}[6/10] Installing Python dependencies...${NC}"
pip3 install --upgrade pip
pip3 install -r requirements.txt

echo -e "${GREEN}[7/10] Creating installation directory...${NC}"
mkdir -p "$INSTALL_DIR"
cp -r src templates static config systemd scripts "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/scripts/"*.py
chmod +x "$INSTALL_DIR/src/main.py"

echo -e "${GREEN}[8/10] Creating configuration directory...${NC}"
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    cp config/config.yaml.example "$CONFIG_DIR/config.yaml"
    echo "Created default configuration"
else
    echo "Configuration file already exists"
fi

# Set permissions
chown -R root:root "$INSTALL_DIR"
chown -R root:root "$CONFIG_DIR"
chmod 600 "$CONFIG_DIR/config.yaml"

echo -e "${GREEN}[9/10] Installing systemd service...${NC}"
cp systemd/growmate.service "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable growmate.service

# Configure hostapd and dnsmasq
echo -e "${GREEN}[10/10] Configuring network services...${NC}"

# Stop and disable services (will be started by application when needed)
systemctl stop hostapd || true
systemctl stop dnsmasq || true
systemctl disable hostapd || true
systemctl disable dnsmasq || true

# Copy configuration templates
cp config/hostapd.conf.template /etc/hostapd/hostapd.conf
cp config/dnsmasq.conf.template /etc/dnsmasq.conf

# Update hostapd default config path
if [ -f /etc/default/hostapd ]; then
    sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd
fi

echo ""
echo "============================================================"
echo -e "${GREEN}Installation Complete!${NC}"
echo "============================================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Test hardware (optional):"
echo "   sudo python3 $INSTALL_DIR/scripts/test_hardware.py"
echo ""
echo "2. Reboot to enable I2C and Camera:"
echo "   sudo reboot"
echo ""
echo "3. After reboot, start the service:"
echo "   sudo systemctl start growmate"
echo ""
echo "4. Check service status:"
echo "   sudo systemctl status growmate"
echo ""
echo "5. View logs:"
echo "   sudo journalctl -u growmate -f"
echo ""
echo "6. On first boot, device will enter AP mode:"
echo "   - Connect to WiFi: GrowMate-XXXXXX"
echo "   - Password: growmate"
echo "   - Open browser: http://192.168.4.1"
echo "   - Configure WiFi and device settings"
echo ""
echo "============================================================"
