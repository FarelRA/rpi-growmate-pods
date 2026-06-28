import asyncio
import copy
import pytest
from unittest.mock import MagicMock, AsyncMock


MINIMAL_CONFIG = {
    "device": {"id": "growmate-test"},
    "api": {
        "sensor_url": "https://test.growmate.bond/api/v2/sensors",
        "stream_register_url": "https://test.growmate.bond/api/v2/stream/register",
        "timeout_sensor": 30.0,
        "timeout_stream_register": 10.0,
    },
    "circuit_breaker": {"failure_threshold": 5, "recovery_timeout": 60, "success_threshold": 2},
    "retry": {"max_attempts": 6, "initial_delay": 1.0, "max_delay": 32.0, "jitter": 0.25},
}


@pytest.fixture
def mock_deps(mocker):
    mocker.patch("api_client.get_env_device_id", return_value="test-device-abc")
    mocker.patch("api_client.get_env_api_key", return_value="test-api-key-xyz")
    mocker.patch("api_client.get_correlation_id", return_value="corr-123")


@pytest.fixture
def client(mock_deps):
    from api_client import APIClient
    c = APIClient(copy.deepcopy(MINIMAL_CONFIG))
    return c


@pytest.fixture
def fast_client(mock_deps):
    from api_client import APIClient
    c = APIClient(copy.deepcopy(MINIMAL_CONFIG))
    c.retry_handler.max_attempts = 1
    return c


@pytest.fixture
def mock_response():
    async def _make(data=None, status=200, raise_on_status=True):
        data = data or {}
        resp = AsyncMock()
        resp.status = status
        resp.json = AsyncMock(return_value=data)
        resp.__aenter__.return_value = resp
        resp.__aexit__.return_value = None
        if raise_on_status and status >= 400:
            from aiohttp import ClientResponseError
            resp.raise_for_status = MagicMock(
                side_effect=ClientResponseError(
                    None, None, status=status
                )
            )
        else:
            resp.raise_for_status = MagicMock()
        return resp
    return _make


@pytest.fixture
def mock_session(client, mock_response):
    session = MagicMock()
    session.post = MagicMock()
    session.close = AsyncMock()
    client.session = session
    return session


class TestInit:
    def test_reads_sensor_url(self):
        from api_client import APIClient
        c = APIClient(copy.deepcopy(MINIMAL_CONFIG))
        assert c.sensor_url == "https://test.growmate.bond/api/v2/sensors"
        assert c.stream_register_url == "https://test.growmate.bond/api/v2/stream/register"

    def test_reads_default_urls(self, mocker):
        mocker.patch("api_client.get_env_device_id", return_value="d")
        mocker.patch("api_client.get_env_api_key", return_value="k")
        mocker.patch("api_client.get_correlation_id", return_value="c")
        from api_client import APIClient
        cfg = copy.deepcopy(MINIMAL_CONFIG)
        cfg.pop("api")
        c = APIClient(cfg)
        from api_client import SENSOR_URL, STREAM_REGISTER_URL
        assert c.sensor_url == SENSOR_URL
        assert c.stream_register_url == STREAM_REGISTER_URL

    def test_reads_api_key_and_device_id(self, mocker):
        mocker.patch("api_client.get_env_device_id", return_value="dev-1")
        mocker.patch("api_client.get_env_api_key", return_value="key-1")
        mocker.patch("api_client.get_correlation_id", return_value="c")
        from api_client import APIClient
        c = APIClient(copy.deepcopy(MINIMAL_CONFIG))
        assert c.device_id == "dev-1"
        assert c.api_key == "key-1"

    def test_creates_circuit_breakers(self, client):
        assert client.sensor_circuit_breaker is not None
        assert client.stream_circuit_breaker is not None
        assert client.sensor_circuit_breaker.name == "sensor_api"
        assert client.stream_circuit_breaker.name == "stream_api"

    def test_creates_retry_handler(self, client):
        assert client.retry_handler is not None
        assert client.retry_handler.max_attempts == 6


class TestHeaders:
    def test_contains_api_key(self, client):
        h = client._get_headers()
        assert h["x-api-key"] == "test-api-key-xyz"

    def test_contains_correlation_id(self, client):
        h = client._get_headers()
        assert h["X-Correlation-Id"] == "corr-123"

    def test_content_type_json(self, client):
        h = client._get_headers()
        assert h["Content-Type"] == "application/json"

    def test_correlation_fallback_to_none(self, mocker):
        mocker.patch("api_client.get_env_device_id", return_value="d")
        mocker.patch("api_client.get_env_api_key", return_value="k")
        mocker.patch("api_client.get_correlation_id", return_value=None)
        from api_client import APIClient
        c = APIClient(copy.deepcopy(MINIMAL_CONFIG))
        h = c._get_headers()
        assert h["X-Correlation-Id"] == "none"


