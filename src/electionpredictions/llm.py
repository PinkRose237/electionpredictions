"""OpenAI-compatible chat client for the OpenCode gateway (key OPENCODE_API_KEY, base AI_BASE_URL).

Callers ask for JSON with a *chain* of models (config.AI_MODELS_REVISION / AI_MODELS_NARRATIVE): the first
model that answers with valid JSON wins; a model that is refused, rate-limited, down or malformed hands over
to the next. Only an invalid key (401) or an account without credit (402) stops the chain.
`benchmark()` (CLI `ai-benchmark`) times every candidate model on a small structured task."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Optional

import requests

from . import config
from .config import USER_AGENT


def available() -> bool:
    return bool(config.OPENCODE_API_KEY)


class AuthError(RuntimeError):
    """The key itself is unusable (401/402): no model will work."""


class ModelError(RuntimeError):
    """This model could not answer; the next one in the chain may."""


# OpenCode routes requests by session; one id per pipeline run keeps prompt-cache reuse across calls.
SESSION_ID = os.environ.get("OPENCODE_SESSION_ID") or f"electionpredictions-{uuid.uuid4()}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.OPENCODE_API_KEY}", "Content-Type": "application/json", "User-Agent": USER_AGENT,
            "x-opencode-session": SESSION_ID}


def _post(path: str, body: dict, timeout: int = 300) -> requests.Response:
    return requests.post(f"{config.AI_BASE_URL.rstrip('/')}/{path.lstrip('/')}", json=body, timeout=timeout, headers=_headers())


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
    """Pull the first JSON object out of a model reply (tolerates code fences, preamble and think blocks)."""
    text = re.sub(r"<think>.*?</think>", "", text.strip(), flags=re.S).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        out = json.loads(text)
        if isinstance(out, dict):
            return out
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    depth = 0
    in_str = esc = False
    for i in range(max(start, 0), len(text)):
        ch = text[i]
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("no JSON object in response")


def complete(system: str, user: str, model: str, retries: int = 3, max_tokens: int = 4000, timeout: int = 300) -> str:
    """One model, both endpoint shapes. Raises AuthError (key unusable) or ModelError (try another model)."""
    attempts = [
        # reasoning models spend part of the cap thinking before the JSON, so leave generous room
        ("chat/completions", {"model": model, "temperature": 0.2, "max_tokens": max_tokens,
                              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}),
        ("responses", {"model": model, "instructions": system, "max_output_tokens": max_tokens, "input": [{"role": "user", "content": user}]}),
    ]
    if model.startswith("muse-spark"):
        attempts.reverse()  # served through the Responses API on OpenCode Zen
    problems = []
    for path, body in attempts:
        for attempt in range(retries):
            try:
                r = _post(path, body, timeout=timeout)
            except requests.RequestException as e:
                problems.append(f"{path}: {e.__class__.__name__}")
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 401:
                raise AuthError(f"OpenCode rejected the API key (HTTP 401): {r.text[:200]}")
            if r.status_code == 402:
                raise AuthError(f"OpenCode account has no credit (HTTP 402): {r.text[:200]}")
            if r.status_code == 400 and "temperature" in r.text.lower() and "temperature" in body:
                body = {k: v for k, v in body.items() if k != "temperature"}   # some models accept only their default
                problems.append(f"{path}: retrying without temperature")
                continue
            if r.status_code in (403, 404, 405) or (r.status_code == 400 and ("endpoint" in r.text.lower() or "model" in r.text.lower())):
                problems.append(f"{path}: HTTP {r.status_code}: {r.text[:160]}")
                break  # per-model or per-endpoint refusal: try the other shape, then the next model
            if r.status_code == 429 or r.status_code >= 500:
                problems.append(f"{path}: HTTP {r.status_code}")
                time.sleep(5 * (attempt + 1))
                continue
            if not r.ok:
                problems.append(f"{path}: HTTP {r.status_code}: {r.text[:160]}")
                break
            try:
                text = _extract_text(r.json())
            except ValueError:
                text = ""
            if not text:
                problems.append(f"{path}: empty response")
                continue
            return text
    if problems and all("subscription is required" in p for p in problems):
        raise AuthError("OpenCode Go subscription is not active: " + problems[0])
    raise ModelError(f"{model}: " + " | ".join(problems[-4:]))


def ask_json_with(system: str, user: str, models: list[str], max_tokens: int = 4000, timeout: int = 300) -> tuple[dict, str]:
    """Try each model in turn; returns (parsed JSON, model that answered)."""
    errors = []
    for model in models:
        try:
            text = complete(system, user, model, max_tokens=max_tokens, timeout=timeout)
            try:
                return parse_json(text), model
            except (ValueError, json.JSONDecodeError):
                text = complete(system, user + "\n\nYour previous reply was not valid JSON. Reply with the JSON object only.", model,
                                max_tokens=max_tokens, timeout=timeout)
                return parse_json(text), model
        except AuthError:
            raise
        except (ModelError, ValueError, json.JSONDecodeError) as e:
            errors.append(f"{model}: {str(e)[:200]}")
            continue
    raise RuntimeError("no model answered: " + " || ".join(errors))


def ask_json(system: str, user: str, max_tokens: int = 4000, models: Optional[list[str]] = None) -> dict:
    return ask_json_with(system, user, models or config.AI_MODELS_NARRATIVE, max_tokens=max_tokens)[0]


# ---------------------------------------------------------------------------- diagnostics
def probe() -> dict:
    """One tiny request to the first model of each chain, plus the gateway's model list."""
    out = {"base_url": config.AI_BASE_URL, "key_present": bool(config.OPENCODE_API_KEY), "session": SESSION_ID,
           "revision_chain": config.AI_MODELS_REVISION, "narrative_chain": config.AI_MODELS_NARRATIVE}
    for label, model in (("revision", config.AI_MODELS_REVISION[0]), ("narrative", config.AI_MODELS_NARRATIVE[0])):
        try:
            out[label] = {"model": model, "text": complete("Reply with the single word OK.", "Say OK.", model, retries=1, max_tokens=400)[:60]}
        except Exception as e:  # noqa: BLE001
            out[label] = {"model": model, "error": str(e)[:300]}
    try:
        r = requests.get(f"{config.AI_BASE_URL.rstrip('/')}/models", timeout=60, headers=_headers())
        out["models"] = [m.get("id") for m in (r.json().get("data") or [])] if r.ok else r.status_code
    except Exception as e:  # noqa: BLE001
        out["models"] = repr(e)
    return out


