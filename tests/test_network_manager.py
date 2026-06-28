import asyncio
import copy
import subprocess
import pytest
from unittest.mock import MagicMock, call


CONFIG_WITH_AP = {
    "ap_mode": {
        "ssid": "GrowMate-Explicit",
        "password": "testpass",
        "channel": 6,
        "interface": "wlan0",
    },
    "network": {
        "wifi": {
            "interface": "wlan0",
            "connect_timeout": 15,
            "connect_retries": 5,
        },
    },
}

CONFIG_EMPTY_AP = {"ap_mode": {}, "network": {"wifi": {}}}


def make_result(stdout="", returncode=0):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = ""
    return r


@pytest.fixture
def mock_subproc(mocker):
    m = mocker.patch("subprocess.run", return_value=make_result())
    return m


@pytest.fixture
def mock_subproc_conditional(mocker):
    _results = {}

    def set_command(pattern, stdout="", returncode=0):
        _results[pattern] = (stdout, returncode)

    def side_effect(command, *args, **kwargs):
        cmd_str = " ".join(command)
        for pat, (stdout, rc) in _results.items():
            if pat in cmd_str:
                if kwargs.get("check", True) and rc != 0:
                    raise subprocess.CalledProcessError(rc, command, stdout, "")
                return make_result(stdout, rc)
        return make_result()

    m = mocker.patch("subprocess.run", side_effect=side_effect)
    m.set_command = set_command
    return m


@pytest.fixture
def mock_paths(mocker):
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.read_text", return_value="template {SSID} {PASSWORD} {CHANNEL}")
    mocker.patch("pathlib.Path.write_text")


@pytest.fixture
def manager(mock_subproc):
    from network_manager import NetworkManager
    return NetworkManager(copy.deepcopy(CONFIG_WITH_AP))


@pytest.fixture
def empty_manager(mock_subproc):
    from network_manager import NetworkManager
    return NetworkManager(copy.deepcopy(CONFIG_EMPTY_AP))


class TestInit:
    def test_explicit_ssid_password_channel(self, manager):
        assert manager.ap_ssid == "GrowMate-Explicit"
        assert manager.ap_password == "testpass"
        assert manager.ap_channel == 6

    def test_defaults_for_missing_fields(self, empty_manager):
        from network_manager import AP_PASSWORD, AP_IP_ADDRESS, AP_NETMASK, \
            AP_DHCP_RANGE_START, AP_DHCP_RANGE_END, WIFI_CONNECT_TIMEOUT, WIFI_CONNECT_RETRIES
        assert empty_manager.ap_password == AP_PASSWORD
        assert empty_manager.ap_ip == AP_IP_ADDRESS
        assert empty_manager.ap_netmask == AP_NETMASK
        assert empty_manager.ap_dhcp_start == AP_DHCP_RANGE_START
        assert empty_manager.ap_dhcp_end == AP_DHCP_RANGE_END
        assert empty_manager.ap_channel == 1
        assert empty_manager.wifi_connect_timeout == WIFI_CONNECT_TIMEOUT
        assert empty_manager.wifi_connect_retries == WIFI_CONNECT_RETRIES

    def test_config_ap_mode_empty_dict(self, mock_subproc):
        from network_manager import NetworkManager, AP_PASSWORD, WLAN_INTERFACE
        mgr = NetworkManager({"ap_mode": {}, "network": {}})
        assert mgr.ap_password == AP_PASSWORD
        assert mgr.wlan_interface == WLAN_INTERFACE

    def test_wifi_interface_from_ap_mode(self, mock_subproc):
        from network_manager import NetworkManager
        mgr = NetworkManager({
            "ap_mode": {"interface": "ap0"},
            "network": {},
        })
        assert mgr.wlan_interface == "ap0"

    def test_wifi_interface_from_network_wifi(self, mock_subproc):
        from network_manager import NetworkManager
        mgr = NetworkManager({
            "ap_mode": {"interface": "ap0"},
            "network": {"wifi": {"interface": "wlan1"}},
        })
        assert mgr.wlan_interface == "wlan1"


