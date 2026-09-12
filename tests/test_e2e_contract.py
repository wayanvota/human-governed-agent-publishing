from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EndToEndContract(unittest.TestCase):
    maxDiff = None

    def cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "human_agent_publishing.cli", *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def demo(self, root: Path) -> Path:
        packet = root / "synthetic-packet"
        result = self.cli("demo", str(packet))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()), packet)
        return packet

    def hold(self, packet: Path, *, write_release: bool) -> Path | None:
        facilitator_path = packet / "reviews/facilitator-final.json"
        facilitator = load(facilitator_path)
        facilitator["decision"] = "HUMAN_HOLD"
        facilitator["triggers"] = ["APPROVAL"]
        facilitator["human_review_required"] = True
        facilitator["reason"] = "A fictional editor must release the exact packet."
        save(facilitator_path, facilitator)
        if not write_release:
            return None

        message = packet / "decisions/user-message.txt"
        message.parent.mkdir(parents=True, exist_ok=True)
        message.write_text("PUBLISH this exact fictional package.\n", encoding="utf-8")
        decision = packet / "decisions/human-release.json"
        save(
            decision,
            {
                "source": "direct_user_message",
                "decision": "PUBLISH",
                "response": message.read_text(encoding="utf-8").strip(),
                "recorded_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=1)
                ).isoformat(),
                "user_message_sha256": digest(message),
                "facilitator_review_sha256": digest(facilitator_path),
                "artifact_sha256": digest(packet / "artifact.md"),
                "metadata_sha256": digest(packet / "metadata.json"),
            },
        )
        return decision

    def test_U01_public_cli_help_lists_the_six_supported_commands(self) -> None:
        result = self.cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("demo", "verify", "hash", "preflight", "route", "cost-report"):
            self.assertIn(command, result.stdout)

    def test_U02_demo_command_creates_a_complete_fictional_packet(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            expected = {
                "artifact.md",
                "metadata.json",
                "policy.json",
                "prompt-manifest.json",
                "runtime.json",
                "records/sources.json",
                "records/entities.json",
                "reviews/claim-check.json",
                "reviews/skeptic.json",
                "reviews/facilitator-final.json",
            }
            actual = {
                str(path.relative_to(packet))
                for path in packet.rglob("*")
                if path.is_file()
            }
            self.assertTrue(expected.issubset(actual))
            self.assertTrue(load(packet / "metadata.json")["demo"])

    def test_U03_complete_demo_packet_verifies_through_the_cli(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            result = self.cli("verify", str(packet), "--allow-demo")
            self.assertEqual(result.returncode, 0, result.stderr)
            decision = json.loads(result.stdout)
            self.assertEqual(decision["status"], "DEMO_VERIFIED")
            self.assertEqual(decision["final_decision"], "AUTONOMOUS")

    def test_U04_all_three_review_preflights_accept_the_exact_packet(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            for stage in ("claim-checker", "skeptic", "facilitator-final"):
                with self.subTest(stage=stage):
                    result = self.cli(
                        "preflight", str(packet), "--stage", stage, "--allow-demo"
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)["stage"], stage)

    def test_U05_route_command_resolves_a_role_without_calling_a_provider(self) -> None:
        result = self.cli("route", "claim-checker")
        self.assertEqual(result.returncode, 0, result.stderr)
        route = json.loads(result.stdout)
        self.assertEqual(route["provider"], "openai")
        self.assertGreater(route["max_output_tokens"], 0)

    def test_U06_hash_command_reports_the_exact_artifact_digest(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            artifact = packet / "artifact.md"
            result = self.cli("hash", str(artifact))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), digest(artifact))

    def test_U07_cost_report_summarizes_an_append_only_fixture(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = Path(directory) / "usage.jsonl"
            rows = [
                {
                    "recorded_at": "2026-09-11T12:00:00+00:00",
                    "role": "monitor",
                    "estimated_cost_usd": 0.01,
                },
                {
                    "recorded_at": "2026-09-11T12:01:00+00:00",
                    "role": "skeptic",
                    "estimated_cost_usd": 0.04,
                },
            ]
            ledger.write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )
            result = self.cli("cost-report", str(ledger), "--month", "2026-09")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["calls"], 2)
            self.assertEqual(report["estimated_cost_usd"], 0.05)

    def test_U08_direct_human_release_unlocks_only_the_held_packet(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            decision = self.hold(packet, write_release=True)
            result = self.cli(
                "verify",
                str(packet),
                "--allow-demo",
                "--human-decision",
                str(decision),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["final_decision"], "HUMAN_HOLD")

    def test_U09_second_demo_refuses_to_overwrite_an_existing_packet(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            result = self.cli("demo", str(packet))
            self.assertEqual(result.returncode, 2)
            self.assertIn("already contains files", result.stderr)

    def test_U10_verifier_returns_the_digest_bound_to_the_reviews(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            result = self.cli("verify", str(packet), "--allow-demo")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout)["artifact_sha256"],
                digest(packet / "artifact.md"),
            )

    def test_A01_demo_packet_is_blocked_from_the_live_release_path(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            result = self.cli("verify", str(packet))
            self.assertEqual(result.returncode, 2)
            self.assertIn("cannot enter the live release path", result.stderr)

    def test_A02_artifact_mutation_invalidates_all_downstream_reviews(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            (packet / "artifact.md").write_text("Changed.\n", encoding="utf-8")
            result = self.cli("verify", str(packet), "--allow-demo")
            self.assertEqual(result.returncode, 2)
            self.assertIn("artifact_sha256 changed", result.stderr)

    def test_A03_evidence_mutation_is_detected_before_release(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            (packet / "evidence/source-1.md").write_text(
                "Changed fictional evidence.\n", encoding="utf-8"
            )
            result = self.cli("verify", str(packet), "--allow-demo")
            self.assertEqual(result.returncode, 2)
            self.assertIn("evidence changed", result.stderr)

    def test_A04_prompt_mutation_invalidates_the_prompt_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            prompt = next((packet / "prompts").glob("*.md"))
            prompt.write_text(prompt.read_text(encoding="utf-8") + "Changed.\n")
            result = self.cli("verify", str(packet), "--allow-demo")
            self.assertEqual(result.returncode, 2)
            self.assertIn("changed after manifest creation", result.stderr)

    def test_A05_credential_bearing_filename_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            (packet / ".env.local").write_text("FICTIONAL=value\n", encoding="utf-8")
            result = self.cli("verify", str(packet), "--allow-demo")
            self.assertEqual(result.returncode, 2)
            self.assertIn("credential-bearing filename", result.stderr)

    def test_A06_symlink_inside_the_packet_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            packet = self.demo(root)
            outside = root / "outside.txt"
            outside.write_text("fictional outside record\n", encoding="utf-8")
            (packet / "outside-link").symlink_to(outside)
            result = self.cli("verify", str(packet), "--allow-demo")
            self.assertEqual(result.returncode, 2)
            self.assertIn("contains symlink", result.stderr)

    def test_A07_malformed_metadata_json_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            (packet / "metadata.json").write_text("{not-json\n", encoding="utf-8")
            result = self.cli("verify", str(packet), "--allow-demo")
            self.assertEqual(result.returncode, 2)
            self.assertIn("not readable JSON", result.stderr)

    def test_A08_skeptic_review_cannot_predate_claim_check(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            claim = load(packet / "reviews/claim-check.json")
            skeptic_path = packet / "reviews/skeptic.json"
            skeptic = load(skeptic_path)
            skeptic["reviewed_at"] = (
                datetime.fromisoformat(claim["reviewed_at"]) - timedelta(seconds=1)
            ).isoformat()
            save(skeptic_path, skeptic)
            result = self.cli("verify", str(packet), "--allow-demo")
            self.assertEqual(result.returncode, 2)
            self.assertIn("predates Claim Checker", result.stderr)

    def test_A09_human_hold_never_becomes_consent_by_silence(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.demo(Path(directory))
            self.hold(packet, write_release=False)
            result = self.cli("verify", str(packet), "--allow-demo")
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires a direct human release", result.stderr)

    def test_A10_source_path_cannot_escape_the_packet(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            packet = self.demo(root)
            outside = root / "outside.md"
            outside.write_text("fictional outside source\n", encoding="utf-8")
            registry_path = packet / "records/sources.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry[0]["path"] = "../../outside.md"
            registry[0]["sha256"] = digest(outside)
            save(registry_path, registry)
            result = self.cli("verify", str(packet), "--allow-demo")
            self.assertEqual(result.returncode, 2)
            self.assertIn("outside the packet", result.stderr)


if __name__ == "__main__":
    unittest.main()
