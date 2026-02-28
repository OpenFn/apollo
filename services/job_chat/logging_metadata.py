import json
import time
from typing import Any, Dict, Optional


SENSITIVE_TOP_LEVEL_KEYS = {"api_key"}


def describe_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def parse_bool_flag(value: Any, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def parse_retry_after_header(raw_retry_after: Optional[str], default: int = 60) -> int:
    if raw_retry_after is None:
        return default

    try:
        return int(float(raw_retry_after))
    except (TypeError, ValueError):
        return default


def build_request_log_metadata(data_dict: Dict[str, Any]) -> Dict[str, Any]:
    payload_shape: Dict[str, str] = {}
    for key, value in data_dict.items():
        if key == "_request_id":
            continue
        if key in SENSITIVE_TOP_LEVEL_KEYS:
            payload_shape[key] = "redacted"
        else:
            payload_shape[key] = describe_type(value)

    context = data_dict.get("context")
    context_keys = sorted(context.keys()) if isinstance(context, dict) else []
    context_shape = (
        {key: describe_type(value) for key, value in context.items()}
        if isinstance(context, dict)
        else {}
    )

    history = data_dict.get("history")
    history_length = len(history) if isinstance(history, list) else 0

    return {
        "request_id": data_dict.get("_request_id"),
        "payload_shape": payload_shape,
        "history_length": history_length,
        "context_keys": context_keys,
        "context_shape": context_shape,
        "stream": parse_bool_flag(data_dict.get("stream"), default=False),
        "suggest_code": parse_bool_flag(data_dict.get("suggest_code"), default=False),
        "download_adaptor_docs": parse_bool_flag(data_dict.get("download_adaptor_docs"), default=True),
        "refresh_rag": parse_bool_flag(data_dict.get("refresh_rag"), default=False),
    }


def build_completion_log(
    *,
    request_id: Optional[str],
    started_at: float,
    status_code: int,
) -> Dict[str, Any]:
    return {
        "request_id": request_id,
        "duration_ms": int((time.time() - started_at) * 1000),
        "status_code": status_code,
    }


def build_error_log(
    *,
    request_id: Optional[str],
    started_at: float,
    status_code: int,
    error_type: str,
    error_class: str,
) -> Dict[str, Any]:
    return {
        "request_id": request_id,
        "duration_ms": int((time.time() - started_at) * 1000),
        "status_code": status_code,
        "error_type": error_type,
        "error_class": error_class,
    }


def to_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)
