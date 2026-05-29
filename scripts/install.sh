#!/bin/bash
#
# GrowMate Pods - Automated Installation Script
# Raspberry Pi Zero W Installation
#
# This script installs the GrowMate plant monitoring system on a fresh
# Raspberry Pi OS installation. It handles all dependencies, system
# configuration, and service setup.
#
# Usage:
#   sudo ./install.sh
#
# Or remote installation:
#   curl -sSL https://raw.githubusercontent.com/USER/rpi-growmate-pods/main/scripts/install.sh | sudo bash
#

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Installation paths
INSTALL_DIR="/opt/growmate"
CONFIG_DIR="/etc/growmate"
SERVICE_FILE="/etc/systemd/system/growmate.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Error handler
error_exit() {
    log_error "$1"
    exit 1
}

# Print banner
print_banner() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║                                                            ║"
    echo "║              GrowMate Pods - Installation                  ║"
    echo "║          Raspberry Pi Zero W Plant Monitoring              ║"
    echo "║                                                            ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
}

# Check if running as root
check_root() {
    log_info "Checking root privileges..."
    if [ "$EUID" -ne 0 ]; then
        error_exit "This script must be run as root. Use: sudo ./install.sh"
    fi
    log_success "Running as root"
}

# Check if running on Raspberry Pi
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

# Update system packages
update_system() {
    log_info "Updating system packages..."
    apt-get update -qq || error_exit "Failed to update package lists"
    log_success "System package lists updated"
}

# Install system dependencies
install_system_deps() {
    log_info "Installing system dependencies..."
    
    PACKAGES=(
        # Python
        python3
        python3-pip
        python3-dev
        python3-venv
        
        # I2C tools
        i2c-tools
        
        # GPIO libraries
        libgpiod2
        python3-libgpiod
        
        # Camera support
        libcamera-apps
        python3-libcamera
        python3-picamera2
        
        # Network tools for AP mode
        hostapd
        dnsmasq
        
        # Build tools (for some Python packages)
        build-essential
        
        # System utilities
        git
        curl
    )
    
    log_info "Installing: ${PACKAGES[*]}"
    apt-get install -y -qq "${PACKAGES[@]}" || error_exit "Failed to install system dependencies"
    log_success "System dependencies installed"
}

# Enable I2C interface
enable_i2c() {
    log_info "Enabling I2C interface..."
    
    # Check if I2C is already enabled
    if lsmod | grep -q i2c_bcm2835; then
        log_success "I2C already enabled"
        return
    fi
    
    # Enable I2C using raspi-config non-interactive mode
    raspi-config nonint do_i2c 0 || log_warning "Failed to enable I2C via raspi-config"
    
    # Ensure I2C modules are loaded
    if ! grep -q "^i2c-dev" /etc/modules; then
        echo "i2c-dev" >> /etc/modules
    fi
    if ! grep -q "^i2c-bcm2835" /etc/modules; then
        echo "i2c-bcm2835" >> /etc/modules
    fi
    
    # Load I2C modules immediately
    modprobe i2c-dev 2>/dev/null || true
    modprobe i2c-bcm2835 2>/dev/null || true
    
    log_success "I2C interface enabled"
}

# Enable Camera interface
enable_camera() {
    log_info "Enabling Camera interface..."
    
    # Enable camera using raspi-config non-interactive mode
    raspi-config nonint do_camera 0 || log_warning "Failed to enable camera via raspi-config"
    
    # For newer Raspberry Pi OS (Bullseye+), camera is enabled by default with libcamera
    log_success "Camera interface enabled"
}

# Create installation directory
create_install_dir() {
    log_info "Creating installation directory: $INSTALL_DIR"
    
    # Backup existing installation if present
    if [ -d "$INSTALL_DIR" ]; then
        BACKUP_DIR="${INSTALL_DIR}.backup.$(date +%Y%m%d_%H%M%S)"
        log_warning "Existing installation found. Backing up to: $BACKUP_DIR"
        mv "$INSTALL_DIR" "$BACKUP_DIR"
    fi
    
    mkdir -p "$INSTALL_DIR"
    log_success "Installation directory created"
}

# Copy project files
copy_files() {
    log_info "Copying project files to $INSTALL_DIR..."
    
    # Copy source files
    cp -r "$PROJECT_ROOT/src" "$INSTALL_DIR/" || error_exit "Failed to copy src/"
    cp -r "$PROJECT_ROOT/templates" "$INSTALL_DIR/" || error_exit "Failed to copy templates/"
    cp -r "$PROJECT_ROOT/static" "$INSTALL_DIR/" || error_exit "Failed to copy static/"
    cp -r "$PROJECT_ROOT/config" "$INSTALL_DIR/" || error_exit "Failed to copy config/"
    cp "$PROJECT_ROOT/requirements.txt" "$INSTALL_DIR/" || error_exit "Failed to copy requirements.txt"
    
    # Copy documentation
    [ -f "$PROJECT_ROOT/README.md" ] && cp "$PROJECT_ROOT/README.md" "$INSTALL_DIR/"
    [ -f "$PROJECT_ROOT/WIRING.md" ] && cp "$PROJECT_ROOT/WIRING.md" "$INSTALL_DIR/"
    
    log_success "Project files copied"
}

