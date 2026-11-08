from __future__ import annotations

MASK_CHARS = "•" * 8


def mask_secret(value: str | None, visible: int = 4) -> str | None:
    """Return a display-safe form of a secret: prefix + mask + suffix.

    Short values are fully masked so a 6-character secret cannot be reconstructed
    from its mask halves.
    """
    if not value:
        return None
    if len(value) <= visible * 2:
        return MASK_CHARS
    return f"{value[:visible]}{MASK_CHARS}{value[-visible:]}"
