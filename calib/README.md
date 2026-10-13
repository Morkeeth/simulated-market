# calib: score a simulated result against what really happened

`make demo` predicts whether a doc change helps, hurts or makes no detectable change. That prediction is SIMULATED. This folder scores it against real outcomes, next to a second arm called **silent_null** that always predicts "no change".

The simulator has earned trust only if it is right more often than silent_null. Until that difference is large enough to test, the verdict is **undetermined**.

## Add a real outcome and score it

```
make demo
python3 -m calib.score --delta runs/delta-<base>-<head>.json \
  --add-base 0/1 --add-head 1/1 --source "I followed both versions on my laptop"
```

`--add-base K/N` means K of N people reached the goal on the published doc. `--add-head K/N` is the same for the patched doc. One person who tried both versions writes `0/1` or `1/1` on each side. A team with real numbers from before and after a docs change writes those counts.

A row needs both sides. One side alone says nothing about direction, so the scorer rejects it rather than reading it as "no change".

To score again without adding a row: `make score DELTA=runs/delta-<base>-<head>.json`.

The private workspace collects observations through one frozen, distinct-person, single-arm cohort and scores that whole cohort as one row. Its embedded result opens that same saved cohort.

The standalone `web/index.html` is a separate offline import reader. It imports existing rows only after a study design is declared; it does not collect sessions. Imports replace the browser-only set, stay separate from workspace records, and retain an explicit design label. Legacy browser-entered rows remain exportable but unscored until classified. Crossover and before/after rows describe different designs and possible biases; the command-line counts above do not establish independence or implement the workspace trial protocol.

## How the verdict works

- Each row has an observed direction: helped, hurt or no change, from comparing the two rates.
- Each arm is **right** on a row when its predicted direction matches. The simulator predicts the delta's direction. Silent_null predicts no change.
- Only rows where exactly one arm is right can separate the two. An exact two-sided sign test runs on those rows, the same test the delta uses on users.
- At least **6** such rows, all on one side, are needed before p can fall below 0.05: 2 x 0.5^6 = 0.03125, while 2 x 0.5^5 = 0.0625. Below that the verdict is **undetermined**, whatever the counts say.
- Otherwise the verdict is **simulator ahead**, **silent_null ahead**, or **tied** when p is not below 0.05.
- The raw leader is picked with a strict greater-than, silent_null first, so equal counts leave silent_null in front.
- The size error (mean absolute error in the goal rate change) always carries the **UNCALIBRATED** badge.

## Files

| File | In git | What it holds |
|---|---|---|
| `score.py` | yes | The scorer. This is the canonical version. |
| `vectors.json` | yes | Worked cases with expected results. `score.py` and `web/score.js` must both match them (`make test`). |
| `outcomes.jsonl` | **no** | Your real outcome rows. They stay on your machine. |
| `scores.jsonl` | **no** | One row per score: delta file, run files, seed, labels, n and verdict. |

An outcome row, one per line:

```
{"base": {"reached": 0, "n": 1}, "head": {"reached": 1, "n": 1},
 "base_doc_sha256": "<from the delta file>", "head_doc_sha256": "<from the delta file>",
 "source": "where this came from", "runner": "optional name"}
```

Rows only count for the delta whose two doc hashes they carry.
