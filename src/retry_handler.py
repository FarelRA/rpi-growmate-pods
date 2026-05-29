"""
Retry Handler with Exponential Backoff for GrowMate Pods.

Implements exponential backoff with jitter to handle transient failures
gracefully and avoid thundering herd problem.

Error Handling - Exponential Backoff & Circuit Breaker

Backoff Strategy:
- Attempt 1: 1s ± 0.25s = 0.75-1.25s
- Attempt 2: 2s ± 0.5s = 1.5-2.5s
- Attempt 3: 4s ± 1s = 3-5s
- Attempt 4: 8s ± 2s = 6-10s
- Attempt 5: 16s ± 4s = 12-20s
- Attempt 6: 32s ± 8s = 24-40s

Error Categorization:
- Transient (retry): network timeout, 5xx errors, connection errors
- Permanent (don't retry): 4xx errors (except 429), invalid data
- Rate limit (backoff longer): 429 errors
"""

import asyncio
import logging
import random
from typing import Callable, Any, Optional, Type
from enum import Enum


logger = logging.getLogger("growmate.retry_handler")


class ErrorCategory(Enum):
    """Error categories for retry logic."""
    TRANSIENT = "TRANSIENT"      # Retry with exponential backoff
    PERMANENT = "PERMANENT"      # Don't retry
    RATE_LIMIT = "RATE_LIMIT"    # Retry with longer backoff
    CIRCUIT_OPEN = "CIRCUIT_OPEN"  # Circuit breaker open


class RetryableError(Exception):
    """Base class for retryable errors."""
    pass


class PermanentError(Exception):
    """Error that should not be retried."""
    pass


class RateLimitError(RetryableError):
    """Rate limit error (429)."""
    pass


def categorize_error(error: Exception) -> ErrorCategory:
    """
    Categorize error for retry logic.
    
    Args:
        error: Exception to categorize
        
    Returns:
        Error category
    """
    import aiohttp
    from circuit_breaker import CircuitBreakerOpenError
    
    # Circuit breaker open
    if isinstance(error, CircuitBreakerOpenError):
        return ErrorCategory.CIRCUIT_OPEN
    
    # Rate limit error
    if isinstance(error, RateLimitError):
        return ErrorCategory.RATE_LIMIT
    
    # Permanent error
    if isinstance(error, PermanentError):
        return ErrorCategory.PERMANENT
    
    # HTTP errors
    if isinstance(error, aiohttp.ClientResponseError):
        status = error.status
        
        # 4xx errors (except 429) are permanent
        if 400 <= status < 500:
            if status == 429:
                return ErrorCategory.RATE_LIMIT
            else:
                return ErrorCategory.PERMANENT
        
        # 5xx errors are transient
        if 500 <= status < 600:
            return ErrorCategory.TRANSIENT
    
    # Network errors are transient
    if isinstance(error, (
        aiohttp.ClientError,
        asyncio.TimeoutError,
        ConnectionError,
        OSError
    )):
        return ErrorCategory.TRANSIENT
    
    # Default: treat as transient
    return ErrorCategory.TRANSIENT


async def exponential_backoff_retry(
    func: Callable,
    *args,
    max_attempts: int = 6,
    initial_delay: float = 1.0,
    max_delay: float = 32.0,
    jitter: float = 0.25,
    **kwargs
) -> Any:
    """
    Retry function with exponential backoff and jitter.
    
    Args:
        func: Async function to retry
        *args: Positional arguments for function
        max_attempts: Maximum number of attempts (default: 6)
        initial_delay: Initial delay in seconds (default: 1.0)
        max_delay: Maximum delay in seconds (default: 32.0)
        jitter: Jitter factor (default: 0.25 = ±25%)
        **kwargs: Keyword arguments for function
        
    Returns:
        Function result
        
    Raises:
        Exception: Last exception if all attempts fail
    """
    last_exception = None
    
    for attempt in range(max_attempts):
        try:
            # Attempt to execute function
            result = await func(*args, **kwargs)
            
            # Success
            if attempt > 0:
                logger.info(
                    f"Retry successful on attempt {attempt + 1}/{max_attempts}"
                )
            
            return result
            
        except Exception as e:
            last_exception = e
            
            # Categorize error
            category = categorize_error(e)
            
            # Check if should retry
            if category == ErrorCategory.PERMANENT:
                logger.error(
                    f"Permanent error, not retrying: {e}"
                )
                raise
            
            if category == ErrorCategory.CIRCUIT_OPEN:
                logger.warning(
                    f"Circuit breaker open, not retrying: {e}"
                )
                raise
            
            # Last attempt, give up
            if attempt == max_attempts - 1:
                logger.error(
                    f"All {max_attempts} retry attempts failed: {e}"
                )
                raise
            
            # Calculate delay with exponential backoff
            delay = min(initial_delay * (2 ** attempt), max_delay)
            
            # Add jitter: ±25% (prevents thundering herd)
            jitter_amount = delay * jitter * (2 * random.random() - 1)
            delay += jitter_amount
            
            # Ensure delay is positive
            delay = max(0.1, delay)
            
            # Rate limit errors get longer backoff
            if category == ErrorCategory.RATE_LIMIT:
                delay *= 2.0
                logger.warning(
                    f"Rate limit error (attempt {attempt + 1}/{max_attempts}), "
                    f"retrying in {delay:.2f}s: {e}"
                )
            else:
                logger.warning(
                    f"Transient error (attempt {attempt + 1}/{max_attempts}), "
                    f"retrying in {delay:.2f}s: {e}"
                )
            
            # Wait before retry
            await asyncio.sleep(delay)
    
    # Should never reach here, but just in case
    raise last_exception


