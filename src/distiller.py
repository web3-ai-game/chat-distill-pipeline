#!/usr/bin/env python3
"""
AI Distiller - summarize and extract key knowledge from parsed documents.
Supports Gemini (free) and Grok (paid) as backends.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import requests


class Distiller:
    """AI-powered document distillation."""

    PROVIDERS = {
        "gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "model": "gemini-2.0-flash",
            "cost_input": 0.0,   # Free tier
            "cost_output": 0.0,
            "max_tokens": 4000,
            "max_input_chars": 15000,
        },
        "grok": {
            "base_url": "https://api.x.ai/v1",
            "model": "grok-4-0709",
            # Pricing from local docs (USD per 1M tokens); override in config if needed.
            "cost_input": 3.0,
            "cost_output": 15.0,
            "max_tokens": 3000,
            "max_input_chars": 12000,
        },
    }

    SYSTEM_PROMPT = """You are a knowledge distillation expert. Your job is to extract and compress 
the essential knowledge from documents into structured, actionable summaries and vector-ready signals.

Rules:
- Be factual, concise, and structured
- Preserve key data points, numbers, and specific details
- Remove filler, repetition, and formatting noise
- Output pure JSON, no markdown wrapping
- Use the document's original language for the summary
- Apply low-temperature shearing: keep high-confidence useful signals only
- Ignore exaggerated, explicit, or clearly non-actionable noise when extracting vectors"""

    def __init__(self, provider: str = "gemini", api_key: Optional[str] = None,
                 config: Optional[dict] = None):
        if provider not in self.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")

        self.provider = provider
        self.runtime_config = config or {}
        provider_overrides = self.runtime_config.get(provider, {})
        self.provider_config = {**self.PROVIDERS[provider], **provider_overrides}
        self.model = self.provider_config["model"]
        self.temperature = float(
            self.provider_config.get("temperature", self.runtime_config.get("temperature", 0.3))
        )
        self.max_tokens = int(
            self.provider_config.get("max_tokens", self.runtime_config.get("max_tokens", 3000))
        )
        self.max_input_chars = int(
            self.provider_config.get("max_input_chars", self.runtime_config.get("max_input_chars", 12000))
        )
        self.cost_input = float(self.provider_config.get("cost_input", 0.0))
        self.cost_output = float(self.provider_config.get("cost_output", 0.0))
        self.min_content_length = int(self.runtime_config.get("min_content_length", 50))
        self.budget_usd = float(self.runtime_config.get("budget_usd", 0.0) or 0.0)
        self.stop_on_budget = bool(self.runtime_config.get("stop_on_budget", True))
        self.profile = self.runtime_config.get("profile", "default")

        if provider == "gemini":
            self.api_key = (
                api_key
                or os.getenv("GEMINI_API_KEY")
                or os.getenv("GOOGLE_AI_API_KEY")
            )
        elif provider == "grok":
            self.api_key = (
                api_key
                or os.getenv("GROK_API_KEY")
                or os.getenv("XAI_API_KEY")
            )
            # Keep backward compatibility with old env name.
            if self.api_key and not os.getenv("GROK_API_KEY"):
                os.environ["GROK_API_KEY"] = self.api_key

        if not self.api_key:
            raise ValueError(f"No API key for {provider}. Set env var or pass api_key.")

        self.stats = {
            "distilled": 0,
            "skipped": 0,
            "failed": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "stopped_reason": "",
        }

    def _call_gemini(self, prompt: str) -> dict:
        """Call Gemini API."""
        url = (f"{self.provider_config['base_url']}/models/"
               f"{self.model}:generateContent"
               f"?key={self.api_key}")

        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
                "responseMimeType": "application/json",
            },
            "systemInstruction": {
                "parts": [{"text": self.SYSTEM_PROMPT}]
            }
        }

        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        # Extract text
        text = data["candidates"][0]["content"]["parts"][0]["text"]

        # Token usage
        usage = data.get("usageMetadata", {})
        input_tokens = usage.get("promptTokenCount", 0)
        output_tokens = usage.get("candidatesTokenCount", 0)

        return {"text": text, "input_tokens": input_tokens, "output_tokens": output_tokens}

    def _call_grok(self, prompt: str) -> dict:
        """Call Grok (xAI) API - OpenAI compatible."""
        url = f"{self.provider_config['base_url']}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.provider_config.get("force_json", False):
            payload["response_format"] = {"type": "json_object"}

        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        return {"text": text, "input_tokens": input_tokens, "output_tokens": output_tokens}

    def _call_ai(self, prompt: str) -> dict:
        """Route to the appropriate AI provider."""
        if self.provider == "gemini":
            return self._call_gemini(prompt)
        elif self.provider == "grok":
            return self._call_grok(prompt)
        raise ValueError(f"Unknown provider: {self.provider}")

    def _build_prompt(self, entry: dict) -> str:
        """Build distillation prompt for a document."""
        content = entry.get("content", "")
        # Limit content to avoid token limits
        max_chars = self.max_input_chars
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n[... truncated, {len(entry['content'])} chars total]"

        return f"""Distill this document into structured knowledge.

