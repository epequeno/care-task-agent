"""De-identify FHIR resources before any of them reach a model.

Four jobs, all testable without a network:

* ``redact`` — strip direct identifiers and generalise dates to the year.
* ``direct_identifier_strings`` — the literal strings in a record that identify the
  patient: name parts, contact points, identifier values, addresses, birth date.
* ``scrub_free_text`` — remove those strings from prose. ``redact`` works on *keys*,
  and FHIR puts names in free text too: a real Task came back from a public sandbox
  reading ``"Review appointment request from Babara Rice"``.
* ``find_direct_identifiers`` — assert no direct-identifier key survived.

``direct_identifier_strings`` has two callers on purpose — the tools scrub with it and
the eval checks against it — so the check cannot drift from the scrub.

The rule the repo holds to: **nothing reaches the model without passing through here.**
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from typing import Any

# Keys that carry a direct identifier under FHIR R4 (names, contact points, the
# identifier list, and links out to other parties).
DIRECT_IDENTIFIER_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "address",
        "telecom",
        "identifier",
        "photo",
        "contact",
        "communication",
        "generalPractitioner",
        "managingOrganization",
        "link",
    }
)

# Dates generalised to the year only (FHIR dates are strings, e.g. "1980-04-12").
DATE_KEYS: frozenset[str] = frozenset({"birthDate"})

# Inside a direct-identifier element, the keys whose *string* is patient data. The
# rest of the subtree is vocabulary — ``system``, ``code``, ``use``, ``type`` — which
# says what an identifier is, not what it is for this patient.
IDENTIFIER_VALUE_KEYS: frozenset[str] = frozenset(
    {
        "family",
        "given",
        "prefix",
        "suffix",
        "line",
        "city",
        "district",
        "state",
        "postalCode",
        "country",
        "value",
        "reference",
        "display",
        "data",
        "url",
    }
)


def redact(resource: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy with direct identifiers removed and dates generalised."""
    return _walk(copy.deepcopy(resource))


def _walk(node: Any) -> Any:
    if isinstance(node, list):
        return [_walk(item) for item in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in DIRECT_IDENTIFIER_KEYS:
            continue
        if key in DATE_KEYS and isinstance(value, str) and len(value) >= 4:
            out[key] = value[:4]
            continue
        out[key] = _walk(value)
    return out


def direct_identifier_strings(resource: Any) -> list[str]:
    """Every literal string in a resource that identifies the patient directly.

    Whole subtrees are walked, because FHIR keeps a name in
    ``name[].family``/``given[]`` — the key is not where the value is. Nothing is
    dropped for being short: a three-letter surname is a direct identifier.
    """
    found: list[str] = []

    def walk(node: Any, inside_identifier: bool, parent_key: str | None = None) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, inside_identifier or key in DIRECT_IDENTIFIER_KEYS, key)
        elif isinstance(node, list):
            for item in node:
                walk(item, inside_identifier, parent_key)
        elif isinstance(node, str):
            # Values only inside an identifier element: a `value` key elsewhere is a
            # dose or a lab number, and a model that reads the record should say it.
            is_value = inside_identifier and parent_key in IDENTIFIER_VALUE_KEYS
            if is_value or parent_key in DATE_KEYS:
                found.append(node)

    walk(resource, False)
    return sorted(set(found))


def scrub_free_text(value: str, forbidden: Iterable[str]) -> str:
    """Remove known identifier strings from a free-text value.

    Whole words only, longest first: "Rice" must not be cut out of "Briceno", and a
    full name has to go before its parts do. Whitespace left behind is collapsed.
    """
    out = value
    for needle in sorted({item for item in forbidden if item}, key=len, reverse=True):
        out = re.sub(rf"(?<!\w){re.escape(needle)}(?!\w)", " ", out)
    return re.sub(r"\s+", " ", out).strip()


def find_direct_identifiers(resource: Any, path: str = "$") -> list[str]:
    """Return the paths of any direct-identifier keys still present."""
    hits: list[str] = []
    if isinstance(resource, list):
        for i, item in enumerate(resource):
            hits += find_direct_identifiers(item, f"{path}[{i}]")
    elif isinstance(resource, dict):
        for key, value in resource.items():
            if key in DIRECT_IDENTIFIER_KEYS:
                hits.append(f"{path}.{key}")
            hits += find_direct_identifiers(value, f"{path}.{key}")
    return hits
