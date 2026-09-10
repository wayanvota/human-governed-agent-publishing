# Adaptation guide

## 1. Write the editorial brief first

Define audience, geography or subject scope, evidence hierarchy, prohibited claims, correction policy, publication cadence, and the human who remains accountable.

Bad brief: “Cover important technology news.”

Useful brief: “Cover dated decisions affecting municipal technology procurement. Prefer contracts, agendas, filings, and direct statements. Treat vendor claims as claims. Name people only when they made or materially influenced the decision.”

The agents cannot recover a missing editorial theory by holding more meetings with one another.

## 2. Define authority in machine-readable policy

Copy [`config/policy.example.json`](../config/policy.example.json). Replace its sample content types, sensitive subjects, trigger thresholds, and allowed human decisions.

Keep external actions narrow. Publishing a reported article does not automatically authorize email distribution, source contact, corrections, account changes, purchases, or social posting.

## 3. Edit and version the prompts

Adapt every file in [`prompts/`](../prompts/). Keep role boundaries explicit.

Record prompt hashes in `prompt-manifest.json`. A model response created under one set of instructions should not silently qualify under another.

## 4. Choose an orchestrator

The prompts can run through an API, agent framework, local model runner, or manual copy-and-paste process. The release gate remains provider-neutral.

Require structured output for Claim Checker, Skeptic, and Facilitator records. Validate the response outside the model. Record actual tool use from the provider trace rather than asking the model whether it searched.

Use [`config/model-routing.openai.example.json`](../config/model-routing.openai.example.json) as an optional cost-control example. It routes by editorial consequence, not prestige or prompt length. Replace its models and dated prices with choices validated against your own packets.

Load shared and role-specific instructions from [`prompts/context/`](../prompts/context/) instead of sending the entire workflow to every agent. Run `preflight_agent_call()` immediately before Claim Checker, Skeptic, and final Facilitator calls. Append actual provider usage to a private operational ledger.

The implementation details and evaluation requirements are in [`cost-controls.md`](cost-controls.md).

## 5. Protect the human decision channel

Store human decision records where the unattended process cannot write them. Capture the direct message or approval event, its timestamp, actor identity, and the exact hashes released.

For higher-risk publishing, use signed approvals from an authenticated control plane. Local file permissions alone may be insufficient.

## 6. Build a CMS adapter

Keep the adapter small. It should translate reviewed metadata into CMS fields, verify the draft through an authenticated read-back, publish, then verify the public result anonymously.

Test duplicate slugs, stale drafts, changed media, partial API failures, rate limits, cache delays, and concurrent human edits.

Do not put a model call inside the final release function. Release should be boring. Boring is lovely when the alternative is an autonomous correction notice.

## 7. Add publication-specific tests

At minimum, test that release stops when:

- an artifact changes after review;
- metadata changes after review;
- a source file no longer matches its registry hash;
- Claim Checker has an unresolved finding;
- Skeptic requests rework;
- final review predates Skeptic approval;
- a hold lacks a human release;
- a human release refers to another package;
- prompt or runtime configuration changes;
- a demo packet reaches the live adapter;
- a credential-bearing file appears in the packet;
- a symlink points outside the packet;
- the CMS draft differs from the reviewed package;
- public verification fails;
- rollback would overwrite a concurrent edit.

## 8. Start with draft-only operation

Run the system in observation mode. Compare its packets with human decisions and edits. Then allow draft creation. Consider automatic release only after repeated evidence that the gates fail closed and the public read-back works.

Cadence is never a reason to lower the evidence threshold.
