import asyncio
import copy
import json
import os
import time
import yaml
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, PropertyMock, mock_open, call

import aiohttp
import pytest
from pydantic import ValidationError


class TestConfigValidatorManager:
    def test_round_trip_preserves_values(self, tmp_path, minimal_config):
        from config_validator import validate_config
        from config_manager import ConfigManager
        cfg_path = tmp_path / "config.yaml"
        mgr = ConfigManager(config_path=cfg_path, enable_validation=True)
        mgr.config = copy.deepcopy(minimal_config)
        mgr.save()
        mgr2 = ConfigManager(config_path=cfg_path, enable_validation=True)
        mgr2.load()
        assert mgr2.config["version"] == minimal_config["version"]
        assert mgr2.config["device"]["id"] == minimal_config["device"]["id"]
        assert mgr2.config["network"]["wifi_ssid"] == minimal_config["network"]["wifi_ssid"]
        assert mgr2.config["intervals"]["sensor_reading"] == minimal_config["intervals"]["sensor_reading"]

    def test_env_override_device_id(self, tmp_path, minimal_config, monkeypatch):
        from config_manager import ConfigManager
        import yaml
        monkeypatch.setenv("DEVICE_ID", "env-overridden-device")
        cfg_path = tmp_path / "config.yaml"
        with open(cfg_path, "w") as f:
            yaml.dump(minimal_config, f)
        mgr = ConfigManager(config_path=cfg_path)
        mgr.load()
        assert mgr.config["device"]["id"] == "env-overridden-device"

    def test_dot_notation_get_set_persistence(self, minimal_config):
        from config_manager import ConfigManager
        mgr = ConfigManager()
        mgr.config = copy.deepcopy(minimal_config)
        original = mgr.get("network.wifi_ssid")
        mgr.set("network.wifi_ssid", "custom-ssid")
        assert mgr.get("network.wifi_ssid") == "custom-ssid"
        mgr.set("intervals.sensor_reading", 120)
        assert mgr.get("intervals.sensor_reading") == 120

    def test_validate_then_save_then_reload_no_changes(self, tmp_path, minimal_config):
        from config_validator import validate_config
        from config_manager import ConfigManager
        validate_config(minimal_config)
        cfg_path = tmp_path / "config.yaml"
        mgr = ConfigManager(config_path=cfg_path)
        mgr.config = copy.deepcopy(minimal_config)
        mgr.save()
        mgr2 = ConfigManager(config_path=cfg_path)
        mgr2.load()
        assert mgr2.config == mgr.config

    def test_invalid_config_validator_rejects(self, minimal_config):
        from config_validator import validate_config
        bad = copy.deepcopy(minimal_config)
        bad["device"]["id"] = ""
        with pytest.raises(ValidationError):
            validate_config(bad)

    def test_env_override_bool_feature_flag(self, tmp_path, minimal_config, monkeypatch):
        from config_manager import ConfigManager
        import yaml
        monkeypatch.setenv("GROWMATE_FEATURES_OFFLINE_QUEUE", "false")
        cfg_path = tmp_path / "config.yaml"
        with open(cfg_path, "w") as f:
            yaml.dump(minimal_config, f)
        mgr = ConfigManager(config_path=cfg_path)
        mgr.load()
        assert mgr.config["features"]["offline_queue"] is False


