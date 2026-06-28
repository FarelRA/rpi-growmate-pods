import pytest
import logging
from logging_config import (
    setup_logging, set_correlation_id, get_correlation_id,
    generate_correlation_id, clear_correlation_id, update_log_levels,
    CorrelationIdFilter, CustomJsonFormatter, ConsoleFormatter,
)


class TestCorrelationIdFilter:
    def test_filter_adds_correlation_id(self):
        filter_ = CorrelationIdFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        assert filter_.filter(record) is True
        assert hasattr(record, "correlation_id")

    def test_filter_uses_context_var(self):
        set_correlation_id("test-id-123")
        filter_ = CorrelationIdFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        filter_.filter(record)
        assert record.correlation_id == "test-id-123"
        clear_correlation_id()


class TestCustomJsonFormatter:
    def test_init_sets_device_id(self):
        fmt = CustomJsonFormatter("%(message)s", device_id="growmate-test")
        assert fmt.device_id == "growmate-test"

    def test_default_device_id(self):
        fmt = CustomJsonFormatter("%(message)s")
        assert fmt.device_id == "unknown"


class TestConsoleFormatter:
    def test_format_includes_level(self):
        fmt = ConsoleFormatter(use_colors=False)
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
        output = fmt.format(record)
        assert "INFO" in output
        assert "hello" in output

    def test_format_includes_component(self):
        fmt = ConsoleFormatter(use_colors=False)
        record = logging.LogRecord("growmate.sensors", logging.WARNING, "", 0, "warn", (), None)
        output = fmt.format(record)
        assert "sensors" in output
        assert "WARNING" in output


class TestSetupLogging:
    def test_setup_with_defaults(self):
        config = {"logging": {}, "intervals": {}}
        setup_logging(config, device_id="test-device")
        root = logging.getLogger()
        assert len(root.handlers) > 0

    def test_setup_with_json_format(self):
        config = {"logging": {"format": "json", "level": "INFO"}, "intervals": {}}
        setup_logging(config, device_id="test-device")

    def test_setup_with_text_format(self):
        config = {"logging": {"format": "text", "level": "DEBUG"}, "intervals": {}}
        setup_logging(config, device_id="test-device")

    def test_setup_with_module_overrides(self):
        config = {
            "logging": {
                "level": "WARNING",
                "modules": {"growmate.sensors": "DEBUG"},
            },
            "intervals": {},
        }
        setup_logging(config, device_id="test-device")
        sensors_logger = logging.getLogger("growmate.sensors")
        assert sensors_logger.level <= logging.DEBUG


class TestCorrelationId:
    def test_set_and_get(self):
        clear_correlation_id()
        set_correlation_id("my-trace-id")
        assert get_correlation_id() == "my-trace-id"
        clear_correlation_id()

    def test_default_is_none(self):
        clear_correlation_id()
        assert get_correlation_id() is None

    def test_generate_is_uuid(self):
        cid = generate_correlation_id()
        assert isinstance(cid, str)
        assert len(cid) > 10
        assert "-" in cid

    def test_clear(self):
        set_correlation_id("something")
        clear_correlation_id()
        assert get_correlation_id() is None


class TestUpdateLogLevels:
    def test_update_root_level(self):
        config = {"logging": {"level": "ERROR"}, "intervals": {}}
        setup_logging(config)
        update_log_levels(config)

    def test_update_module_levels(self):
        config = {
            "logging": {
                "level": "WARNING",
                "modules": {"growmate.sensors": "DEBUG", "growmate.api": "ERROR"},
            },
            "intervals": {},
        }
        setup_logging(config)
        update_log_levels(config)
        assert logging.getLogger("growmate.sensors").level <= logging.DEBUG
        assert logging.getLogger("growmate.api").level <= logging.ERROR

    def test_invalid_module_level(self):
        config = {
            "logging": {
                "modules": {"growmate.test": "INVALID"},
            },
            "intervals": {},
        }
        setup_logging(config)
        update_log_levels(config)


class TestCustomJsonFormatterFormat:
    def test_format_with_extra_fields(self):
        fmt = CustomJsonFormatter("%(message)s")
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        record.extra_fields = {"custom": "value"}
        output = fmt.format(record)
        import json
        data = json.loads(output)
        assert data["custom"] == "value"

    def test_format_with_exception_info(self):
        import sys
        fmt = CustomJsonFormatter("%(message)s")
        record = logging.LogRecord("test", logging.ERROR, "", 0, "msg", (), None)
        try:
            raise ValueError("test error")
        except ValueError:
            record.exc_info = sys.exc_info()
        output = fmt.format(record)
        import json
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]


class TestConsoleFormatterColors:
    def test_format_with_colors(self, mocker):
        mocker.patch("sys.stdout.isatty", return_value=True)
        fmt = ConsoleFormatter(use_colors=True)
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
        output = fmt.format(record)
        assert "\033[32m" in output
        assert "\033[0m" in output

    def test_format_with_exception_info(self):
        import sys
        fmt = ConsoleFormatter(use_colors=False)
        record = logging.LogRecord("test", logging.ERROR, "", 0, "msg", (), None)
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            record.exc_info = sys.exc_info()
        output = fmt.format(record)
        assert "RuntimeError" in output
        assert "boom" in output


class TestSetupLoggingFileHandlerFailure:
    def test_setup_file_handler_permission_error(self, mocker):
        mocker.patch("logging.handlers.RotatingFileHandler", side_effect=PermissionError("denied"))
        config = {"logging": {}, "intervals": {}}
        setup_logging(config)


class TestUpdateLogLevelsHandlerErrors:
    def test_handler_setlevel_attribute_error(self):
        config = {"logging": {"level": "INFO"}, "intervals": {}}
        setup_logging(config)
        root = logging.getLogger()
        class _FakeHandler(logging.Handler):
            def __init__(self):
                super().__init__()
            def setLevel(self, level):
                raise AttributeError
            def emit(self, record):
                pass
        root.handlers.append(_FakeHandler())
        update_log_levels(config)
