"""Centralized runtime paths for generated local artifacts."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path(os.getenv("RUNTIME_DIR", str(BASE_DIR / "runtime"))).resolve()
DB_DIR = Path(os.getenv("DB_DIR", str(RUNTIME_DIR / "db"))).resolve()
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", str(RUNTIME_DIR / "chroma"))).resolve()
EXPORTS_DIR = Path(os.getenv("EXPORTS_DIR", str(RUNTIME_DIR / "exports"))).resolve()
THINKING_DIR = Path(os.getenv("THINKING_DIR", str(RUNTIME_DIR / "thinking"))).resolve()

def ensure_runtime_dirs() -> None:
    """Create expected runtime directories when missing."""
    for path in (RUNTIME_DIR, DB_DIR, CHROMA_DIR, EXPORTS_DIR, THINKING_DIR):
        path.mkdir(parents=True, exist_ok=True)
