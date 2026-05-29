#!/usr/bin/env python3
"""
Phase 4 verification script.

Tests network and onboarding components without requiring hardware or root access.
For full testing, manual verification on actual Raspberry Pi hardware is required.
"""

import sys
import os
from pathlib import Path

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Test results tracking
tests_passed = 0
tests_failed = 0


def test_result(name: str, passed: bool, details: str = ""):
    """Record and print test result."""
    global tests_passed, tests_failed
    
    if passed:
        tests_passed += 1
        print(f"✓ {name}")
        if details:
            print(f"  {details}")
    else:
        tests_failed += 1
        print(f"✗ {name}")
        if details:
            print(f"  ERROR: {details}")


def test_imports():
    """Test that Phase 4 modules can be imported."""
    print("\n" + "=" * 60)
    print("TEST: Module Imports")
    print("=" * 60)
    
    try:
        from network_manager import NetworkManager
        test_result("Import network_manager", True)
    except Exception as e:
        test_result("Import network_manager", False, str(e))
    
    try:
        from onboarding_portal import app, init_onboarding
        test_result("Import onboarding_portal", True)
    except Exception as e:
        test_result("Import onboarding_portal", False, str(e))


def test_configuration_templates():
    """Test that configuration templates exist and are valid."""
    print("\n" + "=" * 60)
    print("TEST: Configuration Templates")
    print("=" * 60)
    
    base_dir = Path(__file__).parent.parent
    
    # Check hostapd.conf.template
    hostapd_template = base_dir / "config" / "hostapd.conf.template"
    if hostapd_template.exists():
        content = hostapd_template.read_text()
        has_ssid_placeholder = "GrowMate-XXXXXX" in content
        has_password = "growmate" in content
        test_result(
            "hostapd.conf.template",
            has_ssid_placeholder and has_password,
            f"SSID placeholder: {has_ssid_placeholder}, Password: {has_password}"
        )
    else:
        test_result("hostapd.conf.template", False, "File not found")
    
    # Check dnsmasq.conf.template
    dnsmasq_template = base_dir / "config" / "dnsmasq.conf.template"
    if dnsmasq_template.exists():
        content = dnsmasq_template.read_text()
        has_dhcp_range = "192.168.4.2,192.168.4.20" in content
        has_interface = "interface=wlan0" in content
        test_result(
            "dnsmasq.conf.template",
            has_dhcp_range and has_interface,
            f"DHCP range: {has_dhcp_range}, Interface: {has_interface}"
        )
    else:
        test_result("dnsmasq.conf.template", False, "File not found")


def test_html_template():
    """Test that HTML template matches ESP32 format."""
    print("\n" + "=" * 60)
    print("TEST: HTML Template (ESP32 Compatibility)")
    print("=" * 60)
    
    base_dir = Path(__file__).parent.parent
    index_html = base_dir / "templates" / "index.html"
    
    if index_html.exists():
        content = index_html.read_text()
        
        # Check for ESP32-specific elements
        checks = {
            "Inline CSS": "<style>" in content and "body{font-family:system-ui" in content,
            "GrowMate onboarding title": "GrowMate onboarding" in content,
            "Device ID field": "id='deviceId'" in content,
            "WiFi scan button": "id='scanBtn'" in content,
            "SSID select": "id='ssid'" in content,
            "Password input": "id='password'" in content,
            "Save button": "id='saveBtn'" in content,
            "Status div": "id='status'" in content,
            "API calls": "/api/config" in content and "/api/networks" in content,
            "Dark theme colors": "#0f172a" in content and "#111827" in content,
        }
        
        all_passed = all(checks.values())
        test_result("HTML template structure", all_passed)
        
        for check_name, passed in checks.items():
            if not passed:
                print(f"  Missing: {check_name}")
    else:
        test_result("HTML template", False, "File not found")


def test_network_manager_structure():
    """Test NetworkManager class structure."""
    print("\n" + "=" * 60)
    print("TEST: NetworkManager Structure")
    print("=" * 60)
    
    try:
        from network_manager import NetworkManager
        from config_manager import ConfigManager
        
        # Create test config
        config_mgr = ConfigManager()
        config = config_mgr.get_default_config()
        
        # Create NetworkManager instance
        nm = NetworkManager(config)
        
        # Check methods exist
        methods = [
            'scan_networks',
            'start_ap_mode',
            'stop_ap_mode',
            'connect_to_wifi',
            'is_connected',
            'get_ip_address',
            '_generate_hostapd_conf'
        ]
        
        for method in methods:
            has_method = hasattr(nm, method)
            test_result(f"NetworkManager.{method}", has_method)
        
        # Check AP SSID format
        ap_ssid = nm.ap_ssid
        is_valid_format = ap_ssid.startswith('GrowMate-') and len(ap_ssid) == 16
        test_result(
            "AP SSID format",
            is_valid_format,
            f"SSID: {ap_ssid} (should be GrowMate-XXXXXX)"
        )
        
    except Exception as e:
        test_result("NetworkManager structure", False, str(e))


