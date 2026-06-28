import copy
import signal
import asyncio
import threading
import pytest
from unittest.mock import MagicMock, AsyncMock, PropertyMock, call


@pytest.fixture(autouse=True)
def _mock_signal(mocker):
    mocker.patch("main.signal.signal")


@pytest.fixture(autouse=True)
def _mock_logging_config(mocker):
    mocker.patch("main.setup_logging")
    mocker.patch("main.generate_correlation_id", return_value="corr-123")
    mocker.patch("main.set_correlation_id")
    mocker.patch("main.clear_correlation_id")
    mocker.patch("main.update_log_levels")


@pytest.fixture(autouse=True)
def _mock_run_onboarding_server(mocker):
    mock = MagicMock()
    def invoke_callback(*args, **kwargs):
        callback = kwargs.get('callback')
        if callback:
            callback()
    mock.side_effect = invoke_callback
    mocker.patch("main.run_onboarding_server", mock)


@pytest.fixture(autouse=True)
def _patch_missing_run_health_monitor(mocker):
    mocker.patch("main.run_health_monitor", AsyncMock(), create=True)


@pytest.fixture
def mock_app_components(mocker):
    mocker.patch("main.SensorReader")
    mocker.patch("main.ActuatorController")
    mocker.patch("main.APIClient")
    mocker.patch("main.CameraService")
    mocker.patch("main.NetworkManager")
    mocker.patch("main.QueueManager")
    mocker.patch("main.UploadProcessor")
    mocker.patch("main.HealthMonitor")
    mocker.patch("main.ConfigWatcher")
    mocker.patch("main.AsyncIOScheduler")


@pytest.fixture
def config_mgr(mocker, minimal_config):
    cfg = copy.deepcopy(minimal_config)
    mock = MagicMock()
    mock.config = cfg
    mock.get.side_effect = lambda key, default=None: (
        cfg.get(key, default)
    )
    mock.is_provisioned.return_value = False
    mocker.patch("main.ConfigManager", return_value=mock)
    return mock


@pytest.fixture
def provisioned_config_mgr(mocker, minimal_config):
    cfg = copy.deepcopy(minimal_config)
    cfg["network"]["provisioned"] = True
    cfg["network"]["wifi_ssid"] = "MyWiFi"
    mock = MagicMock()
    mock.config = cfg
    mock.get.side_effect = lambda key, default=None: (
        cfg.get(key, default)
    )
    mock.is_provisioned.return_value = True
    mocker.patch("main.ConfigManager", return_value=mock)
    return mock


@pytest.fixture
def app_with_mocks(mocker, mock_app_components, config_mgr, minimal_config):
    cfg = copy.deepcopy(minimal_config)
    cfg["network"]["provisioned"] = True
    config_mgr.config = cfg
    config_mgr.get.side_effect = lambda key, default=None: cfg.get(key, default)

    from main import GrowMateApp
    app = GrowMateApp()
    app.config = cfg

    app.sensors = MagicMock()
    app.sensors.async_read_all_sensors = AsyncMock()
    app.sensors.async_get_current_state = AsyncMock()
    app.sensors.cleanup = MagicMock()

    app.actuators = MagicMock()
    app.actuators.async_get_state = AsyncMock()
    app.actuators.async_process_commands = AsyncMock()
    app.actuators.async_cleanup = AsyncMock()

    app.api_client = MagicMock()
    app.api_client.device_id = "growmate-test"
    app.api_client.upload_sensor_data = AsyncMock()
    app.api_client.initialize = AsyncMock()
    app.api_client.cleanup = AsyncMock()

    app.network = MagicMock()
    app.network.is_connected = AsyncMock()

    app.queue = None
    app.consecutive_failures = 0
    return app


