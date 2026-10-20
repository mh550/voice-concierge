## Outcome
The run delivered 31 of 38 features (C1–C6, plus P1). Only 26 are verified and merged, in PRs #2–#5 and the earlier C1 merge. C6's five features pass but are unverified and unmerged. C7 (5 features) and C8 (2 features) were never started. The deadline ended the run at 8.09 h, 38 sessions, $131.59 ($4.24 per passing feature), with 828 tests. The cause was pace, not failure: builds took 8–46 min each and averaged about 15 min, and the plan and review sessions added another 3 h.

## Non-passing features by cause
All 7 non-passing features (C7-01..05, C8-01..02) have cause "not reached", with detail "run ended: deadline".
- None has a progress entry or a final result, because none was attempted.
- This is a pace and scope problem: 38 features did not fit in the time budget.
- No feature was refused or failed.

## Harness behaviour
- **Guards:** repairs, red_unpass, verify_failed, limit_waits and verify_escalations were all 0. That is plausible: every verify returned "hold".
- **Deadline gap:** the log reads "08:13 C6-05 passes=true … 08:13 deadline reached". C6 was left unverified and unmerged, and C6 also holds the privacy and forget-me work. The C1–C5 verifies cost $0.18–$0.36 and took 1–2 min each, so reserving that time would have been cheap.
- **Review cost:** review took $28.38 (21.6% of the run) and plan took $24.54 (18.6%), together 40%. Build took $70.94. C6-05 was itself a review session and found 2 Important issues. Reviews are therefore sometimes worth it, but the cost is uniform.
- **Verify depth:** verify sessions did re-run steps. The C1 verify reported "33 of 33 steps", re-ran check.sh, and read the assertions of each named test. The C2 verify added 26 rows, and the P1 verify re-ran every step. Verify wall time was 56–108 s on Sonnet, so these checks are mostly test reading, not independent end-to-end runs.
- **Summary field:** `tests.start` is 1 (the smoke test). It is not wrong this time.

## Proposed harness changes
1. **Run each milestone's verify and merge before the deadline is allowed to end the run** (driver deadline logic). The driver should stop starting new features when remaining time is less than roughly one feature plus one verify, then verify and merge the last milestone. Evidence: C6 has 5 passing features that are unverified and unmerged, at a verify cost of about $0.30. This has not been proposed in an earlier retro.
2. **Make review conditional or cheaper** (driver config / review prompt). Run one review for each milestone with more than 4 features or a risky area, or use Sonnet for the first pass. Evidence: $28.38 for 9 review sessions. This is the fifth repeat of the proposal from `v2-2026-10-18`, `agent-harness-2026-10-19`, `rane-one-mixxx-2026-10-19` and `portfolio_site-2026-10-20`.
3. **Size the feature list to the time budget at plan or init time** (init prompt). Estimate about 15 min per feature plus overhead, and mark the tail milestones as optional. Evidence: 38 features × the observed average of about 15 min exceeds the 8 h budget. Not proposed before.
