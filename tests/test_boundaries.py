"""Architectural boundary tests — the brief's core claims must be mechanically true."""
import pathlib
import re

from _util import ROOT

SRC = ROOT / "src"


def test_only_platformx_is_os_conditional():
    """sys.platform checks must live only in src/platformx/."""
    offenders = []
    for py in SRC.rglob("*.py"):
        if "platformx" in py.parts:
            continue
        text = py.read_text()
        if re.search(r"\bsys\.platform\b", text):
            offenders.append(str(py.relative_to(ROOT)))
    assert not offenders, f"sys.platform used outside platformx: {offenders}"


def test_replay_does_not_import_agent_or_llm():
    """Static guard mirroring the import-linter contract (belt and suspenders)."""
    banned = ("import openai", "import anthropic", "from openai", "from anthropic",
              "src.agent", "from ..agent", "from ...agent")
    for py in (SRC / "replay").rglob("*.py"):
        text = py.read_text()
        for token in banned:
            assert token not in text, f"{py.name} references {token}"
