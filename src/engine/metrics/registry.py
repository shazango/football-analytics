"""Registers a metric's Python implementation against its definition id.

Kept separate from definitions.py: the YAML is data, this is code, and a
definition can exist (e.g. for documentation review) before its
implementation is registered, or vice versa during development.
"""

from typing import Callable

_REGISTRY: dict[str, Callable] = {}


def register(definition_id: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        _REGISTRY[definition_id] = fn
        return fn

    return decorator


def get_implementation(definition_id: str) -> Callable:
    try:
        return _REGISTRY[definition_id]
    except KeyError:
        raise KeyError(
            f"no implementation registered for metric '{definition_id}'"
        ) from None
