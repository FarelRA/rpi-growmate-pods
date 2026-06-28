import asyncio
import copy
import pytest
from unittest.mock import MagicMock, AsyncMock


SENSOR_ITEM = {
    "id": 1,
    "device_id": "growmate-test",
    "firmware_version": "2.0.0",
    "sensor_data": [{"type": "temp", "value": 25.0}],
    "current_state": {"status": "ok"},
    "retry_count": 0,
}

MINIMAL_CONFIG = {
    "upload_processor": {
        "max_concurrent": 3,
        "delay": 0.5,
        "idle_sleep": 2.0,
        "batch_sleep": 0.1,
    },
}


@pytest.fixture
def mock_queue(mocker):
    q = AsyncMock()
    q.async_dequeue_next_sensor = AsyncMock(return_value=None)
    q.async_mark_sensor_uploaded = AsyncMock(return_value=True)
    q.async_mark_sensor_failed = AsyncMock(return_value=True)
    return q


@pytest.fixture
def mock_api(mocker):
    api = AsyncMock()
    api.upload_sensor_data = AsyncMock(return_value=[{"action": "water"}])
    api.get_circuit_breaker_stats = MagicMock(return_value={
        "sensor_api": {"state": "CLOSED"},
    })
    return api


@pytest.fixture
def processor(mock_queue, mock_api):
    from upload_processor import UploadProcessor
    p = UploadProcessor(mock_queue, mock_api, copy.deepcopy(MINIMAL_CONFIG))
    return p


class TestInit:
    def test_reads_config_values(self, mock_queue, mock_api):
        from upload_processor import UploadProcessor
        p = UploadProcessor(mock_queue, mock_api, copy.deepcopy(MINIMAL_CONFIG))
        assert p.max_concurrent_uploads == 3
        assert p.upload_delay == 0.5
        assert p._idle_sleep == 2.0
        assert p._batch_sleep == 0.1

    def test_defaults_when_missing(self, mock_queue, mock_api):
        from upload_processor import UploadProcessor
        p = UploadProcessor(mock_queue, mock_api, {})
        from upload_processor import UPLOADER_DEFAULTS
        assert p.max_concurrent_uploads == UPLOADER_DEFAULTS["max_concurrent"]
        assert p.upload_delay == UPLOADER_DEFAULTS["delay"]
        assert p._idle_sleep == UPLOADER_DEFAULTS["idle_sleep"]
        assert p._batch_sleep == UPLOADER_DEFAULTS["batch_sleep"]

    def test_starts_with_zero_stats(self, processor):
        assert processor.stats["sensor_uploads_success"] == 0
        assert processor.stats["sensor_uploads_failed"] == 0
        assert processor.stats["total_processed"] == 0

    def test_creates_semaphore(self, processor):
        assert isinstance(processor.upload_semaphore, asyncio.Semaphore)
        assert processor.upload_semaphore._value == 3


class TestIsCircuitOpen:
    def test_returns_false_when_closed(self, processor):
        assert processor._is_circuit_open() is False

    def test_returns_true_when_open(self, mock_queue, mock_api):
        from upload_processor import UploadProcessor
        mock_api.get_circuit_breaker_stats = MagicMock(return_value={
            "sensor_api": {"state": "OPEN"},
        })
        p = UploadProcessor(mock_queue, mock_api, {})
        assert p._is_circuit_open() is True

    def test_returns_false_on_exception(self, processor, mock_api):
        mock_api.get_circuit_breaker_stats.side_effect = ValueError()
        assert processor._is_circuit_open() is False


