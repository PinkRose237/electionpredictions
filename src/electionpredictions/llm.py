"""OpenAI-compatible chat client for the OpenCode gateway (model AI_MODEL, key OPENCODE_API_KEY).

Used by the model-revision step (revision.py) and the written summaries (narrative.py). Replies are strict JSON."""
from __future__ import annotations

import json
import os
import re
import time
import uuid

import requests

from .config import AI_BASE_URL, AI_MODEL, OPENCODE_API_KEY, USER_AGENT


def available() -> bool:
    return bool(OPENCODE_API_KEY)


class AuthError(RuntimeError):
    pass


# ---------------------------------------------------------------------------- HTTP + parsing
# OpenCode Go routes requests by session; one id per pipeline run keeps prompt-cache reuse across races.
SESSION_ID = os.environ.get("OPENCODE_SESSION_ID") or f"electionpredictions-{uuid.uuid4()}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {OPENCODE_API_KEY}", "Content-Type": "application/json", "User-Agent": USER_AGENT,
            "x-opencode-session": SESSION_ID}


def _post(path: str, body: dict, timeout: int = 180) -> requests.Response:
    return requests.post(f"{AI_BASE_URL.rstrip('/')}/{path.lstrip('/')}", json=body, timeout=timeout, headers=_headers())


def _extract_text(data: dict) -> str:
    if isinstance(data.get("choices"), list) and data["choices"]:
        content = (data["choices"][0].get("message") or {}).get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return (content or "").strip()
    if data.get("output_text"):
        return str(data["output_text"]).strip()
    text = []
    for item in data.get("output", []) or []:
        for part in item.get("content", []) or []:
            if part.get("type") in ("output_text", "text") and part.get("text"):
                text.append(part["text"])
    return "".join(text).strip()


def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates code fences and preamble)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("no JSON object in response")


def complete(system: str, user: str, retries: int = 3, max_tokens: int = 4000) -> str:
    attempts = [
        # reasoning models spend part of the cap thinking before the JSON, so leave generous room
        ("chat/completions", {"model": AI_MODEL, "temperature": 0.2, "max_tokens": max_tokens,
                              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}),
        ("responses", {"model": AI_MODEL, "instructions": system, "max_output_tokens": max_tokens, "input": [{"role": "user", "content": user}]}),
    ]
    if AI_MODEL.startswith("muse-spark"):
        attempts.reverse()  # Muse Spark is served through the Responses API on OpenCode Zen; chat/completions 500s
    last = None
    denied = []
    for path, body in attempts:
        for attempt in range(retries):
            r = _post(path, body)
            if r.status_code == 401:
                raise AuthError(f"OpenCode rejected the API key (HTTP 401): {r.text[:200]}")
            if r.status_code == 402:
                raise AuthError(f"OpenCode account has no credit (HTTP 402): {r.text[:200]} — add funds at opencode.ai")
            if r.status_code == 403:
                # can be a per-endpoint or per-model permission rather than a bad key: try the other shape first
                denied.append(f"{path}: HTTP 403: {r.text[:200]}")
                break
            if r.status_code in (404, 405) or (r.status_code == 400 and "endpoint" in r.text.lower()):
                last = f"{path}: HTTP {r.status_code}: {r.text[:120]}"
                break
            if r.status_code == 429 or r.status_code >= 500:
                last = f"{path}: HTTP {r.status_code}"
                time.sleep(4 * (attempt + 1))
                continue
            if not r.ok:
                raise RuntimeError(f"{path}: HTTP {r.status_code}: {r.text[:200]}")
            text = _extract_text(r.json())
            if not text:
                raise RuntimeError(f"{path}: empty response")
            return text
    if denied and len(denied) == len(attempts):
        raise AuthError("OpenCode refused both endpoints (check the key and that the model is enabled for it): " + " | ".join(denied))
    raise RuntimeError(f"OpenCode request failed ({last or denied})")


def probe() -> dict:
    """One tiny request per endpoint shape; returns statuses and response snippets for diagnosis."""
    out = {"base_url": AI_BASE_URL, "model": AI_MODEL, "key_present": bool(OPENCODE_API_KEY), "key_prefix": OPENCODE_API_KEY[:6] + "…" if OPENCODE_API_KEY else None,
           "session": SESSION_ID}
    tests = [
        ("chat/completions", {"model": AI_MODEL, "max_tokens": 20, "messages": [{"role": "user", "content": "Reply with the single word OK."}]}),
        ("responses", {"model": AI_MODEL, "max_output_tokens": 20, "input": [{"role": "user", "content": "Reply with the single word OK."}]}),
        ("models", None),
    ]
    for path, body in tests:
        try:
            if body is None:
                r = requests.get(f"{AI_BASE_URL.rstrip('/')}/{path}", timeout=60, headers=_headers())
            else:
                r = _post(path, body, timeout=60)
            snippet = r.text[:300].replace("\n", " ")
            entry = {"status": r.status_code, "body": snippet}
            if r.ok and body is not None:
                try:
                    entry["text"] = _extract_text(r.json())[:80]
                except Exception as e:  # noqa: BLE001
                    entry["parse_error"] = repr(e)
            if r.ok and body is None:
                try:
                    ids = [m.get("id") for m in (r.json().get("data") or [])]
                    entry["models"] = [i for i in ids if i and "muse" in i.lower()][:10] or ids[:10]
                except Exception as e:  # noqa: BLE001
                    entry["parse_error"] = repr(e)
            out[path] = entry
        except Exception as e:  # noqa: BLE001
            out[path] = {"error": repr(e)}
    return out




def ask_json(system: str, user: str, max_tokens: int = 4000) -> dict:
    """complete() + parse_json(), with one retry asking for bare JSON."""
    text = complete(system, user, max_tokens=max_tokens)
    try:
        return parse_json(text)
    except (ValueError, json.JSONDecodeError):
        text = complete(system, user + "\n\nYour previous reply was not valid JSON. Reply with the JSON object only.", max_tokens=max_tokens)
        return parse_json(text)
