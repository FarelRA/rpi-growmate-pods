import signal
import pytest
from camera_service import CameraService


class TestCameraServiceInit:
    def test_default_config(self):
        cam = CameraService()
        assert cam._enabled is True
        assert cam._port == 8554
        assert cam.running is False
        assert cam.process is None
        assert cam.crash_count == 0

    def test_custom_config(self):
        cam = CameraService({"enabled": False, "port": 9999, "width": 320})
        assert cam._enabled is False
        assert cam._port == 9999


class TestCameraServiceStartStream:
    def test_start_stream_disabled(self, mocker):
        mocker.patch("camera_service.subprocess.Popen")
        cam = CameraService({"enabled": False})
        result = cam.start_stream()
        assert result is False
        assert cam.running is False

    def test_start_stream_finds_existing_process(self, mocker):
        mock_pid = 12345
        mocker.patch("camera_service.subprocess.run",
                     return_value=mocker.MagicMock(returncode=0, stdout=str(mock_pid)))
        mocker.patch.object(CameraService, "_is_pid_alive", return_value=True)
        mocker.patch("camera_service.subprocess.Popen")

        cam = CameraService()
        result = cam.start_stream()
        assert result is True
        assert cam.running is True

    def test_start_stream_success(self, mocker):
        mock_process = mocker.MagicMock()
        mock_process.pid = 99999
        mocker.patch("camera_service.subprocess.Popen", return_value=mock_process)

        cam = CameraService()
        result = cam.start_stream()
        assert result is True
        assert cam.running is True
        assert cam.process is mock_process

    def test_start_stream_popen_error(self, mocker):
        mocker.patch("camera_service.subprocess.Popen", side_effect=FileNotFoundError)
        cam = CameraService()
        result = cam.start_stream()
        assert result is False
        assert cam.running is False

    def test_start_stream_generic_exception(self, mocker):
        mocker.patch("camera_service.subprocess.Popen", side_effect=Exception("generic"))
        cam = CameraService()
        result = cam.start_stream()
        assert result is False
        assert cam.running is False


class TestCameraServiceStopStream:
    def test_stop_stream_sends_sigterm(self, mocker):
        mock_kill = mocker.patch("camera_service.os.kill")
        mock_wait = mocker.patch.object(CameraService, "_wait_for_exit")

        mock_process = mocker.MagicMock()
        mock_process.pid = 11111
        cam = CameraService()
        cam.process = mock_process
        cam.running = True

        cam.stop_stream()
        mock_kill.assert_called_once_with(11111, signal.SIGTERM)
        mock_wait.assert_called_once_with(11111, timeout=5)
        assert cam.running is False
        assert cam.process is None

    def test_stop_stream_process_already_dead(self, mocker):
        mocker.patch("camera_service.os.kill", side_effect=ProcessLookupError)
        mocker.patch.object(CameraService, "_wait_for_exit")

        mock_process = mocker.MagicMock()
        mock_process.pid = 22222
        cam = CameraService()
        cam.process = mock_process
        cam.running = True

        cam.stop_stream()
        assert cam.running is False
        assert cam.process is None

    def test_stop_stream_no_pid(self, mocker):
        mocker.patch("camera_service.os.kill")
        cam = CameraService()
        cam.stop_stream()
        assert cam.running is False

    def test_stop_stream_uses_pid_attr(self, mocker):
        mock_kill = mocker.patch("camera_service.os.kill")
        mock_wait = mocker.patch.object(CameraService, "_wait_for_exit")
        cam = CameraService()
        cam.process = None
        cam._pid = 33333
        cam.running = True
        cam.stop_stream()
        mock_kill.assert_called_once_with(33333, signal.SIGTERM)
        mock_wait.assert_called_once_with(33333, timeout=5)
        assert cam.running is False
        assert cam.process is None

    def test_stop_stream_generic_exception(self, mocker):
        mocker.patch("camera_service.os.kill", side_effect=PermissionError("denied"))
        mock_process = mocker.MagicMock()
        mock_process.pid = 44444
        cam = CameraService()
        cam.process = mock_process
        cam.running = True
        cam.stop_stream()
        assert cam.running is False
        assert cam.process is None


class TestCameraServiceIsProcessAlive:
    def test_is_process_alive_false_not_running(self):
        cam = CameraService()
        assert cam.is_process_alive() is False

    def test_is_process_alive_true(self, mocker):
        mock_process = mocker.MagicMock()
        mock_process.poll.return_value = None
        cam = CameraService()
        cam.process = mock_process
        cam.running = True
        assert cam.is_process_alive() is True

    def test_is_process_alive_false_poll_not_none(self, mocker):
        mock_process = mocker.MagicMock()
        mock_process.poll.return_value = 0
        cam = CameraService()
        cam.process = mock_process
        cam.running = True
        assert cam.is_process_alive() is False

    def test_is_process_alive_via_pid(self, mocker):
        cam = CameraService()
        cam.running = True
        cam.process = None
        cam._pid = 55555
        mocker.patch.object(cam, "_is_pid_alive", return_value=True)
        assert cam.is_process_alive() is True

    def test_is_process_alive_fallback_false(self):
        cam = CameraService()
        cam.running = True
        cam.process = None
        assert cam.is_process_alive() is False


