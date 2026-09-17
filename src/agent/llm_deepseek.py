"""DeepSeek V4.1 Flash provider (OpenAI-compatible). Vision + function calling.

All model specifics live here. The discovery loop only sees `AgentAction`. Model id
and base_url come from config, never hardcoded — swapping to another OpenAI-compatible
provider (or OpenAI itself) is a one-line change.

DeepSeek notes: native multimodal (base64 image in the content array); tools/
tool_choice for function calling; no response_format — irrelevant here since we drive
structure via function calling.
"""
from __future__ import annotations

import base64
import json

from .provider import AgentAction

_REASON = {"type": "string", "description": "One short sentence: why this action now (recorded as evidence)."}

_TOOLS = [
    {"type": "function", "function": {
        "name": "click", "description": "Click the numbered mark.",
        "parameters": {"type": "object", "properties": {
            "mark": {"type": "integer"}, "reason": _REASON}, "required": ["mark"]}}},
    {"type": "function", "function": {
        "name": "type", "description": "Focus the field at/near the mark and type text.",
        "parameters": {"type": "object", "properties": {
            "mark": {"type": "integer"}, "text": {"type": "string"}, "reason": _REASON},
            "required": ["mark", "text"]}}},
    {"type": "function", "function": {
        "name": "key", "description": "Press a key such as enter or tab.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "reason": _REASON}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "read", "description": "Read the value shown at the mark (for extraction).",
        "parameters": {"type": "object", "properties": {
            "mark": {"type": "integer"}, "reason": _REASON}, "required": ["mark"]}}},
    {"type": "function", "function": {
        "name": "done", "description": "The goal is complete; return outputs.",
        "parameters": {"type": "object", "properties": {
            "outputs": {"type": "object"}, "reason": _REASON}}}},
    {"type": "function", "function": {
        "name": "escalate", "description": "Cannot safely proceed; hand to a human.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string"}}, "required": ["reason"]}}},
]

_SYSTEM = (
    "You operate a legacy banking UI by vision only — there is no DOM. You are shown a "
    "screenshot with numbered red marks over text lines and input fields, plus a legend. "
    "Choose ONE tool call per turn to make progress toward the goal. Prefer clicking the "
    "mark whose text matches a control (link/button) and typing into the mark nearest an "
    "input label.\n"
    "To extract a field, call read on the mark for the row LABEL (e.g. 'Savings Balance', "
    "'Member Name'), NOT on the value cell itself — replay extracts the text to the right "
    "of the label, so reading a value cell would hard-code one member's data. Read each "
    "requested field once (the value you read is echoed back in HISTORY), then immediately "
    "call done. Do not repeat a read you already performed."
)


class DeepSeekProvider:
    def __init__(self, api_key: str, base_url: str, model: str,
                 timeout_s: float = 120.0, max_retries: int = 1):
        from openai import OpenAI

        # Bounded client: a stalled provider call must fail fast, not hang the run.
        self._client = OpenAI(api_key=api_key, base_url=base_url,
                              timeout=timeout_s, max_retries=max_retries)
        self._model = model

    def decide(self, goal: str, png_overlay: bytes, legend: str, history: list[str]) -> AgentAction:
        b64 = base64.b64encode(png_overlay).decode()
        user = [
            {"type": "text", "text": f"GOAL: {goal}\n\nMARK LEGEND:\n{legend}\n\n"
                                     f"HISTORY:\n" + ("\n".join(history[-8:]) or "(none)")},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            tools=_TOOLS,
            tool_choice="auto",
            temperature=0,
        )
        return self._parse(resp)

    @staticmethod
    def _parse(resp) -> AgentAction:
        choice = resp.choices[0].message
        calls = getattr(choice, "tool_calls", None)
        if not calls:
            return AgentAction(kind="escalate", reason="model returned no tool call")
        call = calls[0]
        name = call.function.name
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        return AgentAction(
            kind=name, mark=args.get("mark"), text=args.get("text"), name=args.get("name"),
            outputs=args.get("outputs", {}) or {}, reason=args.get("reason"),
        )
