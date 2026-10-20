status: run
<!-- Steer this run from the GitHub app: edit this file on branch harness/voice-concierge-2026-10-20.
     Change the first line to "status: pause" or "status: stop"; write answers to questions under "## Answers".
     The harness pulls before every session; every session reads this file at startup. -->

## Question (C7-05, 2026-10-20) — two step texts I can't meet without you

C7-05 failed verification on two steps. Both conflict with rules only you can change; the review work itself is done.

1. **Step 1 path.** The step wants the diff at `/tmp/voice-concierge/review-C7.diff`. CLAUDE.md and the harness say
   write only in the worktree and `/tmp/harness/voice-concierge/voice-concierge-2026-10-20/` (where it is now, 2595 lines).
   Answer **1a** "OK to write to /tmp/voice-concierge/" or **1b** "amend step 1 to the scratch dir" (you edit the step).
2. **Step 3 grep.** It can never come back empty: it matches its own text and C4-02's step in `feature_list.json`,
   plus `progress.md` and `metrics.jsonl` (all under `.harness`, which I may not edit). The only other hits are the
   fake key C4-02 step 2 requires verbatim (`tests/test_gate.py:12`, `docs/plans/2026-10-20-C4-extraction.md:388`).
   No real secret, IP or hostname anywhere. Answer **2a** "add `':!.harness' ':!tests/test_gate.py'
   ':!docs/plans/2026-10-20-C4-extraction.md'` to the grep" (you edit the step), or **2b** "build the fake key by
   string concatenation in the test and reword the C4 plan" (I do it; C4-02 step 2's verbatim string then no
   longer appears in the test file).

## Answers

- 2026-10-20 (for Michael, by his chat session): **1b** and **2a**. Step 1 now writes to `$HARNESS_SCRATCH/review-C7.diff`;
  step 3's grep now excludes `.harness`, `tests/test_gate.py` and `docs/plans/2026-10-20-C4-extraction.md` (the fake key
  C4-02 requires is fine). Both step texts are edited in feature_list.json. Finish C7-05, then C8. Keep it efficient:
  the portfolio follow-up (VC4–VC5) is queued right after this run.


- 2026-10-20 (for Michael, by his chat session): **Health port: yes, bind it to 127.0.0.1** (`AgentServer(host="127.0.0.1")`),
  test-first, in the next session (alongside C8), and drop MORNING.md's "keep 8081 closed at the firewall" line. The
  other MORNING.md questions (D7–D13) keep their defaults for now.
