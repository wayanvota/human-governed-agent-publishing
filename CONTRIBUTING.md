# Contributing

Contributions should improve a concrete safeguard, portability, documentation, or test coverage.

Before opening a pull request:

1. Keep examples wholly fictional.
2. Do not add model or CMS credentials.
3. Add a regression test for changed gate behavior.
4. Run `python -m unittest discover -s tests -v`.
5. Explain whether the change weakens, preserves, or strengthens a release invariant.

Changes that allow an agent to bypass a human hold, reuse an approval after package changes, or publish demo content will not be accepted.

