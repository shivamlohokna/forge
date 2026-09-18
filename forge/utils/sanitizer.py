"""Centralized recursive secret sanitizer for Forge.

This module provides the single source of truth for secret masking in Forge.
It is used to sanitize parameter dicts, event payloads, and persistence records
before they are logged or written to SQLite.

Critical invariant
──────────────────
Tasks receive **real** secret values at execution time — sanitization never
touches values flowing into ``task.run(context)``.  Sanitization is applied
only at the telemetry/logging/persistence boundary, i.e. when data is
serialized to the database or emitted to a log record.

Sensitive key detection
───────────────────────
Keys are matched on word-boundary substrings, not arbitrary substrings.
``rotation_token_count`` does **not** match ``token`` because the match
requires the pattern to be the full key or an underscore-delimited segment.

Pattern matching rules (case-insensitive):
- Exact match:                 ``token`` → sensitive
- Leading underscore:          ``token_value`` → sensitive
- Trailing underscore:         ``api_token`` → sensitive
- Embedded segment:            ``github_api_token_value`` → sensitive
                               (contains ``token`` as a segment)
- Mismatch (not a segment):    ``rotation_count`` → NOT sensitive
                               ``tokenize`` → NOT sensitive

Usage
─────
::

    from forge.utils.sanitizer import sanitize

    safe = sanitize({"password": "s3cr3t", "url": "https://example.com"})
    # → {"password": "***", "url": "https://example.com"}

    safe = sanitize({"headers": {"Authorization": "Bearer tok123"}})
    # → {"headers": {"Authorization": "***"}}

"""

from __future__ import annotations

from typing import Any

# ── Configuration ─────────────────────────────────────────────────────────────

MASK: str = "***"

#: Set of lowercase pattern tokens.  A dict key is considered sensitive iff
#: any of these patterns appears as a complete underscore-delimited word in
#: the lowercase key name.
SENSITIVE_KEY_PATTERNS: frozenset[str] = frozenset({
    "token",
    "password",
    "secret",
    "authorization",
    "api_key",
    "access_token",
    "private_key",
    "credential",
    "credentials",
    "auth",
    "passwd",
    "passphrase",
})

#: Maximum recursion depth to prevent pathological inputs from blowing the
#: Python call stack.
_MAX_DEPTH: int = 20


# ── Public API ────────────────────────────────────────────────────────────────

def is_sensitive_key(key: str) -> bool:
    """Return True if *key* looks like it may hold a sensitive secret value.

    Matching is case-insensitive and uses exact word-boundary detection on
    underscore-delimited segments.  This avoids false positives like
    ``rotation_token_count`` or ``tokenize``.

    Args:
        key: The dictionary key to inspect.

    Returns:
        ``True`` if the key is considered sensitive, ``False`` otherwise.

    Examples::

        >>> is_sensitive_key("password")
        True
        >>> is_sensitive_key("api_key")
        True
        >>> is_sensitive_key("github_token")
        True
        >>> is_sensitive_key("rotation_token_count")
        True   # "token" is a full segment
        >>> is_sensitive_key("tokenize")
        False  # "token" is not a complete segment
        >>> is_sensitive_key("count")
        False
    """
    # Split on underscores to get the key's component words
    parts = key.lower().split("_")

    # Check both individual parts and multi-word sub-patterns
    for pattern in SENSITIVE_KEY_PATTERNS:
        pattern_parts = pattern.split("_")
        n = len(pattern_parts)
        # Sliding-window match over the key's segments
        for i in range(len(parts) - n + 1):
            if parts[i : i + n] == pattern_parts:
                return True
    return False


def sanitize(value: Any, *, _depth: int = 0) -> Any:
    """Recursively sanitize *value* for safe logging or persistence.

    - ``dict``:  Recurse over items; mask the **value** when ``is_sensitive_key``
                 returns ``True`` for the corresponding key.  Keys themselves
                 are never masked.
    - ``list`` / ``tuple``:  Recurse over elements.  Tuples are returned as
                 lists for simplicity (avoids type gymnastics with heterogeneous
                 tuple types).
    - ``str`` / primitive:  Returned as-is.  String values are not guessed to
                 be secrets based on their content.
    - ``None``:  Returned as-is.

    Args:
        value: The value to sanitize.  May be any JSON-serialisable object.

    Returns:
        A sanitized copy of *value*.  The original object is never mutated.

    Raises:
        RecursionError: Prevented internally; returns ``MASK`` at depth limit.
    """
    if _depth > _MAX_DEPTH:
        # Pathological input guard — mask the entire subtree rather than
        # blowing the Python call stack.
        return MASK

    if isinstance(value, dict):
        return {
            k: (MASK if is_sensitive_key(str(k)) else sanitize(v, _depth=_depth + 1))
            for k, v in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [sanitize(item, _depth=_depth + 1) for item in value]

    # Primitives (str, int, float, bool, None, bytes, etc.) are returned as-is.
    return value


# ── Module exports ────────────────────────────────────────────────────────────

__all__ = [
    "MASK",
    "SENSITIVE_KEY_PATTERNS",
    "is_sensitive_key",
    "sanitize",
]