class TestGetApSsid:
    def test_explicit_via_config(self, manager):
        assert manager._get_ap_ssid() == "GrowMate-Explicit"

    def test_fallback_via_utils(self, mock_subproc, mocker):
        mocker.patch("utils.get_ap_ssid", return_value="GrowMate-ABCDEF")
        from network_manager import NetworkManager
        mgr = NetworkManager({"ap_mode": {"ssid": ""}, "network": {}})
        result = mgr._get_ap_ssid()
        assert result == "GrowMate-ABCDEF"

    def test_empty_ssid_in_config(self, mock_subproc, mocker):
        mocker.patch("utils.get_ap_ssid", return_value="GrowMate-FALLBACK")
        from network_manager import NetworkManager
        mgr = NetworkManager({"ap_mode": {"ssid": ""}, "network": {}})
        assert mgr._get_ap_ssid() == "GrowMate-FALLBACK"


class TestRunCommand:
    def test_success(self, manager, mock_subproc):
        mock_subproc.return_value = make_result("ok", 0)
        result = manager._run_command(["test", "cmd"])
        assert result.stdout == "ok"
        mock_subproc.assert_called_once_with(
            ["test", "cmd"], capture_output=True, text=True, check=True
        )

    def test_failure_with_check_true(self, manager, mock_subproc):
        mock_subproc.side_effect = subprocess.CalledProcessError(
            1, ["fail"], "", "error msg"
        )
        with pytest.raises(subprocess.CalledProcessError):
            manager._run_command(["fail"])

    def test_failure_with_check_false(self, manager, mock_subproc):
        mock_subproc.return_value = make_result("", 1)
        result = manager._run_command(["fail"], check=False)
        assert result.returncode == 1


class TestScanNetworks:
    NMWLI_OUTPUT = "MyWiFi:80:WPA2\nGuest:30:\nHidden::\n"

    @pytest.mark.asyncio
    async def test_normal_parsing(self, mock_subproc_conditional, mocker):
        mock_subproc_conditional.set_command(
            "nmcli -t -f SSID,SIGNAL,SECURITY device wifi list",
            self.NMWLI_OUTPUT
        )
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        networks = await mgr.scan_networks()
        assert len(networks) == 3
        assert networks[0]["ssid"] == "MyWiFi"
        assert networks[0]["rssi"] == -44
        assert networks[0]["security"] == "WPA2"
        assert networks[1]["ssid"] == "Guest"
        assert networks[1]["rssi"] == -79
        assert networks[1]["security"] == ""
        assert networks[2]["ssid"] == "Hidden"

    @pytest.mark.asyncio
    async def test_empty_output(self, mock_subproc_conditional, mocker):
        mock_subproc_conditional.set_command(
            "nmcli -t -f SSID,SIGNAL,SECURITY device wifi list",
            ""
        )
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        networks = await mgr.scan_networks()
        assert networks == []

    @pytest.mark.asyncio
    async def test_error_returns_empty_list(self, mock_subproc_conditional, mocker):
        mock_subproc_conditional.set_command(
            "nmcli -t -f SSID,SIGNAL,SECURITY device wifi list",
            "",
            returncode=1
        )
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        networks = await mgr.scan_networks()
        assert networks == []


class TestGenerateHostapdConf:
    def test_successful_generation(self, manager, mock_paths):
        assert manager._generate_hostapd_conf() is True

    def test_template_not_found(self, manager, mocker):
        mocker.patch("pathlib.Path.exists", return_value=False)
        assert manager._generate_hostapd_conf() is False

    def test_io_error_during_read(self, manager, mocker):
        mocker.patch("pathlib.Path.exists", return_value=True)
        mocker.patch("pathlib.Path.read_text", side_effect=OSError("denied"))
        assert manager._generate_hostapd_conf() is False

    def test_uses_correct_placeholders(self, manager, mocker):
        read_mock = mocker.patch("pathlib.Path.read_text", return_value="{SSID}|{PASSWORD}|{CHANNEL}")
        write_mock = mocker.patch("pathlib.Path.write_text")
        mocker.patch("pathlib.Path.exists", return_value=True)
        assert manager._generate_hostapd_conf() is True
        write_mock.assert_called_once_with("GrowMate-Explicit|testpass|6")


