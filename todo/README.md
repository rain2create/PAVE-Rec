# TODO and Active Planning

This directory contains implementation planning and unresolved discussion
items. It is intentionally separate from `docs/`, which contains stable module
references and the current research design.

Current files:

- `implementation_roadmap.md`: high-level phased delivery plan.
- `phase_1_discussion.md`: ordered Phase 1 decision checklist.

When a later phase is about to begin, create a dedicated
`phase_<n>_discussion.md` before implementing that phase. Do not create detailed
decision files for future phases prematurely.

## Status convention

- `Pending`: not yet discussed or confirmed.
- `In Discussion`: currently being evaluated.
- `Confirmed`: explicitly accepted and ready to implement.
- `Deferred`: intentionally left open behind an interface, Mock, or config.
- `Blocked`: cannot proceed without an external prerequisite.

## Working rule

For each item:

1. Review the relevant module documents.
2. Explain the decision boundary and dependencies.
3. Present viable options and trade-offs.
4. Record the user's decision or explicit deferral.
5. Update affected stable documentation.
6. Implement only the confirmed scope.

Research choices must not be inferred from whichever implementation is easiest.
