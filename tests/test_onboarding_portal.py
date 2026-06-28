import copy
import pytest
from unittest.mock import MagicMock, AsyncMock


class TestInitOnboarding:
    def test_creates_config_manager_and_network_manager(self, mocker, minimal_config):
        mock_cm_cls = mocker.patch("onboarding_portal.ConfigManager")
        mock_nm_cls = mocker.patch("onboarding_portal.NetworkManager")

        import onboarding_portal
        onboarding_portal.config_manager = None
        onboarding_portal.network_manager = None
        onboarding_portal.init_onboarding(minimal_config)

        mock_cm_cls.assert_called_once()
        mock_nm_cls.assert_called_once_with(minimal_config)
        assert onboarding_portal.config_manager is not None
        assert onboarding_portal.network_manager is not None
        assert onboarding_portal.config_manager.config == minimal_config

    def test_with_existing_network_mgr(self, mocker, minimal_config):
        mock_cm_cls = mocker.patch("onboarding_portal.ConfigManager")
        mock_nm_cls = mocker.patch("onboarding_portal.NetworkManager")
        existing_nm = MagicMock()

        import onboarding_portal
        onboarding_portal.config_manager = None
        onboarding_portal.network_manager = None
        onboarding_portal.init_onboarding(minimal_config, existing_nm)

        mock_cm_cls.assert_called_once()
        mock_nm_cls.assert_not_called()
        assert onboarding_portal.network_manager is existing_nm


class TestGetConfig:
    def test_returns_device_id_and_wifi_ssid(self, mocker):
        mock_cm = MagicMock()
        mock_cm.get.side_effect = lambda key, default=None: {
            "device.id": "test-device-42",
            "network.wifi_ssid": "MyWiFi",
        }.get(key, default)
        mocker.patch("onboarding_portal.config_manager", mock_cm)

        from onboarding_portal import app
        client = app.test_client()
        resp = client.get("/api/config")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["deviceId"] == "test-device-42"
        assert data["wifiSsid"] == "MyWiFi"

    def test_returns_500_on_error(self, mocker):
        mock_cm = MagicMock()
        mock_cm.get.side_effect = Exception("oops")
        mocker.patch("onboarding_portal.config_manager", mock_cm)

        from onboarding_portal import app
        client = app.test_client()
        resp = client.get("/api/config")

        assert resp.status_code == 500
        data = resp.get_json()
        assert "error" in data


class TestScanNetworks:
    def test_returns_network_list(self, mocker):
        mock_nm = MagicMock()
        mock_nm.scan_networks = AsyncMock(return_value=[
            {"ssid": "HomeNet", "rssi": -45, "security": "WPA2"},
            {"ssid": "Guest", "rssi": -72, "security": ""},
        ])
        mocker.patch("onboarding_portal.network_manager", mock_nm)

        from onboarding_portal import app
        client = app.test_client()
        resp = client.get("/api/networks")

        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["networks"]) == 2
        assert data["networks"][0]["ssid"] == "HomeNet"
        assert data["networks"][0]["rssi"] == -45
        assert data["networks"][0]["authMode"] == 3
        assert data["networks"][1]["ssid"] == "Guest"
        assert data["networks"][1]["authMode"] == 0

    def test_returns_500_on_scan_error(self, mocker):
        mock_nm = MagicMock()
        mock_nm.scan_networks = AsyncMock(side_effect=Exception("scan failed"))
        mocker.patch("onboarding_portal.network_manager", mock_nm)

        from onboarding_portal import app
        client = app.test_client()
        resp = client.get("/api/networks")

        assert resp.status_code == 500
        data = resp.get_json()
        assert "error" in data