class TestConfigWatcherHotReload:
    def test_watcher_detects_file_change_and_reloads(self, tmp_path, minimal_config):
        import yaml
        from config_manager import ConfigManager
        cfg_path = tmp_path / "config.yaml"
        with open(cfg_path, "w") as f:
            yaml.dump(minimal_config, f)
        mgr = ConfigManager(config_path=cfg_path)
        mgr.load()
        assert mgr.config["intervals"]["sensor_reading"] == 60
        modified = copy.deepcopy(minimal_config)
        modified["intervals"]["sensor_reading"] = 120
        with open(cfg_path, "w") as f:
            yaml.dump(modified, f)
        mgr2 = ConfigManager(config_path=cfg_path)
        mgr2.load()
        assert mgr2.config["intervals"]["sensor_reading"] == 120

    def test_hot_reload_reloadable_change_applies(self, minimal_config, mocker):
        from config_manager import ConfigManager
        mgr = ConfigManager()
        initial = copy.deepcopy(minimal_config)
        modified = copy.deepcopy(minimal_config)
        modified["intervals"]["sensor_reading"] = 300
        mgr.config = copy.deepcopy(initial)
        mocker.patch.object(Path, "exists", return_value=True)
        m = mock_open(read_data=yaml.dump(modified))
        mocker.patch("builtins.open", m)
        mocker.patch("config_manager.ConfigManager.validate", return_value=True)
        changes = mgr.reload()
        assert "intervals.sensor_reading" in changes
        assert changes["intervals.sensor_reading"] == (60, 300)
        assert mgr.config["intervals"]["sensor_reading"] == 300

    def test_hot_reload_non_reloadable_raises_value_error(self, minimal_config, mocker):
        from config_manager import ConfigManager
        mgr = ConfigManager()
        initial = copy.deepcopy(minimal_config)
        modified = copy.deepcopy(minimal_config)
        modified["network"]["provisioned"] = True
        mgr.config = copy.deepcopy(initial)
        mocker.patch.object(Path, "exists", return_value=True)
        m = mock_open(read_data=yaml.dump(modified))
        mocker.patch("builtins.open", m)
        mocker.patch("config_manager.ConfigManager.validate", return_value=True)
        with pytest.raises(ValueError, match="Non-reloadable"):
            mgr.reload()
        assert mgr.config["network"]["provisioned"] is False

    def test_hot_reload_callback_notified(self, minimal_config, mocker):
        from config_manager import ConfigManager
        mgr = ConfigManager()
        mgr.config = copy.deepcopy(minimal_config)
        modified = copy.deepcopy(minimal_config)
        modified["intervals"]["sensor_reading"] = 150
        mocker.patch.object(Path, "exists", return_value=True)
        m = mock_open(read_data=yaml.dump(modified))
        mocker.patch("builtins.open", m)
        mocker.patch("config_manager.ConfigManager.validate", return_value=True)
        received = []
        mgr.register_reload_callback(lambda c: received.append(c))
        changes = mgr.reload()
        assert len(received) == 1
        assert received[0] == changes


