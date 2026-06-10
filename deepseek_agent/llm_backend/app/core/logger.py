from __future__ import annotations

import contextvars
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger as _base_logger


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _env_enabled(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_log_dir() -> Path:
    configured = os.getenv("AI_KEFU_LOG_DIR")
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path
    return PROJECT_ROOT / "logs"


LOG_DIR = _resolve_log_dir()
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_LEVEL = os.getenv("AI_KEFU_LOG_LEVEL", "INFO").upper()
CONSOLE_LOG_ENABLED = _env_enabled("AI_KEFU_CONSOLE_LOG", "1")
TRACE_LOG_ENABLED = _env_enabled("AI_KEFU_TRACE_LOG", "0")
DEBUG_TRACE_ENABLED = _env_enabled("AI_KEFU_DEBUG_TRACE", "0")

_request_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "request_log_context", default={}
)
_trace_context: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "request_trace_context", default=None
)

_ORDERED_FIELDS = (
    "event",
    "request_id",
    "conversation_id",
    "user_id",
    "thread_id",
    "path",
    "method",
    "status",
    "client",
    "node",
    "tool",
    "model",
    "elapsed_ms",
    "reason",
)

_INTERNAL_EXTRA_FIELDS = {"formatted", "log_sink", "console"}


def _clean_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)

    text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = " ".join(text.split())
    if not text:
        return '""'
    if any(char.isspace() for char in text) or any(char in text for char in ['"', "="]):
        text = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{text}"'
    return text


def _format_log_line(record: dict[str, Any]) -> str:
    extra = record["extra"]
    service = extra.get("service") or record["name"]
    parts = [
        f"ts={record['time'].strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}",
        f"level={record['level'].name}",
        f"service={_clean_value(service)}",
    ]

    for key in _ORDERED_FIELDS:
        if key in extra:
            parts.append(f"{key}={_clean_value(extra.get(key))}")

    for key in sorted(extra):
        if key in _ORDERED_FIELDS or key in _INTERNAL_EXTRA_FIELDS or key == "service":
            continue
        parts.append(f"{key}={_clean_value(extra.get(key))}")

    message = record["message"]
    if message:
        parts.append(f"message={_clean_value(message)}")

    source = f"{record['name']}:{record['function']}:{record['line']}"
    parts.append(f"source={_clean_value(source)}")
    return " ".join(parts)


def _patch_record(record: dict[str, Any]) -> None:
    extra = record["extra"]
    for key, value in _request_context.get().items():
        extra.setdefault(key, value)
    extra["formatted"] = _format_log_line(record)
    _append_trace_event(record)


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _append_trace_event(record: dict[str, Any]) -> None:
    trace_events = _trace_context.get()
    if trace_events is None or record["extra"].get("log_sink") == "trace":
        return

    extra = record["extra"]
    service = extra.get("service") or record["name"]
    event = {
        "ts": record["time"].strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "level": record["level"].name,
        "service": _json_safe_value(service),
    }

    for key in _ORDERED_FIELDS:
        if key in extra:
            event[key] = _json_safe_value(extra.get(key))

    for key in sorted(extra):
        if key in _ORDERED_FIELDS or key in _INTERNAL_EXTRA_FIELDS or key == "service":
            continue
        event[key] = _json_safe_value(extra.get(key))

    message = record["message"]
    if message:
        event["message"] = _json_safe_value(message)

    event["source"] = f"{record['name']}:{record['function']}:{record['line']}"
    trace_events.append(event)


def _is_access_log(record: dict[str, Any]) -> bool:
    return record["extra"].get("log_sink") == "access"


def _is_trace_sink(record: dict[str, Any]) -> bool:
    return record["extra"].get("log_sink") == "trace"


def _is_app_log(record: dict[str, Any]) -> bool:
    return (
        not _is_access_log(record)
        and not _is_trace_sink(record)
        and record["level"].no < _base_logger.level("ERROR").no
    )


def _is_error_log(record: dict[str, Any]) -> bool:
    return (
        not _is_access_log(record)
        and not _is_trace_sink(record)
        and record["level"].no >= _base_logger.level("ERROR").no
    )


def _is_trace_log(record: dict[str, Any]) -> bool:
    return _is_trace_sink(record) and record["exception"] is not None


def _is_console_log(record: dict[str, Any]) -> bool:
    if not CONSOLE_LOG_ENABLED or _is_access_log(record) or _is_trace_sink(record):
        return False
    return record["extra"].get("console") is True or record["level"].no >= _base_logger.level("WARNING").no


_base_logger.remove()
logger = _base_logger.patch(_patch_record)

logger.add(
    sys.stdout,
    format="{extra[formatted]}",
    level="INFO",
    filter=_is_console_log,
    colorize=False,
)

logger.add(
    str(LOG_DIR / "access_{time:YYYY-MM-DD}.log"),
    rotation="00:00",
    retention="14 days",
    format="{extra[formatted]}",
    level="INFO",
    filter=_is_access_log,
    encoding="utf-8",
)

logger.add(
    str(LOG_DIR / "app_{time:YYYY-MM-DD}.log"),
    rotation="00:00",
    retention="14 days",
    format="{extra[formatted]}",
    level=LOG_LEVEL,
    filter=_is_app_log,
    encoding="utf-8",
)

logger.add(
    str(LOG_DIR / "error_{time:YYYY-MM-DD}.log"),
    rotation="00:00",
    retention="30 days",
    format="{extra[formatted]}",
    level="ERROR",
    filter=_is_error_log,
    encoding="utf-8",
)

if TRACE_LOG_ENABLED:
    logger.add(
        str(LOG_DIR / "trace_{time:YYYY-MM-DD}.log"),
        rotation="00:00",
        retention="7 days",
        format="{extra[formatted]}",
        level="ERROR",
        filter=_is_trace_log,
        encoding="utf-8",
    )


def get_logger(service: str):
    """Return a logger bound to a stable service name."""
    return logger.bind(service=service)


def bind_request_context(
    request_id: str,
    user_id: int | str | None = None,
    conversation_id: int | str | None = None,
    thread_id: str | None = None,
):
    context = {"request_id": request_id}
    if user_id is not None:
        context["user_id"] = user_id
    if conversation_id is not None:
        context["conversation_id"] = conversation_id
    if thread_id is not None:
        context["thread_id"] = thread_id
    return _request_context.set(context)


def reset_request_context(token) -> None:
    _request_context.reset(token)


def start_trace():
    return _trace_context.set([])


def get_trace() -> list[dict[str, Any]]:
    trace_events = _trace_context.get()
    return list(trace_events) if trace_events is not None else []


def clear_trace() -> None:
    _trace_context.set(None)


def log_event(event_logger, level: str, event: str, **fields: Any) -> None:
    exception = fields.pop("exception", None)
    event_logger.bind(event=event, **fields).log(level.upper(), "")

    if exception and TRACE_LOG_ENABLED:
        event_logger.bind(event=event, log_sink="trace", **fields).opt(
            exception=exception
        ).log(level.upper(), "")


def log_structured(event_type: str, data: dict):
    """Compatibility helper for older structured log call sites."""
    log_event(get_logger("structured"), "INFO", event_type, **data)