class TestSaveConfig:
    @pytest.fixture
    def mock_cm(self, mocker, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        mock_cm = MagicMock()
        mock_cm.config = cfg
        mock_cm.get.side_effect = lambda key, default=None: cfg.get(key, default)
        mocker.patch("onboarding_portal.config_manager", mock_cm)
        return mock_cm

    @pytest.fixture
    def mock_shutdown(self, mocker):
        return mocker.patch("onboarding_portal._shutdown_server")

    def test_saves_wifi_credentials_json(self, mocker, mock_cm, mock_shutdown):
        mock_cb = MagicMock()
        mocker.patch("onboarding_portal.onboarding_complete_callback", mock_cb)

        from onboarding_portal import app
        client = app.test_client()
        resp = client.post("/api/config", json={
            "wifiSsid": "TestNet",
            "wifiPassword": "secret123",
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert "Configuration saved" in data["message"]
        mock_cm.update_from_onboarding.assert_called_once_with("TestNet", "secret123")
        mock_cm.save.assert_called_once()
        mock_cb.assert_called_once()
        mock_shutdown.assert_called_once()

    def test_saves_wifi_credentials_form(self, mocker, mock_cm, mock_shutdown):
        mock_cb = MagicMock()
        mocker.patch("onboarding_portal.onboarding_complete_callback", mock_cb)

        mock_render = mocker.patch("onboarding_portal.render_template", return_value="<html>ok</html>")

        from onboarding_portal import app
        client = app.test_client()
        resp = client.post("/api/config", data={
            "wifiSsid": "FormNet",
            "wifiPassword": "formpass",
        })

        assert resp.status_code == 200
        mock_cm.update_from_onboarding.assert_called_once_with("FormNet", "formpass")
        mock_cm.save.assert_called_once()
        mock_cb.assert_called_once()
        mock_shutdown.assert_called_once()
        mock_render.assert_called_once_with("success.html")

    def test_missing_ssid_returns_400(self, mocker, mock_cm):
        from onboarding_portal import app
        client = app.test_client()

        resp = client.post("/api/config", json={"wifiPassword": "pass"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert "SSID" in data["error"]

        resp2 = client.post("/api/config", data={"wifiPassword": "pass"})
        assert resp2.status_code == 400
        assert "SSID" in resp2.data.decode()

    def test_ssid_too_long_returns_400(self, mocker, mock_cm):
        from onboarding_portal import app
        client = app.test_client()
        long_ssid = "A" * 33

        resp = client.post("/api/config", json={
            "wifiSsid": long_ssid, "wifiPassword": "pass"
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert "max 32" in data["error"]

        resp2 = client.post("/api/config", data={
            "wifiSsid": long_ssid, "wifiPassword": "pass"
        })
        assert resp2.status_code == 400
        assert "max 32" in resp2.data.decode()

    def test_password_too_long_returns_400(self, mocker, mock_cm):
        from onboarding_portal import app
        client = app.test_client()
        long_pw = "B" * 65

        resp = client.post("/api/config", json={
            "wifiSsid": "ValidNet", "wifiPassword": long_pw
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert "max 64" in data["error"]

        resp2 = client.post("/api/config", data={
            "wifiSsid": "ValidNet", "wifiPassword": long_pw
        })
        assert resp2.status_code == 400
        assert "max 64" in resp2.data.decode()

    def test_calls_onboarding_complete_callback(self, mocker, mock_cm, mock_shutdown):
        mock_cb = MagicMock()
        mocker.patch("onboarding_portal.onboarding_complete_callback", mock_cb)

        from onboarding_portal import app
        client = app.test_client()
        client.post("/api/config", json={
            "wifiSsid": "CallbackNet", "wifiPassword": "pass"
        })

        mock_cb.assert_called_once()

    def test_no_data_returns_400(self, mocker, mock_cm):
        from onboarding_portal import app
        client = app.test_client()

        resp = client.post("/api/config", json={})
        assert resp.status_code == 400

        resp2 = client.post("/api/config", data={})
        assert resp2.status_code == 400


class TestFavicon:
    def test_returns_svg_with_correct_content_type(self):
        from onboarding_portal import app
        client = app.test_client()
        resp = client.get("/favicon.ico")

        assert resp.status_code == 200
        assert resp.content_type == "image/svg+xml"
        assert b"<svg" in resp.data
        assert b"xmlns" in resp.data


class TestIndex:
    def test_returns_rendered_template(self, mocker):
        mock_render = mocker.patch(
            "onboarding_portal.render_template", return_value="<html>mocked</html>"
        )

        from onboarding_portal import app
        client = app.test_client()
        resp = client.get("/")

        assert resp.status_code == 200
        assert b"mocked" in resp.data
        mock_render.assert_called_once_with("index.html")


class TestSaveConfigExceptions:
    def test_save_config_generic_exception_json(self, mocker):
        mock_cm = MagicMock()
        mock_cm.get.return_value = ""
        mocker.patch("onboarding_portal.config_manager", mock_cm)
        mock_cm.save.side_effect = Exception("save error")

        from onboarding_portal import app
        client = app.test_client()
        resp = client.post("/api/config", json={
            "wifiSsid": "TestNet", "wifiPassword": "secret123"
        })
        assert resp.status_code == 500
        data = resp.get_json()
        assert "save error" in data["error"]

    def test_save_config_generic_exception_form(self, mocker):
        mock_cm = MagicMock()
        mock_cm.get.return_value = ""
        mocker.patch("onboarding_portal.config_manager", mock_cm)
        mock_cm.save.side_effect = Exception("save error")

        from onboarding_portal import app
        client = app.test_client()
        resp = client.post("/api/config", data={
            "wifiSsid": "TestNet", "wifiPassword": "secret123"
        })
        assert resp.status_code == 500
        assert b"save error" in resp.data


class TestShutdownServer:
    def test_shutdown_with_func(self):
        from onboarding_portal import app, _shutdown_server
        with app.test_request_context():
            from flask import request
            mock_func = MagicMock()
            request.environ["werkzeug.server.shutdown"] = mock_func
            _shutdown_server()
            mock_func.assert_called_once()

    def test_shutdown_without_func(self):
        from onboarding_portal import app, _shutdown_server
        with app.test_request_context():
            _shutdown_server()


class TestRunOnboardingServer:
    def test_run_onboarding_server_sets_callback_and_starts(self, mocker, minimal_config):
        mock_init = mocker.patch("onboarding_portal.init_onboarding")
        mock_app_run = mocker.patch("flask.Flask.run")

        from onboarding_portal import run_onboarding_server, onboarding_complete_callback
        assert onboarding_complete_callback is None

        callback = MagicMock()
        run_onboarding_server(minimal_config, host="192.168.4.1", port=8080,
                              callback=callback, network_mgr=None)

        from onboarding_portal import onboarding_complete_callback as cb
        assert cb is callback
        mock_init.assert_called_once_with(minimal_config, None)
        mock_app_run.assert_called_once_with(
            host="192.168.4.1", port=8080, debug=False,
            threaded=True, use_reloader=False
        )


class TestMainBlock:
    def test_main_block_executes_on_direct_run(self, mocker):
        import runpy
        import onboarding_portal

        mock_run = mocker.patch("flask.Flask.run")
        mock_cm_cls = mocker.patch("config_manager.ConfigManager")
        mock_cm = MagicMock()
        mock_cm.get_default_config.return_value = {"test_key": "test_value"}
        mock_cm_cls.return_value = mock_cm

        runpy.run_path(onboarding_portal.__file__,
                       init_globals=onboarding_portal.__dict__,
                       run_name="__main__")

        mock_run.assert_called_once()
