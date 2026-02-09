"""Pytest configuration — add the project root to sys.path for test discovery."""

import sys
from pathlib import Path

# Ensure odoo_mcp package is importable without installing
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
