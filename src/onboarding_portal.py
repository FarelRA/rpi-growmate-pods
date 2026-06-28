"""
Onboarding portal for GrowMate Pods - WiFi setup web interface.

Flask web application for device configuration in AP mode.
Provides web interface for WiFi scanning, credential entry,
and device configuration.

Features:
- WiFi scan via /api/networks for user-friendly network selection
- WiFi credentials entry (SSID + password)
- Works without JavaScript (native form fallback)
- Enhanced with AJAX when JavaScript is available
- Shuts down gracefully after successful configuration
"""

import logging
from flask import Flask, request, jsonify, render_template
from typing import Dict, Optional
from config_manager import ConfigManager
from network_manager import NetworkManager


logger = logging.getLogger("growmate.onboarding")


# Create Flask app
app = Flask(__name__, 
            template_folder='../templates',
            static_folder='../static')


# Global instances (initialized via init_onboarding)
config_manager: ConfigManager = None
network_manager: NetworkManager = None

# Callback to notify main application when onboarding is complete
onboarding_complete_callback: Optional[callable] = None


def init_onboarding(config: Dict, network_mgr: Optional[NetworkManager] = None):
    """
    Initialize onboarding portal with configuration.

    Args:
        config: Configuration dictionary
        network_mgr: Optional pre-created NetworkManager instance
    """
    global config_manager, network_manager
    config_manager = ConfigManager()
    config_manager.config = config
    if network_mgr:
        network_manager = network_mgr
    else:
        network_manager = NetworkManager(config)
    logger.info("Onboarding portal initialized")


@app.route('/')
def index():
    """
    Main onboarding page.

    Returns:
        Rendered HTML template
    """
    return render_template('index.html')


@app.route('/api/config', methods=['GET'])
def get_config():
    """
    Get current device configuration.

    Returns:
        JSON response with device ID and WiFi SSID
    """
    try:
        device_id = config_manager.get('device.id', 'unknown')
        wifi_ssid = config_manager.get('network.wifi_ssid', '')

        return jsonify({
            'deviceId': device_id,
            'wifiSsid': wifi_ssid
        })
    except Exception as e:
        logger.error(f"Failed to get config: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/networks', methods=['GET'])
def scan_networks():
    """
    Scan for available WiFi networks.

    Returns:
        JSON response with list of networks
    """
    try:
        import asyncio
        networks = asyncio.run(network_manager.scan_networks())

        formatted_networks = [
            {
                'ssid': net['ssid'],
                'rssi': net['rssi'],
                'authMode': 3 if net.get('security') else 0
            }
            for net in networks
        ]

        return jsonify({
            'networks': formatted_networks
        })
    except Exception as e:
        logger.error(f"Failed to scan networks: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/config', methods=['POST'])
def save_config():
    """
    Save WiFi configuration from onboarding form.

    Supports both JSON (AJAX) and form data (native form submission).

    Expected payload:
    {
        "wifiSsid": "MyNetwork",
        "wifiPassword": "password123"
    }

    Returns:
        JSON response for AJAX requests, redirect for form submissions
    """
    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()

        if not data:
            if request.is_json:
                return jsonify({'error': 'No data provided'}), 400
            return "No data provided", 400

        wifi_ssid = data.get('wifiSsid', '').strip()
        wifi_password = data.get('wifiPassword', '')

        if not wifi_ssid:
            error_msg = 'WiFi SSID is required'
            if request.is_json:
                return jsonify({'error': error_msg}), 400
            return error_msg, 400

        if len(wifi_ssid) > 32:
            error_msg = 'WiFi SSID too long (max 32 chars)'
            if request.is_json:
                return jsonify({'error': error_msg}), 400
            return error_msg, 400

        if len(wifi_password) > 64:
            error_msg = 'WiFi password too long (max 64 chars)'
            if request.is_json:
                return jsonify({'error': error_msg}), 400
            return error_msg, 400

        config_manager.update_from_onboarding(wifi_ssid, wifi_password)
        config_manager.save()

        logger.info(f"WiFi configuration saved: SSID={wifi_ssid}")
        logger.info("Onboarding complete, device will connect to WiFi")

        if onboarding_complete_callback:
            onboarding_complete_callback()

        _shutdown_server()

        if request.is_json:
            return jsonify({
                'message': 'Configuration saved. Device will connect to your WiFi network.'
            })
        else:
            return render_template('success.html')

    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        if request.is_json:
            return jsonify({'error': str(e)}), 500
        return f"Error: {str(e)}", 500


def _shutdown_server():
    """Shutdown Flask server gracefully."""
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        logger.warning("Not running with Werkzeug server, cannot shutdown gracefully")
    else:
        func()


@app.route('/favicon.ico')
def favicon():
    """
    Serve favicon (location pin icon).

    Returns:
        SVG favicon
    """
    svg = '''<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
    <rect width='64' height='64' rx='14' fill='#111827'/>
    <path d='M32 12c8 0 14 6 14 14 0 11-14 26-14 26S18 37 18 26c0-8 6-14 14-14Z' fill='#22c55e'/>
    <circle cx='32' cy='26' r='6' fill='#0f172a'/>
</svg>'''
    return svg, 200, {'Content-Type': 'image/svg+xml'}


def run_onboarding_server(
    config: Dict,
    host: str = '0.0.0.0',
    port: int = 80,
    callback: Optional[callable] = None,
    network_mgr: Optional[NetworkManager] = None,
):
    """
    Run onboarding web server.

    Blocks until configuration is saved, then returns control to caller.

    Args:
        config: Configuration dictionary
        host: Host to bind to (default: 0.0.0.0)
        port: Port to bind to (default: 80)
        callback: Optional callback to call when onboarding is complete
        network_mgr: Optional pre-created NetworkManager instance
    """
    global onboarding_complete_callback

    onboarding_complete_callback = callback

    init_onboarding(config, network_mgr)

    logger.info(f"Starting onboarding server on {host}:{port}")
    logger.info(f"Connect to http://{host} and enter WiFi credentials")

    app.run(
        host=host,
        port=port,
        debug=False,
        threaded=True,
        use_reloader=False,
    )

    logger.info("Onboarding server stopped, WiFi configuration saved")


if __name__ == '__main__':
    from config_manager import ConfigManager

    config_mgr = ConfigManager()
    config = config_mgr.get_default_config()

    run_onboarding_server(config, port=8080)
