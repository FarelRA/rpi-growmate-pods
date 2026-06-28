import asyncio
import pytest
from retry_handler import (
    RetryHandler, ErrorCategory, RetryableError, PermanentError,
    RateLimitError, categorize_error, exponential_backoff_retry, retry_async,
)
from circuit_breaker import CircuitBreakerOpenError


class TestErrorCategory:
    def test_values(self):
        assert ErrorCategory.TRANSIENT.value == "TRANSIENT"
        assert ErrorCategory.PERMANENT.value == "PERMANENT"
        assert ErrorCategory.RATE_LIMIT.value == "RATE_LIMIT"
        assert ErrorCategory.CIRCUIT_OPEN.value == "CIRCUIT_OPEN"


class TestCategorizeError:
    def test_retryable_error(self):
        assert categorize_error(RetryableError()) == ErrorCategory.TRANSIENT

    def test_permanent_error(self):
        assert categorize_error(PermanentError()) == ErrorCategory.PERMANENT

    def test_rate_limit_error(self):
        assert categorize_error(RateLimitError()) == ErrorCategory.RATE_LIMIT

    def test_circuit_breaker_open_error(self):
        assert categorize_error(CircuitBreakerOpenError()) == ErrorCategory.CIRCUIT_OPEN

    def test_aiohttp_client_error_transient(self, mocker):
        err = type("ClientError", (Exception,), {})
        mocker.patch("aiohttp.ClientError", err)
        assert categorize_error(err()) == ErrorCategory.TRANSIENT

    def test_http_429_rate_limit(self, mocker):
        err_cls = type("ClientResponseError", (Exception,), {})
        mocker.patch("aiohttp.ClientResponseError", err_cls)
        err = err_cls()
        err.status = 429
        assert categorize_error(err) == ErrorCategory.RATE_LIMIT

    def test_http_400_permanent(self, mocker):
        err_cls = type("ClientResponseError", (Exception,), {})
        mocker.patch("aiohttp.ClientResponseError", err_cls)
        err = err_cls()
        err.status = 400
        assert categorize_error(err) == ErrorCategory.PERMANENT

    def test_http_500_transient(self, mocker):
        err_cls = type("ClientResponseError", (Exception,), {})
        mocker.patch("aiohttp.ClientResponseError", err_cls)
        err = err_cls()
        err.status = 500
        assert categorize_error(err) == ErrorCategory.TRANSIENT

    def test_timeout_error(self):
        assert categorize_error(asyncio.TimeoutError()) == ErrorCategory.TRANSIENT

    def test_connection_error(self):
        assert categorize_error(ConnectionError()) == ErrorCategory.TRANSIENT

    def test_os_error(self):
        assert categorize_error(OSError()) == ErrorCategory.TRANSIENT

    def test_generic_exception_defaults_transient(self):
        assert categorize_error(ValueError("test")) == ErrorCategory.TRANSIENT


