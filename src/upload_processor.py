import asyncio
import logging
from typing import Optional, Dict
from queue_manager import QueueManager
from api_client import APIClient
from circuit_breaker import CircuitBreakerOpenError


logger = logging.getLogger("growmate.upload_processor")


UPLOADER_DEFAULTS = {
    "max_concurrent": 3,
    "delay": 0.5,
    "idle_sleep": 2.0,
    "batch_sleep": 0.1,
}


class UploadProcessor:

    def __init__(self, queue_manager: QueueManager, api_client: APIClient, config: dict):
        self.queue = queue_manager
        self.api_client = api_client
        self.config = config

        up_cfg = config.get('upload_processor', {})
        self.max_concurrent_uploads = up_cfg.get('max_concurrent', UPLOADER_DEFAULTS['max_concurrent'])
        self.upload_delay = up_cfg.get('delay', UPLOADER_DEFAULTS['delay'])
        self._idle_sleep = up_cfg.get('idle_sleep', UPLOADER_DEFAULTS['idle_sleep'])
        self._batch_sleep = up_cfg.get('batch_sleep', UPLOADER_DEFAULTS['batch_sleep'])

        self.stats = {
            'sensor_uploads_success': 0,
            'sensor_uploads_failed': 0,
            'total_processed': 0,
        }

        self.upload_semaphore = asyncio.Semaphore(self.max_concurrent_uploads)

    def _is_circuit_open(self) -> bool:
        try:
            cb_stats = self.api_client.get_circuit_breaker_stats()
            sensor_state = cb_stats.get('sensor_api', {}).get('state', 'CLOSED')
            return sensor_state == 'OPEN'
        except Exception:
            return False

    async def process_sensor_item(self, item: dict) -> bool:
        try:
            device_id = item['device_id']
            firmware_version = item['firmware_version']
            sensor_data = item['sensor_data']
            current_state = item['current_state']
            retry_count = item['retry_count']
            item_id = item['id']

            logger.debug(
                f"Processing sensor data: ID {item_id}, "
                f"retry {retry_count}, {len(sensor_data)} sensors"
            )

            commands = await self.api_client.upload_sensor_data(sensor_data, current_state)

            if commands is not None:
                await self.queue.async_mark_sensor_uploaded(item_id)
                self.stats['sensor_uploads_success'] += 1
                self.stats['total_processed'] += 1

                logger.info(f"Sensor data uploaded successfully: ID {item_id}")

                return True
            else:
                await self.queue.async_mark_sensor_failed(item_id)
                self.stats['sensor_uploads_failed'] += 1
                self.stats['total_processed'] += 1

                logger.warning(f"Sensor data upload failed: ID {item_id}")
                return False

        except Exception as e:
            logger.error(f"Error processing sensor item: {e}")
            try:
                await self.queue.async_mark_sensor_failed(item['id'])
            except Exception:
                pass
            return False

    async def process_queue_once(self) -> int:
        processed = 0

        if self._is_circuit_open():
            logger.debug("Circuit breaker open, skipping upload drain")
            return 0

        sensor_item = await self.queue.async_dequeue_next_sensor()
        if sensor_item:
            async with self.upload_semaphore:
                await self.process_sensor_item(sensor_item)
                processed += 1
                await asyncio.sleep(self.upload_delay)

        return processed

    async def run_continuous(self, shutdown_event: asyncio.Event):
        logger.info("Upload processor started (sensor-only, V2)")

        try:
            while not shutdown_event.is_set():
                try:
                    processed = await self.process_queue_once()

                    if processed == 0:
                        await asyncio.sleep(self._idle_sleep)
                    else:
                        await asyncio.sleep(self._batch_sleep)

                except Exception as e:
                    logger.error(f"Error in upload processor loop: {e}")
                    await asyncio.sleep(5.0)

            logger.info("Upload processor stopped")

        except asyncio.CancelledError:
            logger.info("Upload processor cancelled")
            raise

    def get_stats(self) -> dict:
        return self.stats.copy()

    def reset_stats(self):
        self.stats = {
            'sensor_uploads_success': 0,
            'sensor_uploads_failed': 0,
            'total_processed': 0,
        }