def test_onboarding_portal_routes():
    """Test Flask app routes."""
    print("\n" + "=" * 60)
    print("TEST: Onboarding Portal Routes")
    print("=" * 60)
    
    try:
        from onboarding_portal import app
        
        # Get all routes
        routes = []
        for rule in app.url_map.iter_rules():
            routes.append((rule.rule, ','.join(rule.methods)))
        
        # Expected routes
        expected_routes = {
            '/': 'GET',
            '/api/config': 'GET,POST',
            '/api/networks': 'GET',
            '/favicon.ico': 'GET',
        }
        
        for route, methods in expected_routes.items():
            found = any(r[0] == route for r in routes)
            test_result(f"Route {route}", found, f"Methods: {methods}")
        
    except Exception as e:
        test_result("Onboarding portal routes", False, str(e))


def test_api_response_formats():
    """Test API response formats match ESP32."""
    print("\n" + "=" * 60)
    print("TEST: API Response Formats (ESP32 Compatibility)")
    print("=" * 60)
    
    try:
        from onboarding_portal import app, init_onboarding
        from config_manager import ConfigManager
        import json
        
        # Initialize onboarding
        config_mgr = ConfigManager()
        config = config_mgr.get_default_config()
        init_onboarding(config)
        
        # Test client
        with app.test_client() as client:
            # Test GET /api/config
            response = client.get('/api/config')
            data = json.loads(response.data)
            
            has_device_id = 'deviceId' in data
            has_wifi_ssid = 'wifiSsid' in data
            test_result(
                "GET /api/config format",
                has_device_id and has_wifi_ssid,
                f"Keys: {list(data.keys())}"
            )
            
            # Test favicon
            response = client.get('/favicon.ico')
            is_svg = response.content_type == 'image/svg+xml'
            has_location_pin = b'M32 12c8 0 14 6 14 14' in response.data
            test_result(
                "Favicon (location pin)",
                is_svg and has_location_pin,
                f"Content-Type: {response.content_type}"
            )
        
    except Exception as e:
        test_result("API response formats", False, str(e))


def test_esp32_compatibility():
    """Test ESP32 compatibility features."""
    print("\n" + "=" * 60)
    print("TEST: ESP32 Compatibility Features")
    print("=" * 60)
    
    try:
        from utils import get_ap_ssid, get_device_id
        
        # Test device ID format
        device_id = get_device_id()
        test_result(
            "Device ID format",
            device_id.startswith('growmate-'),
            f"Device ID: {device_id}"
        )
        
        # Test AP SSID format (last 6 chars of device ID)
        ap_ssid = get_ap_ssid()
        expected_suffix = device_id[-6:].upper()
        actual_suffix = ap_ssid.replace('GrowMate-', '')
        test_result(
            "AP SSID from device ID",
            actual_suffix == expected_suffix,
            f"SSID: {ap_ssid}, Expected suffix: {expected_suffix}"
        )
        
    except Exception as e:
        test_result("ESP32 compatibility", False, str(e))


def main():
    """Run all Phase 4 tests."""
    print("\n" + "=" * 60)
    print("PHASE 4: Network & Onboarding System - Verification Tests")
    print("=" * 60)
    print("\nTesting software components (hardware tests require Raspberry Pi)...")
    
    # Run all tests
    test_imports()
    test_configuration_templates()
    test_html_template()
    test_network_manager_structure()
    test_onboarding_portal_routes()
    test_api_response_formats()
    test_esp32_compatibility()
    
    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Passed: {tests_passed}")
    print(f"Failed: {tests_failed}")
    print(f"Total:  {tests_passed + tests_failed}")
    
    if tests_failed == 0:
        print("\n✓ ALL TESTS PASSED - Phase 4 Software Components Ready")
        print("\nNext Steps:")
        print("1. Deploy to Raspberry Pi hardware")
        print("2. Test AP mode creation (requires root)")
        print("3. Test web portal access from phone/laptop")
        print("4. Test WiFi configuration and client mode switch")
        return 0
    else:
        print(f"\n✗ {tests_failed} TEST(S) FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(main())
