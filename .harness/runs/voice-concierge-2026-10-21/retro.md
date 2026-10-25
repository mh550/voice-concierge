## Outcome
Delivered. All 22 features across V1–V6 passed, were verified and were merged (PRs #9–#14). Tests went from 940 to 1247. The run cost $80.59 ($3.66 per passing feature) over 6.8 h wall, with 32 sessions and none refused or environmental. Nothing needed a continuation. The previous voice-concierge run cost $163.71 and needed two continuations. Nothing in this run's logs explains the improvement.

## Non-passing features by cause
None. There were no "not done" features. Two non-final events were both recovered:
- V3-03 was un-passed by the red-suite guard at 06:16 ("suite red after the session"). It passed 5 minutes later.
- V2-05 failed its verify re-check ("V2-05 failed the re-check, back in the queue") and passed on the second try. That was model quality, caught by verify.

## Harness behaviour
- **Guards:** `red_unpass` fired once (V3-03) and `verify_failed` once (V2-05). Both were correct and both recovered. There were 0 repairs, 0 limit waits and 0 escalations.
- **Review cost:** review sessions were the second-biggest spend at $22.39, 28% of the run. Each of V1-03, V2-06 and V3's review cost $4.84–$5.01, about the same as a build session. For comparison, verify cost $2.37 in total.
- **Plan sessions:** plan cost $7.03 across 6 milestones.
- **Idle time:** none seen. Driver time was 0.2 h and each merge followed verify within about 3 minutes.
- **Verify:** it uses Sonnet and re-runs `.harness/check.sh`. For example, V1 verify reported "972 tests, exit 0" and V2 reported "1091 tests pass". The V2-05 failure shows it checks real behaviour. I did not compare evidence rows with step counts, because `feature_list.json` has no evidence field and I looked at only 3 `metrics.jsonl` verify rows.
- **Logging:** the ledger records the cost split but not the model split per role.

## Proposed harness changes
1. **Cap or skip the per-milestone review for small milestones** (driver config). Evidence: review was $22.39 of $80.59 here, and V5 and V6 each had only 2 features. Earlier retros proposed this in `v2-2026-10-18`, `agent-harness-2026-10-19`, `rane-one-mixxx-2026-10-19`, `portfolio_site-2026-10-20`, `portfolio_site-2026-10-20-2` and `voice-concierge-2026-10-20`. It has been proposed seven times and is still unfixed.
2. **Run review on Sonnet, or only when the verify diff is large** (driver model routing). Evidence: Sonnet built V4-03 and V5-01 and passed both, and verify on Sonnet costs about $0.30–0.54. Review on Opus costs about 10× that. This overlaps with proposal 1, but it is a cheaper route. No earlier retro proposed it.
3. **Add the per-role model split and the review-to-build ratio to `summary.json`.** Evidence: `by_model` is not broken out by role, so I could not confirm which roles ran on Opus. No earlier retro proposed it. This is low priority.
