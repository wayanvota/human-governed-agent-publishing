# Review schemas

These JSON Schemas document the model-produced fields for the three structured review roles and the human release record.

The Python verifier performs its own strict validation, adds exact-file bindings outside the model, and checks review order. Do not rely on model-produced hashes.

- [`claim-review.schema.json`](claim-review.schema.json)
- [`skeptic-review.schema.json`](skeptic-review.schema.json)
- [`facilitator-review.schema.json`](facilitator-review.schema.json)
- [`human-release.schema.json`](human-release.schema.json)

