# Architecture Decision Records

Repository: mlops-sentinel
Last reviewed: 2026-05-05

## ADR-001: Documentation-First Maintenance
Decision:
- Operational documents are added before broad refactors.

Rationale:
- Reduces onboarding friction and preserves project intent.

Consequences:
- Contributors get clearer context before implementation changes.

## ADR-002: Small, Verifiable Changes
Decision:
- Prefer small, focused commits that can be validated quickly.

Rationale:
- Improves rollback safety and review quality.

Consequences:
- Slightly higher commit volume, but better traceability.
