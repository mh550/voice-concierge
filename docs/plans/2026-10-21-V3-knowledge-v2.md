# V3: knowledge v2 and talking about itself (spec 2026-10-21 §5, §7)

The pack (`knowledge/michael.md`) was built from the portfolio files at `81bb0fc`. Michael's resume v4 and the
site's new angle are newer, and the agent had no words for itself: asked how its memory works, it had nothing to
say, and it was told never to mention "the pack", a word it then used. V3 re-vendors the sources, adds the resume and
a source file about the agent, rebuilds the pack around the new positioning with a spoken section about the agent
itself, rewords the instructions so the word "pack" never reaches a visitor, checks the provider terms, and adds a
drift check for the vendored files. The spec's defaults are taken as written; where a feature's step and the repo
disagree, this plan says which wins (see "Decision numbers").

| Feature | What | Tests |
|---|---|---|
| V3-01 | this plan | none (plan) |
| V3-02 | re-vendor the five files with header lines; `resume-v4.md`, `concierge.md`, `SOURCE.md`; rebuild `knowledge/michael.md` | `tests/test_knowledge.py`, `tests/test_prompt.py` (budget) |
| V3-03 | `concierge/prompt.py` wording; the policy check as D21 in `docs/decisions.md`; one README § Privacy sentence | `tests/test_prompt.py`, `tests/test_readme.py` |
| V3-04 | `scripts/check_sources.py`; MORNING step; D22 *default* | `tests/test_scripts.py`, `tests/test_morning.py` |
| V3-05 | review of the milestone diff, fixes test-first, notes under `## Review` here | as the findings need |

Order: V3-02 → V3-03 (its budget test needs the new pack) → V3-04 (its fixture trees need the headers V3-02 writes)
→ V3-05.

## Re-vendoring the sources (V3-02)

`CLAUDE.md` forbids reading `~/projects/portfolio_site`; the repo is public, so clone it into the scratch directory.

```sh
S="${HARNESS_SCRATCH:-/tmp/harness/voice-concierge/voice-concierge-2026-10-21}"
rm -rf "$S/portfolio_site"
git clone --depth 1 https://github.com/mh550/portfolio_site "$S/portfolio_site"
C=$(git -C "$S/portfolio_site" rev-parse --short=7 HEAD)
D=$(git -C "$S/portfolio_site" log -1 --format=%cs)
for p in Bio.md src/lib/data/profile.ts src/lib/data/experience.ts src/lib/data/projects.ts src/lib/data/skills.ts; do
  b=$(basename "$p")
  case "$b" in
    *.md) h="<!-- vendored from mh550/portfolio_site@$C $p -->" ;;
    *.ts) h="// vendored from mh550/portfolio_site@$C $p" ;;
  esac
  { printf '%s\n' "$h"; cat "$S/portfolio_site/$p"; } > "knowledge/sources/$b"
done
```

- **Header line**, exactly one, first line of each of the five files: `// vendored from mh550/portfolio_site@<commit>
  <path>` in `.ts`, `<!-- vendored from mh550/portfolio_site@<commit> <path> -->` in `.md`. `<commit>` is the 7-character
  short hash, `<path>` the repo path (`Bio.md`, `src/lib/data/projects.ts`, …). The rest of each file is byte for byte
  the clone's. The regex the tests and the drift script share:
  `^(?://|<!--) vendored from mh550/portfolio_site@([0-9a-f]{7,40}) (\S+)(?: -->)?$`.
