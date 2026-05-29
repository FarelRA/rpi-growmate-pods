"""
Health Monitor for GrowMate Pods.

Tracks system health metrics including:
- Circuit breaker states
- Retry statistics
- Queue depth and statistics
- Upload success/failure rates
- Overall system health

Error Handling - Exponential Backoff & Circuit Breaker
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Any
from datetime import datetime


logger = logging.getLogger("growmate.health_monitor")


class HealthStatus:
    """Health status levels."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


class HealthMonitor:
    """
    Monitors system health and aggregates metrics.
    
    Collects metrics from:
    - Circuit breakers (API client)
    - Retry handler (API client)
    - Queue manager
    - Upload processor
    """
    
    def __init__(self, api_client=None, queue_manager=None, upload_processor=None):
        """
        Initialize health monitor.
        
        Args:
            api_client: API client instance (for circuit breaker stats)
            queue_manager: Queue manager instance (for queue stats)
            upload_processor: Upload processor instance (for upload stats)
        """
        self.api_client = api_client
        self.queue_manager = queue_manager
        self.upload_processor = upload_processor
        
        # Health tracking
        self.start_time = time.time()
        self.last_health_check = None
        self.health_status = HealthStatus.HEALTHY
        
        # Metrics history (for trend analysis)
        self.metrics_history = []
        self.max_history_size = 100  # Keep last 100 health checks
        
        logger.info("Health monitor initialized")
    
    def set_components(self, api_client=None, queue_manager=None, upload_processor=None):
        """
        Set component references after initialization.
        
        Args:
            api_client: API client instance
            queue_manager: Queue manager instance
            upload_processor: Upload processor instance
        """
        if api_client:
            self.api_client = api_client
        if queue_manager:
            self.queue_manager = queue_manager
        if upload_processor:
            self.upload_processor = upload_processor
    
    async def collect_metrics(self) -> Dict[str, Any]:
        """
        Collect all system metrics.
        
        Returns:
            Dictionary with all metrics
        """
        metrics = {
            'timestamp': datetime.now().isoformat(),
            'uptime_seconds': time.time() - self.start_time,
            'health_status': self.health_status
        }
        
        # Circuit breaker metrics
        if self.api_client:
            try:
                cb_stats = self.api_client.get_circuit_breaker_stats()
                metrics['circuit_breakers'] = cb_stats
            except Exception as e:
                logger.error(f"Failed to collect circuit breaker metrics: {e}")
                metrics['circuit_breakers'] = {'error': str(e)}
        
        # Retry handler metrics
        if self.api_client:
            try:
                retry_stats = self.api_client.get_retry_stats()
                metrics['retry_handler'] = retry_stats
            except Exception as e:
                logger.error(f"Failed to collect retry metrics: {e}")
                metrics['retry_handler'] = {'error': str(e)}
        
        # Queue metrics
        if self.queue_manager:
            try:
                queue_stats = await self.queue_manager.async_get_stats()
                metrics['queue'] = queue_stats
            except Exception as e:
                logger.error(f"Failed to collect queue metrics: {e}")
                metrics['queue'] = {'error': str(e)}
        
        # Upload processor metrics
        if self.upload_processor:
            try:
                upload_stats = self.upload_processor.get_stats()
                metrics['upload_processor'] = upload_stats
            except Exception as e:
                logger.error(f"Failed to collect upload processor metrics: {e}")
                metrics['upload_processor'] = {'error': str(e)}
        
        return metrics
    
    def assess_health(self, metrics: Dict[str, Any]) -> str:
        """
        Assess overall system health based on metrics.
        
        Args:
            metrics: Collected metrics
            
        Returns:
            Health status (HEALTHY, DEGRADED, UNHEALTHY)
        """
        issues = []
        
        # Check circuit breakers
        cb_metrics = metrics.get('circuit_breakers', {})
        for endpoint, stats in cb_metrics.items():
            if isinstance(stats, dict):
                state = stats.get('state')
                if state == 'OPEN':
                    issues.append(f"Circuit breaker '{endpoint}' is OPEN")
                elif state == 'HALF_OPEN':
                    issues.append(f"Circuit breaker '{endpoint}' is HALF_OPEN (testing recovery)")
        
        # Check queue depth
        queue_metrics = metrics.get('queue', {})
        if isinstance(queue_metrics, dict):
            sensor_depth = queue_metrics.get('sensor_queue_depth', 0)
            image_depth = queue_metrics.get('image_queue_depth', 0)
            
            # Warn if queue is >80% full
            max_sensor = 6000
            max_image = 100
            
            if sensor_depth > max_sensor * 0.8:
                issues.append(f"Sensor queue at {sensor_depth}/{max_sensor} (>80%)")
            if image_depth > max_image * 0.8:
                issues.append(f"Image queue at {image_depth}/{max_image} (>80%)")
        
        # Check upload success rate
        upload_metrics = metrics.get('upload_processor', {})
        if isinstance(upload_metrics, dict):
            total = upload_metrics.get('total_processed', 0)
            failed = upload_metrics.get('sensor_uploads_failed', 0) + upload_metrics.get('image_uploads_failed', 0)
            
            if total > 10:  # Only assess if we have enough data
                failure_rate = (failed / total) * 100
                if failure_rate > 50:
                    issues.append(f"High upload failure rate: {failure_rate:.1f}%")
        
        # Determine health status
        if len(issues) == 0:
            return HealthStatus.HEALTHY
        elif len(issues) <= 2:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.UNHEALTHY
    
    async def check_health(self) -> Dict[str, Any]:
        """
        Perform health check and return status.
        
        Returns:
            Dictionary with health status and metrics
        """
        # Collect metrics
        metrics = await self.collect_metrics()
        
        # Assess health
        health_status = self.assess_health(metrics)
        self.health_status = health_status
        self.last_health_check = time.time()
        
        # Add to history
        self.metrics_history.append({
            'timestamp': metrics['timestamp'],
            'health_status': health_status,
            'metrics': metrics
        })
        
        # Trim history if too large
        if len(self.metrics_history) > self.max_history_size:
            self.metrics_history = self.metrics_history[-self.max_history_size:]
        
        # Log health status
        if health_status == HealthStatus.HEALTHY:
            logger.debug("System health: HEALTHY")
        elif health_status == HealthStatus.DEGRADED:
            logger.warning(f"System health: DEGRADED - {metrics}")
        else:
            logger.error(f"System health: UNHEALTHY - {metrics}")
        
        return {
            'health_status': health_status,
            'metrics': metrics
        }
    
    def get_health_summary(self) -> Dict[str, Any]:
        """
        Get health summary with key metrics.
        
        Returns:
            Dictionary with health summary
        """
        summary = {
            'health_status': self.health_status,
            'uptime_seconds': time.time() - self.start_time,
            'last_health_check': self.last_health_check
        }
        
        # Add circuit breaker states
        if self.api_client:
            try:
                cb_stats = self.api_client.get_circuit_breaker_stats()
                summary['circuit_breaker_states'] = {
                    endpoint: stats.get('state', 'UNKNOWN')
                    for endpoint, stats in cb_stats.items()
                }
            except:
                pass
        
        # Add queue depth
        if self.queue_manager:
            try:
                # Note: This is a sync call, may need to be wrapped in async
                summary['queue_depth'] = 'N/A (async required)'
            except:
                pass
        
        return summary
    
    def get_metrics_history(self, limit: int = 10) -> list:
        """
        Get recent metrics history.
        
        Args:
            limit: Number of recent entries to return
            
        Returns:
            List of recent metrics
        """
        return self.metrics_history[-limit:]
    
    def reset_metrics(self):
        """Reset all metrics and history."""
        self.metrics_history = []
        self.health_status = HealthStatus.HEALTHY
        self.last_health_check = None
        logger.info("Health metrics reset")


async def run_health_monitor(
    health_monitor: HealthMonitor,
    interval: int = 60,
    shutdown_event: Optional[asyncio.Event] = None
):
    """
    Run health monitor continuously.
    
    Args:
        health_monitor: HealthMonitor instance
        interval: Check interval in seconds (default: 60)
        shutdown_event: Event to signal shutdown
    """
    logger.info(f"Health monitor started (interval: {interval}s)")
    
    try:
        while True:
            if shutdown_event and shutdown_event.is_set():
                break
            
            try:
                # Perform health check
                await health_monitor.check_health()
            except Exception as e:
                logger.error(f"Health check failed: {e}")
            
            # Wait for next check
            if shutdown_event:
                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(),
                        timeout=interval
                    )
                    break  # Shutdown signaled
                except asyncio.TimeoutError:
                    pass  # Continue to next check
            else:
                await asyncio.sleep(interval)
        
        logger.info("Health monitor stopped")
        
    except asyncio.CancelledError:
        logger.info("Health monitor cancelled")
        raise
