import asyncio
import logging
import os
from typing import Dict, List, Optional

import aiohttp

from utils import (
    FIRMWARE_VERSION,
    API_TIMEOUT_SENSOR,
    API_TIMEOUT_STREAM_REGISTER,
    SENSOR_INTERVAL_SECONDS,
    get_env_device_id,
    get_env_api_key,
)
from circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from retry_handler import (
    RetryHandler,
    exponential_backoff_retry,
    categorize_error,
    ErrorCategory,
    PermanentError,
    RateLimitError,
)
from logging_config import get_correlation_id


SENSOR_URL = "https://growmate.bond/api/v2/sensors"
STREAM_REGISTER_URL = "https://growmate.bond/api/v2/stream/register"


logger = logging.getLogger("growmate.api")


class APIClient:

    def __init__(self, config: Dict):
        self.config = config
        self.device_id = get_env_device_id()
        self.api_key = get_env_api_key()

        self.sensor_url = config.get('api', {}).get('sensor_url', SENSOR_URL)
        self.stream_register_url = config.get('api', {}).get(
            'stream_register_url', STREAM_REGISTER_URL
        )

        self.session: Optional[aiohttp.ClientSession] = None

        cb_cfg = config.get('circuit_breaker', {})
        self.sensor_circuit_breaker = CircuitBreaker(
            name="sensor_api",
            failure_threshold=cb_cfg.get('failure_threshold', 5),
            recovery_timeout=cb_cfg.get('recovery_timeout', 60.0),
            success_threshold=cb_cfg.get('success_threshold', 2)
        )
        self.stream_circuit_breaker = CircuitBreaker(
            name="stream_api",
            failure_threshold=cb_cfg.get('failure_threshold', 5),
            recovery_timeout=cb_cfg.get('recovery_timeout', 60.0),
            success_threshold=cb_cfg.get('success_threshold', 2)
        )

        retry_config = config.get('retry', {})
        self.retry_handler = RetryHandler(
            max_attempts=retry_config.get('max_attempts', 6),
            initial_delay=retry_config.get('initial_delay', 1.0),
            max_delay=retry_config.get('max_delay', 32.0),
            jitter=retry_config.get('jitter', 0.25)
        )

        self.stream_registered = False
        self.last_stream_url: Optional[str] = None

        logger.info(
            f"API client initialized for device: {self.device_id} "
            f"(V2: sensor_url={self.sensor_url})"
        )

    def update_retry_config(self, retry_config: Dict):
        self.retry_handler.update_config(
            max_attempts=retry_config.get('max_attempts'),
            initial_delay=retry_config.get('initial_delay'),
            max_delay=retry_config.get('max_delay'),
            jitter=retry_config.get('jitter')
        )

    def update_circuit_breaker_config(self, cb_config: Dict):
        self.sensor_circuit_breaker.update_config(
            failure_threshold=cb_config.get('failure_threshold'),
            recovery_timeout=cb_config.get('recovery_timeout'),
            success_threshold=cb_config.get('success_threshold')
        )
        self.stream_circuit_breaker.update_config(
            failure_threshold=cb_config.get('failure_threshold'),
            recovery_timeout=cb_config.get('recovery_timeout'),
            success_threshold=cb_config.get('success_threshold')
        )

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()

    async def initialize(self):
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=60)
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector
            )
            logger.info("HTTP session initialized with connection pooling")

    async def cleanup(self):
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("HTTP session closed")

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': self.api_key,
            'X-Correlation-Id': get_correlation_id() or 'none',
        }
        return headers

    async def register_stream(self, stream_url: str) -> bool:
        if not self.session:
            await self.initialize()

        payload = {
            "deviceId": self.device_id,
            "streamUrl": stream_url,
        }

        async def _register():
            logger.debug(f"Registering stream: {stream_url}")
            async with self.session.post(
                self.stream_register_url,
                json=payload,
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT_STREAM_REGISTER)
            ) as response:
                if response.status == 429:
                    raise RateLimitError("Rate limit exceeded (429)")

                if 400 <= response.status < 500:
                    raise PermanentError(f"Client error: {response.status}")

                response.raise_for_status()
                data = await response.json()
                success = data.get("success", False)

                if success:
                    logger.info(f"Stream registered: {stream_url}")
                    self.stream_registered = True
                    self.last_stream_url = stream_url
                else:
                    logger.warning(f"Stream registration returned success=false: {data}")

                return success

        try:
            async def _register_with_circuit_breaker():
                return await self.stream_circuit_breaker.call(_register)

            return await self.retry_handler.execute(_register_with_circuit_breaker)

        except CircuitBreakerOpenError:
            logger.warning("Stream registration rejected: circuit breaker open")
            return False
        except PermanentError as e:
            logger.error(f"Stream registration failed: permanent error: {e}")
            return False
        except Exception as e:
            logger.error(f"Stream registration failed after retries: {e}")
            return False

    async def upload_sensor_data(
        self, sensors: List[Dict], current_state: Dict
    ) -> Optional[List[Dict]]:
        if not self.session:
            await self.initialize()

        payload = {
            "deviceId": self.device_id,
            "firmwareVersion": FIRMWARE_VERSION,
            "sensors": sensors,
            "currentState": current_state,
        }

        async def _upload():
            logger.debug(f"Uploading sensor data: {len(sensors)} sensors")

            async with self.session.post(
                self.sensor_url,
                json=payload,
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT_SENSOR)
            ) as response:
                if response.status == 429:
                    raise RateLimitError(f"Rate limit exceeded (429)")

                if 400 <= response.status < 500:
                    raise PermanentError(f"Client error: {response.status}")

                response.raise_for_status()

                data = await response.json()
                commands = data.get('commands', [])

                logger.info(
                    f"Sensor upload successful, received {len(commands)} commands"
                )
                return commands

        try:
            async def _upload_with_circuit_breaker():
                return await self.sensor_circuit_breaker.call(_upload)

            commands = await self.retry_handler.execute(_upload_with_circuit_breaker)
            return commands

        except CircuitBreakerOpenError:
            logger.warning("Sensor upload rejected: circuit breaker open")
            return None
        except PermanentError as e:
            logger.error(f"Sensor upload failed: permanent error: {e}")
            return None
        except Exception as e:
            logger.error(f"Sensor upload failed after all retries: {e}")
            return None

    def get_circuit_breaker_stats(self) -> Dict:
        return {
            'sensor_api': self.sensor_circuit_breaker.get_stats(),
            'stream_api': self.stream_circuit_breaker.get_stats(),
        }

    def get_retry_stats(self) -> Dict:
        return self.retry_handler.get_stats()

    def reset_circuit_breakers(self):
        self.sensor_circuit_breaker.reset()
        self.stream_circuit_breaker.reset()
        logger.info("All circuit breakers reset")

    def is_stream_registered(self) -> bool:
        return self.stream_registered

    def get_last_stream_url(self) -> Optional[str]:
        return self.last_stream_url


async def upload_sensors(config: Dict, sensors: List[Dict], current_state: Dict) -> Optional[List[Dict]]:
    async with APIClient(config) as client:
        return await client.upload_sensor_data(sensors, current_state)
