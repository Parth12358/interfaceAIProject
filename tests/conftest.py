"""Test-session environment checks.

With `-q` the skip reasons are otherwise invisible, so a machine without Tesseract
would show a wall of dots and silently drop roughly half the suite — precisely the
coverage that proves the load-bearing claims (deterministic replay, the error
taxonomy, locator rungs, handoff resume). Surface it loudly instead.
"""
from _util import HAS_TESS


def pytest_report_header(config):
    if HAS_TESS:
        return "tesseract OCR: available"
    return "tesseract OCR: MISSING — OCR/replay/error-taxonomy tests will be SKIPPED"


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if HAS_TESS:
        return
    terminalreporter.write_sep("=", "WARNING: tesseract OCR not found")
    terminalreporter.write_line(
        "~half the suite was skipped (replay engine, error taxonomy, locator rungs, "
        "handoff resume). Install tesseract (see README) and re-run for full coverage."
    )
