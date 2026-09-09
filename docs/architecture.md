# Architecture

## One workflow, two kinds of work

This pattern separates interpretive editorial work from deterministic release control.

Agents can search, compare, extract, draft, and critique. Their output remains probabilistic. Even a structured response can be confidently wrong.

Ordinary code verifies the facts about the package that software can actually know:

- required files exist;
- hashes match exact bytes;
- reviews occurred in the required order;
- decisions use allowed values;
- unresolved findings block release;
- a held package has a later, direct human release;
- the released artifact is the reviewed artifact.

The verifier cannot establish truth. It can establish that the current package is the same package that passed the required process.

## State model

```text
DISCOVERED
  -> EVIDENCE_TRIAGED
  -> ATTENTION_SCREENED
  -> RESEARCHED
  -> ENTITIES_RESOLVED
  -> DRAFTED
  -> CLAIM_CHECKED
  -> SKEPTIC_APPROVED
  -> FINAL_ATTENTION_SCREENED
  -> RELEASE_VERIFIED
  -> PUBLISHED
  -> PUBLIC_VERIFIED
```

Either attention screen may branch to `HUMAN_HOLD`. A `REVISE` result returns work to the named upstream role. A `REJECT` or human `PASS` ends the item.

Model this as a state machine in the orchestrator. Do not infer state from the presence of a file alone.

## Review graph

Each review binds its inputs with SHA-256 hashes.

- Claim Checker binds the artifact, metadata, evidence registry, entity registry, policy, prompts, and runtime manifest.
- Skeptic binds those files plus the exact Claim Checker record.
- Final Facilitator binds those files plus the exact Skeptic record.
- A human release binds the held Facilitator record and exact artifact package.

The sequence forms a directed review graph. Change an upstream byte and every dependent approval becomes stale.

Hash binding protects integrity, not truth. A perfectly hashed false claim remains false.

## Prompt and runtime provenance

Prompt files and `runtime.json` belong inside the review boundary. The runtime manifest should record:

- provider and model identifiers;
- model snapshot or version when available;
- reasoning and sampling settings;
- orchestrator and schema versions;
- enabled tools;
- whether external search actually ran;
- UTC timestamps and response identifiers;
- prompt hashes.

The template verifier binds the prompt and runtime manifests. Production systems should populate them from the actual API response and tool trace, not from agent self-report.

## Human-attention gate

Many human-in-the-loop systems ask for approval on every item. Humans learn to click through. The attention gate instead screens for conditions where human judgment is unusually valuable or authorization is required.

The default triggers are Approval, Expertise, Variance, and Interest. Adapt them to the publication. A health or legal publication will need stricter subject-specific triggers.

The human decision record should live outside the directory that scheduled agents can write. The template validates record contents, but filesystem separation must be implemented by the deployer.

For stronger assurance, sign human decisions with an identity-backed mechanism. A text file labeled `direct_user_message` is an operational control, not cryptographic proof of identity.

## Source and entity registries

The package carries explicit source and entity records so reviews can test more than prose.

Each source should record its type, provenance, access date, interest or independence, limitations, and local evidence-file hash when applicable. Each entity should record canonical name, relevant role, identifying source, confidence, ambiguity, and why the entity appears.

Registries should be updated before review and reconciled again after the final edit. Database-backed implementations need snapshot or transaction semantics so the reviewed export cannot drift during release.

## CMS adapter contract

The reusable core stops before publication. A CMS adapter should:

1. Receive the exact reviewed package.
2. Call `verify_packet()` immediately before mutation.
3. Create or reuse only an exact matching draft.
4. Read the draft back and compare every material field.
5. Publish only the unchanged draft.
6. Read the public page and media back through an anonymous endpoint.
7. Write a durable success or failure receipt.
8. Roll back only when doing so will not overwrite a concurrent human change.

Idempotency matters. A safe retry should reuse the same exact draft or stop on a conflict.

## Threat model

This pattern addresses accidental drift, skipped review, malformed records, stale approval, unauthorized autonomy, and some prompt-injection paths.

It does not solve:

- false or incomplete source material;
- correlated failure among agents using the same model;
- compromised operator accounts;
- malicious code running with write access to approvals;
- legal review requirements;
- source confidentiality;
- CMS compromise;
- model-provider retention or training policies.

Deployers must match controls to actual harm. A community events digest and an investigative publication should not share the same release authority merely because both can produce Markdown.

