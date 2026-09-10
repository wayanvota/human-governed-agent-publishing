from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from human_agent_publishing.cli import ROOT, create_demo
from human_agent_publishing.efficiency import (
    append_usage_record,
    build_usage_record,
    estimate_cost,
    load_compact_context,
    load_routing_config,
    preflight_agent_call,
    resolve_route,
    summarize_usage,
)
from human_agent_publishing.gate import GateError


ROUTING_CONFIG = ROOT / "config/model-routing.openai.example.json"


class RoutingTests(unittest.TestCase):
    def test_low_risk_and_release_gate_routes_differ(self) -> None:
        config = load_routing_config(ROUTING_CONFIG)
        self.assertEqual(resolve_route(config, "monitor").model, "gpt-5.6-luna")
        self.assertEqual(resolve_route(config, "evidence-analyst").model, "gpt-5.6-terra")
        self.assertEqual(resolve_route(config, "claim-checker").model, "gpt-5.5")
        self.assertEqual(resolve_route(config, "skeptic").reasoning_effort, "high")

    def test_explicit_route_override_is_scoped_to_one_call(self) -> None:
        config = load_routing_config(ROUTING_CONFIG)
        route = resolve_route(
            config,
            "monitor",
            model="evaluation-model",
            reasoning_effort="high",
            max_output_tokens=1234,
        )
        self.assertEqual(route.model, "evaluation-model")
        self.assertEqual(route.max_output_tokens, 1234)

    def test_compact_context_combines_common_and_role_files(self) -> None:
        text = load_compact_context(ROOT / "prompts", "entity-resolver")
        self.assertIn("Shared publication context", text)
        self.assertIn("Entity Resolver context", text)
        self.assertNotIn("Human-Governed Agent Publishing", text)


class PreflightTests(unittest.TestCase):
    def packet(self, root: Path) -> Path:
        packet = root / "packet"
        create_demo(packet, announce=False)
        return packet

    def test_each_review_stage_passes_for_exact_demo_packet(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.packet(Path(directory))
            for stage in ("claim-checker", "skeptic", "facilitator-final"):
                result = preflight_agent_call(packet, stage, allow_demo=True)
                self.assertEqual(result["status"], "PREFLIGHT_READY")
                self.assertEqual(result["stage"], stage)

    def test_changed_artifact_stops_before_skeptic_call(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.packet(Path(directory))
            (packet / "artifact.md").write_text("Changed after claim review.\n")
            with self.assertRaisesRegex(GateError, "changed after Claim Checker"):
                preflight_agent_call(packet, "skeptic", allow_demo=True)

    def test_demo_requires_explicit_preflight_permission(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.packet(Path(directory))
            with self.assertRaisesRegex(GateError, "require --allow-demo"):
                preflight_agent_call(packet, "claim-checker")


class UsageTests(unittest.TestCase):
    def test_cost_estimate_separates_token_classes_and_tools(self) -> None:
        config = load_routing_config(ROUTING_CONFIG)
        usage = {
            "input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 200, "cache_write_tokens": 100},
            "output_tokens": 500,
            "output_tokens_details": {"reasoning_tokens": 100},
            "total_tokens": 1500,
        }
        self.assertEqual(
            estimate_cost(
                usage,
                model="gpt-5.6-terra",
                config=config,
                web_search_calls=1,
            ),
            0.01769,
        )

    def test_usage_ledger_appends_and_summarizes_by_role(self) -> None:
        config = load_routing_config(ROUTING_CONFIG)
        monitor = resolve_route(config, "monitor")
        checker = resolve_route(config, "claim-checker")
        usage = {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100}
        with TemporaryDirectory() as directory:
            log = Path(directory) / "usage.jsonl"
            append_usage_record(
                log,
                build_usage_record(
                    role="monitor",
                    route=monitor,
                    response_id="response-1",
                    usage=usage,
                    config=config,
                ),
            )
            append_usage_record(
                log,
                build_usage_record(
                    role="claim-checker",
                    route=checker,
                    response_id="response-2",
                    usage=usage,
                    config=config,
                    decision="PASS",
                    web_search_calls=1,
                ),
            )
            rows = [json.loads(line) for line in log.read_text().splitlines()]
            report = summarize_usage(log)
        self.assertEqual(len(rows), 2)
        self.assertEqual(report["calls"], 2)
        self.assertEqual(report["by_role"]["monitor"]["calls"], 1)
        self.assertEqual(report["by_role"]["claim-checker"]["calls"], 1)


if __name__ == "__main__":
    unittest.main()
