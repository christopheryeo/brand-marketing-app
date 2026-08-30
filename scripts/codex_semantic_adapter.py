#!/usr/bin/env python3
"""Authenticated Codex adapter for one strict semantic-extraction batch."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODEX = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
SCHEMA = ROOT / "schemas" / "semantic-batch-response.schema.json"


def main() -> int:
    request = json.load(sys.stdin)
    prompt = """You are a high-precision business knowledge extractor.

For each supplied email thread representative, extract only information explicitly supported by its subject/content.

Entity definitions:
- marketing-campaign: a named, coordinated marketing effort or distribution programme; not a single email.
- product-service: a named commercial offering, award programme, media package, platform or service.
- project-initiative: a named, time-bounded operational initiative; not routine correspondence.
- sales-opportunity: a specific prospective commercial deal, sponsorship, award package sale or partnership under discussion.
- topic: a stable named business subject useful for retrieval, not a generic word such as email, meeting, company or brand.

Outcome definitions:
- action: an explicit requested or assigned next step.
- commitment: an explicit promise by a participant to do something.
- business-decision: an explicit choice or approval already made.

Rules:
1. Use the sourceLocator exactly as supplied.
2. Copy evidenceText exactly and contiguously from that item's subject or content.
3. Set confidence >= 0.90 only when the type and name/description are unambiguous.
4. Do not infer entities from signatures, disclaimers, quoted boilerplate or generic category words.
5. Deduplicate repeated mentions within an item.
6. Omit items that have neither accepted entities nor outcomes. Return no more than three entities and three outcomes per item.
7. Return JSON only, conforming exactly to the supplied response schema.

Input batch:
""" + json.dumps(request, ensure_ascii=False)
    with tempfile.TemporaryDirectory(prefix="ib-semantic-") as temporary:
        output = Path(temporary) / "result.json"
        command = [
            str(CODEX), "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules",
            "--skip-git-repo-check", "-m", "gpt-5.6-terra", "-s", "read-only",
            "-C", temporary, "--output-schema", str(SCHEMA), "-o", str(output), "-",
        ]
        process = subprocess.run(command, input=prompt, text=True, capture_output=True, timeout=1200, check=False)
        if process.returncode != 0 or not output.exists():
            sys.stderr.write(process.stderr[-4000:] + process.stdout[-4000:])
            return process.returncode or 1
        response = json.loads(output.read_text(encoding="utf-8"))
        json.dump(response, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
