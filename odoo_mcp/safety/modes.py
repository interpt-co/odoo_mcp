"""Operation mode enforcement - stub for Group 2.

Defines the safety mode enforcement interfaces.
"""

from __future__ import annotations

from typing import Literal


class ModeViolationError(Exception):
    """Raised when an operation violates the current mode restrictions."""

    pass


class SafetyConfig:
    """Mode-based operation safety enforcement (Group 2 implements)."""

    def __init__(self, mode: Literal["readonly", "readwrite", "full"] = "readwrite"):
        self.mode = mode

    def check_write_allowed(self) -> None:
        if self.mode == "readonly":
            raise ModeViolationError(
                "Write operations are not allowed in readonly mode."
            )

    def check_delete_allowed(self) -> None:
        if self.mode != "full":
            raise ModeViolationError(
                "Delete operations are only allowed in full mode."
            )

    def is_readonly(self) -> bool:
        return self.mode == "readonly"

    def is_full(self) -> bool:
        return self.mode == "full"


def enforce_mode(
    mode: Literal["readonly", "readwrite", "full"],
    required: Literal["readonly", "readwrite", "full"],
) -> None:
    """Raise ModeViolationError if current mode is insufficient."""
    levels = {"readonly": 0, "readwrite": 1, "full": 2}
    if levels[mode] < levels[required]:
        raise ModeViolationError(
            f"Operation requires '{required}' mode but current mode is '{mode}'."
        )