- **`knowledge/sources/SOURCE.md`** is rewritten to say: copied from `mh550/portfolio_site` at commit `` `<C>` ``
  (`main`, `<D>`), the five paths, each file's first line is a header naming the repo, path and commit; plus the line
  `resume v4 of 2026-10-20, from the spec` (`resume-v4.md`, from `docs/specs/2026-10-21-integrated-concierge.md` §7);
  `concierge.md` (facts about this agent, from this repo's `README.md` and `docs/spec.md` §4.0); and the rule: **where
  the resume and the vendored files differ, the resume wins** (it is newer). It keeps the form
  ``commit `<hex>` `` so `concierge.knowledge.sources_commit` (V2-05) still finds the commit, and it has **exactly one**
  ``commit `<hex>` `` match in the whole file (`test_pack_stats_commit_is_the_one_in_source_md` unpacks one), on the
  fallback path too (``commit `81bb0fc` ``).
- **Fallback if the clone fails** (offline, or GitHub down): leave the five files' contents at `81bb0fc`, still add the
  header lines with `81bb0fc` and their paths (the files are that commit's, unmodified), write in `SOURCE.md` "the
  clone failed on 2026-10-21; the five files stay at `81bb0fc`", and say so in the progress entry.
- **Seen by this session** (2026-10-21, a scratch clone): `main` was `b7c974f` (2026-10-20). Against `81bb0fc`,
  `Bio.md`, `profile.ts`, `experience.ts` and `skills.ts` are identical; `projects.ts` gained a `voice-concierge`
  project and re-ordered four `order:` values. V3-02 clones again and uses whatever `main` is then.
- Nothing from the clone other than these five files enters the repo. The clone stays in scratch.

### `knowledge/sources/resume-v4.md`

The §7 resume text, from `**MICHAEL HERRON**` to the coursework line, with the blockquote `> ` markers removed and
the markdown otherwise as §7 has it, preceded by one line `<!-- resume v4 of 2026-10-20, from
docs/specs/2026-10-21-integrated-concierge.md §7; no phone number, on purpose -->` and followed by the positioning
block from §7's first paragraph (positioning line `Agentic Systems Engineer`, the subline, the tagline), so the
pack's "Positioning and contact" can cite one file. **No phone number**: §7 leaves it out and it never enters the
repo (public). The email, site, GitHub and LinkedIn handle are already published by `profile.ts`.

### `knowledge/sources/concierge.md`

First line: `<!-- Facts about this agent, written from README.md and docs/spec.md §4.0 of mh550/voice-concierge. -->`.
Then a heading `# Voice Concierge (this agent)` (so the pack heading's name appears verbatim in the sources, as
`test_every_name_appears_verbatim_in_the_sources` requires) and short plain sentences, each one traceable to the
repo line in brackets below (the brackets are this plan's, not the file's). The file carries at least the numbers the
pack may cite: **30 days, 10 minutes, 5 sessions a day, 1,500 characters, 1,200 words** (and "LiveKit Agents 1.8",
which the pack need not repeat).

| Fact | Basis |
|---|---|
| A voice agent for Michael's portfolio site that talks about his work and remembers returning visitors; by voice or by typed message, one memory | README l.1–7, l.20–21 |
| Built on LiveKit Agents 1.8 in Python; runs on Michael's home box and connects out to LiveKit Cloud; the memory is one local SQLite file | README l.6–7; spec D3 |
| One thread of memory per visitor; nothing is read or written across threads, so nothing is shared between visitors | spec §4.0 "Memory as an attack surface"; README l.108 |
| Facts sit in a few typed slots (name, role, company, interests, what they asked about, whether they want a follow-up), each kept with where it was learned (voice or text) and when | spec §4.0 "Profile, not collection", "Provenance and confidence"; README l.20–21 |
| A short summary of each visit | README l.33–35 (episodes), l.114 |
| Notes are taken in the background after a turn, never while answering | spec §4.0 "Hot path vs background writes" |
| A correction keeps history: the old fact is marked no longer valid, not overwritten | spec §4.0 "Temporal validity" |
| A write gate refuses instructions, links and secrets; a name is stored only after the visitor confirms it | README l.108; spec §4.0 "ASR errors" |
| "Forget me" on the page erases everything linked to the visitor; a visitor can also ask it to forget one thing | README l.22–24, l.120 |
| A thread idle for 30 days is deleted | spec B6; README l.120 |
| It carries a fixed description of Michael's work, at most 1,200 words, that the provider caches; the visitor's memory is at most 1,500 characters; a small working context is compacted on long calls | spec §4.0 "Context is a budget", "Stable, cached prefix"; spec §4.10 (1,200 words); README l.114 |
| A session ends after 10 minutes at most; a visitor gets 5 sessions a day | README l.188; spec B7 |
| It shows the visitor, on the page, what it remembers and what its memory did | README l.27–36 |
| It can't: chat about general topics, guess numbers, or remember a visitor across browsers (the visitor id is kept in the browser) | README l.16–17, l.166; spec §4.1, l.58 |
| Michael's agent harness built it overnight from a written spec, after the memory design was researched and written down practice by practice | spec l.4, §4.0 (D6); `docs/background/memory-research.md` |

The file must not contain "knowledge pack" or "specs in, verified milestones out", and nothing about providers'
spend, keys, hostnames or the LiveKit project name beyond "LiveKit Cloud".

## The pack's new outline (V3-02)

At most 1,200 words (`tests/test_knowledge.py`), and static + pack at most 3,000 estimated tokens
(`tests/test_prompt.py::test_static_plus_pack_within_budget`, `ceil(chars / 3.5)`). Today the pack is 1,121 words,
7,675 characters (2,193 tokens) and the static instructions 550 tokens: 2,743. V3-03's wording (below) measures 648 tokens of
static text (+98), so **the pack must stay under about 8,230 characters (≈ 2,352 tokens)**. At the pack's 6.85
characters a word that is about 1,200 words: the token cap and the word cap bind together. Target: section bodies as
budgeted below (1,038 words, about 1,146 with headings and `Source:` lines), giving about 2,894 tokens, a margin of
about 100; V3-02 states the measured margin. Every section starts with its heading and a `Source:` line
naming one file (a section with two sources has two `Source:` lines, both within three lines of the heading, as
`test_every_section_names_its_source_within_three_lines` and `test_every_source_line_names_an_existing_source_file`
read them).

| # | Section (heading text exactly) | Source line(s) | Words | Content |
|---|---|---|---|---|
| 0 | `# Michael Herron` | – | 3 | title |
| 1 | `## Positioning and contact` | `resume-v4.md`, `profile.ts` | 70 | "Agentic Systems Engineer"; "I build the harnesses, memory and verification around AI agents, and the integrations they run on."; the tagline; email, LinkedIn and GitHub URLs exactly as `profile.ts` has them (the URL test reads them there); the site as `www.mherron.dev` (the resume wins over `profile.ts`' `siteUrl`); Durham, NC (`profile.ts`) |
| 2 | `## About` | `Bio.md` | 70 | Duke CS; what he builds now (agentic systems, integrations), from the Bio and the resume summary line where the resume wins; the outdoor sports in one clause |
| 3 | `## Experience` | `resume-v4.md`, `experience.ts` | 200 | "Full-Stack Software Engineer at MAXX Potential", February 2026 – present: the three v4 bullets, spoken (one sentence each). "Founding Full-Stack Software Engineer at Builder Clarity", March 2025 – November 2025: the three v4 bullets. Then Tahoma Films and the snowboard coaching, one line each (their facts from `experience.ts`, which is named on a second `Source:` line) |
| 4 | `## Education` | `resume-v4.md` | 35 | "B.S. in Computer Science at Duke University", Visual & Media Studies minor, graduated December 2024; the coursework in one clause |
| 5 | `## Skills` | `resume-v4.md` | 75 | four groups in the resume's order, cased exactly as §7 has them: `Agentic AI`, `Languages & Web`, `Data & Integration`, `Infra & Tools`, each one line |
| 6 | `## Project: Voice Concierge (this agent)` | `concierge.md` | 190 | every row of the concierge.md table above, as spoken sentences (no lists inside the paragraph lines, no file names, no code names) |
| 7 | `## Project: Agent Harness` | `projects.ts`, `resume-v4.md` | 90 | what it is (deterministic Bash harness, Claude Code agents in isolated git worktrees, merges only verified trees), context engineering (fresh context per feature, rules as procedural memory, retros as episodic), runs on his home server, steered from phone; "189 features passed in 4 days at ~$3 each" (resume); dates as the resume has them ("October 2026 - present" wins over `projects.ts`' "Sep – Oct 2026"); the GitHub URL from `projects.ts`. The Oct 17 one-night figures are dropped (the resume's figure is newer) |
| 8 | `## Project: Self-hosted music library & DJ crate pipeline` | `projects.ts` | 65 | refreshed with the resume's two bullets where they differ |
| 9 | `## Project: Linear Adoption + Agentic Bug Workflow` | `projects.ts` | 40 | the outcome only; the MAXX bullet carries the numbers |
| 10 | `## Project: GoHighLevel ↔ JobTread Integration` | `projects.ts` | 40 | the outcome only; the Builder Clarity bullet carries the numbers |
| 11 | `## Project: HitList: offline-first street-spot scouting app` | `projects.ts` | 50 | as now, shortened |
| 12 | `## Project: React Native Paint Estimator` | `projects.ts` | 35 | as now, shortened |
| 13 | `## Project: RingCentral ↔ JobTread Integration` | `projects.ts` | 30 | as now, shortened |
| 14 | `## Project: Mirrored Google Calendars` | `projects.ts` | 25 | as now, shortened |
| 15 | `## Project: Cherished` | `projects.ts` | 20 | as now, shortened |
| | **Total** | | **1,038** | body text only; the 15 headings and about 18 `Source:` lines add about 108 words, which `pack_word_count` counts: **about 1,146 words**, under the 1,200 cap |

Rules for the text:

- The resume wins where it and the vendored files differ (titles, dates, numbers, skills grouping).
- `test_names_are_derived_from_the_pack` needs `MAXX Potential`, `Builder Clarity` and `Duke University` each written
  after "at" (rows 3 and 4 say how); Cherished, today's other "at Duke University", may be cut. Any capitalised word
  after "at" is read as a name ("at Michael's" would need `Michael's` in the sources): avoid such phrasings.
- Every digit-bearing token, every "at <Company>" name, every `## Project:` name and every URL must appear verbatim
  in `knowledge/sources/` (the existing tests read all of `SOURCE_FILES`, which V3-02 extends to seven files). Write
  `concierge.md` and the pack together so the pack's phrasings ("at LiveKit Cloud", "30 days") are in it verbatim.
- No run of 7 or more digits anywhere in the pack; outside `Source:` lines, never "knowledge pack" or "specs in,
  verified milestones out" (case-insensitive). The word "pack" is avoided in the pack's prose altogether.
- Spoken-friendly: short sentences, no parenthesised asides the voice would read badly, "about three dollars" is not
  written for "~$3" (the number test needs the source's form; the model says it aloud).
- `projects.ts` now has its own `voice-concierge` entry; the pack's section about the agent is still built from
  `concierge.md` only (that entry says "live now" and names spend caps; the agent's own section stays with what this
  repo states). V6 adds slugs to the `Source:` lines (`Source: concierge.md (slug: voice-concierge)`); V6 then changes
  the Source-line tests to read the file name before ` (slug:`.

**What is cut if static + pack goes over 3,000 tokens** (V3-02 measures after V3-03's wording is known; if V3-02 lands
first it uses the static text below for the estimate), in this order, re-measuring after each: (1) `Project:
Cherished`, (2) `Project: Mirrored Google Calendars`, (3) `Project: RingCentral ↔ JobTread Integration` (the
Builder Clarity bullet names RingCentral), (4) About trimmed to 45 words, (5) `Project: Linear Adoption + Agentic Bug
Workflow` (the MAXX bullet covers it). The cut sections are named in V3-02's progress entry and under `## Review`.
The Voice Concierge, Agent Harness, Experience and Skills sections are never cut.

### V3-02 as built

- Sources: the clone's `main` was `b7c974f` (2026-10-20); as V3-01 saw, only `projects.ts` differs from `81bb0fc`.
  No fallback was needed.
- Cut, in the order above: (1) `Project: Cherished` and (2) `Project: Mirrored Google Calendars`. The review's fixes
  (what "Forget me" does not erase, the tools that write during a reply, taking a message for Michael) took the pack
  to 1,212 words, over the word cap; the two cuts bring it to 1,166.
- Measured: 1,166 words, 7,645 characters, 2,185 tokens; static + pack 2,735 today and about 2,833 with V3-03's
  wording (+98), a margin of about 167 under 3,000. The Voice Concierge section is about 340 words, 150 over its
  budget of 190, paid for by the shorter project sections and the two cuts.
- The number scan and the retired-word scan skip only `Source: <file>` lines that name a source file (`_prose()`),
  because `Source: resume-v4.md` carries a digit.

## The instructions (V3-03)

`concierge/prompt.py` `STATIC_INSTRUCTIONS`, the changed lines only (everything else stays byte for byte):

| Now | After V3-03 |
|---|---|
| `- Answer questions about Michael only from the knowledge pack below. If the pack doesn't say, reply "I don't know, but you can ask Michael directly"; …` | `- Answer questions about Michael only from what you know about him below. If it doesn't say, reply "I don't know, but you can ask Michael directly"; …` (rest unchanged) |
| `- Never guess numbers, dates or employers. Repeat them exactly as the pack has them, or say you don't know.` | `- Never guess numbers, dates or employers. Repeat them exactly as they are written below, or say you don't know.` |
| `… and say links as plain site names. Never mention the pack or its "Source:" lines.` | `… and say links as plain site names.` (the sentence is removed) |
| (new rule, after the off-topic rule) | `- When asked about yourself, your memory, what you store or how you were built, answer from the "Voice Concierge (this agent)" section as freely and concretely as any other topic; that is on-topic and Michael wants it explained.` |
| (new rule, after the 1–3 sentences rule, its own line) | `- Never use the words "pack", "knowledge pack" or "source lines" with a visitor; say "what I know about Michael" or "my notes".` |
| `- A section of facts from this visitor's earlier visits may follow the pack. …` | `- A section of facts from this visitor's earlier visits may follow what you know about Michael. …` (rest unchanged) |
| `Knowledge pack (the only source of facts about Michael):` | `What you know about Michael (the only source of facts about him):` |

Each rule stays one line of the string (the `\` continuations join the source lines), so the test can drop the
forbidding rule's own line and search the rest. The module docstring and comments may keep "knowledge pack" (they
are not sent); `STATIC_INSTRUCTIONS` may not, outside that one rule. `test_static_instructions_carry_the_anti_goal_rules`
changes its `"only from the knowledge pack"` assertion to `"only from what you know about him below"`.

### V3-03 as built

- The wording is the table's, plus one clause the review asked for: the forbidding rule ends `…or "my notes", and
  never name the files your facts come from.` The removed sentence also covered the pack's `Source: <file>` lines,
  which the new rule's "source lines" alone did not. Static 662 tokens, static + pack 2,846 (margin 154 under 3,000).
- `test_static_instructions_forbid_the_pack_words` scans the built prompt (static + pack) as well as the static text,
  and asserts no `*.md`/`*.ts` file name in the static text.
- The policy check fetched a fourth page: LiveKit's Acceptable Use Policy, which the terms' §7.4.1 incorporates. D21
  also quotes the terms' §2.6.6 (no misleading users about "the agent's artificial nature").
- Known overlap: "my notes" (the step's words for the pack) is also what the greeting and the pack call the visitor's
  memory. Left as the step has it; V4's evals can show whether the agent blurs the two.

## The policy check (V3-03)

Michael asked whether an agent describing its own implementation conflicts with LiveKit's or the providers' terms.
V3-03 fetches each page in the session (WebFetch, or `curl -sL`; public pages, no keys), reads it for any rule on an
agent or application describing its own system, prompts or design, and records:

| Page | URL (status seen by V3-01 on 2026-10-21) |
|---|---|
| LiveKit Agents docs | https://docs.livekit.io/agents/ (200) |
| LiveKit terms of service (covers LiveKit Cloud; `livekit.io/legal/cloud-terms` is a 404 and `livekit.io/legal` redirects here) | https://livekit.io/legal/terms-of-service (200, served from livekit.com) |
| Anthropic usage policy | https://www.anthropic.com/legal/aup (200) |

The entry in `docs/decisions.md` (heading below under "Decision numbers") gives: the question; each URL with the date
2026-10-21; for each page the relevant clause quoted (at most two sentences) or paraphrased, or "no clause on this";
the finding (none is expected: the agent self-hosts its prompt, and describing its own design is the operator's
content, not the provider's confidential material; if the AUP's disclosure rule, that users be told they are talking
to an AI, applies, note that self-description satisfies it); and what remains for Michael. **If a page cannot be
fetched**, the entry names the URL and the error, records the finding as unconfirmed for that page, and adds "Michael
to confirm by reading <URL>" (also as a question in the progress entry). `README.md` § Privacy gains one sentence:
the concierge describes its own memory design and build on request, and that was checked against LiveKit's docs and terms and
Anthropic's usage policy (docs/decisions.md D21). Never "LiveKit Agents" without "1.8" after it in README prose
(`tests/test_readme.py::test_every_mention_of_livekit_agents_outside_the_mapping_says_1_8`).

## The drift check (V3-04)

`scripts/check_sources.py`, stdlib plus `concierge.knowledge` (for `sources_commit`; it runs from the venv),
network only when no `--fetched` is given.

```
python scripts/check_sources.py [--fetched DIR] [--sources DIR]
```

- `--sources DIR`: the vendored files, default `knowledge/sources` under the repo root (found from `__file__`).
- `--fetched DIR`: a flat directory holding the five upstream files by base name (`Bio.md`, `profile.ts`,
  `experience.ts`, `projects.ts`, `skills.ts`), without header lines. Without it the script downloads them with
  `urllib.request.urlopen(url, timeout=10)` from `RAW = "https://raw.githubusercontent.com/mh550/portfolio_site/main/"`
  plus `REMOTE_PATHS = {"Bio.md": "Bio.md", "profile.ts": "src/lib/data/profile.ts", "experience.ts":
  "src/lib/data/experience.ts", "projects.ts": "src/lib/data/projects.ts", "skills.ts": "src/lib/data/skills.ts"}`
  into a `tempfile.TemporaryDirectory()`, then proceeds exactly as with `--fetched`. All network is in one function,
  `fetch(dest: Path) -> None`, the only caller of `urlopen`, which it calls as `urllib.request.urlopen(...)` after
  `import urllib.request` (never `from urllib.request import urlopen`, so the test's monkeypatch reaches it).
- `diff_sources(local: Path, fetched: Path) -> list[str]`: pure; for each name in `REMOTE_PATHS` order, reads the local
  file's bytes, drops the first line when it matches the header regex above (a local file without a header is
  compared whole), compares with the fetched file's bytes, returns the names that differ. A missing file on either
  side raises `FileNotFoundError` naming it.
- Output, stdout: `sources commit: <hex>` (read with `concierge.knowledge.sources_commit` from `<sources>/SOURCE.md`,
  "unknown" if absent), then `drifted: <name>` per drifted file, or `clean: 5 files match main`.
- Exit codes: **0** clean, **1** drift, **2** a fetch failed (`urllib.error.URLError`, `TimeoutError`, an HTTP
  status other than 200) or a file is missing; the reason goes to stderr (`fetch failed: <name>: <error>` or
  `missing: <name>`).
- It never writes into `knowledge/sources/`: it reports, and re-vendoring stays the manual procedure above.

MORNING.md gains step `## 12. Source drift check` (Stop becomes 13): the command
`.venv/bin/python scripts/check_sources.py`; Check: exit 0 and `clean: 5 files match main`, or exit 1 and the
`drifted:` names (then re-vendor as this plan says and rebuild the pack in a session with a review); Undo: none, it
is read-only. Its "Questions for you" gains D22.

## Decision numbers

The spec's text says "a D" for the policy check and the drift check; the feature steps call them `D18` (V3-03) and
`D19 *default*` (V3-04), numbers written before V2 used D18, D19 and D20 (`docs/decisions.md`). Re-using a number would
make two decisions answer to one name (and MORNING's questions refer to D18–D20 already). So:

- V3-03 writes `## D21: describing itself vs the LiveKit and Anthropic terms (2026-10-21, V3-03; the feature's "D18")`.
  It is Michael's question answered with sources, not a default, so it is not `*default*`.
- V3-04 writes `## D22 *default*: a drift check, not an automatic pack rebuild (2026-10-21, V3-04; the feature's "D19
  *default*")`: the pack is prose an LLM writes from the sources; rebuilding it automatically would need a provider
  key at build time and a human or reviewer pass over facts and tone, so the honest tool reports drift and leaves the
  rebuild to a reviewed session. Rejected: a CI job that regenerates the pack; a test that fails on drift (network in
  the offline suite). Question for Michael: a weekly drift check by systemd timer, or by hand from MORNING only?
- V3-03's and V3-04's progress entries state the substitution (D21 for the step's "D18", D22 for its "D19
  *default*") so the verifier reads them together.
- README § Privacy points to D21. This plan's own choices (the section budget, the cut order, the header format) live
  here, not as a D: the spec puts "what was cut" in the plan.

## Tests by feature

**V3-02** (`tests/test_knowledge.py` unless named):

- `SOURCE_FILES = ("Bio.md", "profile.ts", "experience.ts", "projects.ts", "skills.ts", "resume-v4.md",
  "concierge.md")`; `VENDORED = SOURCE_FILES[:5]`.
- `test_sources_commit_matches_the_headers`: every `VENDORED` file's first line matches the header regex, with its own
  base name at the end of its path, and the commit equals the one `SOURCE.md` names (and `pack_stats().sources_commit`).
- `test_source_md_records_the_resume_and_the_rule`: `SOURCE.md` contains `resume v4 of 2026-10-20, from the spec` and
  says the resume wins.
- `test_resume_has_no_phone_number`: no `\d{7,}` run in `resume-v4.md`, and no phone-shaped number
  (`\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}`, so `919-555-0100` is caught while a date like `2026-10-20` is not).
- `test_concierge_source_names_its_basis`: the first line of `concierge.md` names `README.md` and `docs/spec.md §4.0`.
- `test_the_pack_carries_the_new_positioning`: the Positioning and contact section contains `Agentic Systems Engineer`
  and `I build the harnesses, memory and verification around AI agents, and the integrations they run on.`
- `test_the_pack_has_the_self_description_section`: `## Project: Voice Concierge (this agent)` is a heading, its
  `Source:` is `concierge.md`, and its text contains `Forget me`, `30`, `background` and `LiveKit`.
- `test_the_experience_carries_the_resume_roles`: the Experience section names `MAXX Potential`, `Builder Clarity`,
  `Tahoma Films` and coaching, and the four skill group names, compared case-sensitively as §7 writes them (`Agentic AI`, `Languages & Web`,
  `Data & Integration`, `Infra & Tools`), appear in Skills in that order.
- `test_the_pack_has_no_phone_number_or_retired_words`: the same two number rules on the pack; outside `Source:` lines no
  `knowledge pack` and no `specs in, verified milestones out` (case-insensitive).
- Unchanged and still green against the new sources: `test_pack_is_at_most_1200_words`,
  `test_names_are_derived_from_the_pack`, `test_every_name_appears_verbatim_in_the_sources`, `test_pack_has_no_url_absent_from_the_sources`,
  `test_every_number_and_date_in_the_pack_is_in_the_sources`, the `pack_stats` tests,
  `tests/test_prompt.py::test_static_plus_pack_within_budget` (3,000).

**V3-03:**

- `tests/test_prompt.py::test_static_instructions_forbid_the_pack_words`: with the line containing `Never use the
  words` removed, `STATIC_INSTRUCTIONS.lower()` contains none of `pack`, `knowledge pack`, `source lines`; the full text
  contains `Voice Concierge (this agent)`, `how you were built`, `what I know about Michael` and ends with `What you
  know about Michael (the only source of facts about him):`.
- `tests/test_prompt.py::test_static_instructions_carry_the_anti_goal_rules`: the assertion reworded as above.
- `tests/test_prompt.py::test_static_plus_pack_within_budget`: unchanged, still ≤ 3,000.
- `tests/test_prompt.py::test_static_instructions_carry_the_name_confirmation_rule`: its anchor
  `"earlier visits may follow the pack"` becomes `"earlier visits may follow what you know about Michael"` (the old
  one would raise `ValueError` after the rewording).
- `tests/test_readme.py::test_privacy_says_the_self_description_was_checked`: § Privacy names its own memory design,
  "LiveKit", "Anthropic" and `D21`.
- `tests/test_morning.py::test_questions_cover_every_default` keeps passing (D21 is not `*default*`).

**V3-04** (`tests/test_scripts.py` unless named):

- Fixture trees, built in `tmp_path` by a helper `fetched_tree(tmp_path, change=None)`: `clean/` holds each vendored
  file of `knowledge/sources/` with its header line removed; `drifted/` the same with `projects.ts` given one extra
  line.
- `test_check_sources_clean`: subprocess `--fetched <tmp>/clean --sources <ROOT>/knowledge/sources` (absolute paths)
  exits 0, prints the
  `SOURCE.md` commit and `clean:`.
- `test_check_sources_reports_drift`: on `drifted/` it exits 1 and prints `drifted: projects.ts` and no other name.
- `test_check_sources_exits_2_when_a_file_is_missing`: `clean/` without `skills.ts` exits 2, `missing: skills.ts` on
  stderr.
- `test_diff_sources_strips_only_the_header_line`: `diff_sources` imported by path (importlib, as the other script
  tests do); a local file whose second line differs is reported; a local file without a header compares whole.
- `test_check_sources_never_fetches_in_the_suite`: the module imported in-process with `urllib.request.urlopen`
  monkeypatched to a recorder; `main(["--fetched", clean, "--sources", …])` returns 0 and the recorder is never
  called; `main(["--sources", …])` with the recorder returning a context manager with `.status == 200` and `.read()`
  giving the clean bytes calls it 5 times, each with a `RAW`
  URL and `timeout=10`; an AST check finds `urlopen` only inside `fetch`. No real socket is opened.
- `tests/test_morning.py`: `COMMANDS` gains `.venv/bin/python scripts/check_sources.py` between `memory_history.py`
  and `systemctl --user stop voice-concierge`; `test_twelve_numbered_steps_in_order` becomes
  `test_thirteen_numbered_steps_in_order` (`range(1, 14)`).

**V3-05:** `review-V3.diff` in scratch, read by an Opus reviewer; claims table (every sentence of the Voice Concierge
section with its `concierge.md` line and that line's README or spec basis; every number in Experience and Agent
Harness with its source file); fixes RED → GREEN; simplification pass; `wc -l concierge/*.py` ≤ 250.

## Review

V3-05, 2026-10-21. `git diff 69a43ee..HEAD -- . ':!.harness'` (69a43ee is the last V2 commit, "HARNESS: V2 verified";
1,661 lines) was written to `$HARNESS_SCRATCH/review-V3.diff` and read by an Opus reviewer for facts, privacy, tone,
budget and the drift script's code. A second agent built the claims table below, and I checked its cited lines with
`sed -n`.

**Findings.** 0 Critical, 1 Important, 5 Minor.

- **I1 (fixed, RED → GREEN).** `test_concierge_numbers_are_in_readme_or_spec` and the pack's number test only checked
  that each digit-bearing token appears somewhere in the basis, so "a session ends after 20 minutes" would still pass
  (README.md has a "20"). I checked that: with concierge.md changed to "20 minutes", the old test passed and the new
  `test_concierge_limits_match_the_code` failed (`concierge.md: 10 minutes`). The new test builds each spoken limit
  from the code (`Settings` defaults `session_max_s // 60` minutes, `sessions_per_day` sessions a day,
  `idle_ttl_days` days; `MEMORY_BLOCK_MAX_CHARS` characters; the 1,200-word cap) and requires the phrase in both
  concierge.md and the pack's section.
- **M2 (fixed).** The pack's website (`www.mherron.dev`) comes from the resume, while `profile.ts` has the old
  vercel.app address. SOURCE.md's "the resume wins" list now names contact links (the website).
- **M3 (kept).** "job-description agent" expands the resume's "JD agent" so it reads aloud; the meaning is the
  resume's.
- **M4 (fixed, RED → GREEN).** Symbols reached the TTS: 1.8's `filter_markdown` strips only `~~struck~~` text, and the
  prompt says to repeat numbers exactly as written. `test_the_pack_prose_is_in_spoken_form` (no `~`, `×`, `↔`, `%`,
  `≈`, `→`, `$`, digit-`+` or `/week` in the prose; headings and URLs excepted) failed with 12 hits in 8 phrases. The prose now says "about 8
  issues a week", "twice the sprint throughput", "about 80 percent", "from about 2 days to about 6 hours", "about 8
  hours a week", "4 or more sources", "JobTread and GoHighLevel integration platform", "about 3 dollars each", and "Summers 2023 and 2024". The en dash
  in "12–18-year-old" stays, since the number test needs the source's form.
  Headings keep the `projects.ts` titles (with `↔`), because V4 relies on them (below).
- **M5 (skipped).** The reviewer called `test_check_sources_never_fetches_in_the_suite` a misleading name, since it
  runs `fetch` against a mocked `urlopen`. It is the name V3-04's step uses, so it stays.
- **M6 (FYI, for Michael).** The vendored `Bio.md` carries draft notes and an apprenticeship application answer. They
  are already public upstream and the pack doesn't use them, but this repo now republishes them.

**Second look (Opus, the fixes' diff).** 0 Critical, 2 Important, 2 Minor, all fixed. The limits test matched
"15 sessions a day" as "5 sessions a day", so each phrase now needs a non-digit before it (checked RED with "15").
The symbol set was missing `≈`, `→` and `$`, which `projects.ts` uses (checked RED with "≈ $3"). The other two
were the "&" in the prose and this note's hit count. The reviewer re-checked the rewording against resume-v4.md:9–26
and found no change of meaning. "JobTread and GoHighLevel" drops the arrow's two-way sense, and "integration
platform" keeps it.

**The checks the step names.** Privacy: no phone number in `knowledge/sources/` or the pack
(`test_the_pack_has_no_phone_number_or_retired_words`, `test_resume_has_no_phone_number`; the reviewer also grepped
for phone patterns, hostnames and IPs). The only contact data is the public email and the LinkedIn/GitHub/site links.
The resume wins over the vendored files and SOURCE.md says so: for the harness, the pack follows the resume (~$3,
189 features in 4 days, October 2026) over `projects.ts` (≈$2.53, 55 passing in one day, Sep – Oct 2026), and the
positioning follows the resume over `profile.ts`. The word "pack": `STATIC_INSTRUCTIONS` names it only in the rule
that forbids it, and `test_static_instructions_forbid_the_pack_words` guards both the instructions and the pack.
Budget: static 662 + pack 2,204 = **2,866** estimated tokens of 3,000 with separators, **margin 134**. The pack is
**1,181 words** of 1,200 (19 spare). Before the M4 rewording it was 2,846 tokens (margin 154) and 1,166 words.

**Simplification pass.** `tests/test_knowledge.py`: the two number-tracing tests duplicated one token-strip-and-lookup
expression, which is now `_untraced(text, basis)`. Every `concierge/*.py` is at most 250 lines (`wc -l`: the
largest is `memory_writer.py`, at 250). V3 added no `concierge/` module, and its one `concierge/` change
(`prompt.py`) is wording only.

### Claims: `Project: Voice Concierge (this agent)`

Each sentence is supported by the `concierge.md` paragraph with the same words, and that paragraph by:

| # | Sentence (pack) | README.md / docs/spec.md line |
|---|---|---|
| 1 | This is me: the voice agent on Michael's site. | README.md:3 |
| 2 | I talk about Michael's work and remember returning visitors, whether they talk or type. | README.md:3–4 ("across voice and typed text") |
| 3 | I'm built on LiveKit Agents 1.8, in Python. | README.md:4 |
| 4 | I run on Michael's home box and connect out to LiveKit Cloud, and my memory is one local SQLite file. | README.md:6–7 |
| 5 | Each visitor has one thread of memory, and nothing is shared between visitors. | docs/spec.md:81 (B2); docs/spec.md:113 |
| 6 | I remember a few kinds of fact about a visitor: their name, role, company, interests, what they asked about, and whether they want a follow-up. | README.md:119 (the six slots) |
| 7 | Each fact is kept with where I learned it, by voice or by text, and when. | README.md:120 (`channel`, `valid_from`); README.md:22 |
| 8 | I keep a short summary of each visit. | README.md:115 (visit summary at most 3 sentences) |
| 9 | I take my notes in the background, after a turn, never while I'm answering, unless a visitor asks me to remember or forget something. | README.md:75–80 |
| 10 | A correction keeps history: the old fact is marked no longer valid instead of being overwritten. | README.md:112 |
| 11 | A write gate refuses instructions, links and secrets, and I store a name only after the visitor confirms it. | README.md:109 |
| 12 | I can also take a message for Michael, with an email or phone if the visitor wants. | README.md:26 |
| 13 | Forget me, on the page, erases everything linked to the visitor in my memory. | README.md:23–24; README.md:195 |
| 14 | Transcripts LiveKit keeps for Michael are separate and are not erased by it. | README.md:191; README.md:198–201 |
| 15 | A visitor can also ask me to forget one thing. | README.md:24–25 |
| 16 | A thread idle for 30 days is deleted. | README.md:121; docs/spec.md:85 (B6) |
| 17 | I carry a fixed description of Michael's work, at most 1,200 words, which the provider caches, and what I remember about a visitor is at most 1,500 characters. | docs/spec.md:122 (1,200 words); docs/spec.md:132 (cached prefix); README.md:109 (1,500 characters) |
| 18 | On a long call my small working context is compacted. | README.md:115 (past 24 items or about 4,000 tokens) |
| 19 | A session ends after 10 minutes at most, and a visitor gets 5 sessions a day. | README.md:189; docs/spec.md:86 (B7) |
| 20 | The page shows what I remember and what my memory did. | README.md:28–29 and 33–36 (`concierge.memory`, its events) |
| 21 | I can't chat about general topics, I don't guess numbers, and I can't remember a visitor across browsers. | README.md:18; docs/spec.md:130 ("never guess numbers"); README.md:167 (the id is kept in the browser, so "across browsers" is implied) |
| 22 | Michael's agent harness built me overnight from a written spec, after the memory design was researched and written down practice by practice. | docs/spec.md:4 (the agent-harness, overnight); README.md:4–5 and 10–12 |

The limits in rows 16, 17 and 19 are also tied to the code by `test_concierge_limits_match_the_code`.

### Claims: numbers in `Experience` and `Project: Agent Harness`

| Section | Number (pack) | Source | Other sources |
|---|---|---|---|
| Experience | February 2026 to present (MAXX Potential) | resume-v4.md:9 | experience.ts:14 agrees |
| Experience | about 8 issues a week | resume-v4.md:11 | resume only |
| Experience | twice the sprint throughput (2×) | resume-v4.md:12 | experience.ts:17, projects.ts:378 agree |
| Experience | about 80 percent less bug-filing time | resume-v4.md:12 | experience.ts:17, projects.ts:379 agree |
| Experience | March 2025 to November 2025 (Builder Clarity) | resume-v4.md:15 | experience.ts:28 agrees |
| Experience | 3 clients | resume-v4.md:17 | experience.ts:31 agrees |
| Experience | from about 2 days to about 6 hours | resume-v4.md:17 | experience.ts:31, projects.ts:328 agree |
| Experience | about 8 hours a week per client | resume-v4.md:18 | experience.ts:32 agrees |
| Experience | 4 or more sources (4+) | resume-v4.md:18 | experience.ts:33 agrees |
| Experience | February 2025 (Tahoma Films) | experience.ts:40 | not in the resume |
| Experience | Summers 2023 & 2024 | experience.ts:50 | not in the resume |
| Experience | 12–18-year-old | experience.ts:53 | not in the resume |
| Agent Harness | October 2026 to present | resume-v4.md:22 | projects.ts:171 "Sep – Oct 2026"; the resume wins |
| Agent Harness | 189 features | resume-v4.md:26 | projects.ts:134 "55 features passing in one day"; the resume wins |
| Agent Harness | in 4 days | resume-v4.md:26 | projects.ts says one day (Oct 17); the resume wins |
| Agent Harness | about 3 dollars each (~$3) | resume-v4.md:26 | projects.ts:137 "≈ $2.53"; the resume wins |

## What V4 can rely on

V4's conversation scripts may name these section headings, which V3-02 fixes: `Positioning and contact`, `About`,
`Experience`, `Education`, `Skills`, `Project: Voice Concierge (this agent)`, `Project: Agent Harness`, and the other
`Project:` titles as `projects.ts` has them (minus any the budget cut). And the phrases "what I know about Michael"
and "my notes" as the agent's words for the pack.

## Live steps (Michael)

None in V3 is live. The drift check uses the network and is Michael's to run (MORNING step 12): `.venv/bin/python
scripts/check_sources.py` → exit 0, or the drifted names; read-only, nothing to undo. Whether the agent now describes
itself well is V4's `llm` tier and Michael's morning call.