class TestStartApMode:
    @pytest.mark.asyncio
    async def test_success(self, mocker):
        mocker.patch("pathlib.Path.exists", return_value=True)
        mocker.patch("pathlib.Path.read_text", return_value="template {SSID} {PASSWORD} {CHANNEL}")
        mocker.patch("pathlib.Path.write_text")
        sub_mock = mocker.patch("subprocess.run", return_value=make_result())
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        result = await mgr.start_ap_mode()
        assert result is True
        expected_calls = [
            call(["systemctl", "stop", "wpa_supplicant"], capture_output=True, text=True, check=False),
            call(["systemctl", "stop", "NetworkManager"], capture_output=True, text=True, check=False),
            call(["ip", "link", "set", "wlan0", "down"], capture_output=True, text=True, check=True),
            call(["ip", "addr", "flush", "dev", "wlan0"], capture_output=True, text=True, check=True),
            call(["ip", "addr", "add", "192.168.4.1/24", "dev", "wlan0"], capture_output=True, text=True, check=True),
            call(["ip", "link", "set", "wlan0", "up"], capture_output=True, text=True, check=True),
            call(["systemctl", "start", "hostapd"], capture_output=True, text=True, check=True),
            call(["systemctl", "start", "dnsmasq"], capture_output=True, text=True, check=True),
        ]
        for c in expected_calls:
            assert c in sub_mock.call_args_list

    @pytest.mark.asyncio
    async def test_failure_at_hostapd_gen_returns_false(self, mocker):
        mocker.patch("pathlib.Path.exists", return_value=False)
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        result = await mgr.start_ap_mode()
        assert result is False

    @pytest.mark.asyncio
    async def test_subprocess_error_returns_false(self, mocker):
        mocker.patch("pathlib.Path.exists", return_value=True)
        mocker.patch("pathlib.Path.read_text", return_value="template")
        mocker.patch("pathlib.Path.write_text")
        sub_mock = mocker.patch("subprocess.run")
        sub_mock.side_effect = subprocess.CalledProcessError(1, ["ip"], "", "err")
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        result = await mgr.start_ap_mode()
        assert result is False


class TestStopApMode:
    @pytest.mark.asyncio
    async def test_success(self, mocker):
        sub_mock = mocker.patch("subprocess.run", return_value=make_result())
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        result = await mgr.stop_ap_mode()
        assert result is True
        expected_calls = [
            call(["systemctl", "stop", "hostapd"], capture_output=True, text=True, check=False),
            call(["systemctl", "stop", "dnsmasq"], capture_output=True, text=True, check=False),
            call(["ip", "link", "set", "wlan0", "down"], capture_output=True, text=True, check=False),
            call(["ip", "addr", "flush", "dev", "wlan0"], capture_output=True, text=True, check=False),
            call(["systemctl", "start", "NetworkManager"], capture_output=True, text=True, check=False),
        ]
        for c in expected_calls:
            assert c in sub_mock.call_args_list

    @pytest.mark.asyncio
    async def test_exception_returns_false(self, mocker):
        mocker.patch("subprocess.run", side_effect=OSError("fail"))
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        result = await mgr.stop_ap_mode()
        assert result is False


class TestConnectToWifi:
    @pytest.mark.asyncio
    async def test_first_attempt_succeeds(self, mocker):
        mocker.patch("pathlib.Path.exists", return_value=True)
        mocker.patch("pathlib.Path.read_text", return_value="template")
        mocker.patch("pathlib.Path.write_text")
        sub_mock = mocker.patch("subprocess.run", return_value=make_result())
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        result = await mgr.connect_to_wifi("MyWiFi", "secret")
        assert result is True
        nmcli_call = call(
            ["nmcli", "device", "wifi", "connect", "MyWiFi", "password", "secret"],
            capture_output=True, text=True, check=False
        )
        assert nmcli_call in sub_mock.call_args_list

    @pytest.mark.asyncio
    async def test_retry_then_succeeds(self, mocker):
        mocker.patch("pathlib.Path.exists", return_value=True)
        mocker.patch("pathlib.Path.read_text", return_value="template")
        mocker.patch("pathlib.Path.write_text")
        mocker.patch("asyncio.sleep")

        results = [make_result() for _ in range(5)]
        results.append(make_result("", 1))
        results.append(make_result("", 0))
        sub_mock = mocker.patch("subprocess.run", side_effect=results)
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        result = await mgr.connect_to_wifi("MyWiFi", "secret")
        assert result is True
        nmcli_calls = [
            c for c in sub_mock.call_args_list
            if "nmcli" in " ".join(c[0][0])
        ]
        assert len(nmcli_calls) == 2

    @pytest.mark.asyncio
    async def test_all_retries_fail(self, mocker):
        mocker.patch("pathlib.Path.exists", return_value=True)
        mocker.patch("pathlib.Path.read_text", return_value="template")
        mocker.patch("pathlib.Path.write_text")
        mocker.patch("asyncio.sleep")

        results = [make_result() for _ in range(5)]
        results.extend([make_result("", 1) for _ in range(5)])
        sub_mock = mocker.patch("subprocess.run", side_effect=results)
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        result = await mgr.connect_to_wifi("MyWiFi", "secret")
        assert result is False
        nmcli_calls = [
            c for c in sub_mock.call_args_list
            if "nmcli" in " ".join(c[0][0])
        ]
        assert len(nmcli_calls) == 5

    @pytest.mark.asyncio
    async def test_exception_returns_false(self, mocker):
        mocker.patch("pathlib.Path.exists", return_value=True)
        mocker.patch("pathlib.Path.read_text", return_value="template")
        mocker.patch("pathlib.Path.write_text")
        mocker.patch("subprocess.run", side_effect=OSError("fail"))
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        result = await mgr.connect_to_wifi("MyWiFi", "secret")
        assert result is False


