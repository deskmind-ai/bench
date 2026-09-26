# Reference results · diag suite

Generated from `reference.json`. Real macOS desktop (Finder, TextEdit, Safari), 13 tasks × 3 runs, projection layer on.
A cell is *passes / scored runs* for that task; runs that ended in an environment error are not scored and are shown as `+n env`.
Compare numbers only within one harness version (see [versions.md](versions.md)).

## Summary

| harness | config | system | strict pass | env errors | partial | false DONE | step p50 / p95 |
|---|---|---|---|---|---|---|---|
| v21 | router-v7b | DeskMind Brain two-tier router (0.8B → 4B), revision v7b | 32/39 (82%) | 0 | 0.86 | 2 | 3.26 / 5.55 s |
| v20 | jev | Jev (TypeSafe AI), hosted System One API (cloud reference) | 33/39 (85%) | 0 | 0.88 | 0 | 0.37 / 0.45 s |
| v20 | router-v7 | DeskMind Brain two-tier router (0.8B → 4B), revision v7 | 29/39 (74%) | 0 | 0.77 | 3 | 3.17 / 7.28 s |
| v19 | router-v7 | DeskMind Brain two-tier router (0.8B → 4B), revision v7 | 30/39 (77%) | 0 | 0.82 | 2 | 3.64 / 5.09 s |
| v19 | g11b-4B | DeskMind Brain 4B checkpoint g11b, two-stage serving | 27/39 (69%) | 0 | 0.69 | 3 | 3.36 / 7.56 s |
| v19 | g10b-4B | DeskMind Brain 4B checkpoint g10b, two-stage serving | 24/39 (62%) | 4 | 0.69 | 7 | – |
| v19 | jev | Jev (TypeSafe AI), hosted System One API (cloud reference) | 31/37 (84%) | 2 | 0.85 | 2 | 0.98 / 1.26 s |

## Per task

| task | v21 router-v7b | v20 jev | v20 router-v7 | v19 router-v7 | v19 g11b-4B | v19 g10b-4B | v19 jev |
|---|---|---|---|---|---|---|---|
| G01-finder-sort | 3/3 | 3/3 | 3/3 | 1/3 | 0/3 | 3/3 | 3/3 |
| G02-textedit-edit | 3/3 | 3/3 | 0/3 | 3/3 | 0/3 | 3/3 | 1/3 |
| G03-safari-extract | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| G04-chinese-exact | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| G05-ambiguity-ask | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/1 +2 env |
| G06-wrong-target | 2/3 | 3/3 | 2/3 | 2/3 | 3/3 | 0/3 | 3/3 |
| G07-finder-newfolder | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| G08-finder-move-one | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| G09-finder-navigate-down | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | 3/3 |
| G10-finder-navigate-up | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 +1 env | 3/3 |
| G11-long-scroll | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 +1 env | 3/3 |
| G12-cancel-midway | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 +1 env | 3/3 |
| G13-roundtrip | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 +1 env | 3/3 |
| **all** | **32/39** | **33/39** | **29/39** | **30/39** | **27/39** | **24/39** | **31/37** |

Notes:

- v19 g10b-4B: assembled from three rounds: one repeat, two repeats, and a rerun of G10-G13 whose round-one runs ended in environment errors; step latency is not pooled across rounds.
- v19 jev: G05: two of three runs ended in environment errors and are excluded from the score.
- Step latency is the planner's time per decision, measured by the harness; the local configs ran on an Apple M4 Pro (48 GB).
- `false DONE`: the planner declared the task done while the grader disagreed.
