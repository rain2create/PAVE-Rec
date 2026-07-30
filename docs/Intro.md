# PAVE-Rec

**Personalized Active Video Evidence Acquisition for Recommendation**

PAVE-Rec is a modular agentic recommender for personalized, budget-aware
video evidence acquisition.

Instead of exhaustively perceiving every candidate video, a single agent
controller maintains the current recommendation state, identifies missing
decision-relevant information, selects the most valuable unobserved video
segment, acquires structured evidence through an MLLM, and updates the
ranking. The loop stops when the recommendation is sufficiently certain or
the perception budget is exhausted.

The controller orchestrates interchangeable components for user memory,
initial ranking, information-need estimation, segment valuation, perception,
evidence aggregation, score updating, and stopping. These components are
models and services within one agentic decision loop; they are not separate
autonomous agents.
