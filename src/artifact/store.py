"""Load / save / validate artifacts, and export the JSON Schema."""
from __future__ import annotations

import json
import pathlib

from .schema import Artifact, json_schema


def load(path: str | pathlib.Path) -> Artifact:
    data = json.loads(pathlib.Path(path).read_text())
    return Artifact.model_validate(data)


def loads(text: str) -> Artifact:
    return Artifact.model_validate_json(text)


def save(artifact: Artifact, path: str | pathlib.Path) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(artifact.model_dump_json(indent=2, by_alias=True, exclude_none=True))


def export_json_schema(path: str | pathlib.Path) -> None:
    pathlib.Path(path).write_text(json.dumps(json_schema(), indent=2))
