"""
Structured Logging Configuration

Implements structured JSON logging with correlation IDs, log rotation,
and per-module log levels.

Features:
- JSON logging for files (machine-readable)
- Human-readable logging for console (development)
- Log rotation (10MB per file, 5 backups)
- Correlation IDs for tracing operations across components
- Per-module log levels (hot-reloadable)
- Multiple log destinations (console, file, systemd journal)
"""

import logging
import logging.handlers
import sys
import os
from contextvars import ContextVar
from typing import Optional, Dict
from pythonjsonlogger import jsonlogger
import uuid

# Correlation ID context variable (thread-safe for async)
correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)


class CorrelationIdFilter(logging.Filter):
    """
    Logging filter that adds correlation ID to log records.
    
    Enables tracing of operations across components.
    """
    
    def filter(self, record):
        """Add correlation_id to log record."""
        record.correlation_id = correlation_id_var.get() or 'none'
        return True


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """
    Custom JSON formatter with additional fields.
    
    Adds device_id, component, and correlation_id to JSON logs.
    """
    
    def __init__(self, *args, device_id: str = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.device_id = device_id or 'unknown'
    
    def add_fields(self, log_record, record, message_dict):
        """Add custom fields to JSON log record."""
        super().add_fields(log_record, record, message_dict)
        
        # Standard fields
        log_record['timestamp'] = self.formatTime(record, self.datefmt)
        log_record['level'] = record.levelname
        log_record['logger'] = record.name
        log_record['message'] = record.getMessage()
        
        # Context fields
        log_record['device_id'] = self.device_id
        log_record['component'] = record.name.split('.')[-1]  # Last part of logger name
        log_record['correlation_id'] = getattr(record, 'correlation_id', 'none')
        
        # Exception info
        if record.exc_info:
            log_record['exception'] = self.formatException(record.exc_info)
        
        # Additional fields from extra
        if hasattr(record, 'extra_fields'):
            log_record.update(record.extra_fields)


class ConsoleFormatter(logging.Formatter):
    """
    Human-readable console formatter with colors (optional).
    
    Provides readable logs for development and debugging.
    """
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }
    
    def __init__(self, use_colors: bool = True):
        super().__init__()
        self.use_colors = use_colors and sys.stdout.isatty()
    
    def format(self, record):
        """Format log record for console output."""
        # Get correlation ID
        correlation_id = getattr(record, 'correlation_id', 'none')
        
        # Build message
        if self.use_colors:
            color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            reset = self.COLORS['RESET']
            level_str = f"{color}{record.levelname:8s}{reset}"
        else:
            level_str = f"{record.levelname:8s}"
        
        # Format: [LEVEL] [component] [correlation_id] message
        component = record.name.split('.')[-1]
        msg = f"[{level_str}] [{component:15s}] [{correlation_id[:8]}] {record.getMessage()}"
        
        # Add exception info if present
        if record.exc_info:
            msg += '\n' + self.formatException(record.exc_info)
        
        return msg


def setup_logging(config: Dict, device_id: str = None) -> None:
    """
    Setup structured logging based on configuration.
    
    Configures JSON logging, log rotation, and per-module log levels.
    
    Args:
        config: Configuration dictionary with logging settings
        device_id: Device ID to include in logs
    """
    # Get logging config
    logging_config = config.get('logging', {})
    
    # Root log level
    root_level = logging_config.get('level', 'INFO').upper()
    
    # Log file path
    log_file = logging_config.get('file', '/var/log/growmate/growmate.log')
    
    # Log format
    log_format = logging_config.get('format', 'json').lower()
    
    # Rotation settings
    max_bytes = logging_config.get('max_bytes', 10 * 1024 * 1024)  # 10MB
    backup_count = logging_config.get('backup_count', 5)
    
    # Create log directory if it doesn't exist
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            # Fallback to /tmp if can't create log directory
            log_file = '/tmp/growmate.log'
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture all, filter at handler level
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Add correlation ID filter to root logger
    correlation_filter = CorrelationIdFilter()
    root_logger.addFilter(correlation_filter)
    
    # Console handler (human-readable)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, root_level))
    console_handler.setFormatter(ConsoleFormatter(use_colors=True))
    root_logger.addHandler(console_handler)
    
    # File handler (JSON with rotation)
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, root_level))
        
        if log_format == 'json':
            # JSON formatter for machine-readable logs
            json_formatter = CustomJsonFormatter(
                '%(timestamp)s %(level)s %(logger)s %(message)s',
                device_id=device_id
            )
            file_handler.setFormatter(json_formatter)
        else:
            # Text formatter fallback
            text_formatter = logging.Formatter(
                '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(text_formatter)
        
        root_logger.addHandler(file_handler)
    except (OSError, PermissionError) as e:
        # Log to console if file handler fails
        root_logger.warning(f"Failed to setup file logging: {e}")
    
    # Configure per-module log levels
    module_levels = logging_config.get('modules', {})
    for module_name, level_str in module_levels.items():
        try:
            level = getattr(logging, level_str.upper())
            logger = logging.getLogger(module_name)
            logger.setLevel(level)
        except (AttributeError, ValueError):
            root_logger.warning(f"Invalid log level '{level_str}' for module '{module_name}'")
    
    # Log startup message
    root_logger.info(
        f"Logging initialized: level={root_level}, format={log_format}, "
        f"file={log_file}, rotation={max_bytes}B×{backup_count}"
    )


def set_correlation_id(correlation_id: str) -> None:
    """
    Set correlation ID for current context.
    
    Enables tracing of operations across components.
    
    Args:
        correlation_id: Correlation ID (typically UUID)
    """
    correlation_id_var.set(correlation_id)


def get_correlation_id() -> Optional[str]:
    """
    Get correlation ID for current context.
    
    Returns:
        Correlation ID or None if not set
    """
    return correlation_id_var.get()


def generate_correlation_id() -> str:
    """
    Generate a new correlation ID.
    
    Creates unique ID for tracing operations.
    
    Returns:
        UUID4 string
    """
    return str(uuid.uuid4())


def clear_correlation_id() -> None:
    """Clear correlation ID for current context."""
    correlation_id_var.set(None)


def update_log_levels(config: Dict) -> None:
    """
    Update per-module log levels from configuration.
    
    Supports hot-reload of log levels without restart.
    
    Args:
        config: Configuration dictionary with logging settings
    """
    logging_config = config.get('logging', {})
    
    # Update root level
    root_level = logging_config.get('level', 'INFO').upper()
    root_logger = logging.getLogger()
    
    # Update handler levels (not root logger level, to preserve DEBUG capture)
    for handler in root_logger.handlers:
        try:
            handler.setLevel(getattr(logging, root_level))
        except AttributeError:
            pass
    
    # Update per-module log levels
    module_levels = logging_config.get('modules', {})
    for module_name, level_str in module_levels.items():
        try:
            level = getattr(logging, level_str.upper())
            logger = logging.getLogger(module_name)
            logger.setLevel(level)
        except (AttributeError, ValueError):
            root_logger.warning(f"Invalid log level '{level_str}' for module '{module_name}'")
    
    root_logger.info(f"Log levels updated: root={root_level}, modules={len(module_levels)}")