class TestUploadSensorData:
    @pytest.mark.asyncio
    async def test_upload_success_returns_commands(self, client, mock_session, mock_response):
        resp = await mock_response({"commands": [{"action": "water"}]})
        mock_session.post.return_value = resp
        result = await client.upload_sensor_data(
            [{"type": "temp", "value": 25}], {"status": "ok"}
        )
        assert result == [{"action": "water"}]

    @pytest.mark.asyncio
    async def test_upload_empty_response(self, client, mock_session, mock_response):
        resp = await mock_response({})
        mock_session.post.return_value = resp
        result = await client.upload_sensor_data([{}], {})
        assert result == []

    @pytest.mark.asyncio
    async def test_upload_no_commands_key(self, client, mock_session, mock_response):
        resp = await mock_response({"success": True})
        mock_session.post.return_value = resp
        result = await client.upload_sensor_data([{}], {})
        assert result == []

    @pytest.mark.asyncio
    async def test_upload_400_error_returns_none(self, fast_client, mock_deps, mock_response):
        fast_client.session = MagicMock()
        fast_client.session.post = MagicMock()
        resp = await mock_response({}, status=400)
        fast_client.session.post.return_value = resp
        result = await fast_client.upload_sensor_data([{}], {})
        assert result is None

    @pytest.mark.asyncio
    async def test_upload_429_rate_limit_returns_none(self, fast_client, mock_deps, mock_response):
        fast_client.session = MagicMock()
        fast_client.session.post = MagicMock()
        resp = await mock_response({}, status=429, raise_on_status=False)
        fast_client.session.post.return_value = resp
        result = await fast_client.upload_sensor_data([{}], {})
        assert result is None

    @pytest.mark.asyncio
    async def test_upload_500_error_returns_none(self, fast_client, mock_deps, mock_response):
        fast_client.session = MagicMock()
        fast_client.session.post = MagicMock()
        resp = await mock_response({}, status=500)
        fast_client.session.post.return_value = resp
        result = await fast_client.upload_sensor_data([{}], {})
        assert result is None

    @pytest.mark.asyncio
    async def test_upload_timeout_returns_none(self, fast_client, mock_deps):
        fast_client.session = MagicMock()
        fast_client.session.post = MagicMock(side_effect=asyncio.TimeoutError())
        result = await fast_client.upload_sensor_data([{}], {})
        assert result is None

    @pytest.mark.asyncio
    async def test_upload_initializes_session(self, mocker):
        mocker.patch("api_client.get_env_device_id", return_value="d")
        mocker.patch("api_client.get_env_api_key", return_value="k")
        mocker.patch("api_client.get_correlation_id", return_value="c")
        from api_client import APIClient
        c = APIClient(copy.deepcopy(MINIMAL_CONFIG))
        assert c.session is None
        resp_mock = AsyncMock()
        resp_mock.status = 200
        resp_mock.json = AsyncMock(return_value={"commands": []})
        resp_mock.raise_for_status = MagicMock()
        resp_mock.__aenter__.return_value = resp_mock
        resp_mock.__aexit__.return_value = None
        session_mock = MagicMock()
        session_mock.post = MagicMock(return_value=resp_mock)
        mocker.patch.object(c, "session", None)
        mocker.patch("aiohttp.ClientSession", return_value=session_mock)
        result = await c.upload_sensor_data([{}], {})
        assert result is not None


