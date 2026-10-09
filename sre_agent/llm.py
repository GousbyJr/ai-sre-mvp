"""Optional LLM layer. Returns None when no key / SDK / parseable output, so the agent degrades to rules."""
from __future__ import annotations

import json
import os
import re
from typing import Optional


def ask_json(system: str, user: str, max_tokens: int = 2500) -> Optional[dict]:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=os.getenv("SRE_MODEL", "claude-sonnet-5-5"),
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        return json.loads(text)
    except Exception:
        return None
