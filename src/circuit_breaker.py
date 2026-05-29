"""
Circuit Breaker Pattern for GrowMate Pods.

Implements industry-standard circuit breaker to prevent cascading failures
and allow graceful degradation during API outages.

Error Handling - Exponential Backoff & Circuit Breaker

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Too many failures, requests fail immediately (fast-fail)
- HALF_OPEN: Testing recovery, limited requests pass through

State Transitions:
- CLOSED → OPEN: After N consecutive failures (default: 5)
- OPEN → HALF_OPEN: After timeout period (default: 60s)
- HALF_OPEN → CLOSED: After N consecutive successes (default: 2)
- HALF_OPEN → OPEN: After any failure
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Callable, Any, Optional


logger = logging.getLogger("growmate.circuit_breaker")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "CLOSED"        # Normal operation
    OPEN = "OPEN"            # Failing, reject requests
    HALF_OPEN = "HALF_OPEN"  # Testing recovery


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreaker:
    """
    Circuit breaker implementation for API calls.
    
    Prevents cascading failures by failing fast when API is down.
    Allows periodic testing to detect when API recovers.
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2
    ):
        """
        Initialize circuit breaker.
        
        Args:
            name: Circuit breaker name (for logging)
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            success_threshold: Number of successes needed to close circuit
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        
        # State
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.last_state_change: float = time.time()
        
        # Statistics
        self.total_calls = 0
        self.total_successes = 0
        self.total_failures = 0
        self.total_rejections = 0
        
        logger.info(
            f"Circuit breaker '{name}' initialized: "
            f"failure_threshold={failure_threshold}, "
            f"recovery_timeout={recovery_timeout}s, "
            f"success_threshold={success_threshold}"
        )
    
    def update_config(
        self,
        failure_threshold: Optional[int] = None,
        recovery_timeout: Optional[float] = None,
        success_threshold: Optional[int] = None
    ):
        """
        Update circuit breaker configuration at runtime (Hot-reload support).
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            success_threshold: Number of successes needed to close circuit
        """
        if failure_threshold is not None:
            old_val = self.failure_threshold
            self.failure_threshold = failure_threshold
            logger.info(f"Circuit breaker '{self.name}' failure_threshold: {old_val} → {failure_threshold}")
        
        if recovery_timeout is not None:
            old_val = self.recovery_timeout
            self.recovery_timeout = recovery_timeout
            logger.info(f"Circuit breaker '{self.name}' recovery_timeout: {old_val}s → {recovery_timeout}s")
        
        if success_threshold is not None:
            old_val = self.success_threshold
            self.success_threshold = success_threshold
            logger.info(f"Circuit breaker '{self.name}' success_threshold: {old_val} → {success_threshold}")
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function through circuit breaker.
        
        Args:
            func: Async function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerOpenError: If circuit is open
            Exception: Any exception raised by the function
        """
        self.total_calls += 1
        
        # Check if circuit should transition from OPEN to HALF_OPEN
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._transition_to_half_open()
            else:
                # Circuit still open, reject immediately
                self.total_rejections += 1
                logger.warning(
                    f"Circuit breaker '{self.name}' is OPEN, "
                    f"rejecting call (fast-fail)"
                )
                raise CircuitBreakerOpenError(
                    f"Circuit breaker '{self.name}' is open"
                )
        
        # Attempt to execute function
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _should_attempt_reset(self) -> bool:
        """
        Check if enough time has passed to attempt recovery.
        
        Returns:
            True if should attempt reset, False otherwise
        """
        if self.last_failure_time is None:
            return False
        
        elapsed = time.time() - self.last_failure_time
        return elapsed >= self.recovery_timeout
    
    def _transition_to_half_open(self):
        """Transition from OPEN to HALF_OPEN state."""
        logger.info(
            f"Circuit breaker '{self.name}': OPEN → HALF_OPEN "
            f"(testing recovery after {self.recovery_timeout}s)"
        )
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        self.last_state_change = time.time()
    
    def _on_success(self):
        """Handle successful call."""
        self.total_successes += 1
        
        if self.state == CircuitState.HALF_OPEN:
            # In HALF_OPEN, count successes
            self.success_count += 1
            logger.debug(
                f"Circuit breaker '{self.name}': success in HALF_OPEN "
                f"({self.success_count}/{self.success_threshold})"
            )
            
            if self.success_count >= self.success_threshold:
                # Enough successes, close circuit
                logger.info(
                    f"Circuit breaker '{self.name}': HALF_OPEN → CLOSED "
                    f"(recovered after {self.success_threshold} successes)"
                )
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                self.last_state_change = time.time()
        
        elif self.state == CircuitState.CLOSED:
            # In CLOSED, reset failure count on success
            self.failure_count = 0
    
    def _on_failure(self):
        """Handle failed call."""
        self.total_failures += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.HALF_OPEN:
            # In HALF_OPEN, any failure reopens circuit
            logger.warning(
                f"Circuit breaker '{self.name}': HALF_OPEN → OPEN "
                f"(failure during recovery test)"
            )
            self.state = CircuitState.OPEN
            self.failure_count = 0
            self.success_count = 0
            self.last_state_change = time.time()
        
        elif self.state == CircuitState.CLOSED:
            # In CLOSED, count failures
            self.failure_count += 1
            logger.debug(
                f"Circuit breaker '{self.name}': failure in CLOSED "
                f"({self.failure_count}/{self.failure_threshold})"
            )
            
            if self.failure_count >= self.failure_threshold:
                # Too many failures, open circuit
                logger.error(
                    f"Circuit breaker '{self.name}': CLOSED → OPEN "
                    f"(threshold reached: {self.failure_threshold} failures)"
                )
                self.state = CircuitState.OPEN
                self.last_state_change = time.time()
    
    def get_state(self) -> str:
        """
        Get current circuit breaker state.
        
        Returns:
            State name as string
        """
        return self.state.value
    
    def get_stats(self) -> dict:
        """
        Get circuit breaker statistics.
        
        Returns:
            Dictionary with statistics
        """
        uptime = time.time() - self.last_state_change
        success_rate = (
            (self.total_successes / self.total_calls * 100)
            if self.total_calls > 0 else 0.0
        )
        
        return {
            'name': self.name,
            'state': self.state.value,
            'failure_count': self.failure_count,
            'success_count': self.success_count,
            'total_calls': self.total_calls,
            'total_successes': self.total_successes,
            'total_failures': self.total_failures,
            'total_rejections': self.total_rejections,
            'success_rate': round(success_rate, 2),
            'time_in_current_state': round(uptime, 2),
            'last_failure_time': self.last_failure_time
        }
    
    def reset(self):
        """Reset circuit breaker to initial state."""
        logger.info(f"Circuit breaker '{self.name}' manually reset")
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.last_state_change = time.time()
    
    def is_open(self) -> bool:
        """
        Check if circuit is open.
        
        Returns:
            True if circuit is open, False otherwise
        """
        return self.state == CircuitState.OPEN
    
    def is_closed(self) -> bool:
        """
        Check if circuit is closed.
        
        Returns:
            True if circuit is closed, False otherwise
        """
        return self.state == CircuitState.CLOSED
    
    def is_half_open(self) -> bool:
        """
        Check if circuit is half-open.
        
        Returns:
            True if circuit is half-open, False otherwise
        """
        return self.state == CircuitState.HALF_OPEN