class TestRegisterStream:
    @pytest.mark.asyncio
    async def test_register_success(self, client, mock_session, mock_response):
        resp = await mock_response({"success": True})
        mock_session.post.return_value = resp
        result = await client.register_stream("rtsp://stream")
        assert result is True
        assert client.stream_registered is True
        assert client.last_stream_url == "rtsp://stream"

    @pytest.mark.asyncio
    async def test_register_success_false(self, client, mock_session, mock_response):
        resp = await mock_response({"success": False})
        mock_session.post.return_value = resp
        result = await client.register_stream("rtsp://stream")
        assert result is False

    @pytest.mark.asyncio
    async def test_register_400_permanent_error(self, fast_client, mock_deps, mock_response):
        fast_client.session = MagicMock()
        fast_client.session.post = MagicMock()
        resp = await mock_response({}, status=400)
        fast_client.session.post.return_value = resp
        result = await fast_client.register_stream("rtsp://stream")
        assert result is False

    @pytest.mark.asyncio
    async def test_register_429_rate_limit(self, fast_client, mock_deps, mock_response):
        fast_client.session = MagicMock()
        fast_client.session.post = MagicMock()
        resp = await mock_response({}, status=429, raise_on_status=False)
        fast_client.session.post.return_value = resp
        result = await fast_client.register_stream("rtsp://stream")
        assert result is False

    @pytest.mark.asyncio
    async def test_register_500_error(self, fast_client, mock_deps, mock_response):
        fast_client.session = MagicMock()
        fast_client.session.post = MagicMock()
        resp = await mock_response({}, status=500)
        fast_client.session.post.return_value = resp
        result = await fast_client.register_stream("rtsp://stream")
        assert result is False

    @pytest.mark.asyncio
    async def test_register_initializes_session(self, mocker):
        mocker.patch("api_client.get_env_device_id", return_value="d")
        mocker.patch("api_client.get_env_api_key", return_value="k")
        mocker.patch("api_client.get_correlation_id", return_value="c")
        from api_client import APIClient
        c = APIClient(copy.deepcopy(MINIMAL_CONFIG))
        assert c.session is None
        resp_mock = AsyncMock()
        resp_mock.status = 200
        resp_mock.json = AsyncMock(return_value={"success": True})
        resp_mock.raise_for_status = MagicMock()
        resp_mock.__aenter__.return_value = resp_mock
        resp_mock.__aexit__.return_value = None
        session_mock = MagicMock()
        session_mock.post = MagicMock(return_value=resp_mock)
        mocker.patch("aiohttp.ClientSession", return_value=session_mock)
        result = await c.register_stream("rtsp://stream")
        assert result is True


class TestClose:
    @pytest.mark.asyncio
    async def test_close_closes_session(self, client, mock_session):
        await client.cleanup()
        mock_session.close.assert_called_once()
        assert client.session is None

    @pytest.mark.asyncio
    async def test_close_no_session(self, client):
        client.session = None
        await client.cleanup()


class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_creates_session(self, client, mocker):
        fake_session = MagicMock()
        fake_session.close = AsyncMock()
        mocker.patch("aiohttp.ClientSession", return_value=fake_session)
        client.session = None
        await client.initialize()
        assert client.session is fake_session
        mocker.stopall()
        client.session.close = AsyncMock()
        await client.cleanup()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, client, mocker):
        fake_session = MagicMock()
        fake_session.close = AsyncMock()
        mocker.patch("aiohttp.ClientSession", return_value=fake_session)
        client.session = None
        await client.initialize()
        s1 = client.session
        await client.initialize()
        assert client.session is s1
        mocker.stopall()
        client.session.close = AsyncMock()
        await client.cleanup()


class TestConfigUpdates:
    def test_update_retry_config(self, client, mocker):
        mock_update = mocker.patch.object(client.retry_handler, 'update_config')
        client.update_retry_config({'max_attempts': 3, 'initial_delay': 0.5})
        mock_update.assert_called_once_with(max_attempts=3, initial_delay=0.5, max_delay=None, jitter=None)

    def test_update_circuit_breaker_config(self, client, mocker):
        mock_sensor = mocker.patch.object(client.sensor_circuit_breaker, 'update_config')
        mock_stream = mocker.patch.object(client.stream_circuit_breaker, 'update_config')
        client.update_circuit_breaker_config({
            'failure_threshold': 3, 'recovery_timeout': 30, 'success_threshold': 1
        })
        mock_sensor.assert_called_once_with(failure_threshold=3, recovery_timeout=30, success_threshold=1)
        mock_stream.assert_called_once_with(failure_threshold=3, recovery_timeout=30, success_threshold=1)


