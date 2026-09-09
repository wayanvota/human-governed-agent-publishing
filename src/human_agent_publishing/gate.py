"""Fail-closed verification for an editorial release packet."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any


class GateError(RuntimeError):
    """Raised when a packet cannot proceed to a publishing adapter."""


PRIMARY_FILES = {
    "artifact_sha256": "artifact.md",
    "metadata_sha256": "metadata.json",
    "sources_sha256": "records/sources.json",
    "entities_sha256": "records/entities.json",
    "policy_sha256": "policy.json",
    "prompt_manifest_sha256": "prompt-manifest.json",
    "runtime_sha256": "runtime.json",
}

CLAIM_PATH = "reviews/claim-check.json"
SKEPTIC_PATH = "reviews/skeptic.json"
FACILITATOR_PATH = "reviews/facilitator-final.json"
DECISION_PATH = "decisions/human-release.json"

PROHIBITED_NAMES = {
    ".env",
    ".env.local",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateError(f"Blocked: {path.name} is not readable JSON.") from error


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GateError(f"Blocked: {label} must be a JSON object.")
    return value


def _exact_keys(record: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(record)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise GateError(
            f"Blocked: {label} fields differ from the schema. "
            f"Missing={missing}; unknown={unknown}."
        )


def _time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise GateError(f"Blocked: {label} timestamp is missing.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GateError(f"Blocked: {label} timestamp is invalid.") from error
    if parsed.tzinfo is None:
        raise GateError(f"Blocked: {label} timestamp lacks a timezone.")
    return parsed


def _inside(root: Path, relative: str, label: str) -> Path:
    candidate = root / relative
    if candidate.is_symlink():
        raise GateError(f"Blocked: {label} is a symlink.")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise GateError(f"Blocked: {label} is missing or outside the packet.") from error
    if not resolved.is_file():
        raise GateError(f"Blocked: {label} is not a file.")
    return resolved


def _scan_packet(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise GateError("Blocked: packet root must be a real directory.")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise GateError(f"Blocked: packet contains symlink {path.relative_to(root)}.")
        if path.name.casefold() in PROHIBITED_NAMES:
            raise GateError(
                f"Blocked: packet contains credential-bearing filename {path.relative_to(root)}."
            )


def _primary_hashes(root: Path) -> dict[str, str]:
    return {
        field: sha256_file(_inside(root, relative, relative))
        for field, relative in PRIMARY_FILES.items()
    }


def _validate_bindings(
    bindings: Any,
    expected: dict[str, str],
    label: str,
) -> None:
    record = _require_object(bindings, f"{label} bindings")
    _exact_keys(record, set(expected), f"{label} bindings")
    for field, digest in expected.items():
        if not isinstance(record[field], str) or not SHA256_RE.fullmatch(record[field]):
            raise GateError(f"Blocked: {label} has an invalid {field}.")
        if record[field] != digest:
            raise GateError(f"Blocked: {field} changed after {label} review.")


def _validate_sources(root: Path, sources: Any) -> set[str]:
    if not isinstance(sources, list) or not sources:
        raise GateError("Blocked: source registry is empty or malformed.")
    ids: set[str] = set()
    fields = {"id", "type", "path", "sha256", "status", "limitations"}
    for index, raw in enumerate(sources, start=1):
        source = _require_object(raw, f"source {index}")
        _exact_keys(source, fields, f"source {index}")
        source_id = source["id"]
        if not isinstance(source_id, str) or not source_id.strip() or source_id in ids:
            raise GateError(f"Blocked: source {index} has a missing or duplicate id.")
        ids.add(source_id)
        if source["status"] != "VERIFIED":
            raise GateError(f"Blocked: source {source_id} is not VERIFIED.")
        evidence = _inside(root, source["path"], f"source {source_id}")
        if source["sha256"] != sha256_file(evidence):
            raise GateError(f"Blocked: source {source_id} evidence changed after registration.")
        if not isinstance(source["limitations"], str):
            raise GateError(f"Blocked: source {source_id} limitations must be text.")
    return ids


def _validate_entities(entities: Any, source_ids: set[str]) -> None:
    if not isinstance(entities, list) or not entities:
        raise GateError("Blocked: entity registry is empty or malformed.")
    fields = {
        "name",
        "kind",
        "role",
        "confidence",
        "source_ids",
        "ambiguity",
        "synthetic",
    }
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(entities, start=1):
        entity = _require_object(raw, f"entity {index}")
        _exact_keys(entity, fields, f"entity {index}")
        key = (str(entity["kind"]), str(entity["name"]).casefold())
        if key in seen or not key[1]:
            raise GateError(f"Blocked: entity {index} has a missing or duplicate identity.")
        seen.add(key)
        if entity["kind"] not in {"PERSON", "ORGANIZATION"}:
            raise GateError(f"Blocked: entity {index} has an invalid kind.")
        if entity["confidence"] not in {"HIGH", "MEDIUM", "LOW"}:
            raise GateError(f"Blocked: entity {index} has an invalid confidence.")
        if entity["confidence"] == "LOW" or str(entity["ambiguity"]).strip():
            raise GateError(f"Blocked: entity {entity['name']} remains unresolved.")
        linked = entity["source_ids"]
        if not isinstance(linked, list) or not linked or any(item not in source_ids for item in linked):
            raise GateError(f"Blocked: entity {entity['name']} has invalid source links.")
        if not isinstance(entity["synthetic"], bool):
            raise GateError(f"Blocked: entity {entity['name']} has invalid synthetic status.")


def _validate_prompt_manifest(root: Path, manifest: Any) -> None:
    record = _require_object(manifest, "prompt manifest")
    _exact_keys(record, {"version", "prompts"}, "prompt manifest")
    prompts = record["prompts"]
    if not isinstance(prompts, list) or len(prompts) != 7:
        raise GateError("Blocked: prompt manifest must bind exactly seven prompts.")
    names: set[str] = set()
    for index, raw in enumerate(prompts, start=1):
        prompt = _require_object(raw, f"prompt {index}")
        _exact_keys(prompt, {"name", "path", "sha256"}, f"prompt {index}")
        if prompt["name"] in names:
            raise GateError(f"Blocked: duplicate prompt name {prompt['name']}.")
        names.add(prompt["name"])
        prompt_path = _inside(root, prompt["path"], f"prompt {prompt['name']}")
        if prompt["sha256"] != sha256_file(prompt_path):
            raise GateError(f"Blocked: prompt {prompt['name']} changed after manifest creation.")


def _validate_runtime(runtime: Any) -> bool:
    record = _require_object(runtime, "runtime manifest")
    fields = {
        "provider",
        "model",
        "model_version",
        "orchestrator_version",
        "tools",
        "generated_at",
        "synthetic_demo",
    }
    _exact_keys(record, fields, "runtime manifest")
    _time(record["generated_at"], "runtime manifest")
    for field in ("provider", "model", "orchestrator_version"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise GateError(f"Blocked: runtime manifest lacks {field}.")
    if record["model_version"] is not None and not isinstance(record["model_version"], str):
        raise GateError("Blocked: runtime model_version must be text or null.")
    if not isinstance(record["tools"], list) or not all(isinstance(item, str) for item in record["tools"]):
        raise GateError("Blocked: runtime tools must be a list of names.")
    if not isinstance(record["synthetic_demo"], bool):
        raise GateError("Blocked: runtime synthetic_demo must be boolean.")
    return record["synthetic_demo"]


def _validate_claim(root: Path, review: Any, primary: dict[str, str]) -> datetime:
    record = _require_object(review, "Claim Checker review")
    fields = {
        "reviewer",
        "decision",
        "reviewed_at",
        "bindings",
        "sources_verified",
        "entities_reconciled",
        "findings",
        "issues",
    }
    _exact_keys(record, fields, "Claim Checker review")
    if record["reviewer"] != "claim-checker" or record["decision"] != "PASS":
        raise GateError("Blocked: Claim Checker did not PASS the package.")
    if record["sources_verified"] is not True or record["entities_reconciled"] is not True:
        raise GateError("Blocked: Claim Checker did not verify sources and entities.")
    if record["issues"] != []:
        raise GateError("Blocked: Claim Checker left unresolved issues.")
    findings = record["findings"]
    if not isinstance(findings, list) or not findings:
        raise GateError("Blocked: Claim Checker recorded no findings.")
    finding_fields = {"claim", "status", "evidence", "notes"}
    for index, raw in enumerate(findings, start=1):
        finding = _require_object(raw, f"claim finding {index}")
        _exact_keys(finding, finding_fields, f"claim finding {index}")
        if finding["status"] != "SUPPORTED":
            raise GateError(f"Blocked: claim finding {index} is unresolved.")
        if not str(finding["claim"]).strip() or not str(finding["evidence"]).strip():
            raise GateError(f"Blocked: claim finding {index} lacks evidence.")
    _validate_bindings(record["bindings"], primary, "Claim Checker")
    return _time(record["reviewed_at"], "Claim Checker")


def _validate_skeptic(
    review: Any,
    primary: dict[str, str],
    claim_path: Path,
    claim_time: datetime,
) -> datetime:
    record = _require_object(review, "Skeptic review")
    fields = {
        "reviewer",
        "decision",
        "reviewed_at",
        "bindings",
        "blocking_issues",
        "required_roles",
        "reason",
        "release_eligible",
    }
    _exact_keys(record, fields, "Skeptic review")
    if record["reviewer"] != "skeptic" or record["decision"] != "APPROVE":
        raise GateError("Blocked: Skeptic did not APPROVE the package.")
    if record["blocking_issues"] != [] or record["required_roles"] != []:
        raise GateError("Blocked: Skeptic requires more work.")
    if record["release_eligible"] is not True or not str(record["reason"]).strip():
        raise GateError("Blocked: Skeptic did not mark the package release-eligible.")
    expected = dict(primary)
    expected["claim_review_sha256"] = sha256_file(claim_path)
    _validate_bindings(record["bindings"], expected, "Skeptic")
    reviewed_at = _time(record["reviewed_at"], "Skeptic")
    if reviewed_at < claim_time:
        raise GateError("Blocked: Skeptic review predates Claim Checker review.")
    return reviewed_at


def _validate_facilitator(
    review: Any,
    primary: dict[str, str],
    claim_path: Path,
    skeptic_path: Path,
    skeptic_time: datetime,
) -> tuple[dict[str, Any], datetime]:
    record = _require_object(review, "Facilitator review")
    fields = {
        "reviewer",
        "stage",
        "decision",
        "reviewed_at",
        "bindings",
        "triggers",
        "human_review_required",
        "reason",
    }
    _exact_keys(record, fields, "Facilitator review")
    if record["reviewer"] != "facilitator" or record["stage"] != "FINAL":
        raise GateError("Blocked: final Facilitator review is missing or invalid.")
    if record["decision"] not in {"AUTONOMOUS", "HUMAN_HOLD"}:
        raise GateError("Blocked: Facilitator decision is invalid.")
    if not isinstance(record["triggers"], list) or not str(record["reason"]).strip():
        raise GateError("Blocked: Facilitator reasoning is malformed.")
    expected = dict(primary)
    expected["claim_review_sha256"] = sha256_file(claim_path)
    expected["skeptic_review_sha256"] = sha256_file(skeptic_path)
    _validate_bindings(record["bindings"], expected, "Facilitator")
    reviewed_at = _time(record["reviewed_at"], "Facilitator")
    if reviewed_at < skeptic_time:
        raise GateError("Blocked: final Facilitator review predates Skeptic review.")
    if record["decision"] == "AUTONOMOUS":
        if record["triggers"] != [] or record["human_review_required"] is not False:
            raise GateError("Blocked: autonomous decision contains a human trigger.")
    elif not record["triggers"] or record["human_review_required"] is not True:
        raise GateError("Blocked: HUMAN_HOLD lacks a recorded trigger.")
    return record, reviewed_at


def _validate_human_release(
    root: Path,
    path: Path,
    facilitator_path: Path,
    facilitator_time: datetime,
    primary: dict[str, str],
) -> None:
    try:
        path.resolve(strict=True).relative_to((root / "decisions").resolve(strict=True))
    except (OSError, ValueError) as error:
        raise GateError("Blocked: human release is outside the protected decisions directory.") from error
    record = _require_object(_load_json(path), "human release")
    fields = {
        "source",
        "decision",
        "response",
        "recorded_at",
        "user_message_sha256",
        "facilitator_review_sha256",
        "artifact_sha256",
        "metadata_sha256",
    }
    _exact_keys(record, fields, "human release")
    if record["source"] != "direct_user_message" or record["decision"] != "PUBLISH":
        raise GateError("Blocked: hold lacks a direct human PUBLISH decision.")
    if not str(record["response"]).strip() or not SHA256_RE.fullmatch(str(record["user_message_sha256"])):
        raise GateError("Blocked: human release lacks the direct message record.")
    if record["facilitator_review_sha256"] != sha256_file(facilitator_path):
        raise GateError("Blocked: human release refers to another Facilitator review.")
    if record["artifact_sha256"] != primary["artifact_sha256"]:
        raise GateError("Blocked: human release refers to another artifact.")
    if record["metadata_sha256"] != primary["metadata_sha256"]:
        raise GateError("Blocked: human release refers to other metadata.")
    if _time(record["recorded_at"], "human release") < facilitator_time:
        raise GateError("Blocked: human release predates the hold.")


def verify_packet(
    packet_root: str | Path,
    *,
    allow_demo: bool = False,
    human_decision: str | Path | None = None,
) -> dict[str, Any]:
    """Verify an exact packet and return a provider-neutral release decision."""

    root = Path(packet_root)
    _scan_packet(root)

    metadata = _require_object(_load_json(_inside(root, "metadata.json", "metadata")), "metadata")
    policy = _require_object(_load_json(_inside(root, "policy.json", "policy")), "policy")
    if policy.get("demo_release_forbidden") is not True:
        raise GateError("Blocked: policy must forbid live demo release.")

    runtime = _load_json(_inside(root, "runtime.json", "runtime manifest"))
    runtime_demo = _validate_runtime(runtime)
    demo = metadata.get("demo") is True or runtime_demo
    if demo and not allow_demo:
        raise GateError("Blocked: synthetic demo packets cannot enter the live release path.")

    sources = _load_json(_inside(root, "records/sources.json", "source registry"))
    source_ids = _validate_sources(root, sources)
    entities = _load_json(_inside(root, "records/entities.json", "entity registry"))
    _validate_entities(entities, source_ids)
    prompt_manifest = _load_json(_inside(root, "prompt-manifest.json", "prompt manifest"))
    _validate_prompt_manifest(root, prompt_manifest)

    primary = _primary_hashes(root)
    claim_path = _inside(root, CLAIM_PATH, "Claim Checker review")
    skeptic_path = _inside(root, SKEPTIC_PATH, "Skeptic review")
    facilitator_path = _inside(root, FACILITATOR_PATH, "Facilitator review")

    claim_time = _validate_claim(root, _load_json(claim_path), primary)
    skeptic_time = _validate_skeptic(
        _load_json(skeptic_path), primary, claim_path, claim_time
    )
    facilitator, facilitator_time = _validate_facilitator(
        _load_json(facilitator_path),
        primary,
        claim_path,
        skeptic_path,
        skeptic_time,
    )

    default_decision = root / DECISION_PATH
    decision_path = Path(human_decision) if human_decision else default_decision
    if facilitator["decision"] == "HUMAN_HOLD":
        if not decision_path.exists():
            raise GateError("Blocked: HUMAN_HOLD requires a direct human release.")
        _validate_human_release(
            root, decision_path, facilitator_path, facilitator_time, primary
        )
    elif decision_path.exists():
        raise GateError("Blocked: autonomous packet includes an unexpected human release.")

    return {
        "status": "DEMO_VERIFIED" if demo else "READY",
        "content_type": metadata.get("content_type"),
        "artifact_sha256": primary["artifact_sha256"],
        "final_decision": facilitator["decision"],
    }

