#!/usr/bin/env python3
"""Run Person enrichment Apollo-first through local provider adapters.

Each adapter is an executable command that reads one JSON request from stdin
and writes either a profile object or ``{"profile": {...}}`` to stdout. Later
providers receive the identifiers and fields returned by earlier attempts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from record_enrichment import (
    PROFILE_FIELDS,
    PROVIDER_ORDER,
    ROOT,
    frontmatter,
    minimum_profile,
    record_enrichment,
    record_enrichment_failure,
    validate_enrichment_date,
)
from wiki_pipeline import SGT


Adapter = Callable[[dict[str, Any]], dict[str, Any] | None]
IDENTIFIER_FIELDS = ("displayName", "primaryEmail", "linkedInUrl", "company", "organisation")


def _provider_profile(response: dict[str, Any] | None) -> dict[str, Any]:
    if response is None:
        return {}
    if not isinstance(response, dict):
        raise ValueError("provider response must be an object")
    profile = response.get("profile", response)
    if not isinstance(profile, dict):
        raise ValueError("provider response profile must be an object")
    return {key: value for key, value in profile.items() if key in PROFILE_FIELDS and value not in (None, "", [])}


def run_enrichment(
    person_id: str,
    adapters: Mapping[str, Adapter],
    enrichment_date: str,
    *,
    root: Path = ROOT,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Try configured adapters in the fixed Apollo, Clay, LinkedIn order."""
    validate_enrichment_date(enrichment_date)
    normalised = {name.lower(): adapter for name, adapter in adapters.items()}
    unknown = set(normalised) - set(PROVIDER_ORDER)
    if unknown:
        raise ValueError(f"unsupported provider(s): {', '.join(sorted(unknown))}")
    if "apollo" not in normalised:
        raise ValueError("Apollo adapter is required and must be attempted first")

    path = root / "entities" / "people" / f"{person_id}.md"
    data = frontmatter(path)
    accumulated: dict[str, Any] = {}
    identity = {key: data[key] for key in IDENTIFIER_FIELDS if data.get(key) not in (None, "", [])}
    attempted: list[str] = []
    errors: dict[str, str] = {}

    for provider in PROVIDER_ORDER:
        adapter = normalised.get(provider)
        if adapter is None:
            continue
        attempted.append(provider)
        request = {
            "personId": person_id,
            "provider": provider,
            "identifiers": {**identity, **{key: accumulated[key] for key in IDENTIFIER_FIELDS if key in accumulated}},
            "profile": dict(accumulated),
        }
        try:
            returned = _provider_profile(adapter(request))
        except Exception as error:
            errors[provider] = f"{type(error).__name__}: {error}"
            continue
        accumulated.update(returned)
        if returned and minimum_profile(accumulated):
            result = record_enrichment(
                person_id,
                provider,
                enrichment_date,
                accumulated,
                root=root,
                timestamp=timestamp,
            )
            return {**result, "attemptedProviders": attempted, "providerErrors": errors}

    result = record_enrichment_failure(
        person_id,
        attempted,
        accumulated,
        root=root,
        timestamp=timestamp,
    )
    return {**result, "providerErrors": errors}


def command_adapter(command: str) -> Adapter:
    argv = shlex.split(command)
    if not argv:
        raise ValueError("provider command cannot be empty")

    def call(request: dict[str, Any]) -> dict[str, Any] | None:
        completed = subprocess.run(
            argv,
            input=json.dumps(request),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
            raise RuntimeError(detail)
        output = completed.stdout.strip()
        return json.loads(output) if output else None

    return call


def _commands(items: list[str], parser: argparse.ArgumentParser) -> dict[str, Adapter]:
    result: dict[str, Adapter] = {}
    for item in items:
        if "=" not in item:
            parser.error("--provider-command must be PROVIDER=COMMAND")
        provider, command = item.split("=", 1)
        provider = provider.strip().lower()
        if provider in result:
            parser.error(f"duplicate provider command: {provider}")
        try:
            result[provider] = command_adapter(command)
        except ValueError as error:
            parser.error(str(error))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Person enrichment Apollo-first through local adapters.")
    parser.add_argument("person_id")
    parser.add_argument(
        "--provider-command",
        action="append",
        default=[],
        metavar="PROVIDER=COMMAND",
        help="Adapter command for apollo, clay, or linkedin; repeat for fallbacks",
    )
    parser.add_argument("--date", default=dt.datetime.now(SGT).date().isoformat(), dest="enrichment_date")
    args = parser.parse_args()
    try:
        result = run_enrichment(person_id=args.person_id, adapters=_commands(args.provider_command, parser), enrichment_date=args.enrichment_date)
    except Exception as error:
        print(json.dumps({"status": "failed", "error": f"{type(error).__name__}: {error}"}, indent=2))
        return 1
    print(json.dumps({"status": "ok", **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