class TestQueueUploadProcessor:
    def test_enqueue_then_process_drains_queue(self, tmp_path, minimal_config):
        from queue_manager import QueueManager
        from api_client import APIClient
        from upload_processor import UploadProcessor
        import aiohttp
        db_path = tmp_path / "integration_queue.db"
        qm = QueueManager(db_path)
        qm.initialize()
        qm.enqueue_sensor_data(
            "device-1", "2.0.0",
            [{"kind": "temperature", "value": 25.0}],
            {"pumpEnabled": False}
        )
        assert qm.get_queue_stats()["sensor_queue"]["pending"] == 1
        config = copy.deepcopy(minimal_config)
        config["queue"]["db_path"] = str(db_path)

        async def run():
            async with aiohttp.ClientSession() as session:
                ac = APIClient(config)
                ac.session = session
                upload_mock = AsyncMock(return_value=[{"action": "water"}])
                ac.upload_sensor_data = upload_mock
                up = UploadProcessor(qm, ac, config)
                processed = await up.process_queue_once()
                return processed, qm.get_queue_stats()

        processed, stats = asyncio.run(run())
        assert processed == 1
        assert stats["sensor_queue"]["total"] == 0
        qm.close()

    def test_queue_upload_failure_retains_item(self, tmp_path, minimal_config):
        from queue_manager import QueueManager
        from api_client import APIClient
        from upload_processor import UploadProcessor
        import aiohttp
        db_path = tmp_path / "fail_queue.db"
        qm = QueueManager(db_path)
        qm.initialize()
        qm.enqueue_sensor_data("d1", "2.0.0", [{"kind": "temp", "value": 30}], {})
        config = copy.deepcopy(minimal_config)
        config["queue"]["db_path"] = str(db_path)

        async def run():
            async with aiohttp.ClientSession() as session:
                ac = APIClient(config)
                ac.session = session
                ac.upload_sensor_data = AsyncMock(return_value=None)
                up = UploadProcessor(qm, ac, config)
                processed = await up.process_queue_once()
                return processed, qm.get_queue_stats()

        processed, stats = asyncio.run(run())
        assert processed == 1
        assert stats["sensor_queue"]["total"] == 1
        assert stats["sensor_queue"]["pending"] == 1
        qm.close()

    def test_circuit_breaker_open_skips_processing(self, tmp_path, minimal_config):
        from queue_manager import QueueManager
        from api_client import APIClient
        from upload_processor import UploadProcessor
        db_path = tmp_path / "cb_queue.db"
        qm = QueueManager(db_path)
        qm.initialize()
        qm.enqueue_sensor_data("d1", "2.0.0", [{"kind": "temp", "value": 25}], {})

        async def run():
            ac = APIClient(minimal_config)
            ac.session = MagicMock()
            ac.get_circuit_breaker_stats = MagicMock(return_value={
                "sensor_api": {"state": "OPEN"},
            })
            up = UploadProcessor(qm, ac, minimal_config)
            processed = await up.process_queue_once()
            return processed, qm.get_queue_stats()

        processed, stats = asyncio.run(run())
        assert processed == 0
        assert stats["sensor_queue"]["total"] == 1
        qm.close()

    def test_enqueue_multiple_batch_process(self, tmp_path, minimal_config):
        from queue_manager import QueueManager
        from api_client import APIClient
        from upload_processor import UploadProcessor
        import aiohttp
        db_path = tmp_path / "batch_queue.db"
        qm = QueueManager(db_path)
        qm.initialize()
        for i in range(3):
            qm.enqueue_sensor_data("d1", "2.0.0", [{"kind": "temp", "value": 20 + i}], {})

        config = copy.deepcopy(minimal_config)

        async def run():
            async with aiohttp.ClientSession() as session:
                ac = APIClient(config)
                ac.session = session
                ac.upload_sensor_data = AsyncMock(return_value=[{"action": "water"}])
                up = UploadProcessor(qm, ac, config)
                total = 0
                for _ in range(5):
                    p = await up.process_queue_once()
                    total += p
                    if p == 0:
                        break
                return total, qm.get_queue_stats()

        total, stats = asyncio.run(run())
        assert total == 3
        assert stats["sensor_queue"]["total"] == 0
        qm.close()