class TestRetryHandler:
    def test_default_initialization(self):
        h = RetryHandler()
        assert h.max_attempts == 6
        assert h.initial_delay == 1.0
        assert h.max_delay == 32.0
        assert h.jitter == 0.25

    def test_custom_initialization(self):
        h = RetryHandler(max_attempts=3, initial_delay=2.0, max_delay=10.0, jitter=0.1)
        assert h.max_attempts == 3
        assert h.initial_delay == 2.0
        assert h.max_delay == 10.0
        assert h.jitter == 0.1

    def test_update_config(self):
        h = RetryHandler(max_attempts=3, initial_delay=0.01, max_delay=0.1, jitter=0.0)
        h.update_config(max_attempts=5, initial_delay=0.5)
        assert h.max_attempts == 5
        assert h.initial_delay == 0.5
        assert h.max_delay == 0.1
        assert h.jitter == 0.0

    def test_update_config_partial(self):
        h = RetryHandler()
        h.update_config(max_attempts=10)
        assert h.max_attempts == 10
        assert h.initial_delay == 1.0

    def test_update_config_max_delay(self):
        h = RetryHandler(max_delay=32.0)
        h.update_config(max_delay=64.0)
        assert h.max_delay == 64.0

    def test_update_config_jitter(self):
        h = RetryHandler(jitter=0.25)
        h.update_config(jitter=0.5)
        assert h.jitter == 0.5

    def test_execute_success(self):
        h = RetryHandler(max_attempts=3, initial_delay=0.01, max_delay=0.1, jitter=0.0)

        async def succeed():
            return "ok"

        result = asyncio.run(h.execute(succeed))
        assert result == "ok"
        assert h.total_successes == 1
        assert h.total_attempts == 1

    def test_execute_failure_then_success(self):
        h = RetryHandler(max_attempts=3, initial_delay=0.01, max_delay=0.1, jitter=0.0)
        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RetryableError("transient")
            return "ok"

        result = asyncio.run(h.execute(fail_then_succeed))
        assert result == "ok"
        assert call_count == 2

    def test_execute_all_failures(self):
        h = RetryHandler(max_attempts=2, initial_delay=0.01, max_delay=0.1, jitter=0.0)

        async def always_fail():
            raise RetryableError("always fails")

        with pytest.raises(RetryableError):
            asyncio.run(h.execute(always_fail))
        assert h.total_failures == 1
        assert h.total_attempts == 1

    def test_execute_permanent_error_no_retry(self):
        h = RetryHandler(max_attempts=3, initial_delay=0.01, max_delay=0.1, jitter=0.0)

        async def perm_fail():
            raise PermanentError("permanent")

        with pytest.raises(PermanentError):
            asyncio.run(h.execute(perm_fail))

    def test_execute_circuit_breaker_open(self):
        h = RetryHandler()

        async def cb_open():
            raise CircuitBreakerOpenError("open")

        with pytest.raises(CircuitBreakerOpenError):
            asyncio.run(h.execute(cb_open))

    def test_get_stats(self):
        h = RetryHandler()
        stats = h.get_stats()
        assert "total_attempts" in stats
        assert "total_successes" in stats
        assert "total_failures" in stats
        assert "total_retries" in stats
        assert "success_rate" in stats
        assert stats["total_attempts"] == 0
        assert stats["success_rate"] == 0.0

    def test_reset_stats(self):
        h = RetryHandler()
        h.total_attempts = 10
        h.total_successes = 5
        h.total_failures = 5
        h.reset_stats()
        assert h.total_attempts == 0
        assert h.total_successes == 0
        assert h.total_failures == 0
        assert h.total_retries == 0

    def test_stats_after_execute(self):
        h = RetryHandler(max_attempts=3, initial_delay=0.01, max_delay=0.1, jitter=0.0)

        async def ok():
            return 1

        asyncio.run(h.execute(ok))
        stats = h.get_stats()
        assert stats["total_attempts"] == 1
        assert stats["total_successes"] == 1
        assert stats["success_rate"] == 100.0


class TestExponentialBackoffRetry:
    def test_success_first_attempt(self):
        async def ok():
            return 42

        result = asyncio.run(exponential_backoff_retry(ok, max_attempts=3))
        assert result == 42

    def test_retry_then_succeed(self):
        call_count = 0

        async def fail_then_ok():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RetryableError()
            return "done"

        result = asyncio.run(exponential_backoff_retry(
            fail_then_ok, max_attempts=3, initial_delay=0.01
        ))
        assert result == "done"
        assert call_count == 2

    def test_all_attempts_fail(self):
        async def always_fail():
            raise RetryableError("nope")

        with pytest.raises(RetryableError):
            asyncio.run(exponential_backoff_retry(always_fail, max_attempts=2))

    def test_permanent_error_no_retry(self):
        async def perm_fail():
            raise PermanentError()

        with pytest.raises(PermanentError):
            asyncio.run(exponential_backoff_retry(perm_fail, max_attempts=5))

    def test_rate_limit_error(self):
        call_count = 0

        async def rate_limited():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RateLimitError("too fast")
            return "ok"

        result = asyncio.run(exponential_backoff_retry(
            rate_limited, max_attempts=3, initial_delay=0.01
        ))
        assert result == "ok"
        assert call_count == 2


class TestRetryAsync:
    def test_simple_retry(self):
        async def ok():
            return "done"
        result = asyncio.run(retry_async(ok, max_attempts=2))
        assert result == "done"
