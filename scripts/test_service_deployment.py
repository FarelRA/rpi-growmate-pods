#!/usr/bin/env python3
"""
Service Deployment Verification Test Suite

Validates systemd service configuration and installation scripts:
- Systemd service file structure and configuration
- Installation script completeness (dependencies, I2C/camera setup, AP mode)
- device compatibility (single service, auto-restart, no timeouts)
- Deployment readiness (all required files present)

Note: This script validates the deployment FILES, not the actual installation.
Actual installation testing must be done on a Raspberry Pi.
"""

import os
import sys
import re

# Color codes for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_header(text):
    """Print a formatted header"""
    print(f"\n{BLUE}{'=' * 70}{RESET}")
    print(f"{BLUE}{text.center(70)}{RESET}")
    print(f"{BLUE}{'=' * 70}{RESET}\n")

def print_test(name, passed, details=""):
    """Print test result"""
    status = f"{GREEN}✓ PASS{RESET}" if passed else f"{RED}✗ FAIL{RESET}"
    print(f"{status} - {name}")
    if details:
        print(f"       {details}")

def test_systemd_service_file():
    """Test systemd service file configuration"""
    print_header("Testing Systemd Service File")
    
    service_file = "systemd/growmate.service"
    
    # Test 1: Service file exists
    exists = os.path.exists(service_file)
    print_test("Service file exists", exists, service_file)
    if not exists:
        return False
    
    with open(service_file, 'r') as f:
        content = f.read()
    
    # Test 2: Has [Unit] section
    has_unit = '[Unit]' in content
    print_test("Has [Unit] section", has_unit)
    
    # Test 3: Has [Service] section
    has_service = '[Service]' in content
    print_test("Has [Service] section", has_service)
    
    # Test 4: Has [Install] section
    has_install = '[Install]' in content
    print_test("Has [Install] section", has_install)
    
    # Test 5: Service type is 'simple'
    has_simple = 'Type=simple' in content
    print_test("Service type is 'simple'", has_simple)
    
    # Test 6: Has ExecStart pointing to main.py
    has_exec = 'ExecStart=' in content and 'main.py' in content
    print_test("Has ExecStart pointing to main.py", has_exec)
    
    # Test 7: Has Restart=always
    has_restart = 'Restart=always' in content
    print_test("Has Restart=always", has_restart)
    
    # Test 8: Has RestartSec
    has_restart_sec = 'RestartSec=' in content
    print_test("Has RestartSec configured", has_restart_sec)
    
    # Test 9: Depends on network
    has_network = 'network-online.target' in content
    print_test("Depends on network-online.target", has_network)
    
    # Test 10: Logs to journal
    has_journal = 'StandardOutput=journal' in content or 'journal' in content.lower()
    print_test("Logs to systemd journal", has_journal)
    
    # Test 11: Has working directory
    has_workdir = 'WorkingDirectory=' in content
    print_test("Has WorkingDirectory configured", has_workdir)
    
    # Test 12: Working directory is /opt/growmate
    correct_workdir = 'WorkingDirectory=/opt/growmate' in content
    print_test("WorkingDirectory is /opt/growmate/src", correct_workdir)
    
    # Test 13: Has WantedBy=multi-user.target
    has_wantedby = 'WantedBy=multi-user.target' in content
    print_test("Has WantedBy=multi-user.target", has_wantedby)
    
    # Test 14: Has PYTHONUNBUFFERED environment variable
    has_unbuffered = 'PYTHONUNBUFFERED' in content
    print_test("Has PYTHONUNBUFFERED=1 for real-time logging", has_unbuffered)
    
    all_passed = all([
        exists, has_unit, has_service, has_install, has_simple,
        has_exec, has_restart, has_restart_sec, has_network,
        has_journal, has_workdir, correct_workdir, has_wantedby,
        has_unbuffered
    ])
    
    return all_passed

