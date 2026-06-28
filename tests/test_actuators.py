import copy
import pytest
import actuators
from actuators import ActuatorController, PinMap


class TestPinMap:
    def test_kind_to_gpio_pump(self):
        pm = PinMap({"pump": 10, "fertilizer": 17, "pesticide": 27})
        assert pm.kind_to_gpio("pump") == 10

    def test_kind_to_gpio_fertilizer(self):
        pm = PinMap({"pump": 10, "fertilizer": 17, "pesticide": 27})
        assert pm.kind_to_gpio("fertilizer") == 17

    def test_kind_to_gpio_pesticide(self):
        pm = PinMap({"pump": 10, "fertilizer": 17, "pesticide": 27})
        assert pm.kind_to_gpio("pesticide") == 27

    def test_kind_to_gpio_invalid(self):
        pm = PinMap({"pump": 10, "fertilizer": 17, "pesticide": 27})
        assert pm.kind_to_gpio("nonexistent") is None

    def test_all_pins(self):
        pm = PinMap({"pump": 10, "fertilizer": 17, "pesticide": 27})
        assert pm.all_pins() == [10, 17, 27]

    def test_all_pins_defaults(self):
        pm = PinMap({})
        assert pm.all_pins() == [10, 17, 27]


class TestActuatorControllerInit:
    def test_default_config(self):
        ctrl = ActuatorController()
        assert ctrl._pins.pump == 10
        assert ctrl._pins.fertilizer == 17
        assert ctrl._pins.pesticide == 27
        assert ctrl.pump is not None
        assert ctrl.fertilizer is not None
        assert ctrl.pesticide is not None

    def test_custom_config(self, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        acfg = cfg["actuators"]
        acfg["pins"]["pump"] = 22
        ctrl = ActuatorController(acfg)
        assert ctrl._pins.pump == 22

    def test_defaults_from_empty_dict(self):
        ctrl = ActuatorController({})
        assert ctrl._pins.pump == 10


class TestActuatorControllerState:
    def test_get_state_returns_dict(self):
        ctrl = ActuatorController()
        state = ctrl.get_state()
        assert state["pumpEnabled"] is False
        assert state["lightEnabled"] is False
        assert state["fertilizerEnabled"] is False
        assert state["pesticideEnabled"] is False


class TestActuatorControllerJournal:
    def test_get_relay_journal_empty(self):
        ctrl = ActuatorController()
        assert ctrl.get_relay_journal() == []

    def test_get_relay_journal_after_command(self, mock_sleep):
        ctrl = ActuatorController()
        ctrl.process_commands([{"kind": "pump", "durationMs": 100}])
        journal = ctrl.get_relay_journal()
        assert len(journal) == 2
        assert journal[0]["state"] == "HIGH"
        assert journal[1]["state"] == "LOW"


class TestActuatorControllerProcessCommands:
    def test_empty_commands(self, mock_sleep):
        ctrl = ActuatorController()
        ctrl.process_commands([])
        assert ctrl.get_relay_journal() == []

    def test_light_only_ignored(self, mock_sleep):
        ctrl = ActuatorController()
        ctrl.process_commands([{"kind": "light", "durationMs": 500}])
        assert ctrl.get_relay_journal() == []

    def test_pump_duration(self, mock_sleep):
        ctrl = ActuatorController()
        ctrl.process_commands([{"kind": "pump", "durationMs": 200}])
        ctrl.pump.on.assert_called_once()
        ctrl.pump.off.assert_called_once()

    def test_fertilizer_and_pump(self, mock_sleep):
        ctrl = ActuatorController()
        cmds = [
            {"kind": "pump", "durationMs": 300},
            {"kind": "fertilizer", "durationMs": 300},
        ]
        ctrl.process_commands(cmds)
        ctrl.pump.on.assert_called_once()
        ctrl.fertilizer.on.assert_called_once()
        ctrl.pump.off.assert_called_once()
        ctrl.fertilizer.off.assert_called_once()

    def test_pesticide_and_pump(self, mock_sleep):
        ctrl = ActuatorController()
        cmds = [
            {"kind": "pump", "durationMs": 400},
            {"kind": "pesticide", "durationMs": 400},
        ]
        ctrl.process_commands(cmds)
        ctrl.pump.on.assert_called_once()
        ctrl.pesticide.on.assert_called_once()
        ctrl.pump.off.assert_called_once()
        ctrl.pesticide.off.assert_called_once()

    def test_zero_duration(self, mock_sleep):
        ctrl = ActuatorController()
        ctrl.process_commands([{"kind": "pump", "durationMs": 0}])
        ctrl.pump.on.assert_not_called()

    def test_negative_duration(self, mock_sleep):
        ctrl = ActuatorController()
        ctrl.process_commands([{"kind": "pump", "durationMs": -100}])
        ctrl.pump.on.assert_not_called()

    def test_invalid_kind_ignored(self, mock_sleep):
        ctrl = ActuatorController()
        ctrl.process_commands([{"kind": "unknown", "durationMs": 200}])
        assert ctrl.get_relay_journal() == []

    def test_invalid_kind_mixed_with_valid(self, mock_sleep):
        ctrl = ActuatorController()
        ctrl.process_commands([
            {"kind": "unknown", "durationMs": 200},
            {"kind": "pump", "durationMs": 100},
        ])
        ctrl.pump.on.assert_called_once()
        ctrl.pump.off.assert_called_once()


class TestActuatorControllerReconcile:
    def test_reconcile_all_off(self, mock_sleep):
        ctrl = ActuatorController()
        ctrl.process_commands([{"kind": "pump", "durationMs": 100}])
        ctrl.pump.off.assert_called_once()

    def test_reconcile_mismatch_warning(self, mock_sleep, mocker, caplog):
        ctrl = ActuatorController()
        ctrl.pump.is_active = True
        caplog.set_level("WARNING", logger="growmate.actuators")
        ctrl.process_commands([{"kind": "pump", "durationMs": 100}])
        assert "State reconciliation mismatch" in caplog.text


class TestActuatorControllerCleanup:
    def test_cleanup(self):
        ctrl = ActuatorController()
        ctrl.cleanup()
        ctrl.pump.off.assert_called_once()
        ctrl.fertilizer.off.assert_called_once()
        ctrl.pesticide.off.assert_called_once()
        ctrl.pump.close.assert_called_once()
        ctrl.fertilizer.close.assert_called_once()
        ctrl.pesticide.close.assert_called_once()

    def test_cleanup_with_exceptions(self, mocker):
        ctrl = ActuatorController()
        ctrl.pump.off.side_effect = Exception("cleanup err")
        ctrl.cleanup()
        ctrl.pump.off.assert_called_once()


class TestActuatorControllerAsync:
    @pytest.mark.asyncio
    async def test_async_process_commands(self, mock_sleep):
        ctrl = ActuatorController()
        await ctrl.async_process_commands([{"kind": "pump", "durationMs": 100}])
        ctrl.pump.on.assert_called_once()
        ctrl.pump.off.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_get_state(self):
        ctrl = ActuatorController()
        state = await ctrl.async_get_state()
        assert state["pumpEnabled"] is False

    @pytest.mark.asyncio
    async def test_async_cleanup(self):
        ctrl = ActuatorController()
        await ctrl.async_cleanup()
        ctrl.pump.close.assert_called_once()
