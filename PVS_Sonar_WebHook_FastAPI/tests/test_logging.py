"""
Unit tests for logging configuration.

Tests cover:
- Logger creation and configuration
- Context filter functionality
- Log rotation and cleanup
- Structured logging
- Context manager
"""

import logging
import os
import pytest
import tempfile
import shutil

from app.logging_config import (
    setup_logging,
    get_logger,
    get_component_logger,
    LogContext,
    ContextFilter,
    DailyRotatingFileHandler,
    log_startup,
    log_shutdown,
    log_error_with_traceback,
    DEFAULT_LOG_RETENTION_DAYS,
)


# Fixtures

@pytest.fixture
# Create temporary directory for log files
def temp_log_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
# Reset logging configuration before and after test
def reset_logging():
    # Clear all handlers before test
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.WARNING)  # Suppress logs during tests

    yield

    # Clear all handlers after test
    root_logger.handlers.clear()


# ContextFilter Tests

# Tests for ContextFilter class
class TestContextFilter:

    # Test that filter adds default context values
    def test_adds_default_context(self):
        filter_obj = ContextFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None
        )

        # Record should not have repo_type/repo_name initially
        assert not hasattr(record, 'repo_type')
        assert not hasattr(record, 'repo_name')

        # Apply filter
        result = filter_obj.filter(record)

        # Filter should return True (keep record)
        assert result is True

        # Record should now have default context
        assert hasattr(record, 'repo_type')
        assert hasattr(record, 'repo_name')
        assert record.repo_type == 'SYSTEM'
        assert record.repo_name == 'UNKNOWN'

    # Test that filter preserves existing context values
    def test_preserves_existing_context(self):
        filter_obj = ContextFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None
        )
        record.repo_type = "Git"
        record.repo_name = "MyRepo"

        # Apply filter
        filter_obj.filter(record)

        # Should preserve existing values
        assert record.repo_type == "Git"
        assert record.repo_name == "MyRepo"


# DailyRotatingFileHandler Tests

# Tests for DailyRotatingFileHandler class
class TestDailyRotatingFileHandler:

    # Test that handler creates log directory if needed
    def test_creates_log_directory(self, temp_log_dir):
        log_subdir = os.path.join(temp_log_dir, "subdir")
        log_file = os.path.join(log_subdir, "test.log")

        handler = DailyRotatingFileHandler(filename=log_file)

        # Directory should be created
        assert os.path.exists(log_subdir)
        assert os.path.isfile(log_file)

        handler.close()

    # Test default retention period.
    def test_default_retention(self, temp_log_dir):
        log_file = os.path.join(temp_log_dir, "test.log")
        handler = DailyRotatingFileHandler(filename=log_file)

        assert handler.retention_days == DEFAULT_LOG_RETENTION_DAYS

        handler.close()

    # Test custom retention period
    def test_custom_retention(self, temp_log_dir):
        log_file = os.path.join(temp_log_dir, "test.log")
        handler = DailyRotatingFileHandler(filename=log_file, retention_days=7)

        assert handler.retention_days == 7

        handler.close()


# Logger Creation Tests

# Tests for logger creation functions
class TestLoggerCreation:

    # Test basic logger creation
    def test_get_logger_basic(self, reset_logging):
        logger = get_logger("test_module")

        assert logger.name == "test_module"
        assert logger.level == logging.NOTSET  # Inherits from root

    # Test logger creation with specific log level
    def test_get_logger_with_level(self, reset_logging):
        logger = get_logger("test_module", log_level="DEBUG")

        assert logger.level == logging.DEBUG

    # Test logger creation with dedicated file handler
    def test_get_logger_with_file_handler(self, reset_logging, temp_log_dir):
        logger = get_logger(
            "test_module",
            log_dir=temp_log_dir,
            add_file_handler=True
        )

        # Should have file handler
        assert len(logger.handlers) > 0

        # Check handler type
        file_handlers = [
            h for h in logger.handlers
            if isinstance(h, DailyRotatingFileHandler)
        ]
        assert len(file_handlers) > 0

    # Test component logger creation
    def test_get_component_logger(self, reset_logging):
        logger = get_component_logger("webhook", "Git", "MyRepo")

        # Should return LoggerAdapter
        assert isinstance(logger, logging.LoggerAdapter)

        # Check context
        assert logger.extra['repo_type'] == "Git"
        assert logger.extra['repo_name'] == "MyRepo"


# Setup Logging Tests

# Tests for setup_logging function
class TestSetupLogging:

    # Test that setup_logging creates handlers
    def test_setup_creates_handlers(self, reset_logging, temp_log_dir):
        setup_logging(log_dir=temp_log_dir, console_output=False)

        root_logger = logging.getLogger()

        # Should have at least one handler
        assert len(root_logger.handlers) > 0

    # Test that setup_logging creates log directory
    def test_setup_creates_log_directory(self, reset_logging, temp_log_dir):
        log_subdir = os.path.join(temp_log_dir, "custom_logs")
        setup_logging(log_dir=log_subdir, console_output=False)

        assert os.path.exists(log_subdir)

    # Test log level configuration
    def test_setup_log_level(self, reset_logging, temp_log_dir):
        setup_logging(log_level="DEBUG", log_dir=temp_log_dir)

        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG


