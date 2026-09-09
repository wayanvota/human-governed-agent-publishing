# Design review

## Judgment

The architecture is unusually strong where most agent publishing systems are weakest: it separates editorial judgment from release authority and binds approvals to exact files.

That does not make autonomous reporting safe by default. It creates a defensible control structure that a real editor can inspect, test, and stop.

## Strongest design choices

### Deterministic gates sit outside the agents

An agent can recommend `PASS` or `APPROVE`. Ordinary code checks whether that decision has the right schema, inputs, order, hashes, and unresolved issues. This prevents a persuasive paragraph from becoming an authorization mechanism.

### The Skeptic can return work

Adversarial review has operational authority. `REVISE` identifies upstream roles and blocks downstream work. A critic that cannot stop anything is decorative furniture.

### Human attention is screened twice

Discovery screening limits wasted autonomous work on sensitive or angle-dependent subjects. Final screening catches risks and surprising implications that appear only after reporting.

### Exact-file binding controls drift

Separate hashes for copy, metadata, evidence, entities, images, policy, and reviews stop a familiar failure: approving one package and publishing a cousin of it.

### Release includes read-back

Creating a draft or receiving a successful API response does not prove that the intended public page exists. Authenticated and anonymous verification, plus cautious rollback, closes that gap.

## Weak joints to address

### Prompt and model provenance need equal weight

Hashing article files while leaving prompt versions, model identifiers, tool configuration, or provider response IDs outside the approval boundary creates an incomplete audit trail. This template adds prompt and runtime manifests to the required package.

### Tool use is weaker evidence than source verification

A completed search call proves that a tool ran. It does not prove every citation was opened, interpreted correctly, or checked against the exact claim. Claim findings still require inspectable evidence and human spot checks.

### Agent independence can be overstated

Seven named roles do not create seven independent minds. Shared models, prompts, sources, and context can produce correlated errors. Use distinct roles for accountability and workflow clarity, then test disagreement rather than assuming it.

### Manual record exports can drift

Canonical source and entity registries are valuable, but manual exports can become stale between review and release. Production systems should use content-addressed snapshots or transactional exports.

### Human-message hashes are not identity signatures

A hash proves the message bytes did not change. It does not prove who authored the message. Protected storage and authenticated capture remain necessary. Higher-risk systems should sign approval events.

### CMS coupling limits reuse

Publication-specific metadata, media rules, and API behavior belong in adapters. The core should stop at a provider-neutral `READY` decision.

## Recommended implementation sequence

1. Start with agent prompts and human-only publication.
2. Add structured claim and Skeptic reviews.
3. Add exact package hashes and deterministic verification.
4. Add the two attention screens and protected human decisions.
5. Add draft creation and authenticated read-back.
6. Add public verification and durable receipts.
7. Consider narrow automatic release only after adversarial tests repeatedly fail closed.

The hard part is not generating prose. The hard part is proving which prose, evidence, policy, and decision reached the Publish button together.

