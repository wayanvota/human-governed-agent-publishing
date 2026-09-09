# Repository instructions

This repository is a generic public template. Keep it free of real newsroom packets, private correspondence, credentials, contact lists, unpublished reporting, and publication-specific configuration.

Use only fictional names and `example.invalid` domains in demonstrations and tests.

Preserve these invariants:

- Agent output never directly authorizes publication.
- A hold remains a hold until a direct human decision releases the exact package.
- Any changed artifact, metadata, evidence, prompt, runtime manifest, policy, or review invalidates downstream approval.
- Release verification fails closed.
- Demo content cannot pass the ordinary release path.

Run `python -m unittest discover -s tests -v` after changing Python code or validation behavior.