class TestProcessSensorItem:
    @pytest.mark.asyncio
    async def test_success_calls_mark_uploaded(self, processor, mock_queue, mock_api):
        result = await processor.process_sensor_item(SENSOR_ITEM)
        assert result is True
        mock_api.upload_sensor_data.assert_awaited_once()
        mock_queue.async_mark_sensor_uploaded.assert_awaited_once_with(1)

    @pytest.mark.asyncio
    async def test_success_updates_stats(self, processor, mock_queue, mock_api):
        await processor.process_sensor_item(SENSOR_ITEM)
        assert processor.stats["sensor_uploads_success"] == 1
        assert processor.stats["total_processed"] == 1

    @pytest.mark.asyncio
    async def test_failure_calls_mark_failed(self, processor, mock_queue, mock_api):
        mock_api.upload_sensor_data = AsyncMock(return_value=None)
        result = await processor.process_sensor_item(SENSOR_ITEM)
        assert result is False
        mock_queue.async_mark_sensor_failed.assert_awaited_once_with(1, 5)

    @pytest.mark.asyncio
    async def test_failure_updates_stats(self, processor, mock_queue, mock_api):
        mock_api.upload_sensor_data = AsyncMock(return_value=None)
        await processor.process_sensor_item(SENSOR_ITEM)
        assert processor.stats["sensor_uploads_failed"] == 1
        assert processor.stats["total_processed"] == 1

    @pytest.mark.asyncio
    async def test_exception_during_upload(self, processor, mock_queue, mock_api):
        mock_api.upload_sensor_data = AsyncMock(side_effect=ValueError("fail"))
        result = await processor.process_sensor_item(SENSOR_ITEM)
        assert result is False

    @pytest.mark.asyncio
    async def test_exception_still_calls_mark_failed(self, processor, mock_queue, mock_api):
        mock_api.upload_sensor_data = AsyncMock(side_effect=ValueError("fail"))
        await processor.process_sensor_item(SENSOR_ITEM)
        mock_queue.async_mark_sensor_failed.assert_awaited_once_with(1, 5)


class TestProcessQueueOnce:
    @pytest.mark.asyncio
    async def test_processes_item_when_available(self, processor, mock_queue, mock_api):
        mock_queue.async_dequeue_next_sensor = AsyncMock(return_value=SENSOR_ITEM)
        processed = await processor.process_queue_once()
        assert processed == 1
        mock_api.upload_sensor_data.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_empty(self, processor, mock_queue):
        mock_queue.async_dequeue_next_sensor = AsyncMock(return_value=None)
        processed = await processor.process_queue_once()
        assert processed == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_circuit_open(self, processor, mock_api):
        mock_api.get_circuit_breaker_stats = MagicMock(return_value={
            "sensor_api": {"state": "OPEN"},
        })
        processed = await processor.process_queue_once()
        assert processed == 0


class TestContinuousLoop:
    @pytest.mark.asyncio
    async def test_processes_then_sleeps_batch(self, processor, mock_queue):
        mock_queue.async_dequeue_next_sensor = AsyncMock(
            side_effect=[SENSOR_ITEM, None]
        )
        shutdown = asyncio.Event()
        task = asyncio.create_task(processor.run_continuous(shutdown))
        await asyncio.sleep(0.3)
        shutdown.set()
        await asyncio.wait_for(task, timeout=2.0)
        assert processor.stats["total_processed"] == 1

    @pytest.mark.asyncio
    async def test_empty_queue_sleeps_idle(self, processor, mock_queue):
        mock_queue.async_dequeue_next_sensor = AsyncMock(return_value=None)
        shutdown = asyncio.Event()
        task = asyncio.create_task(processor.run_continuous(shutdown))
        await asyncio.sleep(0.1)
        shutdown.set()
        await asyncio.wait_for(task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_cancelled_error_stops(self, processor, mock_queue):
        shutdown = asyncio.Event()
        task = asyncio.create_task(processor.run_continuous(shutdown))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class TestStats:
    def test_get_stats_returns_copy(self, processor):
        stats = processor.get_stats()
        stats["total_processed"] = 999
        assert processor.stats["total_processed"] == 0

    def test_reset_stats(self, processor):
        processor.stats["total_processed"] = 10
        processor.reset_stats()
        assert processor.stats["total_processed"] == 0
        assert processor.stats["sensor_uploads_success"] == 0
        assert processor.stats["sensor_uploads_failed"] == 0

    def test_get_stats_isolation(self, processor):
        s1 = processor.get_stats()
        s2 = processor.get_stats()
        assert s1 is not s2
