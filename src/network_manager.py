import logging
import subprocess
import time
import asyncio
from typing import List, Dict, Optional
from pathlib import Path


logger = logging.getLogger("growmate.network")


WLAN_INTERFACE = "wlan0"

AP_IP_ADDRESS = "192.168.4.1"
AP_NETMASK = "255.255.255.0"
AP_DHCP_RANGE_START = "192.168.4.2"
AP_DHCP_RANGE_END = "192.168.4.20"
AP_PASSWORD = "growmate"

HOSTAPD_CONF = "/etc/hostapd/hostapd.conf"
HOSTAPD_TEMPLATE = "/opt/growmate/config/hostapd.conf.template"
DNSMASQ_CONF = "/etc/dnsmasq.conf"
DNSMASQ_TEMPLATE = "/opt/growmate/config/dnsmasq.conf.template"
WPA_SUPPLICANT_CONF = "/etc/wpa_supplicant/wpa_supplicant.conf"

WIFI_CONNECT_TIMEOUT = 12
WIFI_CONNECT_RETRIES = 4


class NetworkManager:

    def __init__(self, config: Dict):
        self.config = config
        self.ap_ssid = self._get_ap_ssid()

        nw = config.get('network', {})
        wifi_cfg = nw.get('wifi', {})

        self.wlan_interface = wifi_cfg.get(
            'interface',
            config.get('ap_mode', {}).get('interface', WLAN_INTERFACE)
        )
        self.wifi_connect_timeout = wifi_cfg.get('connect_timeout', WIFI_CONNECT_TIMEOUT)
        self.wifi_connect_retries = wifi_cfg.get('connect_retries', WIFI_CONNECT_RETRIES)

        ap = config.get('ap_mode', {})
        self.ap_password = ap.get('password', AP_PASSWORD)
        self.ap_ip = ap.get('ip_address', AP_IP_ADDRESS)
        self.ap_netmask = ap.get('netmask', AP_NETMASK)
        self.ap_dhcp_start = ap.get('dhcp_range_start', AP_DHCP_RANGE_START)
        self.ap_dhcp_end = ap.get('dhcp_range_end', AP_DHCP_RANGE_END)
        self.ap_channel = ap.get('channel', 1)

    def _get_ap_ssid(self) -> str:
        ap_cfg = self.config.get('ap_mode', {})
        explicit = ap_cfg.get('ssid')
        if explicit:
            return explicit
        from utils import get_ap_ssid
        return get_ap_ssid()

    def _run_command(self, command: List[str], check: bool = True) -> subprocess.CompletedProcess:
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

    async def scan_networks(self) -> List[Dict]:
        try:
            result = await asyncio.to_thread(
                self._run_command,
                ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list']
            )

            networks = []
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue

                parts = line.split(':')
                if len(parts) >= 2:
                    ssid = parts[0]
                    signal_percent = int(parts[1]) if parts[1].isdigit() else 0
                    security = parts[2] if len(parts) > 2 else ''

                    rssi = int(-100 + (signal_percent * 0.7))

                    if ssid:
                        networks.append({
                            'ssid': ssid,
                            'rssi': rssi,
                            'security': security
                        })

            logger.info(f"Found {len(networks)} WiFi networks")
            return networks

        except Exception as e:
            logger.error(f"Failed to scan networks: {e}")
            return []

    def _generate_dnsmasq_conf(self) -> bool:
        try:
            template_path = Path(DNSMASQ_TEMPLATE)
            if not template_path.exists():
                template_path = Path(__file__).parent.parent / "config" / "dnsmasq.conf.template"

            if not template_path.exists():
                logger.error(f"dnsmasq template not found: {template_path}")
                return False

            template_content = template_path.read_text()
            conf_path = Path(DNSMASQ_CONF)
            conf_path.write_text(template_content)

            logger.info("Generated dnsmasq.conf")
            return True

        except Exception as e:
            logger.error(f"Failed to generate dnsmasq.conf: {e}")
            return False

    def _generate_hostapd_conf(self) -> bool:
        try:
            template_path = Path(HOSTAPD_TEMPLATE)
            if not template_path.exists():
                template_path = Path(__file__).parent.parent / "config" / "hostapd.conf.template"

            if not template_path.exists():
                logger.error(f"hostapd template not found: {template_path}")
                return False

            template_content = template_path.read_text()

            config_content = template_content.replace('{SSID}', self.ap_ssid)
            config_content = config_content.replace('{PASSWORD}', self.ap_password)
            config_content = config_content.replace('{CHANNEL}', str(self.ap_channel))

            conf_path = Path(HOSTAPD_CONF)
            conf_path.write_text(config_content)

            logger.info(f"Generated hostapd.conf with SSID: {self.ap_ssid}")
            return True

        except Exception as e:
            logger.error(f"Failed to generate hostapd.conf: {e}")
            return False

    async def start_ap_mode(self) -> bool:
        try:
            logger.info(f"Starting AP mode: {self.ap_ssid}")

            if not await asyncio.to_thread(self._generate_hostapd_conf):
                logger.error("Failed to generate hostapd configuration")
                return False

            if not await asyncio.to_thread(self._generate_dnsmasq_conf):
                logger.error("Failed to generate dnsmasq configuration")
                return False

            await asyncio.to_thread(self._run_command, ['systemctl', 'stop', 'wpa_supplicant'], check=False)
            await asyncio.to_thread(self._run_command, ['systemctl', 'stop', 'NetworkManager'], check=False)

            await asyncio.to_thread(self._run_command, ['ip', 'link', 'set', self.wlan_interface, 'down'])
            await asyncio.to_thread(self._run_command, ['ip', 'addr', 'flush', 'dev', self.wlan_interface])
            cidr = 24
            if self.ap_netmask:
                try:
                    import ipaddress
                    cidr = ipaddress.IPv4Network(f'0.0.0.0/{self.ap_netmask}').prefixlen
                except Exception:
                    cidr = 24
            await asyncio.to_thread(self._run_command, ['ip', 'addr', 'add', f'{self.ap_ip}/{cidr}', 'dev', self.wlan_interface])
            await asyncio.to_thread(self._run_command, ['ip', 'link', 'set', self.wlan_interface, 'up'])

            await asyncio.to_thread(self._run_command, ['systemctl', 'start', 'hostapd'])
            await asyncio.to_thread(self._run_command, ['systemctl', 'start', 'dnsmasq'])

            logger.info(f"AP mode started: {self.ap_ssid} @ {self.ap_ip}")
            return True

        except Exception as e:
            logger.error(f"Failed to start AP mode: {e}")
            return False

    async def stop_ap_mode(self) -> bool:
        try:
            logger.info("Stopping AP mode")

            await asyncio.to_thread(self._run_command, ['systemctl', 'stop', 'hostapd'], check=False)
            await asyncio.to_thread(self._run_command, ['systemctl', 'stop', 'dnsmasq'], check=False)

            await asyncio.to_thread(self._run_command, ['systemctl', 'start', 'NetworkManager'], check=False)

            logger.info("AP mode stopped")
            return True

        except Exception as e:
            logger.error(f"Failed to stop AP mode: {e}")
            return False

    async def connect_to_wifi(self, ssid: str, password: str) -> bool:
        try:
            logger.info(f"Connecting to WiFi: {ssid}")

            await self.stop_ap_mode()

            for attempt in range(self.wifi_connect_retries):
                result = await asyncio.to_thread(
                    self._run_command,
                    ['nmcli', 'device', 'wifi', 'connect', ssid, 'password', password],
                    check=False
                )

                if result.returncode == 0:
                    logger.info(f"Connected to WiFi: {ssid}")
                    return True

                if attempt < self.wifi_connect_retries - 1:
                    logger.warning(
                        f"WiFi connection attempt {attempt + 1} failed, "
                        f"retrying in {self.wifi_connect_timeout}s..."
                    )
                    await asyncio.sleep(self.wifi_connect_timeout)

            logger.error(f"Failed to connect to WiFi after {self.wifi_connect_retries} attempts: {ssid}")
            return False

        except Exception as e:
            logger.error(f"WiFi connection error: {e}")
            return False

    async def is_connected(self) -> bool:
        try:
            result = await asyncio.to_thread(
                self._run_command,
                ['nmcli', '-t', '-f', 'STATE', 'general'],
                check=False
            )

            state = result.stdout.strip()
            connected = 'connected' in state.lower()

            return connected

        except Exception as e:
            logger.error(f"Failed to check connection status: {e}")
            return False

    async def get_ip_address(self) -> Optional[str]:
        try:
            result = await asyncio.to_thread(
                self._run_command,
                ['ip', '-4', 'addr', 'show', self.wlan_interface],
                check=False
            )

            for line in result.stdout.split('\n'):
                if 'inet ' in line:
                    ip = line.strip().split()[1].split('/')[0]
                    return ip

            return None

        except Exception as e:
            logger.error(f"Failed to get IP address: {e}")
            return None


async def start_ap(config: Dict) -> bool:
    manager = NetworkManager(config)
    return await manager.start_ap_mode()


async def stop_ap(config: Dict) -> bool:
    manager = NetworkManager(config)
    return await manager.stop_ap_mode()


async def connect_wifi(config: Dict, ssid: str, password: str) -> bool:
    manager = NetworkManager(config)
    return await manager.connect_to_wifi(ssid, password)


async def check_connection(config: Dict) -> bool:
    manager = NetworkManager(config)
    return await manager.is_connected()
