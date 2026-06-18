"""Lenient extraction of a <tool> call from raw model output (SPEC §5).

The model is asked for exactly one fenced block:
    <tool>
    {"name": "...", ...}
    </tool>
Models lie about formatting, so we tolerate: missing </tool>, ```json fences,
trailing prose, single quotes, and trailing commas. If nothing parses we return
(None, reason) and the loop feeds a one-line correction back — no wasted turn.
"""
from __future__ import annotations

import re
import json


# accept our tag, Qwen's native <tool_call>, and ```json fences
_TOOL_RE = re.compile(r"<tool(?:_call)?>\s*(.*?)\s*(?:</tool(?:_call)?>|$)", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json|tool)?\s*(.*?)```", re.DOTALL)
# explicit content channel: file bodies go here so quotes/newlines never need
# JSON-escaping (the single biggest source of wasted steps on real code).
_TEXT_RE = re.compile(r"<text>\n?(.*?)\n?</text>", re.DOTALL)
_CONTENT_FENCE = re.compile(r"```[a-zA-Z0-9_+\-]*\n(.*?)\n?```", re.DOTALL)
# function-paren fallback:  name(arg="v", n=1)  or  <name(arg="v")>
_PAREN_RE = re.compile(r"<?\b([a-z_][a-z0-9_]*)\s*\(([^)]*)\)>?", re.IGNORECASE)
_KV_RE = re.compile(r'(\w+)\s*=\s*(".*?"|\'.*?\'|[^,]+)')


def _extract_json_object(s: str) -> str | None:
    start = s.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]
    return None  # unterminated


def _loads_lenient(blob: str):
    # strict=False allows literal newlines/tabs inside strings — crucial because
    # models routinely emit multi-line code in "text" without escaping it.
    try:
        return json.loads(blob, strict=False)
    except json.JSONDecodeError:
        pass
    fixed = re.sub(r",\s*([}\]])", r"\1", blob)            # trailing commas
    try:
        return json.loads(fixed, strict=False)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(re.sub(r"'", '"', fixed), strict=False)  # single quotes
    except json.JSONDecodeError:
        return None


_KNOWN = {
    "list_dir", "read_file", "search", "write_file", "replace_lines",
    "replace_function", "append_file", "run_command", "run_file",
    "docker_ps", "docker_build", "docker_run", "docker_logs", "docker_compose",
    "web_search", "web_fetch",
}


def _coerce(v: str):
    v = v.strip().strip(",").strip()
    if (v[:1], v[-1:]) in (('"', '"'), ("'", "'")):
        return v[1:-1]
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


def _parse_paren_call(text: str):
    """Fallback for `name(arg=...)` / `<name(arg=...)>` dialects Qwen sometimes uses."""
    for m in _PAREN_RE.finditer(text):
        name = m.group(1)
        if name not in _KNOWN:
            continue
        call = {"name": name}
        for km in _KV_RE.finditer(m.group(2)):
            call[km.group(1)] = _coerce(km.group(2))
        return call
    return None


_TEXT_KEYS = ("text", "content", "new_text", "code", "value", "body")


def _extract_content_block(body: str, json_str: str | None) -> str | None:
    """Pull a file body from a <text>…</text> block, or a fenced block that
    appears after the JSON object."""
    m = _TEXT_RE.search(body)
    if m:
        return m.group(1)
    rest = body.split(json_str, 1)[1] if (json_str and json_str in body) else body
    m = _CONTENT_FENCE.search(rest)
    if m:
        return m.group(1)
    return None


def parse_tool_call(text: str):
    """Return (call_dict, error). Exactly one of them is set."""
    m = _TOOL_RE.search(text) or _FENCE_RE.search(text)
    body = m.group(1) if m else None

    if body is not None:
        json_str = _extract_json_object(body)
        obj = _loads_lenient(json_str) if json_str else None
        if isinstance(obj, dict) and "name" in obj:
            if "arguments" in obj and isinstance(obj["arguments"], dict):
                obj = {"name": obj["name"], **obj["arguments"]}
            # fold in a separate content block for file-body tools
            if not any(k in obj for k in _TEXT_KEYS):
                content = _extract_content_block(body, json_str)
                if content is not None:
                    obj["text"] = content
            return obj, None
        if json_str is not None:
            # JSON was present but malformed — DON'T scan code for paren calls
            return None, ("tool JSON was malformed. Put file content in a "
                          "<text>...</text> block, not inside the JSON string.")
        # no JSON in the block → allow the function-paren dialect
        paren = _parse_paren_call(body)
        if paren:
            return paren, None
        return None, "no recognizable tool call in the block"

    # no <tool> block at all: only treat bare function-paren as a call when the
    # text isn't otherwise prose/JSON (avoids matching code in a final answer)
    if "{" not in text and _PAREN_RE.search(text):
        paren = _parse_paren_call(text)
        if paren:
            return paren, None
    return None, "no tool call found"


def has_tool_call(text: str) -> bool:
    # An explicit <tool>/<tool_call> tag is always an attempt (even if malformed,
    # so we can feed the error back rather than treat it as a final answer).
    if _TOOL_RE.search(text):
        return True
    # Otherwise it's only a tool call if it actually parses to one — this stops a
    # ```code``` fence in a final-answer summary from being mistaken for a call.
    return parse_tool_call(text)[0] is not None
