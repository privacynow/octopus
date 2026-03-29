from __future__ import annotations

from collections.abc import Mapping


def json_ready(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return json_ready(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def record(model_cls, payload):
    return model_cls.model_validate(json_ready(payload))


def records(model_cls, rows):
    return [record(model_cls, row) for row in rows]
