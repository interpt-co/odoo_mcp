"""Connection layer - stub interfaces for Group 1."""

from .protocol import OdooProtocol
from .manager import ConnectionManager

__all__ = ["OdooProtocol", "ConnectionManager"]
