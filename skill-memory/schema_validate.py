"""Subset of JSON Schema used by the skill-memory contracts.

The checker covers the keywords in schemas/: ref, const, enum, type, required,
additionalProperties, items, minimum, maximum, minLength, and minItems.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SCHEMAS = ROOT / "schemas"


def load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def validate_instance(instance: Any, schema: dict[str, Any]) -> list[str]:
    return _validate(instance, schema, schema, "$")


def _validate(instance: Any, schema: dict[str, Any], root: dict[str, Any], path: str) -> list[str]:
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return _validate(instance, root["$defs"][name], root, path)
    errors: list[str] = []
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path} must be {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path} must be one of {schema['enum']!r}")
    types = schema.get("type")
    if isinstance(types, str):
        types = [types]
    if types and not _matches(instance, types):
        errors.append(f"{path} has type {type(instance).__name__}, schema wants {types}")
        return errors
    if isinstance(instance, dict) and "properties" in schema:
        properties = schema["properties"]
        if schema.get("additionalProperties") is False:
            extra = sorted(set(instance) - set(properties))
            if extra:
                errors.append(f"{path} has unexpected fields {extra}")
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path} is missing {key}")
        for key, value in instance.items():
            if key in properties:
                errors.extend(_validate(value, properties[key], root, f"{path}.{key}"))
    if isinstance(instance, list) and "items" in schema:
        minimum = schema.get("minItems")
        if isinstance(minimum, int) and len(instance) < minimum:
            errors.append(f"{path} needs at least {minimum} items")
        for index, item in enumerate(instance):
            errors.extend(_validate(item, schema["items"], root, f"{path}[{index}]"))
    if isinstance(instance, str) and "minLength" in schema and len(instance) < schema["minLength"]:
        errors.append(f"{path} is shorter than {schema['minLength']}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path} is below {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path} is above {schema['maximum']}")
    return errors


def _matches(instance: Any, types: list[str]) -> bool:
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    return any(checks[kind](instance) for kind in types)