**File**: {entry.get('file_name', 'unknown')}
**Type**: {entry.get('extension', '')}
**Size**: {entry.get('size_bytes', 0)} bytes
**Path**: {entry.get('relative_path', '')}

**Content**:
{content}

**Output JSON format**:
{{
  "title": "Descriptive title for this document",
  "summary": "2-3 sentence summary of the key content",
  "key_points": ["Point 1", "Point 2", "Point 3"],
  "category": "One of: technical, business, personal, reference, creative, data, misc",
  "topics": ["topic1", "topic2"],
  "importance": 1-5,
  "language": "en or zh or th etc",
  "actionable_items": ["Any action items or todos found"],
  "data_points": ["Any specific numbers, dates, or facts worth preserving"],
  "vector_channels": ["persona", "tech_stack", "timeline"],
  "persona_signals": {{
    "traits": ["calm", "direct", "defensive"],
    "style_tags": ["nomad", "builder"],
    "core_values": ["privacy", "execution"]
  }},
  "tech_stack_signals": {{
    "languages": ["go", "typescript"],
    "frameworks": ["next.js", "express"],
    "platforms": ["firebase", "gcp"],
    "security_domains": ["blue-team", "incident-response"],
    "tools": ["github", "notion"]
  }},
  "timeline_signals": [
    {{"date": "2025-11", "event": "Started project X", "confidence": 0.86}}
  ],
  "drop_content": false,
  "drop_reason": ""
}}

Rules:
- importance: 5=critical reference, 4=high value, 3=useful, 2=minor, 1=trivial
- If the content is mostly empty or unreadable, set importance to 1
- Preserve specific data points (numbers, names, dates)
- Keep the summary in the document's original language
- For "vector_channels":
  - include "persona" if there are stable personality/work-style signals
  - include "tech_stack" if there are concrete stack/tools/architecture signals
  - include "timeline" if there are date/event milestones