class TestSensorActuatorIntegration:
    def test_sensor_reader_and_actuator_controller_construct(self, minimal_config):
        from sensors import SensorReader
        from actuators import ActuatorController
        sensors_cfg = minimal_config.get("sensors", {})
        actuators_cfg = minimal_config.get("actuators", {})
        reader = SensorReader(sensors_cfg)
        controller = ActuatorController(actuators_cfg)
        assert reader is not None
        assert controller is not None
        reader.cleanup()
        controller.cleanup()

    def test_sensors_read_and_actuator_state_combine(self, minimal_config):
        from sensors import SensorReader
        from actuators import ActuatorController
        sensors_cfg = minimal_config.get("sensors", {})
        actuators_cfg = minimal_config.get("actuators", {})
        reader = SensorReader(sensors_cfg)
        controller = ActuatorController(actuators_cfg)
        sensor_data = reader.read_all_sensors()
        assert len(sensor_data) >= 4
        kinds = {s["kind"] for s in sensor_data}
        assert "soil" in kinds
        assert "light" in kinds
        assert "water" in kinds
        assert "temperature" in kinds
        actuator_state = controller.get_state()
        assert "pumpEnabled" in actuator_state
        assert "fertilizerEnabled" in actuator_state
        combined = reader.get_current_state(actuator_state)
        assert combined["pumpEnabled"] == actuator_state["pumpEnabled"]
        assert "batteryCurrent" in combined
        assert "tankSwitchOpen" in combined
        reader.cleanup()
        controller.cleanup()

    def test_combined_payload_structure(self, minimal_config):
        from sensors import SensorReader
        from actuators import ActuatorController
        sensors_cfg = minimal_config.get("sensors", {})
        actuators_cfg = minimal_config.get("actuators", {})
        reader = SensorReader(sensors_cfg)
        controller = ActuatorController(actuators_cfg)
        sensor_data = reader.read_all_sensors()
        actuator_state = controller.get_state()
        current_state = reader.get_current_state(actuator_state)
        payload = {
            "deviceId": minimal_config["device"]["id"],
            "firmwareVersion": "2.0.0",
            "sensors": sensor_data,
            "currentState": current_state,
        }
        assert len(payload["sensors"]) >= 4
        for s in payload["sensors"]:
            assert "kind" in s
            assert "value" in s or "error" in s
        assert payload["currentState"]["pumpEnabled"] is not None
        assert payload["currentState"]["batteryCurrent"] is not None
        reader.cleanup()
        controller.cleanup()