# Install Python dependencies
install_python_deps() {
    log_info "Installing Python dependencies..."
    
    # Install dependencies system-wide (service runs as root)
    pip3 install --upgrade pip -q || log_warning "Failed to upgrade pip"
    pip3 install -r "$INSTALL_DIR/requirements.txt" -q || error_exit "Failed to install Python dependencies"
    
    log_success "Python dependencies installed"
}

# Create configuration directory
create_config_dir() {
    log_info "Creating configuration directory: $CONFIG_DIR"
    
    mkdir -p "$CONFIG_DIR"
    chmod 755 "$CONFIG_DIR"
    
    # Copy example configuration if it doesn't exist
    if [ ! -f "$CONFIG_DIR/config.yaml" ] && [ -f "$INSTALL_DIR/config/config.yaml.example" ]; then
        log_info "Creating example configuration file"
        cp "$INSTALL_DIR/config/config.yaml.example" "$CONFIG_DIR/config.yaml.example"
    fi
    
    log_success "Configuration directory created"
}

# Install systemd service
install_service() {
    log_info "Installing systemd service..."
    
    # Stop service if already running
    if systemctl is-active --quiet growmate; then
        log_info "Stopping existing service..."
        systemctl stop growmate
    fi
    
    # Copy service file
    cp "$PROJECT_ROOT/systemd/growmate.service" "$SERVICE_FILE" || error_exit "Failed to copy service file"
    
    # Reload systemd daemon
    systemctl daemon-reload || error_exit "Failed to reload systemd daemon"
    
    log_success "Systemd service installed"
}

# Enable and start service
enable_service() {
    log_info "Enabling service to start on boot..."
    systemctl enable growmate || error_exit "Failed to enable service"
    log_success "Service enabled"
    
    log_info "Starting GrowMate service..."
    systemctl start growmate || error_exit "Failed to start service"
    log_success "Service started"
}

# Configure hostapd and dnsmasq
configure_ap_mode() {
    log_info "Configuring AP mode support..."
    
    # Stop services (they will be managed by the application)
    systemctl stop hostapd 2>/dev/null || true
    systemctl stop dnsmasq 2>/dev/null || true
    
    # Disable auto-start (application will start them when needed)
    systemctl disable hostapd 2>/dev/null || true
    systemctl disable dnsmasq 2>/dev/null || true
    
    # Unmask hostapd (it's masked by default on some systems)
    systemctl unmask hostapd 2>/dev/null || true
    
    log_success "AP mode support configured"
}

# Set file permissions
set_permissions() {
    log_info "Setting file permissions..."
    
    # Installation directory
    chown -R root:root "$INSTALL_DIR"
    chmod -R 755 "$INSTALL_DIR"
    
    # Make Python files executable
    chmod +x "$INSTALL_DIR/src/main.py"
    
    # Configuration directory
    chown -R root:root "$CONFIG_DIR"
    chmod 755 "$CONFIG_DIR"
    
    log_success "Permissions set"
}

# Display status and next steps
display_status() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║                                                            ║"
    echo "║              Installation Complete!                        ║"
    echo "║                                                            ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
    
    log_info "Service Status:"
    systemctl status growmate --no-pager -l || true
    
    echo ""
    log_info "Installation Summary:"
    echo "  • Installation directory: $INSTALL_DIR"
    echo "  • Configuration directory: $CONFIG_DIR"
    echo "  • Service file: $SERVICE_FILE"
    echo "  • Service status: $(systemctl is-active growmate)"
    echo "  • Auto-start on boot: $(systemctl is-enabled growmate)"
    echo ""
    
    log_info "Next Steps:"
    echo ""
    echo "  1. The GrowMate service is now running"
    echo ""
    echo "  2. If this is the first boot (no configuration):"
    echo "     • The device will enter AP mode automatically"
    echo "     • Connect to WiFi network: GrowMate-XXXXXX"
    echo "     • Password: growmate"
    echo "     • Open browser: http://192.168.4.1"
    echo "     • Configure WiFi, device ID, and API settings"
    echo ""
    echo "  3. If already configured:"
    echo "     • The device will connect to your WiFi"
    echo "     • Start monitoring and uploading data"
    echo ""
    echo "  4. Useful Commands:"
    echo "     • View logs:        journalctl -u growmate -f"
    echo "     • Service status:   systemctl status growmate"
    echo "     • Restart service:  systemctl restart growmate"
    echo "     • Stop service:     systemctl stop growmate"
    echo "     • Disable service:  systemctl disable growmate"
    echo ""
    echo "  5. Configuration file: $CONFIG_DIR/config.yaml"
    echo "     • Edit manually if needed"
    echo "     • Restart service after changes"
    echo ""
    
    # Check if reboot is needed
    if [ ! -e /dev/i2c-1 ] || ! lsmod | grep -q i2c_bcm2835; then
        log_warning "A reboot is recommended to ensure I2C and Camera are fully enabled"
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

# Main installation flow
main() {
    print_banner
    
    log_info "Starting installation..."
    echo ""
    
    # Pre-installation checks
    check_root
    check_platform
    
    # System setup
    update_system
    install_system_deps
    enable_i2c
    enable_camera
    configure_ap_mode
    
    # Application installation
    create_install_dir
    copy_files
    install_python_deps
    create_config_dir
    set_permissions
    
    # Service setup
    install_service
    enable_service
    
    # Completion
    display_status
    
    log_success "Installation completed successfully!"
}

# Run main installation
main "$@"