class TestFullStartupShutdown:
    def test_full_startup_shutdown_cycle(self, mocker, mock_app_components, provisioned_config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["network"]["provisioned"] = True
        cfg["network"]["wifi_ssid"] = "MyWiFi"
        cfg["queue"]["enabled"] = False
        provisioned_config_mgr.config = cfg

        mock_api = MagicMock()
        mock_api.device_id = "growmate-test"
        mock_api.initialize = AsyncMock()
        mock_api.register_stream = AsyncMock(return_value=True)
        mock_api.cleanup = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = True
        mock_camera._port = 8554
        mock_camera.cleanup = MagicMock()
        mocker.patch("main.CameraService", return_value=mock_camera)

        mock_actuators = MagicMock()
        mock_actuators.async_cleanup = AsyncMock()
        mock_actuators.async_get_state = AsyncMock()
        mocker.patch("main.ActuatorController", return_value=mock_actuators)

        mock_sensors = MagicMock()
        mock_sensors.cleanup = MagicMock()
        mocker.patch("main.SensorReader", return_value=mock_sensors)

        mock_network = MagicMock()
        mock_network.stop_ap_mode = AsyncMock()
        mocker.patch("main.NetworkManager", return_value=mock_network)

        mock_scheduler = MagicMock()
        mocker.patch("main.AsyncIOScheduler", return_value=mock_scheduler)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.shutdown_event.set()

        result = asyncio.run(app.run_async())

        assert result == 0
        assert app.sensors is not None
        assert app.actuators is not None
        assert app.api_client is not None
        assert app.camera is not None
        assert app.network is not None
        mock_scheduler.add_job.assert_called()
        mock_scheduler.start.assert_called_once()
        mock_scheduler.shutdown.assert_called_once()

    def test_return_code_1_on_init_failure(self, mocker, mock_app_components, provisioned_config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["network"]["provisioned"] = True
        cfg["network"]["wifi_ssid"] = "MyWiFi"
        provisioned_config_mgr.config = cfg

        mock_sensors = MagicMock()
        mock_sensors.side_effect = Exception("init failure")
        mocker.patch("main.SensorReader", mock_sensors)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        result = asyncio.run(app.run_async())

        assert result == 1


class TestProvisioningFlow:
    def test_unprovisioned_enters_onboarding(self, mocker, mock_app_components, config_mgr, minimal_config):
        config_mgr.is_provisioned.return_value = False
        config_mgr.load.return_value = copy.deepcopy(minimal_config)

        from main import GrowMateApp
        app = GrowMateApp()

        mock_enter_ap = AsyncMock()
        mock_run_async = AsyncMock(return_value=0)
        app.enter_onboarding_mode = mock_enter_ap
        app.run_async = mock_run_async

        _real_asyncio_run = asyncio.run
        mocker.patch("main.asyncio.run", side_effect=lambda coro, *a, **kw: (
            _real_asyncio_run(coro, *a, **kw) if asyncio.iscoroutine(coro) else 0
        ))

        result = app.run()

        mock_enter_ap.assert_awaited_once()
        mock_run_async.assert_not_awaited()
        assert result == 0

    def test_provisioned_skips_onboarding(self, mocker, mock_app_components, provisioned_config_mgr, minimal_config):
        provisioned_config_mgr.is_provisioned.return_value = True
        provisioned_config_mgr.load.return_value = copy.deepcopy(minimal_config)

        from main import GrowMateApp
        app = GrowMateApp()

        mock_enter_ap = AsyncMock()
        mock_run_async = AsyncMock(return_value=0)
        app.enter_onboarding_mode = mock_enter_ap
        app.run_async = mock_run_async

        _real_asyncio_run = asyncio.run
        mocker.patch("main.asyncio.run", side_effect=lambda coro, *a, **kw: (
            _real_asyncio_run(coro, *a, **kw) if asyncio.iscoroutine(coro) else 0
        ))

        result = app.run()

        mock_enter_ap.assert_not_awaited()
        mock_run_async.assert_awaited_once()
        assert result == 0

    def test_onboarding_marks_provisioned(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        mock_network = MagicMock()
        mock_network.start_ap_mode = AsyncMock(return_value=True)
        mock_network.stop_ap_mode = AsyncMock(return_value=True)
        mock_network.connect_to_wifi = AsyncMock(return_value=True)

        config_mgr.get.side_effect = lambda key, default=None: {
            "network.wifi_ssid": "OnboardNet",
            "network.wifi_password": "onpass",
        }.get(key, default)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app._onboarding_complete.set()

        asyncio.run(app.enter_onboarding_mode(mock_network))

        mock_network.start_ap_mode.assert_awaited_once()
        mock_network.stop_ap_mode.assert_awaited_once()
        mock_network.connect_to_wifi.assert_awaited_once_with("OnboardNet", "onpass")
        config_mgr.set.assert_any_call("network.provisioned", True)
        config_mgr.save.assert_called_once()

    def test_onboarding_wifi_connect_fails_gracefully(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        mock_network = MagicMock()
        mock_network.start_ap_mode = AsyncMock(return_value=True)
        mock_network.stop_ap_mode = AsyncMock(return_value=True)
        mock_network.connect_to_wifi = AsyncMock(return_value=False)

        config_mgr.get.side_effect = lambda key, default=None: {
            "network.wifi_ssid": "BadNet",
            "network.wifi_password": "badpass",
        }.get(key, default)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app._onboarding_complete.set()

        asyncio.run(app.enter_onboarding_mode(mock_network))

        mock_network.start_ap_mode.assert_awaited_once()
        mock_network.stop_ap_mode.assert_awaited_once()
        mock_network.connect_to_wifi.assert_awaited_once_with("BadNet", "badpass")
        config_mgr.set.assert_not_called()

    def test_onboarding_with_network_none_creates_new(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        mock_network = MagicMock()
        mock_network.start_ap_mode = AsyncMock(return_value=True)
        mock_network.stop_ap_mode = AsyncMock(return_value=True)
        mock_network.connect_to_wifi = AsyncMock(return_value=True)
        mocker.patch("main.NetworkManager", return_value=mock_network)

        config_mgr.get.side_effect = lambda key, default=None: {
            "network.wifi_ssid": "TestNet",
            "network.wifi_password": "testpass",
        }.get(key, default)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app._onboarding_complete.set()

        asyncio.run(app.enter_onboarding_mode(None))

        mock_network.start_ap_mode.assert_awaited_once()
        mock_network.connect_to_wifi.assert_awaited_once_with("TestNet", "testpass")


class TestSignalHandling:
    def test_sigterm_sets_shutdown_event(self, mocker, mock_app_components, config_mgr):
        mock_loop = MagicMock()
        mocker.patch("main.asyncio.get_running_loop", return_value=mock_loop)

        from main import GrowMateApp
        app = GrowMateApp()

        app._signal_handler(signal.SIGTERM, None)

        mock_loop.call_soon_threadsafe.assert_called_once_with(app.shutdown_event.set)

    def test_sigint_sets_shutdown_event(self, mocker, mock_app_components, config_mgr):
        mock_loop = MagicMock()
        mocker.patch("main.asyncio.get_running_loop", return_value=mock_loop)

        from main import GrowMateApp
        app = GrowMateApp()

        app._signal_handler(signal.SIGINT, None)

        mock_loop.call_soon_threadsafe.assert_called_once_with(app.shutdown_event.set)

    def test_signal_handles_no_running_loop(self, mocker, mock_app_components, config_mgr):
        from main import GrowMateApp
        app = GrowMateApp()

        app._signal_handler(signal.SIGTERM, None)

    def test_signal_handles_runtime_error(self, mocker, mock_app_components, config_mgr):
        mocker.patch("main.asyncio.get_running_loop", side_effect=RuntimeError("no loop"))

        from main import GrowMateApp
        app = GrowMateApp()

        app._signal_handler(signal.SIGTERM, None)


class TestSensorReadingPipeline:
    def test_full_pipeline_with_direct_upload(self, app_with_mocks):
        app = app_with_mocks
        app.sensors.async_read_all_sensors = AsyncMock(return_value={"temperature": 25.0})
        app.sensors.async_get_current_state = AsyncMock(return_value={"mode": "auto"})
        app.actuators.async_get_state = AsyncMock(return_value={"pump": False})
        app.api_client.upload_sensor_data = AsyncMock(return_value=[{"actuator": "pump", "value": True}])
        app.network.is_connected = AsyncMock(return_value=True)

        asyncio.run(app.sensor_reading_job())

        app.sensors.async_read_all_sensors.assert_awaited_once()
        app.actuators.async_get_state.assert_awaited_once()
        app.sensors.async_get_current_state.assert_awaited_once_with({"pump": False})
        app.api_client.upload_sensor_data.assert_awaited_once_with(
            {"temperature": 25.0}, {"mode": "auto"}
        )
        app.actuators.async_process_commands.assert_awaited_once_with(
            [{"actuator": "pump", "value": True}]
        )
        assert app.consecutive_failures == 0

    def test_full_pipeline_with_queue(self, app_with_mocks):
        app = app_with_mocks
        app.queue = MagicMock()
        app.queue.async_enqueue_sensor_data = AsyncMock(return_value=True)
        app.sensors.async_read_all_sensors = AsyncMock(return_value={"temperature": 25.0})
        app.sensors.async_get_current_state = AsyncMock(return_value={"mode": "auto"})
        app.actuators.async_get_state = AsyncMock(return_value={"pump": False})

        asyncio.run(app.sensor_reading_job())

        app.queue.async_enqueue_sensor_data.assert_awaited_once()
        assert app.consecutive_failures == 0

    def test_pipeline_with_empty_sensor_data_increments_failures(self, app_with_mocks):
        app = app_with_mocks
        app.sensors.async_read_all_sensors = AsyncMock(return_value={})

        asyncio.run(app.sensor_reading_job())

        assert app.consecutive_failures == 1

    def test_pipeline_upload_failure_increments_failures(self, app_with_mocks):
        app = app_with_mocks
        app.sensors.async_read_all_sensors = AsyncMock(return_value={"temperature": 25.0})
        app.sensors.async_get_current_state = AsyncMock(return_value={"mode": "auto"})
        app.actuators.async_get_state = AsyncMock(return_value={"pump": False})
        app.api_client.upload_sensor_data = AsyncMock(return_value=None)
        app.network.is_connected = AsyncMock(return_value=True)

        asyncio.run(app.sensor_reading_job())

        app.actuators.async_process_commands.assert_not_awaited()
        assert app.consecutive_failures == 1

    def test_pipeline_skips_upload_when_wifi_disconnected_no_queue(self, app_with_mocks):
        app = app_with_mocks
        app.sensors.async_read_all_sensors = AsyncMock(return_value={"temperature": 25.0})
        app.sensors.async_get_current_state = AsyncMock(return_value={"mode": "auto"})
        app.actuators.async_get_state = AsyncMock(return_value={"pump": False})
        app.network.is_connected = AsyncMock(return_value=False)

        asyncio.run(app.sensor_reading_job())

        app.api_client.upload_sensor_data.assert_not_awaited()
        assert app.consecutive_failures == 1

    def test_pipeline_exception_increments_failures(self, app_with_mocks):
        app = app_with_mocks
        app.sensors.async_read_all_sensors = AsyncMock(side_effect=Exception("sensor error"))

        asyncio.run(app.sensor_reading_job())

        assert app.consecutive_failures == 1

    def test_pipeline_queue_failure_increments_failures(self, app_with_mocks):
        app = app_with_mocks
        app.queue = MagicMock()
        app.queue.async_enqueue_sensor_data = AsyncMock(return_value=False)
        app.sensors.async_read_all_sensors = AsyncMock(return_value={"temperature": 25.0})
        app.sensors.async_get_current_state = AsyncMock(return_value={"mode": "auto"})
        app.actuators.async_get_state = AsyncMock(return_value={"pump": False})

        asyncio.run(app.sensor_reading_job())

        assert app.consecutive_failures == 1


class TestFailureRecovery:
    def test_failure_monitor_triggers_re_onboarding(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["network"]["provisioned"] = True
        cfg["network"]["wifi_ssid"] = "MyWiFi"
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.consecutive_failures = 5

        app.scheduler = MagicMock()
        app.sensors = MagicMock()
        app.sensors.cleanup = MagicMock()
        app.actuators = MagicMock()
        app.actuators.async_cleanup = AsyncMock()
        app.api_client = MagicMock()
        app.api_client.cleanup = AsyncMock()
        app.camera = MagicMock()
        app.camera.cleanup = MagicMock()
        app.network = MagicMock()
        app.network.stop_ap_mode = AsyncMock()
        app.queue = MagicMock()
        app.queue.async_close = AsyncMock()

        mocker.patch.object(app, "enter_onboarding_mode", AsyncMock())
        mocker.patch.object(app, "initialize_components", AsyncMock(return_value=True))
        mocker.patch.object(app, "setup_scheduler", AsyncMock())
        mocker.patch.object(app, "load_configuration", return_value=True)

        asyncio.run(app.failure_monitor_job())

        app.scheduler.shutdown.assert_called_once_with(wait=False)
        app.enter_onboarding_mode.assert_awaited_once()
        app.initialize_components.assert_awaited_once()
        app.setup_scheduler.assert_awaited_once()
        assert app.consecutive_failures == 0

    def test_failure_monitor_below_threshold_does_nothing(self, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.consecutive_failures = 3
        app.scheduler = MagicMock()

        asyncio.run(app.failure_monitor_job())

        app.scheduler.shutdown.assert_not_called()

    def test_failure_monitor_with_upload_processor_task(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["network"]["provisioned"] = True
        cfg["network"]["wifi_ssid"] = "MyWiFi"
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.consecutive_failures = 5

        app.scheduler = MagicMock()
        app.sensors = MagicMock()
        app.sensors.cleanup = MagicMock()
        app.actuators = MagicMock()
        app.actuators.async_cleanup = AsyncMock()
        app.api_client = MagicMock()
        app.api_client.cleanup = AsyncMock()
        app.camera = MagicMock()
        app.camera.cleanup = MagicMock()
        app.network = MagicMock()
        app.network.stop_ap_mode = AsyncMock()
        app.queue = MagicMock()
        app.queue.async_close = AsyncMock()

        mocker.patch.object(app, "enter_onboarding_mode", AsyncMock())
        mocker.patch.object(app, "initialize_components", AsyncMock(return_value=True))
        mocker.patch.object(app, "setup_scheduler", AsyncMock())
        mocker.patch.object(app, "load_configuration", return_value=True)

        async def run():
            async def cancelled_task():
                raise asyncio.CancelledError()
            app.upload_processor_task = asyncio.create_task(cancelled_task())
            await asyncio.sleep(0)
            await app.failure_monitor_job()

        asyncio.run(run())

        app.scheduler.shutdown.assert_called_once_with(wait=False)
        app.enter_onboarding_mode.assert_awaited_once()

    def test_failure_monitor_exception_does_not_crash(self, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.consecutive_failures = 10
        app.scheduler = MagicMock()
        app.scheduler.shutdown.side_effect = Exception("shutdown error")

        asyncio.run(app.failure_monitor_job())


class TestCameraWatchdog:
    def test_watchdog_restarts_dead_process(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        mock_camera = MagicMock()
        mock_camera.is_process_alive.return_value = False
        mock_camera.restart_stream.return_value = True
        mock_camera._port = 8554
        app.camera = mock_camera

        app.api_client = MagicMock()
        app.api_client.register_stream = AsyncMock(return_value=True)

        asyncio.run(app.camera_watchdog_job())

        mock_camera.is_process_alive.assert_called_once()
        mock_camera.restart_stream.assert_called_once()
        app.api_client.register_stream.assert_awaited_once()

    def test_watchdog_skips_when_alive(self, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        mock_camera = MagicMock()
        mock_camera.is_process_alive.return_value = True
        app.camera = mock_camera

        asyncio.run(app.camera_watchdog_job())

        mock_camera.restart_stream.assert_not_called()

    def test_watchdog_skips_when_no_camera(self, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.camera = None

        asyncio.run(app.camera_watchdog_job())

    def test_watchdog_restart_failure_does_not_crash(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        mock_camera = MagicMock()
        mock_camera.is_process_alive.return_value = False
        mock_camera.restart_stream.return_value = False
        mock_camera._port = 8554
        app.camera = mock_camera

        app.api_client = MagicMock()
        app.api_client.register_stream = AsyncMock(return_value=True)

        asyncio.run(app.camera_watchdog_job())

        mock_camera.restart_stream.assert_called_once()
        app.api_client.register_stream.assert_not_awaited()


class TestConfigHotReload:
    def test_config_change_triggers_reload(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        config_mgr.reload = MagicMock(return_value={"intervals.sensor_reading": (60, 30)})
        mocker.patch.object(app.config_manager, 'reload', config_mgr.reload)

        app._on_config_file_changed()

        config_mgr.reload.assert_called_once()

    def test_config_change_updates_scheduler_interval(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.scheduler = MagicMock()
        changes = {"intervals.sensor_reading": (60, 30)}

        app.on_config_reload(changes)

        app.scheduler.reschedule_job.assert_called_once_with(
            'sensor_reading',
            trigger=mocker.ANY,
        )

    def test_config_change_updates_retry_settings(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.api_client = MagicMock()
        changes = {"retry.max_attempts": (6, 10), "retry.initial_delay": (1.0, 2.0)}

        app.on_config_reload(changes)

        app.api_client.update_retry_config.assert_called_once_with(cfg.get('retry', {}))

    def test_config_change_updates_circuit_breaker(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.api_client = MagicMock()
        changes = {"circuit_breaker.failure_threshold": (5, 10)}

        app.on_config_reload(changes)

        app.api_client.update_circuit_breaker_config.assert_called_once_with(cfg.get('circuit_breaker', {}))

    def test_config_change_reload_exception_handled(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        config_mgr.reload = MagicMock(side_effect=Exception("reload error"))
        mocker.patch.object(app.config_manager, 'reload', config_mgr.reload)

        app._on_config_file_changed()


class TestErrorPaths:
    def test_component_init_returns_false(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["queue"]["enabled"] = False
        config_mgr.config = cfg

        mock_sensors = MagicMock()
        mock_sensors.side_effect = Exception("sensor error")
        mocker.patch("main.SensorReader", mock_sensors)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        result = asyncio.run(app.initialize_components())
        assert result is False

    def test_network_manager_init_failure_sets_none(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["queue"]["enabled"] = False
        config_mgr.config = cfg

        mock_sensors = MagicMock()
        mock_sensors.cleanup = MagicMock()
        mocker.patch("main.SensorReader", return_value=mock_sensors)

        mock_actuators = MagicMock()
        mock_actuators.async_cleanup = AsyncMock()
        mocker.patch("main.ActuatorController", return_value=mock_actuators)

        mock_api = MagicMock()
        mock_api.device_id = "test"
        mock_api.initialize = AsyncMock()
        mock_api.cleanup = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = True
        mocker.patch("main.CameraService", return_value=mock_camera)

        mocker.patch("main.NetworkManager", side_effect=Exception("network error"))

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        result = asyncio.run(app.initialize_components())
        assert result is True
        assert app.network is None

    def test_queue_init_failure_returns_false(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["queue"]["enabled"] = True
        config_mgr.config = cfg

        mock_sensors = MagicMock()
        mock_sensors.cleanup = MagicMock()
        mocker.patch("main.SensorReader", return_value=mock_sensors)

        mock_actuators = MagicMock()
        mock_actuators.async_cleanup = AsyncMock()
        mocker.patch("main.ActuatorController", return_value=mock_actuators)

        mock_api = MagicMock()
        mock_api.device_id = "test"
        mock_api.initialize = AsyncMock()
        mock_api.cleanup = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = True
        mocker.patch("main.CameraService", return_value=mock_camera)

        mock_network = MagicMock()
        mocker.patch("main.NetworkManager", return_value=mock_network)

        mock_queue = MagicMock()
        mock_queue.async_initialize = AsyncMock(return_value=False)
        mocker.patch("main.QueueManager", return_value=mock_queue)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        result = asyncio.run(app.initialize_components())
        assert result is False

    def test_camera_startup_failure_logs_warning(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["queue"]["enabled"] = False
        config_mgr.config = cfg

        mock_sensors = MagicMock()
        mock_sensors.cleanup = MagicMock()
        mocker.patch("main.SensorReader", return_value=mock_sensors)

        mock_actuators = MagicMock()
        mock_actuators.async_cleanup = AsyncMock()
        mocker.patch("main.ActuatorController", return_value=mock_actuators)

        mock_api = MagicMock()
        mock_api.device_id = "test"
        mock_api.initialize = AsyncMock()
        mock_api.cleanup = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = False
        mocker.patch("main.CameraService", return_value=mock_camera)

        mock_network = MagicMock()
        mocker.patch("main.NetworkManager", return_value=mock_network)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        result = asyncio.run(app.initialize_components())
        assert result is True


class TestCleanupPathways:
    def test_cleanup_all_components(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.sensors = MagicMock()
        app.sensors.cleanup = MagicMock()
        app.actuators = MagicMock()
        app.actuators.async_cleanup = AsyncMock()
        app.api_client = MagicMock()
        app.api_client.cleanup = AsyncMock()
        app.camera = MagicMock()
        app.camera.cleanup = MagicMock()
        app.network = MagicMock()
        app.network.stop_ap_mode = AsyncMock()
        app.queue = MagicMock()
        app.queue.async_close = AsyncMock()
        app.config_watcher = MagicMock()

        async def run_cleanup():
            app.upload_processor_task = asyncio.create_task(asyncio.sleep(0))
            app.health_monitor_task = asyncio.create_task(asyncio.sleep(0))
            await app.cleanup()

        asyncio.run(run_cleanup())

        app.config_watcher.stop.assert_called_once()
        app.actuators.async_cleanup.assert_awaited_once()
        app.sensors.cleanup.assert_called_once()
        app.camera.cleanup.assert_called_once()
        app.network.stop_ap_mode.assert_awaited_once()
        app.api_client.cleanup.assert_awaited_once()
        app.queue.async_close.assert_awaited_once()

    def test_cleanup_with_none_components(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.sensors = None
        app.actuators = None
        app.api_client = None
        app.camera = None
        app.network = None
        app.queue = None
        app.config_watcher = None

        asyncio.run(app.cleanup())

    def test_cleanup_cancels_tasks(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.sensors = MagicMock()
        app.sensors.cleanup = MagicMock()
        app.actuators = MagicMock()
        app.actuators.async_cleanup = AsyncMock()
        app.api_client = MagicMock()
        app.api_client.cleanup = AsyncMock()
        app.camera = MagicMock()
        app.camera.cleanup = MagicMock()
        app.network = MagicMock()
        app.network.stop_ap_mode = AsyncMock()

        cancelled_health = False
        cancelled_upload = False

        async def health_task():
            nonlocal cancelled_health
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                cancelled_health = True
                raise

        async def upload_task():
            nonlocal cancelled_upload
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                cancelled_upload = True
                raise

        async def run():
            app.health_monitor_task = asyncio.create_task(health_task())
            app.upload_processor_task = asyncio.create_task(upload_task())
            await asyncio.sleep(0)
            await app.cleanup()

        asyncio.run(run())
        assert cancelled_health
        assert cancelled_upload

    def test_cleanup_handles_network_exception(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.network = MagicMock()
        app.network.stop_ap_mode = AsyncMock(side_effect=Exception("network error"))

        asyncio.run(app.cleanup())

        app.network.stop_ap_mode.assert_awaited_once()


class TestMainEntryPoint:
    def test_main_creates_app_and_calls_run(self, mocker):
        mock_app = MagicMock()
        mock_app.run.return_value = 0
        mocker.patch("main.GrowMateApp", return_value=mock_app)
        mocker.patch("main.sys.exit")

        from main import main
        main()

        mock_app.run.assert_called_once()
        import main as main_module
        main_module.sys.exit.assert_called_once_with(0)

    def test_main_returns_1_on_fatal_error(self, mocker, mock_app_components, config_mgr, minimal_config):
        config_mgr.load.return_value = copy.deepcopy(minimal_config)
        config_mgr.is_provisioned.return_value = True

        mock_run_async = AsyncMock(return_value=1)
        _real_asyncio_run = asyncio.run
        mocker.patch("main.asyncio.run", side_effect=lambda coro, *a, **kw: (
            _real_asyncio_run(coro, *a, **kw) if asyncio.iscoroutine(coro) else 0
        ))

        from main import GrowMateApp
        app = GrowMateApp()
        app.run_async = mock_run_async

        result = app.run()

        assert result == 1


class TestRunAsync:
    def test_run_async_sets_up_scheduler_and_stream_registration(self, mocker, mock_app_components, provisioned_config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["queue"]["enabled"] = False
        cfg["network"]["provisioned"] = True
        cfg["network"]["wifi_ssid"] = "MyWiFi"
        provisioned_config_mgr.config = cfg

        mock_scheduler = MagicMock()
        mocker.patch("main.AsyncIOScheduler", return_value=mock_scheduler)

        mock_api = MagicMock()
        mock_api.device_id = "test"
        mock_api.initialize = AsyncMock()
        mock_api.register_stream = AsyncMock(return_value=True)
        mock_api.cleanup = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = True
        mock_camera._port = 8554
        mock_camera.cleanup = MagicMock()
        mocker.patch("main.CameraService", return_value=mock_camera)

        mock_actuators = MagicMock()
        mock_actuators.async_cleanup = AsyncMock()
        mock_actuators.async_get_state = AsyncMock(return_value={})
        mocker.patch("main.ActuatorController", return_value=mock_actuators)

        mock_sensors = MagicMock()
        mock_sensors.cleanup = MagicMock()
        mocker.patch("main.SensorReader", return_value=mock_sensors)

        mock_network = MagicMock()
        mock_network.stop_ap_mode = AsyncMock()
        mocker.patch("main.NetworkManager", return_value=mock_network)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.shutdown_event.set()

        result = asyncio.run(app.run_async())

        assert result == 0
        mock_scheduler.add_job.assert_called()
        mock_scheduler.start.assert_called_once()
        mock_scheduler.shutdown.assert_called_once()

    def test_run_async_with_queue_starts_upload_processor(self, mocker, mock_app_components, provisioned_config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["network"]["provisioned"] = True
        cfg["network"]["wifi_ssid"] = "MyWiFi"
        cfg["queue"]["enabled"] = True
        provisioned_config_mgr.config = cfg

        mock_scheduler = MagicMock()
        mocker.patch("main.AsyncIOScheduler", return_value=mock_scheduler)

        mock_api = MagicMock()
        mock_api.device_id = "test"
        mock_api.initialize = AsyncMock()
        mock_api.register_stream = AsyncMock(return_value=True)
        mock_api.cleanup = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = True
        mock_camera._port = 8554
        mock_camera.cleanup = MagicMock()
        mocker.patch("main.CameraService", return_value=mock_camera)

        mock_actuators = MagicMock()
        mock_actuators.async_cleanup = AsyncMock()
        mock_actuators.async_get_state = AsyncMock(return_value={})
        mocker.patch("main.ActuatorController", return_value=mock_actuators)

        mock_sensors = MagicMock()
        mock_sensors.cleanup = MagicMock()
        mocker.patch("main.SensorReader", return_value=mock_sensors)

        mock_network = MagicMock()
        mock_network.stop_ap_mode = AsyncMock()
        mocker.patch("main.NetworkManager", return_value=mock_network)

        mock_queue = MagicMock()
        mock_queue.async_initialize = AsyncMock(return_value=True)
        mock_queue.async_close = AsyncMock()
        mocker.patch("main.QueueManager", return_value=mock_queue)

        mock_upload_processor = MagicMock()
        mock_upload_processor.run_continuous = AsyncMock()
        mocker.patch("main.UploadProcessor", return_value=mock_upload_processor)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.shutdown_event.set()

        result = asyncio.run(app.run_async())

        assert result == 0
        mock_upload_processor.run_continuous.assert_called_once()

    def test_run_async_with_config_watcher(self, mocker, mock_app_components, provisioned_config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["network"]["provisioned"] = True
        cfg["network"]["wifi_ssid"] = "MyWiFi"
        cfg["queue"]["enabled"] = False
        cfg["features"]["hot_reload"] = True
        provisioned_config_mgr.config = cfg

        mock_scheduler = MagicMock()
        mocker.patch("main.AsyncIOScheduler", return_value=mock_scheduler)

        mock_api = MagicMock()
        mock_api.device_id = "test"
        mock_api.initialize = AsyncMock()
        mock_api.register_stream = AsyncMock(return_value=True)
        mock_api.cleanup = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = True
        mock_camera._port = 8554
        mock_camera.cleanup = MagicMock()
        mocker.patch("main.CameraService", return_value=mock_camera)

        mock_actuators = MagicMock()
        mock_actuators.async_cleanup = AsyncMock()
        mock_actuators.async_get_state = AsyncMock(return_value={})
        mocker.patch("main.ActuatorController", return_value=mock_actuators)

        mock_sensors = MagicMock()
        mock_sensors.cleanup = MagicMock()
        mocker.patch("main.SensorReader", return_value=mock_sensors)

        mock_network = MagicMock()
        mock_network.stop_ap_mode = AsyncMock()
        mocker.patch("main.NetworkManager", return_value=mock_network)

        mock_config_watcher = MagicMock()
        mocker.patch("main.ConfigWatcher", return_value=mock_config_watcher)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.shutdown_event.set()

        result = asyncio.run(app.run_async())

        assert result == 0
        mock_config_watcher.start.assert_called_once()

    def test_run_async_with_hot_reload_disabled(self, mocker, mock_app_components, provisioned_config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["network"]["provisioned"] = True
        cfg["network"]["wifi_ssid"] = "MyWiFi"
        cfg["queue"]["enabled"] = False
        cfg["features"]["hot_reload"] = False
        provisioned_config_mgr.config = cfg

        mock_scheduler = MagicMock()
        mocker.patch("main.AsyncIOScheduler", return_value=mock_scheduler)

        mock_api = MagicMock()
        mock_api.device_id = "test"
        mock_api.initialize = AsyncMock()
        mock_api.register_stream = AsyncMock(return_value=True)
        mock_api.cleanup = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = True
        mock_camera._port = 8554
        mock_camera.cleanup = MagicMock()
        mocker.patch("main.CameraService", return_value=mock_camera)

        mock_actuators = MagicMock()
        mock_actuators.async_cleanup = AsyncMock()
        mock_actuators.async_get_state = AsyncMock(return_value={})
        mocker.patch("main.ActuatorController", return_value=mock_actuators)

        mock_sensors = MagicMock()
        mock_sensors.cleanup = MagicMock()
        mocker.patch("main.SensorReader", return_value=mock_sensors)

        mock_network = MagicMock()
        mock_network.stop_ap_mode = AsyncMock()
        mocker.patch("main.NetworkManager", return_value=mock_network)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.shutdown_event.set()

        result = asyncio.run(app.run_async())

        assert result == 0

    def test_run_async_catches_fatal_error(self, mocker, mock_app_components, provisioned_config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["network"]["provisioned"] = True
        cfg["network"]["wifi_ssid"] = "MyWiFi"
        provisioned_config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        mocker.patch.object(app, "initialize_components", AsyncMock(side_effect=Exception("fatal")))

        result = asyncio.run(app.run_async())

        assert result == 1


class TestStreamRegistration:
    def test_stream_registration_retry_loop(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.camera = MagicMock()
        app.camera._port = 8554
        app.api_client = MagicMock()
        app.api_client.register_stream = AsyncMock()
        app.api_client.register_stream.side_effect = [False, False, True]

        mocker.patch("main.asyncio.wait_for", side_effect=asyncio.TimeoutError())

        asyncio.run(app._register_stream_with_retry())

        assert app.api_client.register_stream.await_count == 3

    def test_stream_registration_returns_early_on_shutdown(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.camera = MagicMock()
        app.camera._port = 8554
        app.api_client = MagicMock()
        call_count = 0
        async def register_stream_side_effect(url):
            nonlocal call_count
            call_count += 1
            app.shutdown_event.set()
            return True
        app.api_client.register_stream = AsyncMock(side_effect=register_stream_side_effect)

        asyncio.run(app._register_stream_with_retry())

        assert call_count == 1

    def test_stream_registration_with_no_api_client(self, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.api_client = None

        asyncio.run(app._register_stream_with_retry())


class TestQueueJobs:
    def test_queue_cleanup_job(self, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.queue = MagicMock()
        app.queue.async_cleanup_old_entries = AsyncMock(return_value=5)

        asyncio.run(app.queue_cleanup_job())

        app.queue.async_cleanup_old_entries.assert_awaited_once_with(24)

    def test_queue_cleanup_job_no_queue(self, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.queue = None

        asyncio.run(app.queue_cleanup_job())

    def test_queue_stats_job(self, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.queue = MagicMock()
        app.queue.async_get_queue_stats = AsyncMock(return_value={
            "sensor_queue": {"pending": 3},
            "metadata": {},
        })
        app.upload_processor = MagicMock()
        app.upload_processor.get_stats.return_value = {
            "sensor_uploads_success": 10,
            "sensor_uploads_failed": 0,
            "total_processed": 10,
        }

        asyncio.run(app.queue_stats_job())

        app.queue.async_get_queue_stats.assert_awaited_once()
        app.upload_processor.get_stats.assert_called_once()

    def test_queue_stats_job_no_queue(self, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.queue = None

        asyncio.run(app.queue_stats_job())