class TestHealthMonitorIntegration:
    def test_collect_metrics_all_sections_present(self, mocker):
        from health_monitor import HealthMonitor
        api = mocker.MagicMock()
        api.get_circuit_breaker_stats.return_value = {"sensor_api": {"state": "CLOSED"}}
        api.get_retry_stats.return_value = {"total_attempts": 10}
        api.is_stream_registered.return_value = True
        qm = mocker.AsyncMock()
        qm.async_get_queue_stats.return_value = {"sensor_queue": {"pending": 3}, "metadata": {}}
        up = mocker.MagicMock()
        up.get_stats.return_value = {"total_processed": 50, "sensor_uploads_failed": 2, "sensor_uploads_success": 48}
        cs = mocker.MagicMock()
        cs.get_stats.return_value = {"process_alive": True, "recent_crashes_1h": 0}
        mocker.patch("health_monitor.subprocess.run", return_value=MagicMock(returncode=0, stdout="100.64.0.1 growmate-dev active\n"))
        mon = HealthMonitor(api_client=api, queue_manager=qm, upload_processor=up, camera_service=cs)

        async def run():
            metrics = await mon.collect_metrics()
            return metrics

        metrics = asyncio.run(run())
        assert "timestamp" in metrics
        assert "uptime_seconds" in metrics
        assert "circuit_breakers" in metrics
        assert "retry_handler" in metrics
        assert "queue" in metrics
        assert "upload_processor" in metrics
        assert "stream_registered" in metrics
        assert "camera" in metrics
        assert "tailscale" in metrics
        assert metrics["circuit_breakers"]["sensor_api"]["state"] == "CLOSED"
        assert metrics["queue"]["sensor_queue"]["pending"] == 3

    def test_check_health_healthy_status(self, mocker):
        from health_monitor import HealthMonitor
        api = mocker.MagicMock()
        api.get_circuit_breaker_stats.return_value = {"sensor_api": {"state": "CLOSED"}}
        api.get_retry_stats.return_value = {}
        api.is_stream_registered.return_value = True
        qm = mocker.AsyncMock()
        qm.async_get_queue_stats.return_value = {"sensor_queue": {"pending": 0}, "metadata": {}}
        up = mocker.MagicMock()
        up.get_stats.return_value = {"total_processed": 100, "sensor_uploads_failed": 0, "sensor_uploads_success": 100}
        cs = mocker.MagicMock()
        cs.get_stats.return_value = {"process_alive": True, "recent_crashes_1h": 0}
        mocker.patch("health_monitor.subprocess.run", return_value=MagicMock(returncode=0, stdout="100.64.0.1 growmate-dev active\n"))
        mon = HealthMonitor(api_client=api, queue_manager=qm, upload_processor=up, camera_service=cs)

        async def run():
            result = await mon.check_health()
            return result

        result = asyncio.run(run())
        assert result["health_status"] == "HEALTHY"
        assert mon.health_status == "HEALTHY"

    def test_check_health_degraded_with_open_circuit(self, mocker):
        from health_monitor import HealthMonitor
        api = mocker.MagicMock()
        api.get_circuit_breaker_stats.return_value = {"sensor_api": {"state": "OPEN"}}
        api.get_retry_stats.return_value = {}
        api.is_stream_registered.return_value = False
        qm = mocker.AsyncMock()
        qm.async_get_queue_stats.return_value = {"sensor_queue": {"pending": 0}, "metadata": {}}
        up = mocker.MagicMock()
        up.get_stats.return_value = {"total_processed": 10, "sensor_uploads_failed": 0, "sensor_uploads_success": 10}
        cs = mocker.MagicMock()
        cs.get_stats.return_value = {"process_alive": True, "recent_crashes_1h": 0}
        mocker.patch("health_monitor.subprocess.run", return_value=MagicMock(returncode=0, stdout="100.64.0.1 growmate-dev active\n"))
        mon = HealthMonitor(api_client=api, queue_manager=qm, upload_processor=up, camera_service=cs)

        async def run():
            result = await mon.check_health()
            return result

        result = asyncio.run(run())
        assert result["health_status"] == "DEGRADED"

    def test_get_health_summary_structure(self, mocker):
        from health_monitor import HealthMonitor
        api = mocker.MagicMock()
        api.get_circuit_breaker_stats.return_value = {"sensor_api": {"state": "CLOSED"}, "stream_api": {"state": "CLOSED"}}
        api.is_stream_registered.return_value = True
        mon = HealthMonitor(api_client=api)
        summary = mon.get_health_summary()
        assert summary["health_status"] == "HEALTHY"
        assert "uptime_seconds" in summary
        assert "stream_registered" in summary
        assert summary["stream_registered"] is True
        assert "circuit_breaker_states" in summary
        assert summary["circuit_breaker_states"]["sensor_api"] == "CLOSED"

    def test_health_monitor_set_components_then_collect(self, mocker):
        from health_monitor import HealthMonitor
        mon = HealthMonitor()
        api = mocker.MagicMock()
        api.get_circuit_breaker_stats.return_value = {}
        api.get_retry_stats.return_value = {}
        api.is_stream_registered.return_value = False
        qm = mocker.AsyncMock()
        qm.async_get_queue_stats.return_value = {"sensor_queue": {"pending": 0}, "metadata": {}}
        up = mocker.MagicMock()
        up.get_stats.return_value = {"total_processed": 0, "sensor_uploads_failed": 0, "sensor_uploads_success": 0}
        mocker.patch("health_monitor.subprocess.run", return_value=MagicMock(returncode=0, stdout="100.64.0.1 growmate-dev active\n"))
        mon.set_components(api_client=api, queue_manager=qm, upload_processor=up)

        async def run():
            metrics = await mon.collect_metrics()
            return metrics

        metrics = asyncio.run(run())
        assert "circuit_breakers" in metrics
        assert "retry_handler" in metrics
        assert "queue" in metrics
        assert "upload_processor" in metrics


