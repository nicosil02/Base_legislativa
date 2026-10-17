"""Tests de congreso_live/notify.py (sin red)."""
from unittest.mock import patch

from congreso_live.notify import acortar_url

_URLOPEN = "congreso_live.notify.urlopen"


def test_acortar_url():
    with patch(_URLOPEN) as mock_urlopen:  # URL corta: ni toca la red
        assert acortar_url("https://x.com/a") == "https://x.com/a"
        mock_urlopen.assert_not_called()

    larga = "https://news.google.com/rss/articles/" + "A" * 500
    ok = type("R", (), {"__enter__": lambda s: s, "__exit__": lambda *a: None,
                        "read": lambda s: b"https://tinyurl.com/abc123"})()
    with patch(_URLOPEN, return_value=ok):
        assert acortar_url(larga) == "https://tinyurl.com/abc123"

    with patch(_URLOPEN, side_effect=TimeoutError("timeout")):  # fail-safe
        assert acortar_url(larga) == larga
