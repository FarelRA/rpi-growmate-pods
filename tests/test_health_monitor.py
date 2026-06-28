import pytest
from health_monitor import HealthMonitor, HealthStatus, run_health_monitor


class TestHealthStatus:
    def test_constants(self):
        assert HealthStatus.HEALTHY == "HEALTHY"
        assert HealthStatus.DEGRADED == "DEGRADED"
        assert HealthStatus.UNHEALTHY == "UNHEALTHY"


class TestHealthMonitor:
    @pytest.fixture
    def monitor(self):
        return HealthMonitor()

    def test_initial_state(self, monitor):
        assert monitor.health_status == HealthStatus.HEALTHY
        assert monitor.start_time > 0
        assert monitor.metrics_history == []

    def test_set_components(self):
        api = object()
        qm = object()
        up = object()
        cs = object()
        mon = HealthMonitor()
        mon.set_components(api_client=api, queue_manager=qm,
                           upload_processor=up, camera_service=cs)
        assert mon.api_client is api
        assert mon.queue_manager is qm
        assert mon.upload_processor is up
        assert mon.camera_service is cs

    def test_set_components_partial(self, monitor):
        api = object()
        monitor.set_components(api_client=api)
        assert monitor.api_client is api
        assert monitor.queue_manager is None

    @pytest.mark.asyncio
    async def test_collect_metrics_basic(self, monitor):
        metrics = await monitor.collect_metrics()
        assert "timestamp" in metrics
        assert "uptime_seconds" in metrics
        assert "health_status" in metrics
        assert metrics["health_status"] == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_collect_metrics_with_components(self, mocker):
        api = mocker.MagicMock()
        api.get_circuit_breaker_stats.return_value = {"sensors": {"state": "CLOSED"}}
        api.get_retry_stats.return_value = {"total_attempts": 10}
        api.is_stream_registered.return_value = True

        qm = mocker.AsyncMock()
        qm.async_get_queue_stats.return_value = {"sensor_queue": {"pending": 5}}

        up = mocker.MagicMock()
        up.get_stats.return_value = {"total_processed": 100, "sensor_uploads_failed": 2}

        cs = mocker.MagicMock()
        cs.get_stats.return_value = {"process_alive": True, "recent_crashes_1h": 0}

        monitor = HealthMonitor(
            api_client=api, queue_manager=qm,
            upload_processor=up, camera_service=cs
        )
        metrics = await monitor.collect_metrics()

        assert metrics["circuit_breakers"]["sensors"]["state"] == "CLOSED"
        assert metrics["retry_handler"]["total_attempts"] == 10
        assert metrics["queue"]["sensor_queue"]["pending"] == 5
        assert metrics["upload_processor"]["total_processed"] == 100
        assert metrics["stream_registered"] is True
        assert metrics["camera"]["process_alive"] is True
        assert "tailscale" in metrics

    @pytest.mark.asyncio
    async def test_collect_metrics_component_error(self, mocker):
        api = mocker.MagicMock()
        api.get_circuit_breaker_stats.side_effect = ValueError("fail")
        monitor = HealthMonitor(api_client=api)
        metrics = await monitor.collect_metrics()
        assert "error" in metrics["circuit_breakers"]

    def test_collect_metrics_retry_stats_exception(self, mocker):
        import asyncio
        api = mocker.MagicMock()
        api.get_circuit_breaker_stats.return_value = {}
        api.get_retry_stats.side_effect = ValueError("fail")
        monitor = HealthMonitor(api_client=api)
        metrics = asyncio.run(monitor.collect_metrics())
        assert "error" in metrics["retry_handler"]

    def test_collect_metrics_queue_stats_exception(self, mocker):
        import asyncio
        qm = mocker.AsyncMock()
        qm.async_get_queue_stats.side_effect = ValueError("fail")
        monitor = HealthMonitor(queue_manager=qm)
        metrics = asyncio.run(monitor.collect_metrics())
        assert "error" in metrics["queue"]

    def test_collect_metrics_upload_stats_exception(self, mocker):
        import asyncio
        up = mocker.MagicMock()
        up.get_stats.side_effect = ValueError("fail")
        monitor = HealthMonitor(upload_processor=up)
        metrics = asyncio.run(monitor.collect_metrics())
        assert "error" in metrics["upload_processor"]

    def test_collect_metrics_stream_registered_exception(self, mocker):
        import asyncio
        api = mocker.MagicMock()
        api.get_circuit_breaker_stats.return_value = {}
        api.get_retry_stats.return_value = {}
        api.is_stream_registered.side_effect = ValueError("fail")
        monitor = HealthMonitor(api_client=api)
        metrics = asyncio.run(monitor.collect_metrics())
        assert metrics["stream_registered"] is False

    def test_collect_metrics_camera_exception(self, mocker):
        import asyncio
        cs = mocker.MagicMock()
        cs.get_stats.side_effect = ValueError("fail")
        monitor = HealthMonitor(camera_service=cs)
        metrics = asyncio.run(monitor.collect_metrics())
        assert "error" in metrics["camera"]

    def test_collect_metrics_tailscale_exception(self, mocker):
        import asyncio
        monitor = HealthMonitor()
        mocker.patch.object(monitor, "_check_tailscale", side_effect=RuntimeError("fail"))
        metrics = asyncio.run(monitor.collect_metrics())
        assert "error" in metrics["tailscale"]

    def test_collect_metrics_tailscale_disconnected(self, mocker):
        import asyncio
        mock_result = mocker.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = ""
        mocker.patch("subprocess.run", return_value=mock_result)
        monitor = HealthMonitor()
        metrics = asyncio.run(monitor.collect_metrics())
        assert metrics["tailscale"]["status"] == "DISCONNECTED"
        assert metrics["tailscale"]["connected"] is False

    def test_collect_metrics_tailscale_filenotfound(self, mocker):
        import asyncio
        mocker.patch("subprocess.run", side_effect=FileNotFoundError("no tailscale"))
        monitor = HealthMonitor()
        metrics = asyncio.run(monitor.collect_metrics())
        assert metrics["tailscale"]["status"] == "DISCONNECTED"
        assert metrics["tailscale"]["connected"] is False

    def test_assess_health_healthy(self, monitor):
        metrics = {
            "circuit_breakers": {},
            "queue": {"sensor_queue": {"pending": 0}},
            "upload_processor": {"total_processed": 0, "sensor_uploads_failed": 0},
            "camera": {"process_alive": True, "recent_crashes_1h": 0},
            "tailscale": {"status": "CONNECTED", "connected": True, "ip": "100.x.x.x"},
        }
        assert monitor.assess_health(metrics) == HealthStatus.HEALTHY

    def test_assess_health_degraded_circuit_breaker(self, monitor):
        metrics = {
            "circuit_breakers": {"sensors": {"state": "OPEN"}},
            "queue": {"sensor_queue": {"pending": 0}},
            "upload_processor": {"total_processed": 0, "sensor_uploads_failed": 0},
            "camera": {"process_alive": True, "recent_crashes_1h": 0},
            "tailscale": {"status": "CONNECTED", "connected": True, "ip": "100.x.x.x"},
        }
        assert monitor.assess_health(metrics) == HealthStatus.DEGRADED

    def test_assess_health_degraded_queue_backlog(self, monitor):
        metrics = {
            "circuit_breakers": {},
            "queue": {"sensor_queue": {"pending": 5000}},
            "upload_processor": {"total_processed": 0, "sensor_uploads_failed": 0},
            "camera": {"process_alive": True, "recent_crashes_1h": 0},
            "tailscale": {"status": "CONNECTED", "connected": True, "ip": "100.x.x.x"},
        }
        assert monitor.assess_health(metrics) == HealthStatus.DEGRADED

    def test_assess_health_unhealthy_camera_crashes(self, monitor):
        metrics = {
            "circuit_breakers": {},
            "queue": {"sensor_queue": {"pending": 0}},
            "upload_processor": {"total_processed": 0, "sensor_uploads_failed": 0},
            "camera": {"process_alive": True, "recent_crashes_1h": 5},
            "tailscale": {"status": "CONNECTED", "connected": True, "ip": "100.x.x.x"},
        }
        assert monitor.assess_health(metrics) == HealthStatus.UNHEALTHY

    def test_assess_health_unhealthy_many_issues(self, monitor):
        metrics = {
            "circuit_breakers": {"sensors": {"state": "OPEN"}, "stream": {"state": "OPEN"}},
            "queue": {"sensor_queue": {"pending": 5000}},
            "upload_processor": {"total_processed": 0, "sensor_uploads_failed": 0},
            "camera": {"process_alive": False, "recent_crashes_1h": 0},
            "tailscale": {"status": "DISCONNECTED", "connected": False, "ip": None},
        }
        assert monitor.assess_health(metrics) == HealthStatus.UNHEALTHY

    def test_assess_health_tailscale_disconnected(self, monitor):
        metrics = {
            "circuit_breakers": {},
            "queue": {"sensor_queue": {"pending": 0}},
            "upload_processor": {"total_processed": 0, "sensor_uploads_failed": 0},
            "camera": {"process_alive": True, "recent_crashes_1h": 0},
            "tailscale": {"status": "DISCONNECTED", "connected": False, "ip": None},
        }
        assert monitor.assess_health(metrics) == HealthStatus.DEGRADED

    def test_assess_health_degraded_half_open(self, monitor):
        metrics = {
            "circuit_breakers": {"sensors": {"state": "HALF_OPEN"}},
            "queue": {"sensor_queue": {"pending": 0}},
            "upload_processor": {"total_processed": 0, "sensor_uploads_failed": 0},
            "camera": {"process_alive": True, "recent_crashes_1h": 0},
            "tailscale": {"status": "CONNECTED", "connected": True, "ip": "100.x.x.x"},
        }
        assert monitor.assess_health(metrics) == HealthStatus.DEGRADED

    def test_assess_health_high_upload_failure(self, monitor):
        metrics = {
            "circuit_breakers": {},
            "queue": {"sensor_queue": {"pending": 0}},
            "upload_processor": {"total_processed": 100, "sensor_uploads_failed": 60},
            "camera": {"process_alive": True, "recent_crashes_1h": 0},
            "tailscale": {"status": "CONNECTED", "connected": True, "ip": "100.x.x.x"},
        }
        assert monitor.assess_health(metrics) == HealthStatus.DEGRADED

    def test_assess_health_tailscale_stopped(self, monitor):
        metrics = {
            "circuit_breakers": {},
            "queue": {"sensor_queue": {"pending": 0}},
            "upload_processor": {"total_processed": 0, "sensor_uploads_failed": 0},
            "camera": {"process_alive": True, "recent_crashes_1h": 0},
            "tailscale": {"status": "STOPPED", "connected": False, "ip": None},
        }
        assert monitor.assess_health(metrics) == HealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_check_health(self, monitor, mocker):
        mocker.patch.object(monitor, "collect_metrics", return_value={
            "timestamp": "2026-01-01T00:00:00",
            "circuit_breakers": {},
            "queue": {"sensor_queue": {"pending": 0}},
            "upload_processor": {"total_processed": 0, "sensor_uploads_failed": 0},
            "camera": {"process_alive": True, "recent_crashes_1h": 0},
            "tailscale": {"status": "CONNECTED", "connected": True, "ip": "100.x.x.x"},
        })
        result = await monitor.check_health()
        assert result["health_status"] == HealthStatus.HEALTHY
        assert monitor.health_status == HealthStatus.HEALTHY
        assert len(monitor.metrics_history) == 1

    def test_check_health_degraded(self, monitor, mocker):
        import asyncio
        mocker.patch.object(monitor, "collect_metrics", return_value={
            "timestamp": "2026-01-01T00:00:00",
            "circuit_breakers": {"sensors": {"state": "OPEN"}},
            "queue": {"sensor_queue": {"pending": 0}},
            "upload_processor": {"total_processed": 0, "sensor_uploads_failed": 0},
            "camera": {"process_alive": True, "recent_crashes_1h": 0},
            "tailscale": {"status": "CONNECTED", "connected": True, "ip": "100.x.x.x"},
        })
        result = asyncio.run(monitor.check_health())
        assert result["health_status"] == HealthStatus.DEGRADED
        assert monitor.health_status == HealthStatus.DEGRADED

    def test_check_health_unhealthy(self, monitor, mocker):
        import asyncio
        mocker.patch.object(monitor, "collect_metrics", return_value={
            "timestamp": "2026-01-01T00:00:00",
            "circuit_breakers": {"sensors": {"state": "OPEN"}, "stream": {"state": "OPEN"}},
            "queue": {"sensor_queue": {"pending": 5000}},
            "upload_processor": {"total_processed": 0, "sensor_uploads_failed": 0},
            "camera": {"process_alive": False, "recent_crashes_1h": 5},
            "tailscale": {"status": "DISCONNECTED", "connected": False, "ip": None},
        })
        result = asyncio.run(monitor.check_health())
        assert result["health_status"] == HealthStatus.UNHEALTHY
        assert monitor.health_status == HealthStatus.UNHEALTHY

    def test_check_health_trims_history(self, monitor, mocker):
        import asyncio
        monitor.max_history_size = 3
        monitor.metrics_history = [{"i": i} for i in range(3)]
        mocker.patch.object(monitor, "collect_metrics", return_value={
            "timestamp": "2026-01-01T00:00:00",
        })
        asyncio.run(monitor.check_health())
        assert len(monitor.metrics_history) == 3
        assert monitor.metrics_history[0]["i"] == 1

    def test_get_health_summary_no_components(self, monitor):
        summary = monitor.get_health_summary()
        assert summary["health_status"] == HealthStatus.HEALTHY
        assert "uptime_seconds" in summary
        assert "stream_registered" in summary

    def test_get_health_summary_with_api(self, mocker):
        api = mocker.MagicMock()
        api.get_circuit_breaker_stats.return_value = {"sensors": {"state": "CLOSED"}}
        api.is_stream_registered.return_value = True
        monitor = HealthMonitor(api_client=api)
        summary = monitor.get_health_summary()
        assert summary["stream_registered"] is True
        assert "sensors" in summary["circuit_breaker_states"]

    def test_get_health_summary_api_exception(self, mocker):
        api = mocker.MagicMock()
        api.get_circuit_breaker_stats.side_effect = ValueError("fail")
        monitor = HealthMonitor(api_client=api)
        summary = monitor.get_health_summary()
        assert summary["stream_registered"] is False
        assert "circuit_breaker_states" not in summary

    def test_get_metrics_history(self, monitor, mocker):
        mocker.patch.object(monitor, "collect_metrics", return_value={
            "timestamp": "2026-01-01T00:00:00",
        })
        import asyncio
        asyncio.run(monitor.check_health())
        history = monitor.get_metrics_history()
        assert len(history) == 1
        assert len(monitor.get_metrics_history(limit=1)) == 1

    def test_reset_metrics(self, monitor, mocker):
        monitor.health_status = HealthStatus.UNHEALTHY
        monitor.metrics_history = [{"test": True}]
        monitor.reset_metrics()
        assert monitor.health_status == HealthStatus.HEALTHY
        assert monitor.metrics_history == []
        assert monitor.last_health_check is None


