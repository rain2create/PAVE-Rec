# TODO and Active Planning

This directory contains implementation planning and unresolved discussion
items. It is intentionally separate from `docs/`, which contains stable module
references and the current research design.

Current files:

- `implementation_roadmap.md`: high-level phased delivery plan.
- `phase_1_discussion.md`: ordered Phase 1 decision checklist.
- `phase_2_discussion.md`: ordered Phase 2 data and Store decision checklist.
- `phase_3_discussion.md`: ordered real Cheap Path, User Memory, and SASRec
  decision checklist.
- `phase_4_discussion.md`: ordered real active perception, selected raw-frame Evidence,
  native-frame MLLM Reranker, and later ≤1B Segment Selector decision checklist.
- `benchmark_construction_proposal.md`: non-normative cross-phase proposal for
  sequential, Segment Value, auxiliary, and cross-dataset benchmarks.
- `initial_ranker_experiment_plan.md`: companion plan for the pluggable Initial
  Ranker boundary, dataset-specific SASRec training, later BERT4Rec/GRU4Rec
  experiments, and Segment Value compatibility.

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
