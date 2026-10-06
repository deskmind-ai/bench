# Reference results · diag suite

Generated from `reference.json`. Real macOS desktop (Finder, TextEdit, Safari), 13 tasks × 3 runs, projection layer on.
A cell is *passes / scored runs* for that task; runs that ended in an environment error are not scored and are shown as `+n env`.
Compare numbers only within one harness version (see [versions.md](versions.md)).

## Summary

| harness | config | system | strict pass | env errors | partial | false DONE | step p50 / p95 |
|---|---|---|---|---|---|---|---|
| v27 | **router-g18b-q8** (current, app 0.5 development build) | DeskMind Brain two-tier router (0.8B → 4B), checkpoint g18b, 8-bit, threshold 0.96 | **39/39 (100%)** | 0 | 1.00 | 0 | 2.28 / 5.62 s |
| v26 | router-g18b-q8 (app 0.4.0) | DeskMind Brain two-tier router (0.8B → 4B), checkpoint g18b, 8-bit, threshold 0.96 | 38/39 (97%) | 0 | 0.97 | 0 | 3.15 / 11.79 s |
| v25 | router-g18b-q8 (app 0.3.x) | DeskMind Brain two-tier router (0.8B → 4B), checkpoint g18b, 8-bit, threshold 0.96 | 39/39 (100%) | 0 | 1.00 | 0 | 2.85 / 9.82 s |
| v25 | router-g14-q8 (previous) | DeskMind Brain two-tier router (0.8B → 4B), 4B checkpoint g14, 8-bit | 36/39 (92%) | 0 | – | 0 | 0.57 / 5.25 s |
| v25 | router-g17-q8 | DeskMind Brain two-tier router (0.8B → 4B), 4B checkpoint g17, 8-bit | 36/39 (92%) | 0 | – | 3 | n/a |
| v23 | router-g14-q8 | DeskMind Brain two-tier router (0.8B → 4B), 4B checkpoint g14, 8-bit | 35/38 (92%) | 1 | – | 0 | 0.59 / 4.60 s |
| v23 | jev | Jev (TypeSafe AI), hosted System One API (cloud reference) | 33/38 (87%) | 1 | – | 2 | 0.36 / 0.44 s |
| v21 | router-v7b | DeskMind Brain two-tier router (0.8B → 4B), revision v7b | 32/39 (82%) | 0 | 0.86 | 2 | 3.26 / 5.55 s |
| v20 | jev | Jev (TypeSafe AI), hosted System One API (cloud reference) | 33/39 (85%) | 0 | 0.88 | 0 | 0.37 / 0.45 s |
| v20 | router-v7 | DeskMind Brain two-tier router (0.8B → 4B), revision v7 | 29/39 (74%) | 0 | 0.77 | 3 | 3.17 / 7.28 s |
| v19 | router-v7 | DeskMind Brain two-tier router (0.8B → 4B), revision v7 | 30/39 (77%) | 0 | 0.82 | 2 | 3.64 / 5.09 s |
| v19 | g11b-4B | DeskMind Brain 4B checkpoint g11b, two-stage serving | 27/39 (69%) | 0 | 0.69 | 3 | 3.36 / 7.56 s |
| v19 | g10b-4B | DeskMind Brain 4B checkpoint g10b, two-stage serving | 24/39 (62%) | 4 | 0.69 | 7 | – |
| v19 | jev | Jev (TypeSafe AI), hosted System One API (cloud reference) | 31/37 (84%) | 2 | 0.85 | 2 | 0.98 / 1.26 s |

## Per task

The other v23 and v25 configs are reported as aggregates only and have no per-task column.

| task | v27 router-g18b-q8 | v26 router-g18b-q8 | v25 router-g18b-q8 | v21 router-v7b | v20 jev | v20 router-v7 | v19 router-v7 | v19 g11b-4B | v19 g10b-4B | v19 jev |
|---|---|---|---|---|---|---|---|---|---|---|
| G01-finder-sort | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 1/3 | 0/3 | 3/3 | 3/3 |
| G02-textedit-edit | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | 3/3 | 0/3 | 3/3 | 1/3 |
| G03-safari-extract | 3/3 | 3/3 | 3/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| G04-chinese-exact | 3/3 | 2/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| G05-ambiguity-ask | 3/3 | 3/3 | 3/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/1 +2 env |
| G06-wrong-target | 3/3 | 3/3 | 3/3 | 2/3 | 3/3 | 2/3 | 2/3 | 3/3 | 0/3 | 3/3 |
| G07-finder-newfolder | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| G08-finder-move-one | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| G09-finder-navigate-down | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | 3/3 |
| G10-finder-navigate-up | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 +1 env | 3/3 |
| G11-long-scroll | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 +1 env | 3/3 |
| G12-cancel-midway | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 +1 env | 3/3 |
| G13-roundtrip | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 +1 env | 3/3 |
| **all** | **39/39** | **38/39** | **39/39** | **32/39** | **33/39** | **29/39** | **30/39** | **27/39** | **24/39** | **31/37** |

Notes:

- v27 router-g18b-q8: Run through a development build of the DeskMind app for 0.5 (deskmind f334e96: public DeskMind Hands 89be730, bench f8e4702, brain 9b5fe73, eyes 86f680e; the check before DONE on, optional notes off). G04 passed 3/3 in 4 steps each (20 on v26): with the document already written and saved, the planner still chose to replace "1,240" with the whole dictated text, which v26's harness spliced into the document; v27 writes it as a rewrite of the field, the field already holds it, the write is refused as nothing changed, and the planner says DONE (hands#9). 160 steps in all against 211 on v26; the lower step p95 comes mostly from G04's long rewrites being gone, not from faster models.
- v26 router-g18b-q8: run through the DeskMind app 0.4.0, the release (public DeskMind Hands 11368c6, the check before DONE on, optional notes off). G04 passed 2/3: the planner alternates between the correct line and a corrupted one and never says DONE, so the result depends on which write is last when the 20-action budget runs out; run 1 ended on the corrupted text. The same loop is in the v25 row below, where all three runs happened to end on the correct text. The cause was found on v27: the harness spliced a REPLACE of "1,240" with the whole text into the document (hands#9).
- v25 router-g18b-q8: run through the DeskMind app 0.3.x (hands 694eb97, optional checks and notes off). G04 passed 3/3, but the planner never said DONE after the goal was reached and each run used its 20-action budget. The run recorded suite hash cce33453b14b: after the graders moved, the hash had stopped covering them; recomputed over the same tasks, fixtures and graders it is 5eec62a0c662.
- v25 router-g14-q8: G03 is the only failing task.
- v25 router-g17-q8: the three false DONEs are on G10; step latency is not comparable (measured while the GPU had other load).
- v23 router-g14-q8 and v23 jev: one G09 run ended in an environment error and is excluded from the score; a rerun of G09 passed 3/3 (not pooled). The two jev false DONEs are on G02.
- v19 g10b-4B: assembled from three rounds: one repeat, two repeats, and a rerun of G10-G13 whose round-one runs ended in environment errors; step latency is not pooled across rounds.
- v19 jev: G05: two of three runs ended in environment errors and are excluded from the score.
- Step latency is the planner's time per decision, measured by the harness; the local configs ran on an Apple M4 Pro (48 GB).
- `false DONE`: the planner declared the task done while the grader disagreed.