class TestIsConnected:
    @pytest.mark.asyncio
    async def test_connected_state(self, mock_subproc_conditional, mocker):
        mock_subproc_conditional.set_command(
            "nmcli -t -f STATE general", "connected"
        )
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        assert await mgr.is_connected() is True

    @pytest.mark.asyncio
    async def test_disconnected_state(self, mock_subproc_conditional, mocker):
        mock_subproc_conditional.set_command(
            "nmcli -t -f STATE general", "asleep"
        )
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        assert await mgr.is_connected() is False

    @pytest.mark.asyncio
    async def test_error_returns_false(self, mock_subproc_conditional, mocker):
        mock_subproc_conditional.set_command(
            "nmcli -t -f STATE general", "", returncode=1
        )
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        assert await mgr.is_connected() is False


class TestGetIpAddress:
    IP_SHOW_OUTPUT = (
        "2: wlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...\n"
        "    inet 192.168.1.100/24 brd 192.168.1.255 scope global wlan0\n"
    )

    @pytest.mark.asyncio
    async def test_ip_found(self, mock_subproc_conditional, mocker):
        mock_subproc_conditional.set_command(
            "ip -4 addr show wlan0", self.IP_SHOW_OUTPUT
        )
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        ip = await mgr.get_ip_address()
        assert ip == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_ip_not_found(self, mock_subproc_conditional, mocker):
        mock_subproc_conditional.set_command(
            "ip -4 addr show wlan0",
            "2: wlan0: <NO-CARRIER> mtu 1500 ...\n"
        )
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        ip = await mgr.get_ip_address()
        assert ip is None

    @pytest.mark.asyncio
    async def test_error_returns_none(self, mock_subproc_conditional, mocker):
        mock_subproc_conditional.set_command(
            "ip -4 addr show wlan0", "", returncode=1
        )
        from network_manager import NetworkManager
        mgr = NetworkManager(copy.deepcopy(CONFIG_WITH_AP))
        ip = await mgr.get_ip_address()
        assert ip is None


class TestStandaloneFunctions:
    @pytest.mark.asyncio
    async def test_start_ap(self, mocker):
        mocker.patch("pathlib.Path.exists", return_value=True)
        mocker.patch("pathlib.Path.read_text", return_value="template")
        mocker.patch("pathlib.Path.write_text")
        mocker.patch("subprocess.run", return_value=make_result())
        from network_manager import start_ap
        result = await start_ap(copy.deepcopy(CONFIG_WITH_AP))
        assert result is True

    @pytest.mark.asyncio
    async def test_stop_ap(self, mocker):
        mocker.patch("subprocess.run", return_value=make_result())
        from network_manager import stop_ap
        result = await stop_ap(copy.deepcopy(CONFIG_WITH_AP))
        assert result is True

    @pytest.mark.asyncio
    async def test_connect_wifi(self, mocker):
        mocker.patch("pathlib.Path.exists", return_value=True)
        mocker.patch("pathlib.Path.read_text", return_value="template")
        mocker.patch("pathlib.Path.write_text")
        mocker.patch("subprocess.run", return_value=make_result())
        from network_manager import connect_wifi
        result = await connect_wifi(copy.deepcopy(CONFIG_WITH_AP), "WiFi", "pass")
        assert result is True

    @pytest.mark.asyncio
    async def test_check_connection(self, mocker):
        sub_mock = mocker.patch("subprocess.run", return_value=make_result("connected"))
        from network_manager import check_connection
        result = await check_connection(copy.deepcopy(CONFIG_WITH_AP))
        assert result is True