class TestFullSensorQueueUploadPipeline:
    def test_end_to_end_with_mocked_network(self, tmp_path, minimal_config):
        import yaml
        from config_manager import ConfigManager
        from sensors import SensorReader
        from actuators import ActuatorController
        from queue_manager import QueueManager
        from api_client import APIClient
        from upload_processor import UploadProcessor
        db_path = tmp_path / "pipeline.db"
        cfg_path = tmp_path / "config.yaml"
        with open(cfg_path, "w") as f:
            yaml.dump(minimal_config, f)
        mgr = ConfigManager(config_path=cfg_path)
        mgr.load()
        config = mgr.config
        config["queue"]["db_path"] = str(db_path)
        qm = QueueManager(db_path)
        qm.initialize()
        reader = SensorReader(config.get("sensors", {}))
        controller = ActuatorController(config.get("actuators", {}))

        sensor_data = reader.read_all_sensors()
        actuator_state = controller.get_state()
        current_state = reader.get_current_state(actuator_state)

        qm.enqueue_sensor_data(
            config["device"]["id"],
            "2.0.0",
            sensor_data,
            current_state
        )
        stats = qm.get_queue_stats()
        assert stats["sensor_queue"]["pending"] == 1

        async def run():
            async with aiohttp.ClientSession() as session:
                ac = APIClient(config)
                ac.session = session
                success_response = MagicMock()
                success_response.status = 200
                success_response.json = AsyncMock(return_value={"commands": []})
                success_response.__aenter__ = AsyncMock(return_value=success_response)
                success_response.__aexit__ = AsyncMock()
                session.post = MagicMock(return_value=success_response)
                up = UploadProcessor(qm, ac, config)
                processed = await up.process_queue_once()
                return processed, qm.get_queue_stats()

        processed, stats = asyncio.run(run())
        assert processed == 1
        assert stats["sensor_queue"]["total"] == 0
        assert int(stats["metadata"]["total_sensor_uploads"]) == 1
        reader.cleanup()
        controller.cleanup()
        qm.close()

    def test_sensor_queue_upload_with_circuit_breaker(self, tmp_path, minimal_config):
        from sensors import SensorReader
        from actuators import ActuatorController
        from queue_manager import QueueManager
        from api_client import APIClient
        from upload_processor import UploadProcessor
        db_path = tmp_path / "cb_pipeline.db"
        qm = QueueManager(db_path)
        qm.initialize()
        reader = SensorReader(minimal_config.get("sensors", {}))
        controller = ActuatorController(minimal_config.get("actuators", {}))
        sensor_data = reader.read_all_sensors()
        state = reader.get_current_state(controller.get_state())
        qm.enqueue_sensor_data("d1", "2.0.0", sensor_data, state)
        stats_before = qm.get_queue_stats()
        assert stats_before["sensor_queue"]["pending"] == 1

        async def run():
            ac = APIClient(minimal_config)
            ac.session = MagicMock()
            ac.get_circuit_breaker_stats = MagicMock(return_value={
                "sensor_api": {"state": "OPEN"},
            })
            up = UploadProcessor(qm, ac, minimal_config)
            processed = await up.process_queue_once()
            qm_stats = qm.get_queue_stats()
            return processed, qm_stats

        processed, stats_after = asyncio.run(run())
        assert processed == 0
        assert stats_after["sensor_queue"]["pending"] == 1
        reader.cleanup()
        controller.cleanup()
        qm.close()

    def test_pipeline_multiple_sensors_enqueued_then_processed(self, tmp_path, minimal_config):
        from queue_manager import QueueManager
        from api_client import APIClient
        from upload_processor import UploadProcessor
        db_path = tmp_path / "multi_pipeline.db"
        qm = QueueManager(db_path)
        qm.initialize()
        for i in range(5):
            qm.enqueue_sensor_data(
                "d1", "2.0.0",
                [{"kind": "temp", "value": 20 + i}, {"kind": "soil", "value": 50 + i}],
                {"pumpEnabled": i % 2 == 0}
            )
        assert qm.get_queue_stats()["sensor_queue"]["pending"] == 5

        async def run():
            async with aiohttp.ClientSession() as session:
                ac = APIClient(minimal_config)
                ac.session = session
                success_response = MagicMock()
                success_response.status = 200
                success_response.json = AsyncMock(return_value={"commands": []})
                success_response.__aenter__ = AsyncMock(return_value=success_response)
                success_response.__aexit__ = AsyncMock()
                session.post = MagicMock(return_value=success_response)
                up = UploadProcessor(qm, ac, minimal_config)
                total = 0
                for _ in range(10):
                    p = await up.process_queue_once()
                    total += p
                    if p == 0:
                        break
                return total, qm.get_queue_stats(), up.get_stats()

        total, stats, up_stats = asyncio.run(run())
        assert total == 5
        assert stats["sensor_queue"]["total"] == 0
        assert up_stats["sensor_uploads_success"] == 5
        qm.close()


