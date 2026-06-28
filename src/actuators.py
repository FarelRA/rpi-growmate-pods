import time
import logging
import asyncio
from typing import Dict, List, Optional
from gpiozero import OutputDevice


logger = logging.getLogger("growmate.actuators")


ACTUATOR_DEFAULTS = {
    "pins": {"pump": 10, "fertilizer": 17, "pesticide": 27},
    "active_high": True,
    "initial_value": False,
    "journal_size": 1000,
    "journal_trim": 500,
}


class PinMap:
    def __init__(self, pins: dict):
        self.pump = pins.get("pump", ACTUATOR_DEFAULTS["pins"]["pump"])
        self.fertilizer = pins.get("fertilizer", ACTUATOR_DEFAULTS["pins"]["fertilizer"])
        self.pesticide = pins.get("pesticide", ACTUATOR_DEFAULTS["pins"]["pesticide"])

    def kind_to_gpio(self, kind: str) -> int:
        return {"pump": self.pump, "fertilizer": self.fertilizer, "pesticide": self.pesticide}.get(kind)

    def all_pins(self) -> list:
        return [self.pump, self.fertilizer, self.pesticide]


class ActuatorController:

    def __init__(self, config: Optional[dict] = None):
        acfg = config or {}
        pin_data = acfg.get("pins", ACTUATOR_DEFAULTS["pins"])
        self._pins = PinMap(pin_data)
        active_high = acfg.get("active_high", ACTUATOR_DEFAULTS["active_high"])
        initial = acfg.get("initial_value", ACTUATOR_DEFAULTS["initial_value"])
        journal_size = acfg.get("journal_size", ACTUATOR_DEFAULTS["journal_size"])
        journal_trim = acfg.get("journal_trim", ACTUATOR_DEFAULTS["journal_trim"])

        self.pump = OutputDevice(self._pins.pump, active_high=active_high, initial_value=initial)
        self.fertilizer = OutputDevice(self._pins.fertilizer, active_high=active_high, initial_value=initial)
        self.pesticide = OutputDevice(self._pins.pesticide, active_high=active_high, initial_value=initial)

        self._relay_journal: List[Dict] = []
        self._journal_size = journal_size
        self._journal_trim = journal_trim

        logger.info(
            "Actuator controller initialized (V2: "
            f"pump=GPIO{self._pins.pump}, "
            f"fertilizer=GPIO{self._pins.fertilizer}, "
            f"pesticide=GPIO{self._pins.pesticide})"
        )

    def _log_relay(self, pin: int, state: bool, command_kind: str):
        entry = {
            "timestamp": time.time(),
            "pin": pin,
            "state": "HIGH" if state else "LOW",
            "command": command_kind,
        }
        self._relay_journal.append(entry)
        if len(self._relay_journal) > self._journal_size:
            self._relay_journal = self._relay_journal[-self._journal_trim:]
        logger.info(
            f"Relay GPIO{pin} → {entry['state']} "
            f"(triggered by '{command_kind}')"
        )

    def get_relay_journal(self) -> List[Dict]:
        return list(self._relay_journal)

    def get_state(self) -> Dict:
        return {
            "pumpEnabled": self.pump.is_active,
            "lightEnabled": False,
            "fertilizerEnabled": self.fertilizer.is_active,
            "pesticideEnabled": self.pesticide.is_active,
        }

    def _get_device(self, kind: str) -> Optional[OutputDevice]:
        return {
            "pump": self.pump,
            "fertilizer": self.fertilizer,
            "pesticide": self.pesticide,
        }.get(kind)

    def _reconcile_state(self, executed_kinds: List[str]):
        for kind in executed_kinds:
            device = self._get_device(kind)
            if device is None:
                continue
            expected = False
            actual = device.is_active
            if actual != expected:
                pin = self._pins.kind_to_gpio(kind)
                logger.warning(
                    f"State reconciliation mismatch for '{kind}': "
                    f"expected GPIO{pin}=LOW, actual=HIGH"
                )

    def process_commands(self, commands: List[Dict]) -> None:
        if not commands:
            logger.debug("No commands to process")
            return

        light_cmds = [c for c in commands if c.get("kind") == "light"]
        for cmd in light_cmds:
            logger.info(
                f"Light command ignored (V2 has no grow light): "
                f"{cmd}"
            )

        relevant = [
            c for c in commands
            if c.get("kind") in ("pump", "fertilizer", "pesticide")
        ]
        if not relevant:
            logger.debug("No executable commands (all were light or unknown)")
            return

        max_ms = max(c.get("durationMs", 0) for c in relevant)
        if max_ms <= 0:
            logger.warning(f"All relevant commands have zero/negative duration: {relevant}")
            return

        for cmd in relevant:
            kind = cmd["kind"]
            device = self._get_device(kind)
            if device is None:
                continue
            device.on()
            self._log_relay(self._pins.kind_to_gpio(kind), True, kind)

        logger.info(
            f"Relays active: {[c['kind'] for c in relevant]} "
            f"for {max_ms}ms"
        )

        time.sleep(max_ms / 1000.0)

        for cmd in relevant:
            kind = cmd["kind"]
            device = self._get_device(kind)
            if device is None:
                continue
            device.off()
            self._log_relay(self._pins.kind_to_gpio(kind), False, kind)

        self._reconcile_state([c["kind"] for c in relevant])

    async def async_process_commands(self, commands: List[Dict]) -> None:
        await asyncio.to_thread(self.process_commands, commands)

    async def async_get_state(self) -> Dict:
        return await asyncio.to_thread(self.get_state)

    def cleanup(self):
        try:
            self.pump.off()
            self.fertilizer.off()
            self.pesticide.off()
            self.pump.close()
            self.fertilizer.close()
            self.pesticide.close()
            logger.info("Actuator cleanup complete")
        except Exception as e:
            logger.warning(f"Actuator cleanup error: {e}")

    async def async_cleanup(self):
        await asyncio.to_thread(self.cleanup)