class TestRunHealthMonitor:
    def test_runs_and_stops_on_shutdown(self, mocker):
        import asyncio
        monitor = HealthMonitor()
        mocker.patch.object(monitor, "check_health", return_value={"health_status": "HEALTHY"})
        shutdown_event = asyncio.Event()
        shutdown_event.set()

        asyncio.run(run_health_monitor(monitor, interval=0.01, shutdown_event=shutdown_event))

    def test_handles_check_health_exception(self, mocker):
        import asyncio
        monitor = HealthMonitor()
        mocker.patch.object(monitor, "check_health", side_effect=ValueError("fail"))
        shutdown_event = asyncio.Event()
        shutdown_event.set()

        asyncio.run(run_health_monitor(monitor, interval=0.01, shutdown_event=shutdown_event))

    def test_run_health_monitor_check_health_exception(self, mocker):
        import asyncio
        monitor = HealthMonitor()
        mocker.patch.object(monitor, "check_health", side_effect=ValueError("fail"))
        shutdown_event = asyncio.Event()
        async def _run():
            task = asyncio.create_task(
                run_health_monitor(monitor, interval=0.01, shutdown_event=shutdown_event)
            )
            await asyncio.sleep(0.15)
            shutdown_event.set()
            await task
        asyncio.run(_run())

    def test_run_health_monitor_no_shutdown_event(self, mocker):
        import asyncio
        monitor = HealthMonitor()
        mocker.patch.object(monitor, "check_health", return_value={"health_status": "HEALTHY"})
        async def _run():
            task = asyncio.create_task(
                run_health_monitor(monitor, interval=0.01, shutdown_event=None)
            )
            await asyncio.sleep(0.08)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        asyncio.run(_run())

    def test_run_health_monitor_cancelled(self, mocker):
        import asyncio
        monitor = HealthMonitor()
        mocker.patch.object(monitor, "check_health", return_value={"health_status": "HEALTHY"})
        shutdown_event = asyncio.Event()
        async def _run():
            task = asyncio.create_task(
                run_health_monitor(monitor, interval=60, shutdown_event=shutdown_event)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        asyncio.run(_run())
