"""Configures a centralized, professional logging system for the application.

This module provides a flexible `setup_logging` function that configures the
root logger for the entire application. It establishes a consistent logging
format and directs log messages to both the console (for human readability)
and to a rotating file (for persistent, machine-readable records).
"""
import logging
import logging.handlers
import sys
import json
from pathlib import Path

class JSONFormatter(logging.Formatter):
    """A custom log formatter that outputs log records as a JSON string.

    This formatter is designed for machine-readability. The structured JSON
    output can be easily ingested, parsed, and indexed by log aggregation tools
    like the ELK Stack (Elasticsearch, Logstash, Kibana), Datadog, Splunk, or Sentry.
    This is a best practice for applications running in a production or automated
    environment.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Formats a log record into a JSON string.

        Args:
            record: The `LogRecord` object to be formatted.

        Returns:
            A JSON string representing the log record.
        """
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.name,
            "funcName": record.funcName,
            "lineno": record.lineno,
        }

        if record.exc_info:
            log_data['exc_info'] = self.formatException(record.exc_info)

        return json.dumps(log_data)

def setup_logging(
    console_level: int = logging.INFO,
    json_logging: bool = True
):
    """
    Initializes the root logger with configurable handlers and formatters.

    This function sets up a robust and production-ready logging system, incorporating best practices:
    - Clear, human-readable console output.
    - Optional structured (JSON) file output for machine parsing.
    - Time-based log rotation to prevent log files from growing indefinitely.
    - Centralized configuration.
    -----------------------------------------------------------------------------
    - **Dual Output:** Logs to both the console and a file.
    - **Log Rotation:** Uses a `TimedRotatingFileHandler` to automatically
      rotate the log file daily, keeping a history of the last 7 days. This
      prevents log files from growing indefinitely.
    - **Structured Logging:** Can output file logs in a machine-readable JSON
      format for easy integration with log analysis tools.
    - **Centralized Configuration:** Configures the root logger, so all loggers
      created in other modules will inherit this configuration.

    Args:
        console_level: The minimum logging level to display on the console (e.g., `logging.INFO`, `logging.DEBUG`).
        json_logging: If True, file logs will be in JSON format.
                      If False, they will be in a human-readable text format.
    """
    base_dir = Path(__file__).resolve().parent.parent.parent
    log_dir = base_dir / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "app.log"

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    if logger.hasHandlers():
        logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)-8s - [%(name)s] - %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=7, encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG) # Always log everything to the file.

    if json_logging:
        file_formatter = JSONFormatter()
    else:
        file_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)-8s - [%(name)s:%(lineno)d] - %(message)s"
        )

    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    logging.info("Logging configured successfully. Console level: %s", logging.getLevelName(console_level))