class RetryHandler:
    """
    Retry handler with configurable backoff strategy.
    
    Provides a reusable retry mechanism with exponential backoff,
    jitter, and error categorization.
    """
    
    def __init__(
        self,
        max_attempts: int = 6,
        initial_delay: float = 1.0,
        max_delay: float = 32.0,
        jitter: float = 0.25
    ):
        """
        Initialize retry handler.
        
        Args:
            max_attempts: Maximum number of attempts (default: 6)
            initial_delay: Initial delay in seconds (default: 1.0)
            max_delay: Maximum delay in seconds (default: 32.0)
            jitter: Jitter factor (default: 0.25 = ±25%)
        """
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.jitter = jitter
        
        # Statistics
        self.total_attempts = 0
        self.total_successes = 0
        self.total_failures = 0
        self.total_retries = 0
        
        logger.info(
            f"Retry handler initialized: "
            f"max_attempts={max_attempts}, "
            f"initial_delay={initial_delay}s, "
            f"max_delay={max_delay}s, "
            f"jitter=±{jitter * 100}%"
        )
    
    def update_config(
        self,
        max_attempts: Optional[int] = None,
        initial_delay: Optional[float] = None,
        max_delay: Optional[float] = None,
        jitter: Optional[float] = None
    ):
        """
        Update retry handler configuration at runtime (Hot-reload support).
        
        Args:
            max_attempts: Maximum number of attempts
            initial_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds
            jitter: Jitter factor (±percentage)
        """
        if max_attempts is not None:
            old_val = self.max_attempts
            self.max_attempts = max_attempts
            logger.info(f"Retry handler max_attempts: {old_val} → {max_attempts}")
        
        if initial_delay is not None:
            old_val = self.initial_delay
            self.initial_delay = initial_delay
            logger.info(f"Retry handler initial_delay: {old_val}s → {initial_delay}s")
        
        if max_delay is not None:
            old_val = self.max_delay
            self.max_delay = max_delay
            logger.info(f"Retry handler max_delay: {old_val}s → {max_delay}s")
        
        if jitter is not None:
            old_val = self.jitter
            self.jitter = jitter
            logger.info(f"Retry handler jitter: ±{old_val * 100}% → ±{jitter * 100}%")
    
    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with retry logic.
        
        Args:
            func: Async function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Function result
            
        Raises:
            Exception: Last exception if all attempts fail
        """
        self.total_attempts += 1
        
        try:
            result = await exponential_backoff_retry(
                func,
                *args,
                max_attempts=self.max_attempts,
                initial_delay=self.initial_delay,
                max_delay=self.max_delay,
                jitter=self.jitter,
                **kwargs
            )
            
            self.total_successes += 1
            return result
            
        except Exception as e:
            self.total_failures += 1
            raise
    
    def get_stats(self) -> dict:
        """
        Get retry handler statistics.
        
        Returns:
            Dictionary with statistics
        """
        success_rate = (
            (self.total_successes / self.total_attempts * 100)
            if self.total_attempts > 0 else 0.0
        )
        
        return {
            'total_attempts': self.total_attempts,
            'total_successes': self.total_successes,
            'total_failures': self.total_failures,
            'total_retries': self.total_retries,
            'success_rate': round(success_rate, 2)
        }
    
    def reset_stats(self):
        """Reset statistics counters."""
        self.total_attempts = 0
        self.total_successes = 0
        self.total_failures = 0
        self.total_retries = 0


# Convenience function for simple retry
async def retry_async(
    func: Callable,
    *args,
    max_attempts: int = 6,
    **kwargs
) -> Any:
    """
    Simple async retry with default settings.
    
    Args:
        func: Async function to retry
        *args: Positional arguments
        max_attempts: Maximum attempts (default: 6)
        **kwargs: Keyword arguments
        
    Returns:
        Function result
    """
    return await exponential_backoff_retry(
        func,
        *args,
        max_attempts=max_attempts,
        **kwargs
    )
