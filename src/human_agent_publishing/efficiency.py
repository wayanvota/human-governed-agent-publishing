"""Cost-aware routing, compact context, and pre-call review checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from . import gate
from .gate import GateError


ROLES = {
    "monitor",
    "evidence-analyst",
    "entity-resolver",
    "claim-checker",
    "digest-editor",
    "skeptic",
    "facilitator",
}
PREFLIGHT_STAGES = {"claim-checker", "skeptic", "facilitator-final"}


@dataclass(frozen=True)
class Route:
    provider: str
    model: str
    reasoning_effort: str
    max_output_tokens: int


def load_routing_config(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        config = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateError(f"Blocked: {source.name} is not readable routing JSON.") from error
    if not isinstance(config, dict) or not isinstance(config.get("routes"), dict):
        raise GateError("Blocked: routing configuration lacks a routes object.")
    if not isinstance(config.get("provider"), str) or not config["provider"].strip():
        raise GateError("Blocked: routing configuration lacks a provider.")
    missing = sorted(ROLES - set(config["routes"]))
    if missing:
        raise GateError(f"Blocked: routing configuration lacks roles {missing}.")
    return config


def resolve_route(
    config: dict[str, Any],
    role: str,
    *,
    model: str | None = None,
    reasoning_effort: str | None = None,
    max_output_tokens: int | None = None,
) -> Route:
    if role not in ROLES:
        raise GateError(f"Blocked: unknown role {role!r}.")
    raw = config["routes"].get(role)
    if not isinstance(raw, dict):
        raise GateError(f"Blocked: route for {role} is malformed.")
    selected_model = model or raw.get("model")
    selected_reasoning = reasoning_effort or raw.get("reasoning_effort")
    selected_max = max_output_tokens or raw.get("max_output_tokens")
    if not isinstance(selected_model, str) or not selected_model.strip():
        raise GateError(f"Blocked: route for {role} lacks a model.")
    if selected_reasoning not in {"none", "low", "medium", "high", "xhigh", "max"}:
        raise GateError(f"Blocked: route for {role} has an invalid reasoning effort.")
    if not isinstance(selected_max, int) or isinstance(selected_max, bool) or selected_max <= 0:
        raise GateError(f"Blocked: route for {role} has an invalid output ceiling.")
    return Route(config["provider"], selected_model, selected_reasoning, selected_max)


def load_compact_context(prompt_root: str | Path, role: str) -> str:
    if role not in ROLES:
        raise GateError(f"Blocked: unknown role {role!r}.")
    root = Path(prompt_root)
    paths = [root / "context/common.md", root / f"context/{role}.md"]
    parts: list[str] = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise GateError(f"Blocked: compact context is unavailable: {path}.")
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise GateError(f"Blocked: compact context is empty: {path}.")
        parts.append(text)
    return "\n\n".join(parts)


def _validate_base_packet(root: Path, *, allow_demo: bool) -> tuple[dict[str, str], bool]:
    gate._scan_packet(root)
    metadata_path = gate._inside(root, "metadata.json", "metadata")
    policy_path = gate._inside(root, "policy.json", "policy")
    metadata = gate._require_object(gate._load_json(metadata_path), "metadata")
    policy = gate._require_object(gate._load_json(policy_path), "policy")
    required_metadata = {"title", "slug", "content_type", "publication"}
    missing = sorted(
        field for field in required_metadata if not str(metadata.get(field, "")).strip()
    )
    if missing:
        raise GateError(f"Blocked by deterministic preflight: metadata lacks {missing}.")
    if metadata["content_type"] not in policy.get("eligible_content", []):
        raise GateError("Blocked by deterministic preflight: content type is not eligible.")
    if policy.get("demo_release_forbidden") is not True:
        raise GateError("Blocked: policy must forbid live demo release.")

    runtime = gate._load_json(gate._inside(root, "runtime.json", "runtime manifest"))
    runtime_demo = gate._validate_runtime(runtime)
    demo = metadata.get("demo") is True or runtime_demo
    if demo and not allow_demo:
        raise GateError("Blocked: synthetic demo packets require --allow-demo.")

    sources = gate._load_json(gate._inside(root, "records/sources.json", "source registry"))
    source_ids = gate._validate_sources(root, sources)
    entities = gate._load_json(gate._inside(root, "records/entities.json", "entity registry"))
    gate._validate_entities(entities, source_ids)
    prompt_manifest = gate._load_json(
        gate._inside(root, "prompt-manifest.json", "prompt manifest")
    )
    gate._validate_prompt_manifest(root, prompt_manifest)
    primary = gate._primary_hashes(root)
    for relative in gate.PRIMARY_FILES.values():
        if gate._inside(root, relative, relative).stat().st_size == 0:
            raise GateError(f"Blocked by deterministic preflight: {relative} is empty.")
    return primary, demo


def preflight_agent_call(
    packet_root: str | Path,
    stage: str,
    *,
    allow_demo: bool = False,
) -> dict[str, Any]:
    """Fail before a costly review call when deterministic prerequisites are stale."""

    if stage not in PREFLIGHT_STAGES:
        raise GateError(f"Blocked: unknown preflight stage {stage!r}.")
    root = Path(packet_root)
    primary, demo = _validate_base_packet(root, allow_demo=allow_demo)

    claim_path: Path | None = None
    claim_time = None
    if stage in {"skeptic", "facilitator-final"}:
        claim_path = gate._inside(root, gate.CLAIM_PATH, "Claim Checker review")
        claim_time = gate._validate_claim(root, gate._load_json(claim_path), primary)

    if stage == "facilitator-final":
        skeptic_path = gate._inside(root, gate.SKEPTIC_PATH, "Skeptic review")
        gate._validate_skeptic(
            gate._load_json(skeptic_path), primary, claim_path, claim_time
        )

    return {
        "status": "PREFLIGHT_READY",
        "stage": stage,
        "demo": demo,
        "artifact_sha256": primary["artifact_sha256"],
    }


def estimate_cost(
    usage: dict[str, Any],
    *,
    model: str,
    config: dict[str, Any],
    web_search_calls: int = 0,
) -> float | None:
    prices = config.get("prices_per_million_tokens", {}).get(model)
    if not isinstance(prices, dict):
        return None
    details = usage.get("input_tokens_details") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    cached = int(details.get("cached_tokens") or 0)
    cache_write = int(details.get("cache_write_tokens") or 0)
    uncached = max(input_tokens - cached - cache_write, 0)
    output = int(usage.get("output_tokens") or 0)
    required_prices = {"input", "cached_input", "cache_write", "output"}
    if not required_prices.issubset(prices):
        return None
    tool_cost = float(config.get("tool_prices_usd", {}).get("web_search_call", 0))
    return round(
        (
            uncached * float(prices["input"])
            + cached * float(prices["cached_input"])
            + cache_write * float(prices["cache_write"])
            + output * float(prices["output"])
        )
        / 1_000_000
        + web_search_calls * tool_cost,
        8,
    )


def build_usage_record(
    *,
    role: str,
    route: Route,
    response_id: str | None,
    usage: dict[str, Any],
    config: dict[str, Any],
    stage: str | None = None,
    decision: str | None = None,
    web_search_calls: int = 0,
) -> dict[str, Any]:
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    cached = int(input_details.get("cached_tokens") or 0)
    cache_write = int(input_details.get("cache_write_tokens") or 0)
    estimated = estimate_cost(
        usage,
        model=route.model,
        config=config,
        web_search_calls=web_search_calls,
    )
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "stage": stage,
        "provider": route.provider,
        "model": route.model,
        "reasoning_effort": route.reasoning_effort,
        "max_output_tokens": route.max_output_tokens,
        "response_id": response_id,
        "decision": decision,
        "input_tokens": input_tokens,
        "uncached_input_tokens": max(input_tokens - cached - cache_write, 0),
        "cached_input_tokens": cached,
        "cache_write_tokens": cache_write,
        "output_tokens": int(usage.get("output_tokens") or 0),
        "reasoning_tokens": int(output_details.get("reasoning_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
        "web_search_calls": web_search_calls,
        "estimated_cost_usd": estimated,
        "pricing_status": "estimated" if estimated is not None else "unknown_model",
        "pricing_as_of": config.get("pricing_as_of"),
    }


def append_usage_record(path: str | Path, record: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, line)
    finally:
        os.close(descriptor)


def summarize_usage(path: str | Path, *, month: str | None = None) -> dict[str, Any]:
    source = Path(path)
    totals: dict[str, dict[str, float | int]] = {}
    calls = 0
    unknown_cost_calls = 0
    estimated_cost = 0.0
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise GateError(f"Blocked: usage log is unavailable: {source}.") from error
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise GateError(f"Blocked: usage log line {number} is invalid JSON.") from error
        if month and not str(record.get("recorded_at", "")).startswith(month + "-"):
            continue
        role = str(record.get("role") or "unknown")
        bucket = totals.setdefault(role, {"calls": 0, "estimated_cost_usd": 0.0})
        bucket["calls"] += 1
        calls += 1
        cost = record.get("estimated_cost_usd")
        if cost is None:
            unknown_cost_calls += 1
        else:
            estimated_cost += float(cost)
            bucket["estimated_cost_usd"] += float(cost)
    for bucket in totals.values():
        bucket["estimated_cost_usd"] = round(float(bucket["estimated_cost_usd"]), 8)
    return {
        "month": month,
        "calls": calls,
        "estimated_cost_usd": round(estimated_cost, 8),
        "unknown_cost_calls": unknown_cost_calls,
        "by_role": totals,
    }


def route_as_dict(route: Route) -> dict[str, Any]:
    return asdict(route)
