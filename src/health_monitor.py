"""
Health Monitor for GrowMate Pods (V2).

Tracks system health metrics:
- Circuit breaker states
- Retry statistics
- Sensor queue depth
- Upload success/failure rates
- Stream registration state
- Tailscale connectivity (IP, status)
- Overall system health
"""

import asyncio
import logging
import time
import os
import subprocess
from typing import Dict, Optional, Any
from datetime import datetime


logger = logging.getLogger("growmate.health_monitor")


class HealthStatus:
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


class HealthMonitor:

    def __init__(self, api_client=None, queue_manager=None, upload_processor=None, camera_service=None):
        self.api_client = api_client
        self.queue_manager = queue_manager
        self.upload_processor = upload_processor
        self.camera_service = camera_service

        self.start_time = time.time()
        self.last_health_check = None
        self.health_status = HealthStatus.HEALTHY

        self.metrics_history = []
        self.max_history_size = 100

        logger.info("Health monitor initialized")

    def set_components(self, api_client=None, queue_manager=None, upload_processor=None, camera_service=None):
        if api_client:
            self.api_client = api_client
        if queue_manager:
            self.queue_manager = queue_manager
        if upload_processor:
            self.upload_processor = upload_processor
        if camera_service:
            self.camera_service = camera_service

    async def collect_metrics(self) -> Dict[str, Any]:
        metrics = {
            'timestamp': datetime.now().isoformat(),
            'uptime_seconds': time.time() - self.start_time,
            'health_status': self.health_status,
        }

        if self.api_client:
            try:
                cb_stats = self.api_client.get_circuit_breaker_stats()
                metrics['circuit_breakers'] = cb_stats
            except Exception as e:
                logger.error(f"Failed to collect circuit breaker metrics: {e}")
                metrics['circuit_breakers'] = {'error': str(e)}

        if self.api_client:
            try:
                retry_stats = self.api_client.get_retry_stats()
                metrics['retry_handler'] = retry_stats
            except Exception as e:
                logger.error(f"Failed to collect retry metrics: {e}")
                metrics['retry_handler'] = {'error': str(e)}

        if self.queue_manager:
            try:
                queue_stats = await self.queue_manager.async_get_queue_stats()
                metrics['queue'] = queue_stats
            except Exception as e:
                logger.error(f"Failed to collect queue metrics: {e}")
                metrics['queue'] = {'error': str(e)}

        if self.upload_processor:
            try:
                upload_stats = self.upload_processor.get_stats()
                metrics['upload_processor'] = upload_stats
            except Exception as e:
                logger.error(f"Failed to collect upload processor metrics: {e}")
                metrics['upload_processor'] = {'error': str(e)}

        if self.api_client:
            try:
                metrics['stream_registered'] = self.api_client.is_stream_registered()
            except Exception as e:
                metrics['stream_registered'] = False

        if self.camera_service:
            try:
                metrics['camera'] = self.camera_service.get_stats()
            except Exception as e:
                logger.error(f"Failed to collect camera metrics: {e}")
                metrics['camera'] = {'error': str(e)}

        try:
            metrics['tailscale'] = self._check_tailscale()
        except Exception as e:
            logger.error(f"Failed to collect Tailscale metrics: {e}")
            metrics['tailscale'] = {'error': str(e)}

        return metrics

    def _check_tailscale(self) -> Dict[str, Any]:
        result = {
            'ip': None,
            'status': 'UNKNOWN',
            'connected': False,
        }
        try:
            out = subprocess.run(
                ['tailscale', 'status'],
                capture_output=True, text=True, timeout=5
            )
            if out.returncode != 0:
                result['status'] = 'DISCONNECTED'
                result['connected'] = False
                return result

            for line in out.stdout.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 2:
                    import re
                    ip_match = re.match(r'^(\d+\.\d+\.\d+\.\d+)', parts[0])
                    if ip_match:
                        result['ip'] = ip_match.group(1)
                        result['status'] = 'CONNECTED' if 'active' in line.lower() else 'STOPPED'
                        result['connected'] = result['status'] == 'CONNECTED'
                        break
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            result['status'] = 'DISCONNECTED'
            result['connected'] = False
            logger.debug(f"Tailscale check failed: {e}")
        return result

    def assess_health(self, metrics: Dict[str, Any]) -> str:
        issues = []

        cb_metrics = metrics.get('circuit_breakers', {})
        for endpoint, stats in cb_metrics.items():
            if isinstance(stats, dict):
                state = stats.get('state')
                if state == 'OPEN':
                    issues.append(f"Circuit breaker '{endpoint}' is OPEN")
                elif state == 'HALF_OPEN':
                    issues.append(f"Circuit breaker '{endpoint}' is HALF_OPEN (testing recovery)")

        queue_metrics = metrics.get('queue', {})
        if isinstance(queue_metrics, dict):
            sensor_queue = queue_metrics.get('sensor_queue', {})
            if isinstance(sensor_queue, dict):
                sensor_depth = sensor_queue.get('pending', 0)

                max_sensor = 6000
                if sensor_depth > max_sensor * 0.8:
                    issues.append(f"Sensor queue at {sensor_depth}/{max_sensor} (>80%)")

        upload_metrics = metrics.get('upload_processor', {})
        if isinstance(upload_metrics, dict):
            total = upload_metrics.get('total_processed', 0)
            failed = upload_metrics.get('sensor_uploads_failed', 0)

            if total > 10:
                failure_rate = (failed / total) * 100
                if failure_rate > 50:
                    issues.append(f"High upload failure rate: {failure_rate:.1f}%")

        camera_metrics = metrics.get('camera', {})
        if isinstance(camera_metrics, dict):
            recent = camera_metrics.get('recent_crashes_1h', 0)
            if recent >= 5:
                issues.append(
                    f"Camera: {recent} crashes in last hour (threshold: 5)"
                )
            alive = camera_metrics.get('process_alive', True)
            if not alive:
                issues.append("Camera process is not running")

        tailscale = metrics.get('tailscale', {})
        if isinstance(tailscale, dict):
            ts_status = tailscale.get('status', 'UNKNOWN')
            if ts_status == 'DISCONNECTED':
                issues.append("Tailscale is DISCONNECTED")
            elif ts_status == 'STOPPED':
                issues.append("Tailscale is STOPPED")

        for issue in issues:
            if issue.startswith("Camera:"):
                return HealthStatus.UNHEALTHY

        if len(issues) == 0:
            return HealthStatus.HEALTHY
        elif len(issues) <= 2:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.UNHEALTHY

    async def check_health(self) -> Dict[str, Any]:
        metrics = await self.collect_metrics()

        health_status = self.assess_health(metrics)
        self.health_status = health_status
        self.last_health_check = time.time()

        self.metrics_history.append({
            'timestamp': metrics['timestamp'],
            'health_status': health_status,
            'metrics': metrics,
        })

        if len(self.metrics_history) > self.max_history_size:
            self.metrics_history = self.metrics_history[-self.max_history_size:]

        if health_status == HealthStatus.HEALTHY:
            logger.debug("System health: HEALTHY")
        elif health_status == HealthStatus.DEGRADED:
            logger.warning(f"System health: DEGRADED - {metrics}")
        else:
            logger.error(f"System health: UNHEALTHY - {metrics}")

        return {
            'health_status': health_status,
            'metrics': metrics,
        }

    def get_health_summary(self) -> Dict[str, Any]:
        summary = {
            'health_status': self.health_status,
            'uptime_seconds': time.time() - self.start_time,
            'last_health_check': self.last_health_check,
            'stream_registered': False,
        }

        if self.api_client:
            try:
                cb_stats = self.api_client.get_circuit_breaker_stats()
                summary['circuit_breaker_states'] = {
                    endpoint: stats.get('state', 'UNKNOWN')
                    for endpoint, stats in cb_stats.items()
                }
                summary['stream_registered'] = self.api_client.is_stream_registered()
            except Exception:
                pass

        return summary

    def get_metrics_history(self, limit: int = 10) -> list:
        return self.metrics_history[-limit:]

    def reset_metrics(self):
        self.metrics_history = []
        self.health_status = HealthStatus.HEALTHY
        self.last_health_check = None
        logger.info("Health metrics reset")


async def run_health_monitor(
    health_monitor: HealthMonitor,
    interval: int = 60,
    shutdown_event: Optional[asyncio.Event] = None
):
    logger.info(f"Health monitor started (interval: {interval}s)")

    try:
        while True:
            if shutdown_event and shutdown_event.is_set():
                break

            try:
                await health_monitor.check_health()
            except Exception as e:
                logger.error(f"Health check failed: {e}")

            if shutdown_event:
                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(),
                        timeout=interval
                    )
                    break
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(interval)

        logger.info("Health monitor stopped")

    except asyncio.CancelledError:
        logger.info("Health monitor cancelled")
        raise
