"""Tier O orchestrator prototype for deskmind#60 (dynamic Workflow orchestration), run on the dyn bench (#62).

A thin layer above the per-step agent: it keeps a living plan of subgoals, runs one subgoal at a time through an
executor (today: `hands do`), detects deviation signals in code, decides at each decision point what to do next
(continue / repair / replan / ask / handoff / stop), asks the user to confirm a plan before its writes and again when a
revised plan adds writes, and journals every plan, decision and question as typed events (schema v1, #62).

It lives in bench until hands has `run_subgoal` (#58); it only shells out to hands and never imports its internals.
"""
