"""
Network management for GrowMate Pods.

Handles WiFi connectivity:
- AP mode (Access Point) for onboarding
- Client mode (Station) for normal operation
- Network scanning and status checking
"""

import logging
import subprocess
import time
from typing import List, Dict, Optional
from pathlib import Path


logger = logging.getLogger("growmate.network")


# Network interface
WLAN_INTERFACE = "wlan0"

# AP mode configuration
AP_IP_ADDRESS = "192.168.4.1"
AP_NETMASK = "255.255.255.0"
AP_DHCP_RANGE_START = "192.168.4.2"
AP_DHCP_RANGE_END = "192.168.4.20"
AP_PASSWORD = "growmate"

# Configuration file paths
HOSTAPD_CONF = "/etc/hostapd/hostapd.conf"
DNSMASQ_CONF = "/etc/dnsmasq.conf"
WPA_SUPPLICANT_CONF = "/etc/wpa_supplicant/wpa_supplicant.conf"

# Timeouts
WIFI_CONNECT_TIMEOUT = 12  # seconds (from ESP32)
WIFI_CONNECT_RETRIES = 4


class NetworkManager:
    """Manages WiFi network connectivity and AP mode."""
    
    def __init__(self, config: Dict):
        """
        Initialize network manager.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.ap_ssid = self._get_ap_ssid()
    
    def _get_ap_ssid(self) -> str:
        """
        Generate AP SSID from device ID.
        
        Format: "GrowMate-XXXXXX" (last 6 chars)
        
        Returns:
            AP SSID string
        """
        from utils import get_ap_ssid
        return get_ap_ssid()
    
    def _run_command(self, command: List[str], check: bool = True) -> subprocess.CompletedProcess:
        """
        Run shell command.
        
        Args:
            command: Command and arguments as list
            check: Raise exception on non-zero exit code
            
        Returns:
            CompletedProcess instance
        """
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=check
            )
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {' '.join(command)}")
            logger.error(f"Error: {e.stderr}")
            raise
    
    def scan_networks(self) -> List[Dict]:
        """
        Scan for available WiFi networks.
        
        Returns:
            List of network dictionaries with ssid, signal, security
        """
        try:
            # Use nmcli to scan networks
            result = self._run_command([
                'nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY',
                'device', 'wifi', 'list'
            ])
            
            networks = []
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                
                parts = line.split(':')
                if len(parts) >= 2:
                    ssid = parts[0]
                    signal = int(parts[1]) if parts[1].isdigit() else 0
                    security = parts[2] if len(parts) > 2 else ''
                    
                    if ssid:  # Skip empty SSIDs
                        networks.append({
                            'ssid': ssid,
                            'signal': signal,
                            'security': security
                        })
            
            logger.info(f"Found {len(networks)} WiFi networks")
            return networks
            
        except Exception as e:
            logger.error(f"Failed to scan networks: {e}")
            return []
    
    def start_ap_mode(self) -> bool:
        """
        Start Access Point mode for onboarding.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Starting AP mode: {self.ap_ssid}")
            
            # Stop any existing network services
            self._run_command(['systemctl', 'stop', 'wpa_supplicant'], check=False)
            
            # Configure network interface
            self._run_command(['ip', 'link', 'set', WLAN_INTERFACE, 'down'])
            self._run_command(['ip', 'addr', 'flush', 'dev', WLAN_INTERFACE])
            self._run_command(['ip', 'addr', 'add', f'{AP_IP_ADDRESS}/24', 'dev', WLAN_INTERFACE])
            self._run_command(['ip', 'link', 'set', WLAN_INTERFACE, 'up'])
            
            # Start hostapd (AP mode)
            self._run_command(['systemctl', 'start', 'hostapd'])
            
            # Start dnsmasq (DHCP/DNS)
            self._run_command(['systemctl', 'start', 'dnsmasq'])
            
            logger.info(f"AP mode started: {self.ap_ssid} @ {AP_IP_ADDRESS}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start AP mode: {e}")
            return False
    
    def stop_ap_mode(self) -> bool:
        """
        Stop Access Point mode.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Stopping AP mode")
            
            # Stop services
            self._run_command(['systemctl', 'stop', 'hostapd'], check=False)
            self._run_command(['systemctl', 'stop', 'dnsmasq'], check=False)
            
            # Reset network interface
            self._run_command(['ip', 'link', 'set', WLAN_INTERFACE, 'down'], check=False)
            self._run_command(['ip', 'addr', 'flush', 'dev', WLAN_INTERFACE], check=False)
            
            logger.info("AP mode stopped")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop AP mode: {e}")
            return False
    
    def connect_to_wifi(self, ssid: str, password: str) -> bool:
        """
        Connect to WiFi network in client mode.
        
        Args:
            ssid: WiFi network SSID
            password: WiFi network password
            
        Returns:
            True if connected, False otherwise
        """
        try:
            logger.info(f"Connecting to WiFi: {ssid}")
            
            # Stop AP mode if running
            self.stop_ap_mode()
            
            # Use nmcli to connect
            result = self._run_command([
                'nmcli', 'device', 'wifi', 'connect', ssid,
                'password', password
            ], check=False)
            
            if result.returncode == 0:
                logger.info(f"Connected to WiFi: {ssid}")
                return True
            else:
                logger.error(f"Failed to connect to WiFi: {result.stderr}")
                return False
            
        except Exception as e:
            logger.error(f"WiFi connection error: {e}")
            return False
    
    def is_connected(self) -> bool:
        """
        Check if connected to WiFi.
        
        Returns:
            True if connected, False otherwise
        """
        try:
            result = self._run_command([
                'nmcli', '-t', '-f', 'STATE', 'general'
            ], check=False)
            
            state = result.stdout.strip()
            connected = 'connected' in state.lower()
            
            return connected
            
        except Exception as e:
            logger.error(f"Failed to check connection status: {e}")
            return False
    
    def get_ip_address(self) -> Optional[str]:
        """
        Get current IP address.
        
        Returns:
            IP address string or None
        """
        try:
            result = self._run_command([
                'ip', '-4', 'addr', 'show', WLAN_INTERFACE
            ], check=False)
            
            # Parse IP address from output
            for line in result.stdout.split('\n'):
                if 'inet ' in line:
                    ip = line.strip().split()[1].split('/')[0]
                    return ip
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get IP address: {e}")
            return None


# Convenience functions
def start_ap(config: Dict) -> bool:
    """Start AP mode."""
    manager = NetworkManager(config)
    return manager.start_ap_mode()


def stop_ap(config: Dict) -> bool:
    """Stop AP mode."""
    manager = NetworkManager(config)
    return manager.stop_ap_mode()


def connect_wifi(config: Dict, ssid: str, password: str) -> bool:
    """Connect to WiFi network."""
    manager = NetworkManager(config)
    return manager.connect_to_wifi(ssid, password)


def check_connection(config: Dict) -> bool:
    """Check if connected to WiFi."""
    manager = NetworkManager(config)
    return manager.is_connected()
