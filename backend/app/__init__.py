from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv as _load_dotenv


def load_dotenv(*args, **kwargs):
    """Load the repo-level .env before transport settings are read.

    The application runs from backend/, but the .env file lives at the repo root.
    Keep this in the package so it is applied before any transport imports.
    """
    root_dir = Path(__file__).resolve().parents[2]
    kwargs.setdefault("dotenv_path", root_dir / ".env")
    return _load_dotenv(*args, **kwargs)


load_dotenv()
