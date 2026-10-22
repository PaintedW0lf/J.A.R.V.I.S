"""Swappable AI provider.

Works with:
  * Anthropic Messages API  (provider="anthropic")  POST {base_url}/v1/messages
  * OpenAI-style gateways    (provider="openai")     POST {base_url}/chat/completions
IBM Consulting Advantage (ICA) gateways expose one of these two styles; copy the
base URL, model name and key from the ICA API page into Jarvis settings.
"""
import json
import re

import httpx

from .config import get_secret, settings


class AIError(Exception):
    pass


def configured():
    s = settings()["ai"]
    return bool(get_secret("ai_key") and s.get("base_url") and s.get("model"))


def _headers(cfg, key):
    h = {"content-type": "application/json"}
    if cfg["provider"] == "anthropic":
        h["anthropic-version"] = "2023-06-01"
        if cfg.get("auth") == "bearer":
            h["authorization"] = f"Bearer {key}"
        else:
            h["x-api-key"] = key
    else:
        h["authorization"] = f"Bearer {key}"
    return h


def complete(system, messages, max_tokens=1200, temperature=0.3):
    """messages: list of {"role": "user"|"assistant", "content": str}. Returns text."""
    cfg = settings()["ai"]
    key = get_secret("ai_key")
    if not configured():
        raise AIError("AI is not set up. Add your ICA or Anthropic key in Settings.")
    base = cfg["base_url"].rstrip("/")
    if cfg["provider"] == "anthropic":
        url = base if base.endswith("/messages") else (base + ("/messages" if base.endswith("/v1") else "/v1/messages"))
        body = {"model": cfg["model"], "max_tokens": max_tokens, "temperature": temperature,
                "system": system, "messages": messages}
    else:
        url = base if base.endswith("/completions") else base + "/chat/completions"
        body = {"model": cfg["model"], "max_tokens": max_tokens, "temperature": temperature,
                "messages": [{"role": "system", "content": system}] + messages}
    try:
        r = httpx.post(url, headers=_headers(cfg, key), json=body, timeout=90)
    except httpx.HTTPError as e:
        raise AIError(f"Couldn't reach the AI service at {base}: {e}") from e
    if r.status_code == 401 or r.status_code == 403:
        raise AIError("The AI service rejected the key. Check the key and auth style in Settings.")
    if r.status_code >= 400:
        raise AIError(f"AI service error {r.status_code}: {r.text[:300]}")
    data = r.json()
    if cfg["provider"] == "anthropic":
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
    return (data["choices"][0]["message"].get("content") or "").strip()


def complete_json(system, prompt, max_tokens=2000):
    """Ask for JSON and parse it, tolerating code fences and stray prose."""
    text = complete(system + "\nRespond with valid JSON only, no prose, no code fences.",
                    [{"role": "user", "content": prompt}], max_tokens=max_tokens, temperature=0)
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        raise AIError("The AI didn't return JSON.")
    return json.loads(m.group(1))


def test():
    return complete("You are a connection test.", [{"role": "user", "content": "Reply with the word ready."}], max_tokens=10)
