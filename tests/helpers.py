"""Test helpers — kept out of conftest so tests can import them directly."""

from __future__ import annotations

from typing import Any


def resources(bundle: dict[str, Any], resource_type: str) -> list[dict[str, Any]]:
    """All resources of one type in a bundle."""
    return [
        entry["resource"]
        for entry in bundle["entry"]
        if entry["resource"]["resourceType"] == resource_type
    ]