BENCH_SYSTEM = """You are the chief modeler of a nonpartisan 2028 U.S. presidential forecast. Rebuild the specification from
the evidence. Return ONLY a JSON object: {"title": string, "summary": string (2 sentences), "reasons": {path: string},
"spec": {"national": {"adjustment": number}, "nominees": {"D": [{"name": string, "p": number, "effect": number}],
"R": [{"name": string, "p": number, "effect": number}]}}}. Odds per party must sum to 1 and include "Other"."""
BENCH_USER = json.dumps({
    "current_spec": {"national": {"adjustment": 0.0},
                     "nominees": {"D": [{"name": "Gavin Newsom", "p": 0.3, "effect": 0.4}, {"name": "Kamala Harris", "p": 0.3, "effect": 0.0},
                                        {"name": "Other", "p": 0.4, "effect": 0}],
                                  "R": [{"name": "JD Vance", "p": 0.5, "effect": -0.7}, {"name": "Other", "p": 0.5, "effect": 0}]}},
    "evidence": {"primary_average_D": {"Kamala Harris": 26, "Gavin Newsom": 15, "Pete Buttigieg": 12},
                 "primary_average_R": {"JD Vance": 38, "Marco Rubio": 22},
                 "headlines": ["Harris tells donors she is weighing a 2028 run", "Rubio says he is focused on his State Department job"],
                 "national_polls": [{"dem": "Gavin Newsom", "rep": "JD Vance", "margin": 3}, {"dem": "Kamala Harris", "rep": "JD Vance", "margin": 4}]},
})


def benchmark(models: list[str], max_tokens: int = 6000) -> list[dict]:
    """Time each model on a small spec-revision task and check the reply is usable."""
    out = []
    for m in models:
        t0 = time.time()
        row = {"model": m}
        try:
            text = complete(BENCH_SYSTEM, BENCH_USER, m, retries=1, max_tokens=max_tokens, timeout=240)
            row["seconds"] = round(time.time() - t0, 1)
            d = parse_json(text)
            spec = d.get("spec") or {}
            noms = spec.get("nominees") or {}
            sums = {p: round(sum(float(c.get("p", 0)) for c in noms.get(p, [])), 3) for p in ("D", "R")}
            row.update(ok=bool(d.get("title") and d.get("summary") and noms.get("D") and noms.get("R")), sums=sums,
                       title=str(d.get("title"))[:90], chars=len(text))
        except Exception as e:  # noqa: BLE001
            row.update(ok=False, seconds=round(time.time() - t0, 1), error=str(e)[:200])
        out.append(row)
        print(json.dumps(row), flush=True)
    return out
