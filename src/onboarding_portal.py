"""
Onboarding portal for GrowMate Pods.

Flask web application for device configuration in AP mode.
Provides web interface for WiFi setup and device configuration.
"""

import logging
import threading
from flask import Flask, request, jsonify, render_template
from typing import Dict, Any
from config_manager import ConfigManager
from network_manager import NetworkManager


logger = logging.getLogger("growmate.onboarding")


# Create Flask app
app = Flask(__name__, 
            template_folder='../templates',
            static_folder='../static')


# Global configuration manager
config_manager: ConfigManager = None
network_manager: NetworkManager = None

# Event to signal onboarding completion (matches ESP32 behavior)
onboarding_complete_event = threading.Event()


def init_onboarding(config: Dict):
    """
    Initialize onboarding portal with configuration.
    
    Args:
        config: Configuration dictionary
    """
    global config_manager, network_manager
    config_manager = ConfigManager()
    config_manager.config = config
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
        JSON response with list of networks (matches ESP32 format)
    """
    try:
        networks = network_manager.scan_networks()
        
        # Format for frontend (matches ESP32 format exactly)
        formatted_networks = [
            {
                'ssid': net['ssid'],
                'rssi': net['rssi'],  # Already in dBm from network_manager
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
    
    Expected JSON payload:
    {
        "wifiSsid": "MyNetwork",
        "wifiPassword": "password123"
    }
    
    Returns:
        JSON response with success message
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        wifi_ssid = data.get('wifiSsid', '').strip()
        wifi_password = data.get('wifiPassword', '')
        
        # Validate input
        if not wifi_ssid:
            return jsonify({'error': 'WiFi SSID is required'}), 400
        
        if len(wifi_ssid) > 32:
            return jsonify({'error': 'WiFi SSID too long (max 32 chars)'}), 400
        
        if len(wifi_password) > 64:
            return jsonify({'error': 'WiFi password too long (max 64 chars)'}), 400
        
        # Update configuration
        config_manager.update_from_onboarding(wifi_ssid, wifi_password)
        config_manager.save()
        
        logger.info(f"Configuration saved: SSID={wifi_ssid}")
        
        # Signal onboarding completion (matches ESP32 ONBOARDING_COMPLETE_BIT)
        # The run_onboarding_server() function is waiting on this event
        onboarding_complete_event.set()
        
        logger.info("Onboarding complete event set")
        
        return jsonify({
            'message': 'Configuration saved. Device will continue with the new settings.'
        })
        
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/favicon.ico')
def favicon():
    """
    Serve favicon (location pin icon, matches ESP32).
    
    Returns:
        SVG favicon
    """
    svg = '''<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
    <rect width='64' height='64' rx='14' fill='#111827'/>
    <path d='M32 12c8 0 14 6 14 14 0 11-14 26-14 26S18 37 18 26c0-8 6-14 14-14Z' fill='#22c55e'/>
    <circle cx='32' cy='26' r='6' fill='#0f172a'/>
</svg>'''
    return svg, 200, {'Content-Type': 'image/svg+xml'}


def run_onboarding_server(config: Dict, host: str = '0.0.0.0', port: int = 80):
    """
    Run onboarding web server.
    
    Blocks until configuration is saved (matches ESP32 behavior).
    
    Args:
        config: Configuration dictionary
        host: Host to bind to (default: 0.0.0.0)
        port: Port to bind to (default: 80)
    """
    global onboarding_complete_event
    
    # Reset event
    onboarding_complete_event.clear()
    
    init_onboarding(config)
    
    logger.info(f"Starting onboarding server on {host}:{port}")
    logger.info("Waiting for configuration... (matches ESP32 portMAX_DELAY behavior)")
    
    # Run Flask app in a separate thread
    server_thread = threading.Thread(
        target=lambda: app.run(
            host=host,
            port=port,
            debug=False,
            threaded=True,
            use_reloader=False
        ),
        daemon=True
    )
    server_thread.start()
    
    # Wait for onboarding completion (matches ESP32 xEventGroupWaitBits with portMAX_DELAY)
    onboarding_complete_event.wait()
    
    logger.info("Onboarding complete, configuration saved")
    
    # Give time for the final HTTP response to be sent before continuing
    # The Flask server thread is a daemon thread, so it will be terminated
    # automatically when the main thread continues (matches ESP32 behavior)
    import time
    time.sleep(2)


if __name__ == '__main__':
    # For testing
    from config_manager import ConfigManager
    
    config_mgr = ConfigManager()
    config = config_mgr.get_default_config()
    
    run_onboarding_server(config, port=8080)
