# Testing Strategy

Repository: mlops-sentinel
Last updated: 2026-05-05

## Layers
- Unit tests for deterministic logic.
- Integration tests for boundary behavior.
- End-to-end smoke checks for critical user flows.

## Quality Gates
- Failing tests block merges into main.
- New features include at least one regression test.
- Bug fixes include reproduction coverage where possible.
