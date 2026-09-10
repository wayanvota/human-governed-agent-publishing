"""Command-line interface for the publishing release gate."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys

from .efficiency import (
    PREFLIGHT_STAGES,
    ROLES,
    load_routing_config,
    preflight_agent_call,
    resolve_route,
    route_as_dict,
    summarize_usage,
)
from .gate import GateError, PRIMARY_FILES, sha256_file, verify_packet


ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _bindings(packet: Path) -> dict[str, str]:
    return {
        field: sha256_file(packet / relative)
        for field, relative in PRIMARY_FILES.items()
    }


def create_demo(packet: Path, *, announce: bool = True) -> None:
    if packet.exists() and any(packet.iterdir()):
        raise GateError("Blocked: demo destination already contains files.")
    packet.mkdir(parents=True, exist_ok=True)

    evidence = packet / "evidence/source-1.md"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        "# Synthetic source document\n\n"
        "This fictional record says the Northbridge Civic Lab published a plan "
        "to test curbside air-quality sensors for thirty days before deciding "
        "whether to expand the program. No real person, place, or event is represented.\n",
        encoding="utf-8",
    )
    (packet / "artifact.md").write_text(
        "# Fictional sensor test remains a test\n\n"
        "**Synthetic demonstration. Do not publish.**\n\n"
        "The Northbridge Civic Lab published a thirty-day sensor test plan. "
        "The document describes a trial, not evidence that the sensors work.\n",
        encoding="utf-8",
    )
    _write_json(
        packet / "metadata.json",
        {
            "title": "Fictional sensor test remains a test",
            "slug": "fictional-sensor-test",
            "content_type": "reported_article",
            "publication": "Example Civic Review",
            "demo": True,
        },
    )
    shutil.copy2(ROOT / "config/policy.example.json", packet / "policy.json")

    packet_prompts = packet / "prompts"
    packet_prompts.mkdir(exist_ok=True)
    prompt_records = []
    for source in sorted((ROOT / "prompts").glob("*.md")):
        destination = packet_prompts / source.name
        shutil.copy2(source, destination)
        prompt_records.append(
            {
                "name": source.stem,
                "path": f"prompts/{source.name}",
                "sha256": sha256_file(destination),
            }
        )
    _write_json(packet / "prompt-manifest.json", {"version": 1, "prompts": prompt_records})

    now = datetime.now(timezone.utc)
    _write_json(
        packet / "runtime.json",
        {
            "provider": "synthetic-demo",
            "model": "none",
            "model_version": None,
            "orchestrator_version": "0.1.0",
            "tools": [],
            "generated_at": now.isoformat(),
            "synthetic_demo": True,
        },
    )
    _write_json(
        packet / "records/sources.json",
        [
            {
                "id": "DEMO-SOURCE-1",
                "type": "LOCAL_SYNTHETIC_RECORD",
                "path": "evidence/source-1.md",
                "sha256": sha256_file(evidence),
                "status": "VERIFIED",
                "limitations": "Synthetic fixture with no external corroboration.",
            }
        ],
    )
    _write_json(
        packet / "records/entities.json",
        [
            {
                "name": "Northbridge Civic Lab",
                "kind": "ORGANIZATION",
                "role": "Published the fictional test plan",
                "confidence": "HIGH",
                "source_ids": ["DEMO-SOURCE-1"],
                "ambiguity": "",
                "synthetic": True,
            }
        ],
    )

    primary = _bindings(packet)
    claim_path = packet / "reviews/claim-check.json"
    _write_json(
        claim_path,
        {
            "reviewer": "claim-checker",
            "decision": "PASS",
            "reviewed_at": (now + timedelta(seconds=1)).isoformat(),
            "bindings": primary,
            "sources_verified": True,
            "entities_reconciled": True,
            "findings": [
                {
                    "claim": "The fictional lab published a thirty-day test plan.",
                    "status": "SUPPORTED",
                    "evidence": "DEMO-SOURCE-1",
                    "notes": "Synthetic demonstration only.",
                }
            ],
            "issues": [],
        },
    )
    skeptic_path = packet / "reviews/skeptic.json"
    skeptic_bindings = dict(primary)
    skeptic_bindings["claim_review_sha256"] = sha256_file(claim_path)
    _write_json(
        skeptic_path,
        {
            "reviewer": "skeptic",
            "decision": "APPROVE",
            "reviewed_at": (now + timedelta(seconds=2)).isoformat(),
            "bindings": skeptic_bindings,
            "blocking_issues": [],
            "required_roles": [],
            "reason": "The demo makes one narrow claim supported by its synthetic fixture.",
            "release_eligible": True,
        },
    )
    facilitator_bindings = dict(primary)
    facilitator_bindings["claim_review_sha256"] = sha256_file(claim_path)
    facilitator_bindings["skeptic_review_sha256"] = sha256_file(skeptic_path)
    _write_json(
        packet / "reviews/facilitator-final.json",
        {
            "reviewer": "facilitator",
            "stage": "FINAL",
            "decision": "AUTONOMOUS",
            "reviewed_at": (now + timedelta(seconds=3)).isoformat(),
            "bindings": facilitator_bindings,
            "triggers": [],
            "human_review_required": False,
            "reason": "Synthetic demo verification only; live release remains forbidden.",
        },
    )
    if announce:
        print(packet)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    demo = commands.add_parser("demo", help="Create a wholly synthetic packet")
    demo.add_argument("directory", type=Path)

    verify = commands.add_parser("verify", help="Verify an exact release packet")
    verify.add_argument("directory", type=Path)
    verify.add_argument("--allow-demo", action="store_true")
    verify.add_argument("--human-decision", type=Path)

    digest = commands.add_parser("hash", help="Print a file's SHA-256 digest")
    digest.add_argument("file", type=Path)

    preflight = commands.add_parser(
        "preflight", help="Check deterministic prerequisites before a review call"
    )
    preflight.add_argument("directory", type=Path)
    preflight.add_argument("--stage", required=True, choices=sorted(PREFLIGHT_STAGES))
    preflight.add_argument("--allow-demo", action="store_true")

    route = commands.add_parser("route", help="Show the configured route for one role")
    route.add_argument("role", choices=sorted(ROLES))
    route.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config/model-routing.openai.example.json",
    )

    costs = commands.add_parser("cost-report", help="Summarize an append-only usage ledger")
    costs.add_argument("log", type=Path)
    costs.add_argument("--month", help="Filter recorded_at to YYYY-MM")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "demo":
            create_demo(args.directory)
        elif args.command == "hash":
            print(sha256_file(args.file))
        elif args.command == "preflight":
            result = preflight_agent_call(
                args.directory, args.stage, allow_demo=args.allow_demo
            )
            print(json.dumps(result, indent=2))
        elif args.command == "route":
            config = load_routing_config(args.config)
            print(json.dumps(route_as_dict(resolve_route(config, args.role)), indent=2))
        elif args.command == "cost-report":
            print(json.dumps(summarize_usage(args.log, month=args.month), indent=2))
        else:
            result = verify_packet(
                args.directory,
                allow_demo=args.allow_demo,
                human_decision=args.human_decision,
            )
            print(json.dumps(result, indent=2))
    except (GateError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
