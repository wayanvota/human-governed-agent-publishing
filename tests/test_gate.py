from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from human_agent_publishing.cli import create_demo
from human_agent_publishing.gate import GateError, sha256_file, verify_packet


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


class GateTests(unittest.TestCase):
    def packet(self, root: Path) -> Path:
        packet = root / "packet"
        create_demo(packet, announce=False)
        return packet

    def test_synthetic_demo_verifies_only_when_explicitly_allowed(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.packet(Path(directory))
            with self.assertRaisesRegex(GateError, "synthetic demo"):
                verify_packet(packet)
            result = verify_packet(packet, allow_demo=True)
            self.assertEqual(result["status"], "DEMO_VERIFIED")

    def test_changed_artifact_invalidates_reviews(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.packet(Path(directory))
            (packet / "artifact.md").write_text("Changed after review.\n")
            with self.assertRaisesRegex(GateError, "artifact_sha256 changed"):
                verify_packet(packet, allow_demo=True)

    def test_changed_source_evidence_is_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.packet(Path(directory))
            (packet / "evidence/source-1.md").write_text("Different evidence.\n")
            with self.assertRaisesRegex(GateError, "evidence changed"):
                verify_packet(packet, allow_demo=True)

    def test_changed_prompt_is_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.packet(Path(directory))
            prompt = next((packet / "prompts").glob("*.md"))
            prompt.write_text(prompt.read_text() + "\nChanged.\n")
            with self.assertRaisesRegex(GateError, "prompt .* changed"):
                verify_packet(packet, allow_demo=True)

    def test_unresolved_claim_is_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.packet(Path(directory))
            path = packet / "reviews/claim-check.json"
            review = load(path)
            review["findings"][0]["status"] = "QUALIFY"
            save(path, review)
            with self.assertRaisesRegex(GateError, "claim finding 1 is unresolved"):
                verify_packet(packet, allow_demo=True)

    def test_skeptic_review_must_follow_claim_review(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.packet(Path(directory))
            claim_time = datetime.fromisoformat(load(packet / "reviews/claim-check.json")["reviewed_at"])
            path = packet / "reviews/skeptic.json"
            review = load(path)
            review["reviewed_at"] = (claim_time - timedelta(seconds=1)).isoformat()
            save(path, review)
            with self.assertRaisesRegex(GateError, "predates Claim Checker"):
                verify_packet(packet, allow_demo=True)

    def test_human_hold_blocks_without_release(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.packet(Path(directory))
            path = packet / "reviews/facilitator-final.json"
            review = load(path)
            review["decision"] = "HUMAN_HOLD"
            review["triggers"] = ["INTEREST"]
            review["human_review_required"] = True
            save(path, review)
            with self.assertRaisesRegex(GateError, "requires a direct human release"):
                verify_packet(packet, allow_demo=True)

    def test_direct_human_release_binds_held_package(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.packet(Path(directory))
            facilitator_path = packet / "reviews/facilitator-final.json"
            facilitator = load(facilitator_path)
            facilitator["decision"] = "HUMAN_HOLD"
            facilitator["triggers"] = ["INTEREST"]
            facilitator["human_review_required"] = True
            save(facilitator_path, facilitator)

            message = packet / "decisions/user-message.txt"
            message.parent.mkdir(parents=True)
            message.write_text("PUBLISH the exact reviewed package.\n")
            decision = packet / "decisions/human-release.json"
            save(
                decision,
                {
                    "source": "direct_user_message",
                    "decision": "PUBLISH",
                    "response": message.read_text().strip(),
                    "recorded_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
                    "user_message_sha256": sha256_file(message),
                    "facilitator_review_sha256": sha256_file(facilitator_path),
                    "artifact_sha256": sha256_file(packet / "artifact.md"),
                    "metadata_sha256": sha256_file(packet / "metadata.json"),
                },
            )
            result = verify_packet(packet, allow_demo=True)
            self.assertEqual(result["final_decision"], "HUMAN_HOLD")

    def test_human_release_for_other_artifact_is_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.packet(Path(directory))
            facilitator_path = packet / "reviews/facilitator-final.json"
            facilitator = load(facilitator_path)
            facilitator["decision"] = "HUMAN_HOLD"
            facilitator["triggers"] = ["APPROVAL"]
            facilitator["human_review_required"] = True
            save(facilitator_path, facilitator)
            decision = packet / "decisions/human-release.json"
            save(
                decision,
                {
                    "source": "direct_user_message",
                    "decision": "PUBLISH",
                    "response": "PUBLISH",
                    "recorded_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
                    "user_message_sha256": "1" * 64,
                    "facilitator_review_sha256": sha256_file(facilitator_path),
                    "artifact_sha256": "2" * 64,
                    "metadata_sha256": sha256_file(packet / "metadata.json"),
                },
            )
            with self.assertRaisesRegex(GateError, "another artifact"):
                verify_packet(packet, allow_demo=True)

    def test_credential_bearing_filename_is_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            packet = self.packet(Path(directory))
            (packet / "credentials.json").write_text("{}\n")
            with self.assertRaisesRegex(GateError, "credential-bearing"):
                verify_packet(packet, allow_demo=True)

    def test_symlink_is_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            packet = self.packet(root)
            target = root / "outside.txt"
            target.write_text("outside\n")
            (packet / "outside-link").symlink_to(target)
            with self.assertRaisesRegex(GateError, "symlink"):
                verify_packet(packet, allow_demo=True)


if __name__ == "__main__":
    unittest.main()
