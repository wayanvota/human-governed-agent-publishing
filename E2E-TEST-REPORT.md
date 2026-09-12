# Human-Governed Agent Publishing end-to-end test report

## Scope

The harness invokes the installed `agent-publish` boundary to create and verify
a complete fictional packet. It covers deterministic preflight, routing,
hashing, cost reporting, the exact human-release path, and fail-closed release
checks. It uses only fictional content and makes no provider or network calls.

## Required categories

| ID | Category | Expected behavior |
| --- | --- | --- |
| U01 | CLI discovery | Six supported public commands are visible |
| U02 | Demo creation | A complete fictional packet is created |
| U03 | Complete verification | Exact demo packet verifies only with explicit permission |
| U04 | Review preflight | Claim Checker, Skeptic, and final Facilitator are ready in order |
| U05 | Model route | A role resolves without calling a provider |
| U06 | Artifact hash | CLI digest matches the exact artifact bytes |
| U07 | Cost report | Append-only usage fixture is summarized by role and month |
| U08 | Human release | Direct human decision releases only its held packet |
| U09 | Safe creation | Existing packet is never overwritten |
| U10 | Release output | Returned digest remains bound to reviewed content |
| A01 | Demo escape | Demo packet cannot enter the live release path |
| A02 | Artifact mutation | Changed copy invalidates downstream approval |
| A03 | Evidence mutation | Changed source evidence blocks release |
| A04 | Prompt mutation | Changed prompt invalidates its manifest |
| A05 | Credential file | Credential-bearing filename blocks the packet |
| A06 | Symlink | Symlink inside a packet is rejected |
| A07 | Malformed JSON | Invalid metadata fails closed |
| A08 | Review ordering | Skeptic cannot predate Claim Checker |
| A09 | Silent hold | Human hold never becomes consent through silence |
| A10 | Path escape | Source path cannot leave the packet root |

## Run locally

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest tests/test_e2e_contract.py -v
python -m unittest discover -s tests -v
python -m py_compile src/human_agent_publishing/*.py
agent-publish --help
```

## Debug and extend

Run one case by its fully qualified test name. Keep fixture names fictional and
use `example.invalid` for any domains. New product behavior should first receive
one success-path case and then the closest mutation, authority, validation, or
filesystem-abuse case. Do not add network calls or provider credentials to this
suite. Keep all release assertions at the CLI boundary unless a lower-level
unit test is specifically testing one validator.

## Verification record

Status: local verification passed on September 11, 2026. GitHub Actions
verification is pending the branch push.

- 20 of 20 explicit E2E categories passed.
- 39 of 39 total tests passed.
- Python byte-compilation and installed CLI discovery passed.
