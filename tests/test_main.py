import copy
import signal
import asyncio
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


class TestApplicationInitialization:
    def test_initializes_all_components(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg
        config_mgr.get.side_effect = lambda key, default=None: cfg.get(key, default)

        mock_api = MagicMock()
        mock_api.device_id = "growmate-test"
        mock_api.initialize = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = True
        mocker.patch("main.CameraService", return_value=mock_camera)

        mock_queue = MagicMock()
        mock_queue.async_initialize = AsyncMock(return_value=True)
        mocker.patch("main.QueueManager", return_value=mock_queue)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        result = asyncio.run(app.initialize_components())

        assert result is True

        import main as main_module
        main_module.SensorReader.assert_called_once_with(cfg.get("sensors", {}))
        main_module.ActuatorController.assert_called_once_with(cfg.get("actuators", {}))
        main_module.APIClient.assert_called_once_with(cfg)
        mock_api.initialize.assert_awaited_once()
        main_module.CameraService.assert_called_once_with(cfg.get("camera", {}))
        mock_camera.start_stream.assert_called_once()
        main_module.NetworkManager.assert_called_once_with(cfg)
        main_module.QueueManager.assert_called_once()
        main_module.UploadProcessor.assert_called_once()
        main_module.HealthMonitor.assert_called_once()

        assert app.sensors is not None
        assert app.actuators is not None
        assert app.api_client is not None
        assert app.camera is not None
        assert app.network is not None
        assert app.queue is not None
        assert app.upload_processor is not None
        assert app.health_monitor is not None

    def test_component_init_failure_returns_false(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["queue"]["enabled"] = False

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        mock_sensors = MagicMock()
        mock_sensors.side_effect = Exception("sensor error")
        mocker.patch("main.SensorReader", mock_sensors)

        result = asyncio.run(app.initialize_components())
        assert result is False


class TestProvisioningMode:
    def test_enters_ap_mode_when_not_provisioned(self, mocker, mock_app_components, config_mgr, minimal_config):
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

    def test_skips_ap_mode_when_provisioned(self, mocker, mock_app_components, config_mgr, minimal_config):
        config_mgr.is_provisioned.return_value = True
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

        mock_enter_ap.assert_not_awaited()
        mock_run_async.assert_awaited_once()
        assert result == 0


class TestSensorReadingJob:
    @pytest.fixture
    def app_with_mocks(self, mocker, mock_app_components, config_mgr, minimal_config):
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

    @pytest.fixture
    def app_with_queue(self, app_with_mocks):
        app_with_mocks.queue = MagicMock()
        app_with_mocks.queue.async_enqueue_sensor_data = AsyncMock(return_value=True)
        return app_with_mocks

    def test_read_upload_execute_cycle(self, app_with_mocks):
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

    def test_handles_upload_failure_gracefully(self, app_with_mocks):
        app = app_with_mocks
        app.sensors.async_read_all_sensors = AsyncMock(return_value={"temperature": 25.0})
        app.sensors.async_get_current_state = AsyncMock(return_value={"mode": "auto"})
        app.actuators.async_get_state = AsyncMock(return_value={"pump": False})
        app.api_client.upload_sensor_data = AsyncMock(return_value=None)
        app.network.is_connected = AsyncMock(return_value=True)

        asyncio.run(app.sensor_reading_job())

        app.api_client.upload_sensor_data.assert_awaited_once()
        app.actuators.async_process_commands.assert_not_awaited()
        assert app.consecutive_failures == 1

    def test_queue_processing_after_upload(self, app_with_queue):
        app = app_with_queue
        app.sensors.async_read_all_sensors = AsyncMock(return_value={"temperature": 25.0})
        app.sensors.async_get_current_state = AsyncMock(return_value={"mode": "auto"})
        app.actuators.async_get_state = AsyncMock(return_value={"pump": False})

        asyncio.run(app.sensor_reading_job())

        app.queue.async_enqueue_sensor_data.assert_awaited_once()
        assert app.consecutive_failures == 0

    def test_sensor_read_failure_increments_counter(self, app_with_mocks):
        app = app_with_mocks
        app.sensors.async_read_all_sensors = AsyncMock(return_value={})

        asyncio.run(app.sensor_reading_job())

        assert app.consecutive_failures == 1

    def test_sensor_read_exception_increments_counter(self, app_with_mocks):
        app = app_with_mocks
        app.sensors.async_read_all_sensors = AsyncMock(
            side_effect=Exception("sensor read error")
        )

        asyncio.run(app.sensor_reading_job())

        assert app.consecutive_failures == 1


class TestSignalHandler:
    def test_triggers_graceful_shutdown(self, mocker, mock_app_components, config_mgr):
        mock_loop = MagicMock()
        mocker.patch("main.asyncio.get_running_loop", return_value=mock_loop)

        from main import GrowMateApp
        app = GrowMateApp()

        app._signal_handler(signal.SIGTERM, None)

        mock_loop.call_soon_threadsafe.assert_called_once_with(app.shutdown_event.set)

    def test_handles_no_running_loop(self, mocker, mock_app_components, config_mgr):
        from main import GrowMateApp
        app = GrowMateApp()

        app._signal_handler(signal.SIGTERM, None)


class TestCleanup:
    def test_stops_all_components(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.sensors = MagicMock()
        app.actuators = MagicMock()
        app.actuators.async_cleanup = AsyncMock()
        app.api_client = MagicMock()
        app.api_client.cleanup = AsyncMock()
        app.camera = MagicMock()
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

    def test_camera_starts_and_stops_with_app(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = True
        mock_camera.cleanup = MagicMock()
        mocker.patch("main.CameraService", return_value=mock_camera)

        mock_api = MagicMock()
        mock_api.device_id = "test"
        mock_api.initialize = AsyncMock()
        mock_api.cleanup = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_queue = MagicMock()
        mock_queue.async_initialize = AsyncMock(return_value=True)
        mock_queue.async_close = AsyncMock()
        mocker.patch("main.QueueManager", return_value=mock_queue)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        asyncio.run(app.initialize_components())

        app.actuators.async_cleanup = AsyncMock()
        app.sensors.cleanup = MagicMock()
        app.network.stop_ap_mode = AsyncMock()

        mock_camera.start_stream.assert_called_once()

        asyncio.run(app.cleanup())

        mock_camera.cleanup.assert_called_once()


class TestHealthMonitorLifecycle:
    def test_health_monitor_initialized_and_task_lifecycle(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg
        cfg["queue"]["enabled"] = False

        mocker.patch("main.ConfigWatcher")

        mock_health = MagicMock()
        mocker.patch("main.HealthMonitor", return_value=mock_health)

        mock_api = MagicMock()
        mock_api.device_id = "test"
        mock_api.initialize = AsyncMock()
        mock_api.register_stream = AsyncMock(return_value=True)
        mock_api.cleanup = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = True
        mock_camera.cleanup = MagicMock()
        mocker.patch("main.CameraService", return_value=mock_camera)

        mock_actuators = MagicMock()
        mock_actuators.async_cleanup = AsyncMock()
        mock_actuators.async_get_state = AsyncMock(return_value={})
        mock_actuators.async_process_commands = AsyncMock()
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

        assert app.health_monitor is not None
        assert result == 0


class TestRunAsync:
    def test_run_async_sets_up_scheduler_and_waits_for_shutdown(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["queue"]["enabled"] = False
        config_mgr.config = cfg

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

    def test_returns_1_on_initialization_failure(self, mocker, mock_app_components, config_mgr):
        from main import GrowMateApp
        app = GrowMateApp()

        mocker.patch.object(app, "initialize_components", AsyncMock(return_value=False))

        result = asyncio.run(app.run_async())

        assert result == 1


class TestMainFunction:
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

    def test_run_fatal_error_returns_1(self, mocker, mock_app_components, config_mgr, minimal_config):
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


class TestEnterOnboardingMode:
    def test_onboarding_mode_flow(self, mocker, mock_app_components, config_mgr, minimal_config):
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


class TestCameraInitFailure:
    def test_camera_start_stream_returns_false(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg
        config_mgr.get.side_effect = lambda key, default=None: cfg.get(key, default)

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = False
        mocker.patch("main.CameraService", return_value=mock_camera)

        mock_api = MagicMock()
        mock_api.device_id = "test"
        mock_api.initialize = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_queue = MagicMock()
        mock_queue.async_initialize = AsyncMock(return_value=True)
        mocker.patch("main.QueueManager", return_value=mock_queue)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        result = asyncio.run(app.initialize_components())
        assert result is True


class TestNetworkManagerInitFailure:
    def test_network_manager_init_raises(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg
        config_mgr.get.side_effect = lambda key, default=None: cfg.get(key, default)

        mock_api = MagicMock()
        mock_api.device_id = "test"
        mock_api.initialize = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = True
        mocker.patch("main.CameraService", return_value=mock_camera)

        mock_queue = MagicMock()
        mock_queue.async_initialize = AsyncMock(return_value=True)
        mocker.patch("main.QueueManager", return_value=mock_queue)

        mocker.patch("main.NetworkManager", side_effect=Exception("network error"))

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        result = asyncio.run(app.initialize_components())
        assert result is True
        assert app.network is None


class TestQueueInitFailure:
    def test_queue_async_initialize_returns_false(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg
        config_mgr.get.side_effect = lambda key, default=None: cfg.get(key, default)

        mock_api = MagicMock()
        mock_api.device_id = "test"
        mock_api.initialize = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = True
        mocker.patch("main.CameraService", return_value=mock_camera)

        mock_queue = MagicMock()
        mock_queue.async_initialize = AsyncMock(return_value=False)
        mocker.patch("main.QueueManager", return_value=mock_queue)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        result = asyncio.run(app.initialize_components())
        assert result is False


class TestQueueDisabled:
    def test_queue_disabled_online_only(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["queue"]["enabled"] = False
        config_mgr.config = cfg
        config_mgr.get.side_effect = lambda key, default=None: cfg.get(key, default)

        mock_api = MagicMock()
        mock_api.device_id = "test"
        mock_api.initialize = AsyncMock()
        mocker.patch("main.APIClient", return_value=mock_api)

        mock_camera = MagicMock()
        mock_camera.start_stream.return_value = True
        mocker.patch("main.CameraService", return_value=mock_camera)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        result = asyncio.run(app.initialize_components())
        assert result is True
        assert app.queue is None
        assert app.upload_processor is None


class TestEnterOnboardingModeFailures:
    def test_start_ap_mode_fails(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        mock_network = MagicMock()
        mock_network.start_ap_mode = AsyncMock(return_value=False)
        mock_network.stop_ap_mode = AsyncMock()

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        asyncio.run(app.enter_onboarding_mode(mock_network))

        mock_network.start_ap_mode.assert_awaited_once()
        mock_network.stop_ap_mode.assert_not_awaited()

    def test_connect_onboarding_wifi_exception(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg
        config_mgr.get.side_effect = lambda key, default=None: {
            "network.wifi_ssid": "TestNet",
            "network.wifi_password": "testpass",
        }.get(key, default)

        mock_network = MagicMock()
        mock_network.connect_to_wifi = AsyncMock(side_effect=Exception("wifi error"))

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        asyncio.run(app._connect_onboarding_wifi(mock_network))
        mock_network.connect_to_wifi.assert_awaited_once_with("TestNet", "testpass")


class TestTailscaleIP:
    def test_get_tailscale_ip_filenotfound(self, mocker):
        mocker.patch("main.asyncio.create_subprocess_exec", side_effect=FileNotFoundError)

        from main import GrowMateApp
        app = GrowMateApp()

        result = asyncio.run(app._get_tailscale_ip())
        assert result is None

    def test_get_tailscale_ip_exception(self, mocker):
        mocker.patch("main.asyncio.create_subprocess_exec", side_effect=Exception("generic error"))

        from main import GrowMateApp
        app = GrowMateApp()

        result = asyncio.run(app._get_tailscale_ip())
        assert result is None

    def test_get_tailscale_ip_subprocess_fails(self, mocker):
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b"", b"tailscale error"))
        mock_create = AsyncMock(return_value=mock_process)
        mocker.patch("main.asyncio.create_subprocess_exec", mock_create)

        from main import GrowMateApp
        app = GrowMateApp()

        result = asyncio.run(app._get_tailscale_ip())
        assert result is None


class TestRegisterStreamWithRetry:
    def test_register_stream_no_api_client(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.api_client = None

        asyncio.run(app._register_stream_with_retry())

    def test_register_stream_fallback_ip(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        mock_api = MagicMock()
        mock_api.register_stream = AsyncMock(return_value=True)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.api_client = mock_api
        app.camera = MagicMock()
        app.camera._port = 8554

        mocker.patch.object(app, "_get_tailscale_ip", AsyncMock(return_value=None))

        asyncio.run(app._register_stream_with_retry())

        mock_api.register_stream.assert_awaited_once()

    def test_register_stream_all_attempts_fail(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["stream_registration"]["max_attempts"] = 3
        cfg["stream_registration"]["base_delay"] = 0.01
        cfg["stream_registration"]["max_delay"] = 0.05
        config_mgr.config = cfg

        mock_api = MagicMock()
        mock_api.register_stream = AsyncMock(return_value=False)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.api_client = mock_api

        mocker.patch.object(app, "_get_tailscale_ip", AsyncMock(return_value="100.64.0.1"))

        asyncio.run(app._register_stream_with_retry())

        assert mock_api.register_stream.await_count == 3

    def test_register_stream_shutdown_during_retry(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["stream_registration"]["max_attempts"] = 3
        cfg["stream_registration"]["base_delay"] = 0.5
        cfg["stream_registration"]["max_delay"] = 1.0
        config_mgr.config = cfg

        mock_api = MagicMock()
        mock_api.register_stream = AsyncMock(return_value=False)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.api_client = mock_api

        mocker.patch.object(app, "_get_tailscale_ip", AsyncMock(return_value="100.64.0.1"))

        async def run():
            asyncio.get_running_loop().call_later(0.01, app.shutdown_event.set)
            await app._register_stream_with_retry()

        asyncio.run(run())

        assert mock_api.register_stream.await_count == 1


class TestSensorReadingJobExtended:
    @pytest.fixture
    def app_with_mocks(self, mocker, mock_app_components, config_mgr, minimal_config):
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

    def test_queue_branch_enqueue_fails(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg
        config_mgr.get.side_effect = lambda key, default=None: cfg.get(key, default)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.sensors = MagicMock()
        app.sensors.async_read_all_sensors = AsyncMock(return_value={"temperature": 25.0})
        app.sensors.async_get_current_state = AsyncMock(return_value={"mode": "auto"})
        app.actuators = MagicMock()
        app.actuators.async_get_state = AsyncMock(return_value={"pump": False})
        app.api_client = MagicMock()
        app.api_client.device_id = "test"

        app.queue = MagicMock()
        app.queue.async_enqueue_sensor_data = AsyncMock(return_value=False)
        app.network = None
        app.consecutive_failures = 0

        asyncio.run(app.sensor_reading_job())
        assert app.consecutive_failures == 1

    def test_no_queue_no_wifi(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg
        config_mgr.get.side_effect = lambda key, default=None: cfg.get(key, default)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.sensors = MagicMock()
        app.sensors.async_read_all_sensors = AsyncMock(return_value={"temperature": 25.0})
        app.sensors.async_get_current_state = AsyncMock()
        app.actuators = MagicMock()
        app.actuators.async_get_state = AsyncMock(return_value={})
        app.api_client = MagicMock()
        app.api_client.device_id = "test"

        app.queue = None
        app.network = MagicMock()
        app.network.is_connected = AsyncMock(return_value=False)
        app.consecutive_failures = 0

        asyncio.run(app.sensor_reading_job())
        assert app.consecutive_failures == 1


class TestFailureMonitorJob:
    def test_failure_monitor_re_onboards(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.consecutive_failures = 10

        app.scheduler = MagicMock()
        app.upload_processor_task = None

        app.cleanup = AsyncMock()
        mock_enter = AsyncMock()
        app.enter_onboarding_mode = mock_enter
        app.load_configuration = MagicMock()
        app.initialize_components = AsyncMock(return_value=True)
        app.setup_scheduler = AsyncMock()

        app.queue = MagicMock()
        app.upload_processor = MagicMock()
        app.upload_processor.run_continuous = AsyncMock()

        asyncio.run(app.failure_monitor_job())

        app.scheduler.shutdown.assert_called_once_with(wait=False)
        app.cleanup.assert_awaited_once()
        mock_enter.assert_awaited_once()
        app.load_configuration.assert_called_once()
        app.initialize_components.assert_awaited_once()
        app.setup_scheduler.assert_awaited_once()
        assert app.upload_processor_task is not None
        assert app.consecutive_failures == 0

    def test_failure_monitor_job_exception(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.consecutive_failures = 10

        app.scheduler = MagicMock()
        app.scheduler.shutdown.side_effect = Exception("shutdown error")

        asyncio.run(app.failure_monitor_job())

    def test_failure_monitor_with_upload_task(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.consecutive_failures = 10
        app.scheduler = MagicMock()
        app.enter_onboarding_mode = AsyncMock()
        app.load_configuration = MagicMock()
        app.initialize_components = AsyncMock(return_value=True)
        app.setup_scheduler = AsyncMock()

        async def run():
            app.upload_processor_task = asyncio.create_task(asyncio.sleep(999))
            app.cleanup = AsyncMock()
            await app.failure_monitor_job()

        asyncio.run(run())
        assert app.consecutive_failures == 0


class TestCameraWatchdogJob:
    def test_camera_watchdog_camera_none(self):
        from main import GrowMateApp
        app = GrowMateApp()
        app.camera = None

        asyncio.run(app.camera_watchdog_job())

    def test_camera_watchdog_process_not_alive(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        mock_camera = MagicMock()
        mock_camera.is_process_alive.return_value = False
        mock_camera.restart_stream.return_value = True

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.camera = mock_camera
        app.api_client = MagicMock()
        app.api_client.register_stream = AsyncMock(return_value=True)

        mocker.patch.object(app, "_get_tailscale_ip", AsyncMock(return_value="100.64.0.1"))

        asyncio.run(app.camera_watchdog_job())

        mock_camera.restart_stream.assert_called_once()
        app.api_client.register_stream.assert_awaited_once()

    def test_camera_watchdog_exception(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        mock_camera = MagicMock()
        mock_camera.is_process_alive.side_effect = Exception("watchdog error")

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.camera = mock_camera

        asyncio.run(app.camera_watchdog_job())


class TestQueueCleanupJob:
    def test_queue_cleanup_job(self):
        from main import GrowMateApp
        app = GrowMateApp()
        app.queue = MagicMock()
        app.queue.async_cleanup_old_entries = AsyncMock(return_value=5)

        asyncio.run(app.queue_cleanup_job())
        app.queue.async_cleanup_old_entries.assert_awaited_once()

    def test_queue_cleanup_job_exception(self):
        from main import GrowMateApp
        app = GrowMateApp()
        app.queue = MagicMock()
        app.queue.async_cleanup_old_entries = AsyncMock(side_effect=Exception("cleanup error"))

        asyncio.run(app.queue_cleanup_job())


class TestQueueStatsJob:
    def test_queue_stats_job(self):
        from main import GrowMateApp
        app = GrowMateApp()
        app.queue = MagicMock()
        app.queue.async_get_queue_stats = AsyncMock(return_value={
            "sensor_queue": {"pending": 1200}
        })
        app.upload_processor = MagicMock()
        app.upload_processor.get_stats.return_value = {
            "sensor_uploads_success": 5,
            "sensor_uploads_failed": 2,
            "total_processed": 7,
        }

        asyncio.run(app.queue_stats_job())
        app.queue.async_get_queue_stats.assert_awaited_once()

    def test_queue_stats_job_exception(self):
        from main import GrowMateApp
        app = GrowMateApp()
        app.queue = MagicMock()
        app.queue.async_get_queue_stats = AsyncMock(side_effect=Exception("stats error"))

        asyncio.run(app.queue_stats_job())


class TestOnConfigFileChanged:
    def test_on_config_file_changed_reloads(self, mocker, mock_app_components, config_mgr, minimal_config):
        config_mgr.reload.return_value = {"test": ("old", "new")}

        from main import GrowMateApp
        app = GrowMateApp()

        app._on_config_file_changed()
        config_mgr.reload.assert_called_once()

    def test_on_config_file_changed_exception(self, mocker, mock_app_components, config_mgr, minimal_config):
        config_mgr.reload.side_effect = Exception("reload error")

        from main import GrowMateApp
        app = GrowMateApp()

        app._on_config_file_changed()


class TestOnConfigReload:
    def test_reload_reschedules_sensor_interval(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.scheduler = MagicMock()

        app.on_config_reload({"intervals.sensor_reading": (60, 30)})
        app.scheduler.reschedule_job.assert_called_once()

    def test_reload_updates_retry(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        mock_api = MagicMock()

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.api_client = mock_api

        app.on_config_reload({"retry.max_attempts": (6, 10)})
        mock_api.update_retry_config.assert_called_once_with(cfg.get("retry", {}))

    def test_reload_updates_circuit_breaker(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        mock_api = MagicMock()

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.api_client = mock_api

        app.on_config_reload({"circuit_breaker.failure_threshold": (5, 10)})
        mock_api.update_circuit_breaker_config.assert_called_once_with(cfg.get("circuit_breaker", {}))

    def test_reload_updates_logging(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.on_config_reload({"logging.level": ("INFO", "DEBUG")})

    def test_reload_updates_features(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.on_config_reload({"features.hot_reload": (True, False)})

    def test_reload_exception(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        mocker.patch("main.update_log_levels", side_effect=Exception("log error"))

        app.on_config_reload({"logging.level": ("INFO", "DEBUG")})


class TestSetupScheduler:
    def test_setup_scheduler_with_queue(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

        mock_scheduler = MagicMock()
        mocker.patch("main.AsyncIOScheduler", return_value=mock_scheduler)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg
        app.queue = MagicMock()

        asyncio.run(app.setup_scheduler())

        assert mock_scheduler.add_job.call_count == 6


class TestCleanupExtended:
    def test_cleanup_cancels_upload_processor_task(self):
        from main import GrowMateApp
        app = GrowMateApp()
        app.config_watcher = None
        app.health_monitor_task = None

        async def run():
            app.upload_processor_task = asyncio.create_task(asyncio.sleep(999))
            app.actuators = MagicMock()
            app.actuators.async_cleanup = AsyncMock()
            app.sensors = MagicMock()
            app.sensors.cleanup = MagicMock()
            app.camera = None
            app.network = None
            app.api_client = None
            app.queue = None
            await app.cleanup()

        asyncio.run(run())

    def test_cleanup_network_stop_ap_exception(self):
        from main import GrowMateApp
        app = GrowMateApp()
        app.config_watcher = None
        app.health_monitor_task = None
        app.upload_processor_task = None
        app.actuators = None
        app.sensors = None
        app.camera = None

        mock_network = MagicMock()
        mock_network.stop_ap_mode = AsyncMock(side_effect=Exception("stop error"))
        app.network = mock_network

        app.api_client = None
        app.queue = None

        asyncio.run(app.cleanup())
        mock_network.stop_ap_mode.assert_awaited_once()


class TestRunAsyncExtended:
    def test_creates_upload_processor_task(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        config_mgr.config = cfg

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

        mock_queue = MagicMock()
        mock_queue.async_initialize = AsyncMock(return_value=True)
        mock_queue.async_close = AsyncMock()
        mocker.patch("main.QueueManager", return_value=mock_queue)

        mock_upload = MagicMock()
        mock_upload.run_continuous = AsyncMock()
        mocker.patch("main.UploadProcessor", return_value=mock_upload)

        mock_network = MagicMock()
        mock_network.stop_ap_mode = AsyncMock()
        mocker.patch("main.NetworkManager", return_value=mock_network)

        mock_actuators = MagicMock()
        mock_actuators.async_cleanup = AsyncMock()
        mocker.patch("main.ActuatorController", return_value=mock_actuators)

        mock_sensors = MagicMock()
        mock_sensors.cleanup = MagicMock()
        mocker.patch("main.SensorReader", return_value=mock_sensors)

        mock_scheduler = MagicMock()
        mocker.patch("main.AsyncIOScheduler", return_value=mock_scheduler)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.shutdown_event.set()

        result = asyncio.run(app.run_async())

        assert result == 0
        assert app.upload_processor_task is not None

    def test_hot_reload_disabled(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["features"]["hot_reload"] = False
        cfg["queue"]["enabled"] = False
        config_mgr.config = cfg

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

        mock_network = MagicMock()
        mock_network.stop_ap_mode = AsyncMock()
        mocker.patch("main.NetworkManager", return_value=mock_network)

        mock_actuators = MagicMock()
        mock_actuators.async_cleanup = AsyncMock()
        mocker.patch("main.ActuatorController", return_value=mock_actuators)

        mock_sensors = MagicMock()
        mock_sensors.cleanup = MagicMock()
        mocker.patch("main.SensorReader", return_value=mock_sensors)

        mock_scheduler = MagicMock()
        mocker.patch("main.AsyncIOScheduler", return_value=mock_scheduler)

        from main import GrowMateApp
        app = GrowMateApp()
        app.config = cfg

        app.shutdown_event.set()

        result = asyncio.run(app.run_async())
        assert result == 0

    def test_run_async_exception_returns_1(self, mocker, mock_app_components, config_mgr, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["queue"]["enabled"] = False
        config_mgr.config = cfg

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

        mock_network = MagicMock()
        mock_network.stop_ap_mode = AsyncMock()
        mocker.patch("main.NetworkManager", return_value=mock_network)

        mock_actuators = MagicMock()
        mock_actuators.async_cleanup = AsyncMock()
        mocker.patch("main.ActuatorController", return_value=mock_actuators)

        mock_sensors = MagicMock()
        mock_sensors.cleanup = MagicMock()
        mocker.patch("main.SensorReader", return_value=mock_sensors)

        from main import GrowMateApp
        mocker.patch.object(GrowMateApp, "setup_scheduler", AsyncMock(side_effect=Exception("scheduler error")))

        app = GrowMateApp()
        app.config = cfg

        result = asyncio.run(app.run_async())
        assert result == 1


class TestMainEntryPoint:
    def test_main_function_exists(self):
        from main import main
        assert callable(main)