- For explicit fantasy/rant/noise, set drop_content=true and provide drop_reason
- Keep only high-confidence, defensible signals (low-temp shearing)"""

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimator for budget gating."""
        if not text:
            return 0
        # Mixed zh/en rough average: ~1 token per 3 chars.
        return max(1, len(text) // 3)

    def _estimate_cost_for_entry(self, entry: dict) -> float:
        """Estimate upper-bound cost before sending API call."""
        content = entry.get("content", "")[:self.max_input_chars]
        est_input = self._estimate_tokens(content) + 700  # prompt/system overhead
        est_output = min(self.max_tokens, 900)
        return (
            (est_input / 1_000_000) * self.cost_input
            + (est_output / 1_000_000) * self.cost_output
        )

    def _extract_json_payload(self, text: str) -> str:
        """Extract best-effort JSON payload from model output."""
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

        # Direct hit
        try:
            json.loads(cleaned)
            return cleaned
        except json.JSONDecodeError:
            pass

        # Find first JSON object/array block
        start_candidates = [i for i in [cleaned.find("{"), cleaned.find("[")] if i >= 0]
        if not start_candidates:
            raise json.JSONDecodeError("No JSON object/array start found", cleaned, 0)

        start = min(start_candidates)
        open_char = cleaned[start]
        close_char = "}" if open_char == "{" else "]"
        depth = 0

        for idx in range(start, len(cleaned)):
            ch = cleaned[idx]
            if ch == open_char:
                depth += 1
            elif ch == close_char:
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start:idx + 1]
                    json.loads(candidate)
                    return candidate

        raise json.JSONDecodeError("Incomplete JSON payload", cleaned, start)

    def _normalize_distill_result(self, value: dict, entry: dict) -> dict:
        """Normalize optional fields to a stable schema for downstream exporters."""
        result = dict(value or {})
        result.setdefault("title", entry.get("file_name", "Untitled"))
        result.setdefault("summary", "")
        result.setdefault("key_points", [])
        result.setdefault("category", "misc")
        result.setdefault("topics", [])
        result.setdefault("importance", 1)
        result.setdefault("language", "unknown")
        result.setdefault("actionable_items", [])
        result.setdefault("data_points", [])
        result.setdefault("vector_channels", [])
        result.setdefault("persona_signals", {})
        result.setdefault("tech_stack_signals", {})
        result.setdefault("timeline_signals", [])
        result.setdefault("drop_content", False)
        result.setdefault("drop_reason", "")

        if not isinstance(result["key_points"], list):
            result["key_points"] = [str(result["key_points"])]
        if not isinstance(result["topics"], list):
            result["topics"] = [str(result["topics"])]
        if not isinstance(result["actionable_items"], list):
            result["actionable_items"] = [str(result["actionable_items"])]
        if not isinstance(result["data_points"], list):
            result["data_points"] = [str(result["data_points"])]
        if not isinstance(result["vector_channels"], list):
            result["vector_channels"] = []
        if not isinstance(result["timeline_signals"], list):
            result["timeline_signals"] = []

        return result

    def distill_entry(self, entry: dict, index: int = 0, total: int = 0) -> dict:
        """Distill a single parsed document entry."""
        fname = entry.get("file_name", "unknown")
        content = entry.get("content", "")

        if not content or len(content) < self.min_content_length:
            self.stats["skipped"] += 1
            print(f"  [{index}/{total}] ⏭️  Skip (no content): {fname}")
            return {
                **entry,
                "distilled": False,
                "distill_result": None,
            }

        print(f"  [{index}/{total}] 🧪 Distilling: {fname} ({len(content)} chars)")

        try:
            prompt = self._build_prompt(entry)
            result = self._call_ai(prompt)

            # Update token stats
            self.stats["input_tokens"] += result["input_tokens"]
            self.stats["output_tokens"] += result["output_tokens"]
            cost = (
                (result["input_tokens"] / 1_000_000) * self.cost_input
                + (result["output_tokens"] / 1_000_000) * self.cost_output
            )
            self.stats["cost_usd"] += cost

            # Parse AI response
            payload_text = self._extract_json_payload(result["text"])
            distill_data = json.loads(payload_text)
            if isinstance(distill_data, list):
                distill_data = distill_data[0] if distill_data else {}
            distill_data = self._normalize_distill_result(distill_data, entry)

            if distill_data.get("drop_content"):
                self.stats["skipped"] += 1
                print(f"           ⏭️  Dropped: {distill_data.get('drop_reason', 'filtered')}")
                return {
                    **entry,
                    "distilled": False,
                    "distill_result": distill_data,
                    "distill_tokens": {
                        "input": result["input_tokens"],
                        "output": result["output_tokens"],
                        "cost": cost,
                    },
                    "distill_error": "Dropped by low-temp shearing rule",
                }

            self.stats["distilled"] += 1
            stars = "⭐" * distill_data.get("importance", 0)
            print(f"           {stars} {distill_data.get('title', '')[:60]}")

            return {
                **entry,
                "distilled": True,
                "distill_result": distill_data,
                "distill_tokens": {
                    "input": result["input_tokens"],
                    "output": result["output_tokens"],
                    "cost": cost,
                },
            }

        except json.JSONDecodeError as e:
            self.stats["failed"] += 1
            print(f"           ❌ JSON parse error: {e}")
            return {**entry, "distilled": False, "distill_error": str(e)}

        except Exception as e:
            self.stats["failed"] += 1
            print(f"           ❌ Error: {e}")
            return {**entry, "distilled": False, "distill_error": str(e)}

    def distill_batch(self, entries: list[dict], output_path: Path,
                      delay: float = 1.0, budget_usd: Optional[float] = None,
                      max_documents: Optional[int] = None) -> list[dict]:
        """Distill a batch of parsed entries."""
        results = []
        total = len(entries)
        budget = self.budget_usd if budget_usd is None else float(budget_usd or 0.0)

        print(
            f"\n🧪 Distilling {total} documents with {self.provider} "
            f"({self.model}, temp={self.temperature}, profile={self.profile})"
        )
        if budget > 0:
            print(f"   Budget cap: ${budget:.2f}")

        for i, entry in enumerate(entries, 1):
            if max_documents and len(results) >= max_documents:
                self.stats["stopped_reason"] = f"Reached max_documents={max_documents}"
                print(f"  🛑 Stop: {self.stats['stopped_reason']}")
                break

            if budget > 0 and self.stop_on_budget:
                estimated = self._estimate_cost_for_entry(entry)
                projected = self.stats["cost_usd"] + estimated
                if self.stats["distilled"] > 0 and projected > budget:
                    self.stats["stopped_reason"] = (
                        f"Projected cost ${projected:.4f} exceeds budget ${budget:.2f}"
                    )
                    print(f"  🛑 Stop: {self.stats['stopped_reason']}")
                    break

            result = self.distill_entry(entry, i, total)
            results.append(result)

            # Save incrementally every 20 items
            if i % 20 == 0:
                self._save_results(results, output_path)
                print(f"  💾 Checkpoint saved ({i}/{total})")

            if budget > 0 and self.stop_on_budget and self.stats["cost_usd"] >= budget:
                self.stats["stopped_reason"] = (
                    f"Cost reached budget cap (${self.stats['cost_usd']:.4f} >= ${budget:.2f})"
                )
                print(f"  🛑 Stop: {self.stats['stopped_reason']}")
                break

            if i < total and delay > 0:
                time.sleep(delay)

        # Final save
        self._save_results(results, output_path)
        self._print_stats()

        return results

    def _save_results(self, results: list[dict], output_path: Path):
        """Save results to file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    def _print_stats(self):
        """Print distillation statistics."""
        print(f"\n📊 Distill Stats ({self.provider}):")
        print(f"   Distilled: {self.stats['distilled']}")
        print(f"   Skipped: {self.stats['skipped']}")
        print(f"   Failed: {self.stats['failed']}")
        print(f"   Tokens: {self.stats['input_tokens']:,} in / "
              f"{self.stats['output_tokens']:,} out")
        if self.stats["cost_usd"] > 0:
            print(f"   Cost: ${self.stats['cost_usd']:.4f}")
        if self.stats["stopped_reason"]:
            print(f"   Stopped: {self.stats['stopped_reason']}")