# LogContext Tests

# Tests for LogContext context manager
class TestLogContext:

    # Test that context manager adds context
    def test_context_manager_adds_context(self, reset_logging):
        logger = get_logger("test_context")

        with LogContext(repo_type="Git", repo_name="TestRepo"):
            # Check global context
            assert hasattr(logging, '_log_context')
            assert logging._log_context['repo_type'] == "Git"
            assert logging._log_context['repo_name'] == "TestRepo"

        # Context should be removed after exit
        assert not hasattr(logging, '_log_context')

    # Test that context manager restores previous context
    def test_context_manager_restores_previous(self, reset_logging):
        # Set initial context
        logging._log_context = {'repo_type': 'TFVC', 'repo_name': 'OldRepo'}

        with LogContext(repo_type="Git", repo_name="NewRepo"):
            assert logging._log_context['repo_type'] == "Git"

        # Should restore previous context
        assert logging._log_context['repo_type'] == "TFVC"
        assert logging._log_context['repo_name'] == "OldRepo"


# Convenience Functions Tests

# Tests for convenience logging functions
class TestConvenienceFunctions:

    # Test log_startup function
    def test_log_startup(self, reset_logging, temp_log_dir):
        setup_logging(log_dir=temp_log_dir)
        logger = get_logger("test_startup")

        # Just verify it doesn't crash
        log_startup(logger, "TestService")

        # Check log file was created
        log_file = os.path.join(temp_log_dir, "app.log")
        assert os.path.exists(log_file)

        # Read with UTF-8 encoding
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
            # Check for either Russian or English text
            assert "Запуск TestService" in content or "Starting TestService" in content

    # Test log_shutdown function
    def test_log_shutdown(self, reset_logging, temp_log_dir):
        setup_logging(log_dir=temp_log_dir)
        logger = get_logger("test_shutdown")

        # Just verify it doesn't crash
        log_shutdown(logger, "TestService")

        # Check log file
        log_file = os.path.join(temp_log_dir, "app.log")
        assert os.path.exists(log_file)

        # Read with UTF-8 encoding
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
            # Check for either Russian or English text
            assert "Остановка TestService" in content or "Shutting down TestService" in content

    # Test log_error_with_traceback function
    def test_log_error_with_traceback(self, reset_logging, temp_log_dir):
        setup_logging(log_dir=temp_log_dir)
        logger = get_logger("test_error")

        try:
            raise ValueError("Test error")
        except Exception as e:
            log_error_with_traceback(
                logger,
                "Operation failed",
                e,
                repo_type="Git",
                repo_name="TestRepo"
            )

        # Check log file
        log_file = os.path.join(temp_log_dir, "app.log")
        assert os.path.exists(log_file)

        with open(log_file, 'r') as f:
            content = f.read()
            assert "Operation failed" in content
            assert "ValueError" in content
            assert "Test error" in content


# Integration Tests

# Integration tests for logging system
class TestLoggingIntegration:

    # Test complete logging flow
    def test_full_logging_flow(self, reset_logging, temp_log_dir):
        # Setup
        setup_logging(
            log_dir=temp_log_dir,
            log_level="INFO",
            console_output=False
        )

        # Get logger
        logger = get_logger("integration_test")

        # Log messages at different levels
        logger.debug("Debug message")  # Should not appear (below INFO)
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")

        # Check log file exists
        log_file = os.path.join(temp_log_dir, "app.log")
        assert os.path.exists(log_file)

        # Read and verify log content
        with open(log_file, 'r') as f:
            log_content = f.read()

        assert "Info message" in log_content
        assert "Warning message" in log_content
        assert "Error message" in log_content
        assert "Debug message" not in log_content  # Filtered out

    # Test that context appears in logs
    def test_context_in_logs(self, reset_logging, temp_log_dir):
        setup_logging(
            log_dir=temp_log_dir,
            console_output=False
        )

        logger = get_logger("context_test")

        # Log with context
        logger.info(
            "Message with context",
            extra={"repo_type": "Git", "repo_name": "TestRepo"}
        )

        # Read log file
        log_file = os.path.join(temp_log_dir, "app.log")
        with open(log_file, 'r') as f:
            log_content = f.read()

        # Verify context in log
        assert "[Git/TestRepo]" in log_content

    # Test multiple loggers working together
    def test_multiple_loggers(self, reset_logging, temp_log_dir):
        setup_logging(log_dir=temp_log_dir, console_output=False)

        logger1 = get_logger("module1")
        logger2 = get_logger("module2")

        logger1.info("Message from module1")
        logger2.info("Message from module2")

        # Both messages should appear in main log
        log_file = os.path.join(temp_log_dir, "app.log")
        with open(log_file, 'r') as f:
            log_content = f.read()

        assert "Message from module1" in log_content
        assert "Message from module2" in log_content
        assert "module1" in log_content
        assert "module2" in log_content
