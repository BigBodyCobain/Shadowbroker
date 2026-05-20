"""Issue #199 (tg12): GDELT military incident ingestion must use HTTPS.

The previous code fetched ``http://data.gdeltproject.org/gdeltv2/lastupdate.txt``
and ~48 export archives over plaintext HTTP, which let a passive observer
identify Shadowbroker nodes by their fetch pattern and let an active MITM
inject doctored export records into the global incident map.

These tests assert the URL constants and outbound URL constructor in
``services/geopolitics.py`` only use HTTPS.
"""
import re
from pathlib import Path


_GEOPOLITICS_SRC = Path(__file__).resolve().parent.parent / "services" / "geopolitics.py"


def _read_source() -> str:
    return _GEOPOLITICS_SRC.read_text(encoding="utf-8")


def test_geopolitics_does_not_use_plaintext_http_for_gdelt():
    """No string literal in geopolitics.py should fetch GDELT over plaintext HTTP."""
    src = _read_source()
    # Strings that would issue an HTTP request — comments are excluded because
    # comments include "http://" in example URLs even after the fix.
    code_lines = [
        ln for ln in src.split("\n")
        if "http://data.gdeltproject.org" in ln and not ln.lstrip().startswith("#")
    ]
    assert code_lines == [], (
        "Found plaintext http://data.gdeltproject.org usage in geopolitics.py:\n"
        + "\n".join(code_lines)
    )


def test_geopolitics_uses_https_for_gdelt():
    """The HTTPS URLs we expect must be present."""
    src = _read_source()
    assert "https://data.gdeltproject.org/gdeltv2/lastupdate.txt" in src
    # The download URL is constructed via f-string with {fname}
    assert re.search(
        r'https://data\.gdeltproject\.org/gdeltv2/\{fname\}', src
    ), "expected https URL template for individual GDELT export downloads"