class TestNetworkManagerHostapd:
    def test_generate_hostapd_config_with_explicit_settings(self, mocker):
        from network_manager import NetworkManager
        mocker.patch("pathlib.Path.exists", return_value=True)
        mocker.patch("pathlib.Path.read_text", return_value="{SSID}|{PASSWORD}|{CHANNEL}")
        write_mock = mocker.patch("pathlib.Path.write_text")
        config = {
            "ap_mode": {
                "ssid": "GrowMate-Custom",
                "password": "secure123",
                "channel": 11,
                "interface": "wlan0",
            },
            "network": {"wifi": {}},
        }
        mgr = NetworkManager(config)
        assert mgr._generate_hostapd_conf() is True
        write_mock.assert_called_once_with("GrowMate-Custom|secure123|11")

    def test_generate_hostapd_config_auto_ssid_from_mac(self, mocker):
        from network_manager import NetworkManager
        mocker.patch("pathlib.Path.exists", return_value=True)
        mocker.patch("pathlib.Path.read_text", return_value="{SSID}|{PASSWORD}|{CHANNEL}")
        write_mock = mocker.patch("pathlib.Path.write_text")
        mocker.patch("utils.get_ap_ssid", return_value="GrowMate-ABCDEF")
        config = {
            "ap_mode": {
                "ssid": "",
                "password": "growmate",
                "channel": 1,
            },
            "network": {"wifi": {}},
        }
        mgr = NetworkManager(config)
        assert mgr._generate_hostapd_conf() is True
        write_mock.assert_called_once_with("GrowMate-ABCDEF|growmate|1")

    def test_generate_hostapd_config_template_not_found(self, mocker):
        from network_manager import NetworkManager
        mocker.patch("pathlib.Path.exists", return_value=False)
        config = {
            "ap_mode": {"ssid": "Test", "password": "pass", "channel": 6},
            "network": {"wifi": {}},
        }
        mgr = NetworkManager(config)
        assert mgr._generate_hostapd_conf() is False

    def test_generate_hostapd_config_with_defaults(self, mocker):
        from network_manager import NetworkManager
        mocker.patch("pathlib.Path.exists", return_value=True)
        mocker.patch("pathlib.Path.read_text", return_value="{SSID}|{PASSWORD}|{CHANNEL}")
        write_mock = mocker.patch("pathlib.Path.write_text")
        config = {
            "ap_mode": {},
            "network": {"wifi": {}},
        }
        mocker.patch("utils.get_ap_ssid", return_value="GrowMate-DEFAULT")
        mgr = NetworkManager(config)
        assert mgr._generate_hostapd_conf() is True
        from network_manager import AP_PASSWORD
        write_mock.assert_called_once_with("GrowMate-DEFAULT|growmate|1")

    def test_generate_hostapd_config_templates_from_config_dir(self, mocker):
        from network_manager import NetworkManager
        exists_mock = mocker.patch("pathlib.Path.exists")
        exists_mock.side_effect = lambda: True
        exists_mock.return_value = True
        read_mock = mocker.patch("pathlib.Path.read_text", return_value="ssid={SSID}\nchannel={CHANNEL}")
        write_mock = mocker.patch("pathlib.Path.write_text")
        config = {
            "ap_mode": {"ssid": "GrowMate-ABCDEF", "password": "test", "channel": 6},
            "network": {"wifi": {}},
        }
        mgr = NetworkManager(config)
        assert mgr._generate_hostapd_conf() is True
        write_mock.assert_called_once_with("ssid=GrowMate-ABCDEF\nchannel=6")


