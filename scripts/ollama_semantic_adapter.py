#!/usr/bin/env python3
"""Private, localhost-only semantic adapter using the installed Ollama Phi-3 model."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "semantic-batch-response.schema.json").read_text(encoding="utf-8"))


def main() -> int:
    request = json.load(sys.stdin)
    prompt = """Extract high-confidence business knowledge from each email item.
Return only JSON matching the response schema.

Entity types:
- marketing-campaign: named coordinated marketing/distribution effort, not one email
- product-service: named commercial offering, award programme, media package, platform or service
- project-initiative: named time-bounded operational initiative
- sales-opportunity: specific prospective deal, sponsorship, award package sale or partnership
- topic: stable named business subject useful for retrieval, never a generic word

Outcomes:
- action: explicit requested or assigned next step
- commitment: explicit promise to act
- business-decision: explicit choice or approval already made

Rules: preserve sourceLocator exactly; evidenceText must be an exact contiguous excerpt from that item's subject/content; confidence must be at least 0.90 only when unambiguous; ignore signatures, disclaimers, quoted boilerplate and generic words; omit empty results. Return at most the single most important entity and at most the single clearest outcome for each item. Keep names and evidence concise.

INPUT:
""" + json.dumps(request, ensure_ascii=False)
    payload = {
        "model": os.environ.get("IB_OLLAMA_MODEL", "phi3:latest"),
        "prompt": prompt,
        "stream": False,
        "format": SCHEMA,
        "keep_alive": "30m",
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 4096, "seed": 7},
    }
    http_request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(http_request, timeout=600) as response:
            result = json.loads(response.read().decode("utf-8"))
        parsed = json.loads(result["response"])
        json.dump(parsed, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    except Exception as error:
        sys.stderr.write(f"local-ollama-adapter-error: {error}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
