# Cost controls

The safest cost reduction is avoiding model calls that ordinary code can reject first. The next safest is giving each agent only the context its role needs. Model downgrades come after those two changes, and only with role-level quality tests.

## 1. Route by consequence

[`config/model-routing.openai.example.json`](../config/model-routing.openai.example.json) defines one route per role. The defaults use lower-cost models for monitoring and entity resolution, a mid-tier model for evidence development and synthesis, and the strongest configured model for claim checking, adversarial review, and final attention decisions.

```python
from human_agent_publishing.efficiency import load_routing_config, resolve_route

config = load_routing_config("config/model-routing.openai.example.json")
route = resolve_route(config, "skeptic")
```

Treat this as a starting policy. A production adapter should permit a scoped override for a difficult packet without rewriting the global configuration.

Do not route by output length alone. A short legal-risk judgment can deserve more reasoning than a long digest.

## 2. Load only role-specific context

[`prompts/context/common.md`](../prompts/context/common.md) carries the publication-wide rules. Each neighboring role file adds only that role's mandate, exclusions, and expected output.

```python
from human_agent_publishing.efficiency import load_compact_context

instructions = load_compact_context("prompts", "entity-resolver")
```

Put stable instructions before dynamic packet material in the provider request. That ordering makes provider prompt caching more likely to help. Preserve evidence in the packet instead of repeating every source and registry row in every call.

## 3. Reject stale work before calling a model

The preflight check verifies deterministic prerequisites for three expensive stages:

| Before this call | The preflight requires |
| --- | --- |
| Claim Checker | Complete metadata, eligible content, valid evidence and entity records, prompt hashes, runtime manifest, and nonempty primary files |
| Skeptic | Everything above plus a clean Claim Checker pass bound to the current package |
| Final Facilitator | Everything above plus a later Skeptic approval bound to the current package and Claim Checker review |

```python
from human_agent_publishing.efficiency import preflight_agent_call

preflight_agent_call("work/packet-123", "skeptic")
```

Run this immediately before the provider call. Keep the final `verify_packet()` check immediately before any CMS mutation. Preflight saves money; the release verifier protects publication authority.

## 4. Log actual usage

After each provider response, pass its usage object to the ledger helper. Do not ask the model to estimate its own tokens or cost.

```python
from human_agent_publishing.efficiency import (
    append_usage_record,
    build_usage_record,
)

record = build_usage_record(
    role="skeptic",
    route=route,
    response_id=response.id,
    usage=response.usage.model_dump(),
    config=config,
    decision="APPROVE",
    web_search_calls=2,
)
append_usage_record("usage/openai.jsonl", record)
```

The JSON Lines ledger uses append mode and owner-only file permissions when it creates the file. It records no prompt text, article copy, evidence, or credentials. Review the storage policy anyway because provider response identifiers may still be operational metadata.

Generate a compact report with:

```bash
agent-publish cost-report usage/openai.jsonl --month 2026-09
```

Cost values are estimates. Reconcile them against the provider bill, especially after pricing, caching, or tool-fee changes.

## 5. Protect quality with role-level evaluation

Before downgrading a route, replay a representative set of accepted, revised, rejected, sensitive, thin-evidence, and stale-package cases. Compare the candidate model with the current route on:

- unsupported claim detection;
- contradictory evidence detection;
- entity ambiguity and date sensitivity;
- false `PASS` or `APPROVE` decisions;
- correct human-attention holds;
- useful edits retained after human review;
- total cost per accepted packet, including retries.

Optimize for the cost of an accepted, defensible packet. A cheap first call that creates two repair calls has merely moved the invoice around.