class TestContextManager:
    def test_async_context_manager(self, mocker):
        mocker.patch("api_client.get_env_device_id", return_value="d")
        mocker.patch("api_client.get_env_api_key", return_value="k")
        mocker.patch("api_client.get_correlation_id", return_value="c")
        import copy
        from api_client import APIClient

        fake_session = MagicMock()
        fake_session.close = AsyncMock()
        mocker.patch("aiohttp.ClientSession", return_value=fake_session)

        async def run():
            async with APIClient(copy.deepcopy(MINIMAL_CONFIG)) as client:
                assert client.session is fake_session
            fake_session.close.assert_called_once()
        asyncio.run(run())

    def test_aenter_aexit_direct(self, mocker):
        mocker.patch("api_client.get_env_device_id", return_value="d")
        mocker.patch("api_client.get_env_api_key", return_value="k")
        mocker.patch("api_client.get_correlation_id", return_value="c")
        import copy
        from api_client import APIClient

        fake_session = MagicMock()
        fake_session.close = AsyncMock()
        mocker.patch("aiohttp.ClientSession", return_value=fake_session)

        async def run():
            c = APIClient(copy.deepcopy(MINIMAL_CONFIG))
            c.session = None
            result = await c.__aenter__()
            assert result is c
            assert c.session is fake_session
            await c.__aexit__(None, None, None)
            fake_session.close.assert_called_once()
        asyncio.run(run())


class TestCircuitBreakerErrors:
    def test_register_stream_circuit_breaker_open(self, client, mock_session):
        import time
        from circuit_breaker import CircuitState
        client.stream_circuit_breaker.state = CircuitState.OPEN
        client.stream_circuit_breaker.last_failure_time = time.time()

        async def run():
            result = await client.register_stream("rtsp://test")
            assert result is False
        asyncio.run(run())

    def test_upload_sensor_data_circuit_breaker_open(self, client, mock_session):
        import time
        from circuit_breaker import CircuitState
        client.sensor_circuit_breaker.state = CircuitState.OPEN
        client.sensor_circuit_breaker.last_failure_time = time.time()

        async def run():
            result = await client.upload_sensor_data(
                [{"type": "temp", "value": 25}], {"status": "ok"}
            )
            assert result is None
        asyncio.run(run())


class TestGetters:
    def test_get_circuit_breaker_stats(self, client, mocker):
        mocker.patch.object(client.sensor_circuit_breaker, 'get_stats',
                            return_value={'name': 'sensor_api'})
        mocker.patch.object(client.stream_circuit_breaker, 'get_stats',
                            return_value={'name': 'stream_api'})
        stats = client.get_circuit_breaker_stats()
        assert stats == {'sensor_api': {'name': 'sensor_api'},
                         'stream_api': {'name': 'stream_api'}}

    def test_get_retry_stats(self, client, mocker):
        mock_get = mocker.patch.object(client.retry_handler, 'get_stats',
                                       return_value={'total_attempts': 5})
        stats = client.get_retry_stats()
        assert stats == {'total_attempts': 5}
        mock_get.assert_called_once()

    def test_reset_circuit_breakers(self, client, mocker):
        mock_sensor = mocker.patch.object(client.sensor_circuit_breaker, 'reset')
        mock_stream = mocker.patch.object(client.stream_circuit_breaker, 'reset')
        client.reset_circuit_breakers()
        mock_sensor.assert_called_once()
        mock_stream.assert_called_once()

    def test_is_stream_registered_default(self, client):
        assert client.is_stream_registered() is False

    def test_is_stream_registered_true(self, client):
        client.stream_registered = True
        assert client.is_stream_registered() is True

    def test_get_last_stream_url_default(self, client):
        assert client.get_last_stream_url() is None

    def test_get_last_stream_url_set(self, client):
        client.last_stream_url = "rtsp://stream"
        assert client.get_last_stream_url() == "rtsp://stream"


class TestStandaloneFunctions:
    def test_upload_sensors(self, mocker):
        mocker.patch("api_client.get_env_device_id", return_value="d")
        mocker.patch("api_client.get_env_api_key", return_value="k")
        mocker.patch("api_client.get_correlation_id", return_value="c")
        import copy
        from api_client import upload_sensors

        resp_mock = AsyncMock()
        resp_mock.status = 200
        resp_mock.json = AsyncMock(return_value={"commands": [{"action": "water"}]})
        resp_mock.raise_for_status = MagicMock()
        resp_mock.__aenter__.return_value = resp_mock
        resp_mock.__aexit__.return_value = None
        session_mock = MagicMock()
        session_mock.post = MagicMock(return_value=resp_mock)
        session_mock.close = AsyncMock()
        mocker.patch("aiohttp.ClientSession", return_value=session_mock)

        async def run():
            result = await upload_sensors(
                copy.deepcopy(MINIMAL_CONFIG),
                [{"type": "temp", "value": 25}],
                {"status": "ok"}
            )
            assert result == [{"action": "water"}]
        asyncio.run(run())
