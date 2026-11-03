"""The language-model interface, plus two implementations.

The rest of the pipeline only knows the tiny `LanguageModel` contract:
    model.name                 -> a label written into the output, e.g. "ollama:qwen2.5:3b"
    model.complete(system, user) -> the model's reply as text (we ask for JSON)

Why an interface: the pipeline code does not change when the model changes. Swap Ollama for a hosted
API (or a bank-approved internal model) by writing one new small class.

    OllamaModel : a model running on THIS computer through the free Ollama app. Nothing leaves the machine.
    StubModel   : a fake, rule-based "model" used for tests and demos. It is NOT intelligent and its
                  results say nothing about how a real model will perform.

Only the Python standard library is used here (urllib), so no new dependency is added.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Protocol

DEFAULT_MODEL = "qwen2.5:3b"
DEFAULT_HOST = "http://localhost:11434"


class ModelUnavailable(RuntimeError):
    """Raised when the model cannot be reached. The message tells the user how to fix it."""


class LanguageModel(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


class OllamaModel:
    """Talks to a local Ollama server over HTTP (POST /api/chat)."""

    def __init__(self, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST, timeout: int = 600):
        self.model, self.host, self.timeout = model, host.rstrip("/"), timeout
        self.name = f"ollama:{model}"

    def _request(self, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.host + path, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def check(self) -> None:
        """Fail early, with a plain-English fix, if Ollama is not running or the model is not downloaded."""
        try:
            tags = self._request("/api/tags")
        except (urllib.error.URLError, OSError) as e:
            raise ModelUnavailable(
                f"Cannot reach Ollama at {self.host} ({e}). Install it from https://ollama.com, start it, "
                f"then run:  ollama pull {self.model}") from e
        have = {m.get("name", "") for m in tags.get("models", [])}
        if not any(h == self.model or h.split(":")[0] == self.model for h in have):
            raise ModelUnavailable(f"Ollama is running but model {self.model!r} is not downloaded. "
                                   f"Run:  ollama pull {self.model}   (downloaded now: {sorted(have) or 'none'})")

    def complete(self, system: str, user: str) -> str:
        reply = self._request("/api/chat", {
            "model": self.model, "stream": False, "format": "json",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            # temperature 0 and a fixed seed: the most repeatable behaviour a model offers
            "options": {"temperature": 0, "seed": 0, "num_ctx": 4096},
        })
        return reply["message"]["content"]


class StubModel:
    """A deterministic fake used by tests and demos. It answers by simple word rules.

    mode="good"   : behaves sensibly.
    mode="invent" : deliberately makes things up, to prove the guardrails in enrich.py reject them.
    """

    SYNONYMS = {
        "cyber": ("cyber", "hack", "breach", "ransom", "attack"),
        "climate": ("carbon", "climate", "emission", "greenhouse"),
        "geopolitical": ("geopolit", "sanction", "tariff", "conflict"),
        "regulatory": ("regulat", "fine", "complian", "legislat", "bribery", "corruption"),
        "supply_chain": ("supplier", "supply", "material"),
        "market": ("market", "demand", "competit", "price"),
        "financial": ("interest", "currency", "liquidity", "credit", "inflation"),
        "operational": ("injur", "safety", "execution", "production", "workforce"),
    }
    ACTION_WORDS = ("manage", "mitigat", "reduce", "control", "monitor", "prevent", "safeguard", "hedg")

    def __init__(self, mode: str = "good"):
        self.mode, self.name, self.calls = mode, f"stub:{mode}", 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        task = re.search(r"TASK:\s*(\w+)", user).group(1)
        text = user.split("TEXT:", 1)[-1].strip()
        sents = re.split(r"(?<=[.!?])\s+", text)
        if task == "category":
            low = text.lower()
            for cat, words in self.SYNONYMS.items():
                if any(w in low for w in words):
                    return json.dumps({"category": cat, "confidence": "medium", "reason": "stub keyword match"})
            return json.dumps({"category": "other", "confidence": "low", "reason": "stub found nothing"})
        if task == "summary":
            if self.mode == "invent":
                return json.dumps({"summary": "Vestas lost 4.2 billion euros after a Brazilian court ruling in 2031."})
            return json.dumps({"summary": " ".join(sents[:2])})
        if task == "mitigation":
            if self.mode == "invent":
                return json.dumps({"mitigation_present": True, "quote": "The company hedges all exposure with insurance."})
            for s in sents:   # crude: a sentence in which "we" take an action
                if re.search(r"\bwe\b", s.lower()) and any(w in s.lower() for w in self.ACTION_WORDS):
                    return json.dumps({"mitigation_present": True, "quote": s})
            return json.dumps({"mitigation_present": False, "quote": None})
        raise ValueError(f"unknown task {task!r}")