class TestCrossComponentEdgeCases:
    def test_config_manager_callback_on_interval_change(self, minimal_config, mocker):
        from config_manager import ConfigManager
        mgr = ConfigManager()
        mgr.config = copy.deepcopy(minimal_config)
        modified = copy.deepcopy(minimal_config)
        modified["intervals"]["sensor_reading"] = 180
        mocker.patch.object(Path, "exists", return_value=True)
        m = mock_open(read_data=yaml.dump(modified))
        mocker.patch("builtins.open", m)
        mocker.patch("config_manager.ConfigManager.validate", return_value=True)
        received = []
        mgr.register_reload_callback(lambda c: received.append(c))
        mgr.reload()
        assert len(received) == 1
        assert "intervals.sensor_reading" in received[0]
        assert received[0]["intervals.sensor_reading"] == (60, 180)

    def test_health_monitor_error_handling_component_failure(self, mocker):
        from health_monitor import HealthMonitor
        api = mocker.MagicMock()
        api.get_circuit_breaker_stats.side_effect = RuntimeError("cb crash")
        api.get_retry_stats.side_effect = RuntimeError("retry crash")
        api.is_stream_registered.side_effect = RuntimeError("stream crash")
        qm = mocker.AsyncMock()
        qm.async_get_queue_stats.side_effect = RuntimeError("queue crash")
        up = mocker.MagicMock()
        up.get_stats.side_effect = RuntimeError("up crash")
        cs = mocker.MagicMock()
        cs.get_stats.side_effect = RuntimeError("camera crash")
        mocker.patch("health_monitor.subprocess.run", side_effect=FileNotFoundError("no tailscale"))
        mon = HealthMonitor(api_client=api, queue_manager=qm, upload_processor=up, camera_service=cs)

        async def run():
            metrics = await mon.collect_metrics()
            return metrics

        metrics = asyncio.run(run())
        assert "error" in metrics["circuit_breakers"]
        assert "error" in metrics["retry_handler"]
        assert "error" in metrics["queue"]
        assert "error" in metrics["upload_processor"]
        assert metrics["stream_registered"] is False
        assert "error" in metrics["camera"]
        assert metrics["tailscale"]["status"] == "DISCONNECTED"

    def test_actuator_commands_from_upload_response(self, minimal_config, mocker):
        from actuators import ActuatorController
        controller = ActuatorController(minimal_config.get("actuators", {}))
        commands = [
            {"kind": "pump", "durationMs": 100},
            {"kind": "fertilizer", "durationMs": 50},
        ]
        controller.process_commands(commands)
        journal = controller.get_relay_journal()
        assert len(journal) == 4
        states = [e["state"] for e in journal]
        assert states.count("HIGH") == 2
        assert states.count("LOW") == 2
        controller.cleanup()

    def test_sensor_reader_health_tracking_after_reads(self, minimal_config):
        from sensors import SensorReader
        reader = SensorReader(minimal_config.get("sensors", {}))
        reader.read_all_sensors()
        health = reader.get_health()
        for sensor_name in ("soil", "light", "water", "temperature", "air", "battery"):
            assert sensor_name in health
            assert health[sensor_name]["consecutive_failures"] == 0
            assert health[sensor_name]["degraded"] is False
        reader.cleanup()

    def test_queue_manager_enqueue_uses_real_sqlite(self, tmp_path):
        from queue_manager import QueueManager
        db_path = tmp_path / "real_sqlite.db"
        qm = QueueManager(db_path)
        qm.initialize()
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        names = {r[0] for r in rows}
        assert "sensor_queue" in names
        assert "queue_metadata" in names
        conn.execute("INSERT INTO sensor_queue(device_id, firmware_version, sensor_data, current_state) VALUES (?,?,?,?)",
                      ("d1", "1.0", "[]", "{}"))
        count = conn.execute("SELECT COUNT(*) FROM sensor_queue").fetchone()[0]
        assert count == 1
        conn.close()
        qm.close()