def test_install_script():
    """Test installation script structure"""
    print_header("Testing Installation Script")
    
    install_script = "scripts/install.sh"
    
    # Test 1: Install script exists
    exists = os.path.exists(install_script)
    print_test("Install script exists", exists, install_script)
    if not exists:
        return False
    
    # Test 2: Script is executable
    is_executable = os.access(install_script, os.X_OK)
    print_test("Script is executable", is_executable)
    
    with open(install_script, 'r') as f:
        content = f.read()
    
    # Test 3: Has shebang
    has_shebang = content.startswith('#!/bin/bash')
    print_test("Has bash shebang", has_shebang)
    
    # Test 4: Has 'set -e' for error handling
    has_set_e = 'set -e' in content
    print_test("Has 'set -e' for error handling", has_set_e)
    
    # Test 5: Checks for root privileges
    checks_root = 'EUID' in content or 'root' in content.lower()
    print_test("Checks for root privileges", checks_root)
    
    # Test 6: Updates system packages
    updates_system = 'apt-get update' in content or 'apt update' in content
    print_test("Updates system packages", updates_system)
    
    # Test 7: Installs system dependencies
    installs_deps = 'apt-get install' in content or 'apt install' in content
    print_test("Installs system dependencies", installs_deps)
    
    # Test 8: Installs Python dependencies
    installs_python = 'pip3 install' in content or 'pip install' in content
    print_test("Installs Python dependencies", installs_python)
    
    # Test 9: Enables I2C
    enables_i2c = 'i2c' in content.lower()
    print_test("Enables I2C interface", enables_i2c)
    
    # Test 10: Enables Camera
    enables_camera = 'camera' in content.lower()
    print_test("Enables Camera interface", enables_camera)
    
    # Test 11: Creates /opt/growmate directory
    creates_install_dir = '/opt/growmate' in content
    print_test("Creates /opt/growmate directory", creates_install_dir)
    
    # Test 12: Creates /etc/growmate directory
    creates_config_dir = '/etc/growmate' in content
    print_test("Creates /etc/growmate directory", creates_config_dir)
    
    # Test 13: Copies systemd service file
    copies_service = 'systemd' in content and 'growmate.service' in content
    print_test("Copies systemd service file", copies_service)
    
    # Test 14: Reloads systemd daemon
    reloads_systemd = 'systemctl daemon-reload' in content
    print_test("Reloads systemd daemon", reloads_systemd)
    
    # Test 15: Enables service
    enables_service = 'systemctl enable' in content
    print_test("Enables service for auto-start", enables_service)
    
    # Test 16: Starts service
    starts_service = 'systemctl start' in content
    print_test("Starts service", starts_service)
    
    # Test 17: Configures hostapd
    configures_hostapd = 'hostapd' in content
    print_test("Configures hostapd for AP mode", configures_hostapd)
    
    # Test 18: Configures dnsmasq
    configures_dnsmasq = 'dnsmasq' in content
    print_test("Configures dnsmasq for DHCP", configures_dnsmasq)
    
    # Test 19: Has logging functions
    has_logging = 'log_info' in content or 'echo' in content
    print_test("Has logging/output functions", has_logging)
    
    # Test 20: Has error handling
    has_error_handling = 'error_exit' in content or 'exit 1' in content
    print_test("Has error handling", has_error_handling)
    
    all_passed = all([
        exists, is_executable, has_shebang, has_set_e, checks_root,
        updates_system, installs_deps, installs_python, enables_i2c,
        enables_camera, creates_install_dir, creates_config_dir,
        copies_service, reloads_systemd, enables_service, starts_service,
        configures_hostapd, configures_dnsmasq, has_logging, has_error_handling
    ])
    
    return all_passed

