import asyncio
import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, PropertyMock, call, patch
from config_watcher import ConfigFileHandler, ConfigWatcher, watch_config_file


class TestConfigFileHandler:
    def test_on_modified_matching_path(self, mocker):
        p = Path("/etc/growmate/config.yaml").resolve()
        handler = ConfigFileHandler(p, lambda: None)
        mocker.patch.object(handler, '_schedule_reload')
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(p)
        handler.on_modified(event)
        handler._schedule_reload.assert_called_once()

    def test_on_modified_ignores_directories(self):
        p = Path("/etc/growmate/config.yaml").resolve()
        handler = ConfigFileHandler(p, lambda: None)
        handler._schedule_reload = MagicMock()
        event = MagicMock()
        event.is_directory = True
        handler.on_modified(event)
        handler._schedule_reload.assert_not_called()

    def test_on_modified_ignores_different_path(self):
        p = Path("/etc/growmate/config.yaml").resolve()
        handler = ConfigFileHandler(p, lambda: None)
        handler._schedule_reload = MagicMock()
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/other/file.yaml"
        handler.on_modified(event)
        handler._schedule_reload.assert_not_called()

    def test_on_created_matching_path(self, mocker):
        p = Path("/etc/growmate/config.yaml").resolve()
        handler = ConfigFileHandler(p, lambda: None)
        mocker.patch.object(handler, '_schedule_reload')
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(p)
        handler.on_created(event)
        handler._schedule_reload.assert_called_once()

    def test_on_created_ignores_directories(self):
        p = Path("/etc/growmate/config.yaml").resolve()
        handler = ConfigFileHandler(p, lambda: None)
        handler._schedule_reload = MagicMock()
        event = MagicMock()
        event.is_directory = True
        handler.on_created(event)
        handler._schedule_reload.assert_not_called()

    def test_schedule_reload_cancels_existing_task(self, mocker):
        p = Path("/etc/growmate/config.yaml").resolve()
        handler = ConfigFileHandler(p, lambda: None)
        mock_task = MagicMock()
        mock_task.done.return_value = False
        handler.debounce_task = mock_task
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        handler.loop = mock_loop
        mocker.patch('time.time', return_value=12345.0)
        handler._schedule_reload()
        mock_task.cancel.assert_called_once()
        mock_loop.is_running.assert_called_once()
        assert handler.last_modified == 12345.0

    def test_schedule_reload_no_loop_does_nothing(self, mocker):
        p = Path("/etc/growmate/config.yaml").resolve()
        handler = ConfigFileHandler(p, lambda: None)
        mocker.patch('time.time', return_value=100.0)
        handler._schedule_reload()
        assert handler.last_modified == 100.0

    def test_debounced_reload_skips_if_remodified(self):
        p = Path("/etc/growmate/config.yaml").resolve()
        callback = MagicMock()
        handler = ConfigFileHandler(p, callback, debounce_seconds=0.01)
        handler.last_modified = 100.0
        with patch('time.time', return_value=100.005):
            asyncio.run(handler._debounced_reload())
        callback.assert_not_called()

    def test_debounced_reload_calls_sync_callback(self):
        p = Path("/etc/growmate/config.yaml").resolve()
        callback = MagicMock()
        handler = ConfigFileHandler(p, callback, debounce_seconds=0.005)
        handler.last_modified = 100.0
        with patch('time.time', return_value=200.0):
            asyncio.run(handler._debounced_reload())
        callback.assert_called_once()

    def test_debounced_reload_calls_async_callback(self):
        p = Path("/etc/growmate/config.yaml").resolve()
        callback = AsyncMock()
        handler = ConfigFileHandler(p, callback, debounce_seconds=0.005)
        handler.last_modified = 100.0
        with patch('time.time', return_value=200.0):
            asyncio.run(handler._debounced_reload())
        callback.assert_awaited_once()

    def test_debounced_reload_handles_exception(self):
        p = Path("/etc/growmate/config.yaml").resolve()
        callback = MagicMock(side_effect=RuntimeError("boom"))
        handler = ConfigFileHandler(p, callback, debounce_seconds=0.005)
        handler.last_modified = 100.0
        with patch('time.time', return_value=200.0):
            asyncio.run(handler._debounced_reload())
        callback.assert_called_once()


class TestConfigWatcher:
    def test_start_normal(self, mocker):
        p = Path("/etc/growmate/config.yaml")
        watcher = ConfigWatcher(p, lambda: None, 1.0)
        mock_observer = MagicMock()
        mocker.patch('config_watcher.Observer', return_value=mock_observer)
        mock_loop = MagicMock()
        watcher.start(mock_loop)
        assert watcher.running is True
        assert watcher.event_handler is not None
        mock_observer.schedule.assert_called_once()
        mock_observer.start.assert_called_once()

    def test_start_twice_idempotent(self, mocker):
        p = Path("/etc/growmate/config.yaml")
        watcher = ConfigWatcher(p, lambda: None, 1.0)
        mock_observer = MagicMock()
        mocker.patch('config_watcher.Observer', return_value=mock_observer)
        mock_loop = MagicMock()
        watcher.start(mock_loop)
        watcher.start(mock_loop)
        assert watcher.running is True
        mock_observer.schedule.assert_called_once()
        mock_observer.start.assert_called_once()

    def test_stop_normal(self, mocker):
        p = Path("/etc/growmate/config.yaml")
        watcher = ConfigWatcher(p, lambda: None, 1.0)
        mock_observer = MagicMock()
        mocker.patch('config_watcher.Observer', return_value=mock_observer)
        mock_loop = MagicMock()
        watcher.start(mock_loop)
        watcher.stop()
        assert watcher.running is False
        assert watcher.observer is None
        assert watcher.event_handler is None
        mock_observer.stop.assert_called_once()
        mock_observer.join.assert_called_once_with(timeout=5.0)

    def test_stop_when_not_running(self):
        p = Path("/etc/growmate/config.yaml")
        watcher = ConfigWatcher(p, lambda: None, 1.0)
        watcher.stop()
        assert watcher.running is False

    def test_context_manager(self, mocker):
        p = Path("/etc/growmate/config.yaml")
        mock_observer = MagicMock()
        mocker.patch('config_watcher.Observer', return_value=mock_observer)
        mock_loop = MagicMock()
        with ConfigWatcher(p, lambda: None, 1.0) as watcher:
            watcher.start(mock_loop)
            assert watcher.running is True
        assert watcher.running is False

    def test_set_event_loop(self):
        p = Path("/etc/growmate/config.yaml").resolve()
        handler = ConfigFileHandler(p, lambda: None)
        loop = MagicMock()
        handler.set_event_loop(loop)
        assert handler.loop == loop


class TestWatchConfigFile:
    def test_watch_config_file_standalone(self, mocker):
        p = Path("/etc/growmate/config.yaml")
        mock_watcher = MagicMock()
        mocker.patch('config_watcher.ConfigWatcher', return_value=mock_watcher)
        shutdown_event = asyncio.Event()
        async def run():
            task = asyncio.create_task(watch_config_file(p, lambda: None, 1.0, shutdown_event))
            await asyncio.sleep(0.01)
            shutdown_event.set()
            await task
        asyncio.run(run())
        mock_watcher.start.assert_called_once()
        mock_watcher.stop.assert_called_once()