class TestCameraServiceFindExistingProcess:
    def test_find_existing_process_found(self, mocker):
        mock_run = mocker.patch("camera_service.subprocess.run")
        mock_run.return_value = mocker.MagicMock(returncode=0, stdout="77777\n")
        mocker.patch.object(CameraService, "_is_pid_alive", return_value=True)
        cam = CameraService()
        pid = cam._find_existing_process()
        assert pid == 77777

    def test_find_existing_process_not_found(self, mocker):
        mock_run = mocker.patch("camera_service.subprocess.run")
        mock_run.return_value = mocker.MagicMock(returncode=1, stdout="")
        cam = CameraService()
        pid = cam._find_existing_process()
        assert pid is None

    def test_find_existing_process_pgrep_not_found(self, mocker):
        mocker.patch("camera_service.subprocess.run", side_effect=FileNotFoundError)
        cam = CameraService()
        pid = cam._find_existing_process()
        assert pid is None


class TestCameraServiceIsPidAlive:
    def test_is_pid_alive_true(self, mocker):
        mocker.patch("camera_service.os.kill")
        cam = CameraService()
        assert cam._is_pid_alive(12345) is True

    def test_is_pid_alive_false(self, mocker):
        mocker.patch("camera_service.os.kill", side_effect=ProcessLookupError)
        cam = CameraService()
        assert cam._is_pid_alive(12345) is False


class TestCameraServiceWaitForExit:
    def test_wait_for_exit_exits_within_timeout(self, mocker):
        kill_mock = mocker.patch("camera_service.os.kill", side_effect=[None, ProcessLookupError])
        mocker.patch("camera_service.time.sleep")
        cam = CameraService()
        cam._wait_for_exit(99999, timeout=5)
        kill_mock.assert_any_call(99999, 0)

    def test_wait_for_exit_timeout_expired(self, mocker):
        kill_mock = mocker.patch("camera_service.os.kill", return_value=None)
        mocker.patch("camera_service.os.waitpid")
        mocker.patch("camera_service.time.sleep")
        mocker.patch("camera_service.time.time", side_effect=[0, 10])
        cam = CameraService()
        cam._wait_for_exit(99999, timeout=1)
        kill_mock.assert_any_call(99999, signal.SIGKILL)

    def test_wait_for_exit_waitpid_raises(self, mocker):
        mocker.patch("camera_service.os.kill", side_effect=[None, None, ProcessLookupError])
        mocker.patch("camera_service.time.sleep")
        mocker.patch("camera_service.time.time", side_effect=[0, 10])
        mocker.patch("camera_service.os.waitpid", side_effect=ChildProcessError)
        cam = CameraService()
        cam._wait_for_exit(99999, timeout=1)


class TestCameraServiceRestart:
    def test_restart_stream_success(self, mocker):
        mock_stop = mocker.patch.object(CameraService, "stop_stream")
        mock_start = mocker.patch.object(CameraService, "start_stream", return_value=True)
        mock_sleep = mocker.patch("camera_service.time.sleep")
        cam = CameraService()
        result = cam.restart_stream()
        assert result is True
        assert cam.crash_count == 1
        assert cam.last_crash_time is not None
        assert len(cam.crash_timestamps) == 1
        mock_stop.assert_called_once()
        mock_start.assert_called_once()
        mock_sleep.assert_called_once_with(cam._restart_delay)

    def test_restart_stream_failure(self, mocker):
        mock_stop = mocker.patch.object(CameraService, "stop_stream")
        mock_start = mocker.patch.object(CameraService, "start_stream", return_value=False)
        mock_sleep = mocker.patch("camera_service.time.sleep")
        cam = CameraService()
        result = cam.restart_stream()
        assert result is False
        assert cam.crash_count == 0
        mock_stop.assert_called_once()
        mock_start.assert_called_once()
        mock_sleep.assert_called_once_with(cam._restart_delay)

    def test_restart_stream_trims_crash_timestamps(self, mocker):
        mock_stop = mocker.patch.object(CameraService, "stop_stream")
        mock_start = mocker.patch.object(CameraService, "start_stream", return_value=True)
        mock_sleep = mocker.patch("camera_service.time.sleep")
        import time
        cam = CameraService()
        cam.crash_timestamps = [time.time() - 7200, time.time() - 1800]
        result = cam.restart_stream()
        assert result is True
        assert len(cam.crash_timestamps) == 2


class TestCameraServiceGetStreamUrl:
    def test_get_stream_url(self):
        cam = CameraService()
        url = cam.get_stream_url("100.64.0.1")
        assert url == "tcp://100.64.0.1:8554"

    def test_get_stream_url_custom_port(self):
        cam = CameraService({"port": 8555})
        url = cam.get_stream_url("10.0.0.1")
        assert url == "tcp://10.0.0.1:8555"


class TestCameraServiceGetStats:
    def test_get_stats_basic(self, mocker):
        mocker.patch("camera_service.time.time", return_value=1000.0)
        mocker.patch.object(CameraService, "is_process_alive", return_value=True)
        cam = CameraService()
        cam.running = True
        cam.crash_count = 3
        cam.crash_timestamps = [900.0, 950.0, 999.0]
        cam.last_crash_time = 999.0
        stats = cam.get_stats()
        assert stats["running"] is True
        assert stats["process_alive"] is True
        assert stats["crash_count"] == 3
        assert stats["recent_crashes_1h"] == 3
        assert stats["last_crash_time"] == 999.0

    def test_get_stats_not_running(self, mocker):
        mocker.patch("camera_service.time.time", return_value=1000.0)
        mocker.patch.object(CameraService, "is_process_alive", return_value=False)
        cam = CameraService()
        stats = cam.get_stats()
        assert stats["running"] is False
        assert stats["process_alive"] is False
        assert stats["crash_count"] == 0


class TestCameraServiceCleanup:
    def test_cleanup(self, mocker):
        mock_stop = mocker.patch.object(CameraService, "stop_stream")
        cam = CameraService()
        cam.cleanup()
        mock_stop.assert_called_once()