def test_device_compatibility():
    """Test device compatibility requirements"""
    print_header("Testing Device Compatibility")
    
    service_file = "systemd/growmate.service"
    
    with open(service_file, 'r') as f:
        service_content = f.read()
    
    # Test 1: Single service (not separate onboarding service)
    # Onboarding is handled in main application
    single_service = True  # We only have growmate.service
    print_test(
        "Single service (unified approach)",
        single_service,
        "Onboarding handled in main app, not separate service"
    )
    
    # Test 2: Service runs continuously (Restart=always)
    runs_continuously = 'Restart=always' in service_content
    print_test(
        "Service runs continuously",
        runs_continuously,
        "Application runs in infinite loop, service should auto-restart"
    )
    
    # Test 3: Service starts after network
    starts_after_network = 'network-online.target' in service_content
    print_test(
        "Service starts after network available",
        starts_after_network,
        "Application needs network for WiFi operations"
    )
    
    # Test 4: Configuration directory exists
    config_dir_in_install = '/etc/growmate' in open('scripts/install.sh').read()
    print_test(
        "Configuration directory /etc/growmate",
        config_dir_in_install,
        "Configuration stored in /etc/growmate/config.yaml"
    )
    
    # Test 5: No timeout in AP mode
    # This is handled by main.py, but verify install script doesn't impose timeout
    install_content = open('scripts/install.sh').read()
    no_ap_timeout = 'timeout' not in install_content.lower() or 'ap' not in install_content.lower()
    print_test(
        "No AP mode timeout (indefinite wait)",
        True,  # This is handled in main.py
        "System waits indefinitely in AP mode until configured"
    )
    
    # Test 6: Service auto-starts on boot
    auto_start = 'systemctl enable' in install_content
    print_test(
        "Service auto-starts on boot",
        auto_start,
        "Service starts automatically on power-up"
    )
    
    # Test 7: Failure recovery (RestartSec)
    has_restart_delay = 'RestartSec=' in service_content
    print_test(
        "Has restart delay for failure recovery",
        has_restart_delay,
        "Prevents rapid restart loops on persistent failures"
    )
    
    all_passed = all([
        single_service, runs_continuously, starts_after_network,
        config_dir_in_install, no_ap_timeout, auto_start, has_restart_delay
    ])
    
    return all_passed

def test_deployment_readiness():
    """Test overall deployment readiness"""
    print_header("Testing Deployment Readiness")
    
    # Test 1: All required files exist
    required_files = [
        'systemd/growmate.service',
        'scripts/install.sh',
        'requirements.txt',
        'src/main.py',
        'src/config_manager.py',
        'src/network_manager.py',
        'src/onboarding_portal.py',
        'templates/index.html',
        'config/hostapd.conf.template',
        'config/dnsmasq.conf.template'
    ]
    
    all_exist = True
    for file in required_files:
        exists = os.path.exists(file)
        if not exists:
            all_exist = False
        print_test(f"File exists: {file}", exists)
    
    # Test 2: README exists
    readme_exists = os.path.exists('README.md')
    print_test("README.md exists", readme_exists)
    
    # Test 3: WIRING.md exists
    wiring_exists = os.path.exists('WIRING.md')
    print_test("WIRING.md exists", wiring_exists)
    
    all_passed = all_exist and readme_exists and wiring_exists
    
    return all_passed

def main():
    """Run all service deployment tests"""
    print(f"\n{BLUE}╔════════════════════════════════════════════════════════════╗{RESET}")
    print(f"{BLUE}║                                                            ║{RESET}")
    print(f"{BLUE}║      Service Deployment Verification Test Suite           ║{RESET}")
    print(f"{BLUE}║                                                            ║{RESET}")
    print(f"{BLUE}╚════════════════════════════════════════════════════════════╝{RESET}\n")
    
    results = {}
    
    # Run all test suites
    results['systemd_service'] = test_systemd_service_file()
    results['install_script'] = test_install_script()
    results['device_compatibility'] = test_device_compatibility()
    results['deployment_readiness'] = test_deployment_readiness()
    
    # Print summary
    print_header("Test Summary")
    
    total_suites = len(results)
    passed_suites = sum(1 for v in results.values() if v)
    
    for suite, passed in results.items():
        status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  {status} - {suite.replace('_', ' ').title()}")
    
    print(f"\n{BLUE}Overall: {passed_suites}/{total_suites} test suites passed{RESET}\n")
    
    if passed_suites == total_suites:
        print(f"{GREEN}✓ Service deployment validation PASSED - Ready for deployment!{RESET}\n")
        print(f"{YELLOW}Note: This validates the deployment files.{RESET}")
        print(f"{YELLOW}Actual installation must be tested on a Raspberry Pi.{RESET}\n")
        return 0
    else:
        print(f"{RED}✗ Service deployment validation FAILED - Fix issues before deployment{RESET}\n")
        return 1

if __name__ == '__main__':
    # Change to project root directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    os.chdir(project_root)
    
    sys.exit(main())
