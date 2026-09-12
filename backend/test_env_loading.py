from __future__ import annotations

import os
from pathlib import Path


def test_env_file_is_loaded(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "PORT25_TRANSPORT=smtp\n"
        "OUR_EMAIL=test@example.com\n"
        "OUR_EMAIL_APP_PASSWORD=secret\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("PORT25_TRANSPORT", raising=False)
    monkeypatch.delenv("OUR_EMAIL", raising=False)
    monkeypatch.delenv("OUR_EMAIL_APP_PASSWORD", raising=False)

    import app

    if not hasattr(app, "load_dotenv"):
        raise AssertionError("app package must expose load_dotenv()")

    app.load_dotenv(dotenv_path=env_path)

    assert os.getenv("PORT25_TRANSPORT") == "smtp"
    assert os.getenv("OUR_EMAIL") == "test@example.com"
    assert os.getenv("OUR_EMAIL_APP_PASSWORD") == "secret"
