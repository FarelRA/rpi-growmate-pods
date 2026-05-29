"""
Onboarding portal for GrowMate Pods - Minimal Web Interface.

Simplified Flask web application for WiFi credentials only.
Provides minimal web interface for WiFi setup in AP mode.

Features:
- WiFi credentials only (SSID + password) - user knows their network name
- Simple blocking Flask server for reliability
- Clean, minimal design
- Progressive enhancement: works without JavaScript, enhanced with AJAX
- Shuts down automatically after successful configuration
"""

import logging
from flask import Flask, request, jsonify, render_template, redirect
from typing import Dict, Optional
from config_manager import ConfigManager


logger = logging.getLogger("growmate.onboarding")


# Create Flask app
app = Flask(__name__, 
            template_folder='../templates',
            static_folder='../static')


# Global configuration manager
config_manager: ConfigManager = None

# Callback to notify main application when onboarding is complete
onboarding_complete_callback: Optional[callable] = None


def init_onboarding(config: Dict):
    """
    Initialize onboarding portal with configuration.
    
    Args:
        config: Configuration dictionary
    """
    global config_manager
    config_manager = ConfigManager()
    config_manager.config = config
    logger.info("Onboarding portal initialized (Minimal WiFi setup)")


@app.route('/')
def index():
    """
    Main onboarding page.
    
    Returns:
        Rendered HTML template
    """
    return render_template('index.html')


@app.route('/api/config', methods=['POST'])
def save_config():
    """
    Save WiFi configuration from onboarding form.
    
    Simplified to WiFi credentials only (SSID + password).
    Supports both JSON (AJAX) and form data (native form submission).
    
    Expected JSON payload or form data:
    {
        "wifiSsid": "MyNetwork",
        "wifiPassword": "password123"
    }
    
    Returns:
        JSON response for AJAX requests, redirect for form submissions
    """
    try:
        # Support both JSON (AJAX) and form data (native form submission)
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
        
        # Validate input
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
        
        # Update configuration
        config_manager.update_from_onboarding(wifi_ssid, wifi_password)
        config_manager.save()
        
        logger.info(f"WiFi configuration saved: SSID={wifi_ssid}")
        logger.info("Onboarding complete, device will connect to WiFi")
        
        # Notify main application (if callback is set)
        if onboarding_complete_callback:
            onboarding_complete_callback()
        
        # Shutdown Flask server after successful configuration
        _shutdown_server()
        
        # Return response
        if request.is_json:
            return jsonify({
                'message': 'Configuration saved. Device will connect to your WiFi network.'
            })
        else:
            # For form submission, return success page
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


def run_onboarding_server(config: Dict, host: str = '0.0.0.0', port: int = 80, callback: Optional[callable] = None):
    """
    Run onboarding web server.
    
    Simplified minimal web interface for WiFi credentials only.
    No threading, no events - just a simple blocking Flask server.
    Blocks until configuration is saved, then returns control to main application.
    
    Args:
        config: Configuration dictionary
        host: Host to bind to (default: 0.0.0.0)
        port: Port to bind to (default: 80)
        callback: Optional callback to call when onboarding is complete
    """
    global onboarding_complete_callback
    
    onboarding_complete_callback = callback
    
    init_onboarding(config)
    
    logger.info(f"Starting minimal onboarding server on {host}:{port}")
    logger.info(f"Connect to http://{host} and enter WiFi credentials")
    
    # Run Flask app (blocks until server is shut down from within save_config route)
    # Simple blocking server - no threading patterns
    app.run(
        host=host,
        port=port,
        debug=False,
        threaded=True,  # Allow multiple concurrent requests
        use_reloader=False
    )
    
    logger.info("Onboarding server stopped, WiFi configuration saved")


if __name__ == '__main__':
    # For testing
    from config_manager import ConfigManager
    
    config_mgr = ConfigManager()
    config = config_mgr.get_default_config()
    
    run_onboarding_server(config, port=8080)
