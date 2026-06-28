import pytest
import time
from circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerOpenError


class TestCircuitBreaker:
    @pytest.fixture
    def cb(self):
        return CircuitBreaker("test", failure_threshold=3, recovery_timeout=5, success_threshold=2)

    def test_initial_state(self, cb):
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb.name == "test"

    def test_get_state_string(self, cb):
        assert cb.get_state() == "CLOSED"

    def test_is_closed(self, cb):
        assert cb.is_closed() is True
        assert cb.is_open() is False
        assert cb.is_half_open() is False

    # ---- CLOSED state (via _on_failure / _on_success) ----

    def test_failure_trips_at_threshold(self, cb):
        cb._on_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 1
        cb._on_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 2
        cb._on_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3

    def test_success_in_closed_resets_failure_count(self, cb):
        cb._on_failure()
        cb._on_failure()
        assert cb.failure_count == 2
        cb._on_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_failure_below_threshold_stays_closed(self, cb):
        cb._on_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 1

    def test_get_stats_returns_dict(self, cb):
        stats = cb.get_stats()
        assert stats["name"] == "test"
        assert stats["state"] == "CLOSED"

    # ---- OPEN state ----

    def test_open_call_raises(self, cb):
        cb._on_failure()
        cb._on_failure()
        cb._on_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.is_open() is True

    async def test_open_rejects_call(self, cb):
        cb._on_failure()
        cb._on_failure()
        cb._on_failure()

        async def dummy():
            return 42

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(dummy)

    def test_open_should_attempt_reset_after_timeout(self, cb):
        cb._on_failure()
        cb._on_failure()
        cb._on_failure()
        assert cb.state == CircuitState.OPEN

        cb.last_failure_time = time.time() - 10
        assert cb._should_attempt_reset() is True

    def test_open_should_not_attempt_before_timeout(self, cb):
        cb._on_failure()
        cb._on_failure()
        cb._on_failure()
        cb.last_failure_time = time.time()  # just now
        assert cb._should_attempt_reset() is False

    # ---- HALF_OPEN state ----

    def test_transition_to_half_open(self, cb):
        cb._on_failure()
        cb._on_failure()
        cb._on_failure()
        cb.last_failure_time = time.time() - 10
        cb._transition_to_half_open()
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.is_half_open() is True

    def test_half_open_success_closes(self, cb):
        cb._on_failure()
        cb._on_failure()
        cb._on_failure()
        cb.last_failure_time = time.time() - 10
        cb._transition_to_half_open()
        assert cb.state == CircuitState.HALF_OPEN

        cb._on_success()
        assert cb.state == CircuitState.HALF_OPEN
        cb._on_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_failure_reopens(self, cb):
        cb._on_failure()
        cb._on_failure()
        cb._on_failure()
        cb.last_failure_time = time.time() - 10
        cb._transition_to_half_open()
        assert cb.state == CircuitState.HALF_OPEN

        cb._on_failure()
        assert cb.state == CircuitState.OPEN

    # ---- Custom configs ----

    def test_custom_thresholds(self):
        cb = CircuitBreaker("custom", failure_threshold=1, recovery_timeout=1, success_threshold=1)
        assert cb.state == CircuitState.CLOSED
        cb._on_failure()
        assert cb.state == CircuitState.OPEN

    def test_update_config(self, cb):
        cb.update_config(failure_threshold=10, recovery_timeout=30.0)
        assert cb.failure_threshold == 10
        assert cb.recovery_timeout == 30.0
        assert cb.success_threshold == 2

    def test_update_config_partial(self, cb):
        cb.update_config(success_threshold=5)
        assert cb.success_threshold == 5
        assert cb.failure_threshold == 3

    # ---- Stats / Reset ----

    def test_reset(self, cb):
        cb._on_failure()
        cb._on_failure()
        cb._on_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb.last_failure_time is None
