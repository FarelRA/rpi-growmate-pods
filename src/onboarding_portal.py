"""
Onboarding portal for GrowMate Pods.

Flask web application for device configuration in AP mode.
Provides web interface for WiFi setup and device configuration.
"""

import logging
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
        JSON response with list of networks
    """
    try:
        networks = network_manager.scan_networks()
        
        # Format for frontend (matches ESP32 format)
        formatted_networks = [
            {
                'ssid': net['ssid'],
                'rssi': net['signal'],
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
        
        return jsonify({
            'message': 'Configuration saved. Device will continue with the new settings.'
        })
        
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/favicon.ico')
def favicon():
    """
    Serve favicon (simple SVG).
    
    Returns:
        SVG favicon
    """
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="40" fill="#4CAF50"/>
        <path d="M50 30 L50 70 M30 50 L70 50" stroke="white" stroke-width="8"/>
    </svg>'''
    return svg, 200, {'Content-Type': 'image/svg+xml'}


def run_onboarding_server(config: Dict, host: str = '0.0.0.0', port: int = 80):
    """
    Run onboarding web server.
    
    Args:
        config: Configuration dictionary
        host: Host to bind to (default: 0.0.0.0)
        port: Port to bind to (default: 80)
    """
    init_onboarding(config)
    
    logger.info(f"Starting onboarding server on {host}:{port}")
    
    # Run Flask app
    app.run(
        host=host,
        port=port,
        debug=False,
        threaded=True
    )


if __name__ == '__main__':
    # For testing
    from config_manager import ConfigManager
    
    config_mgr = ConfigManager()
    config = config_mgr.get_default_config()
    
    run_onboarding_server(config, port=8080)
