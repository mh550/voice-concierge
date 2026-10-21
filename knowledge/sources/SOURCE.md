# Sources for what the agent knows about Michael

Five files copied from the public repo `mh550/portfolio_site` at commit `b7c974f` (`main`, 2026-10-20), cloned into
the scratch directory on 2026-10-21: `Bio.md`, `src/lib/data/profile.ts`, `src/lib/data/experience.ts`,
`src/lib/data/projects.ts`, `src/lib/data/skills.ts`. Each file's first line is a header naming the repo, the commit
and the path (a `//` comment in `.ts`, an HTML comment in `.md`); the rest is the clone's file, unmodified.

Two more files:

- `resume-v4.md`: resume v4 of 2026-10-20, from the spec (`docs/specs/2026-10-21-integrated-concierge.md` §7), with
  the site's new positioning line, subline and tagline. No phone number, on purpose.
- `concierge.md`: facts about this agent, written from this repo's `README.md` and `docs/spec.md` §4.0.

**Where the resume and the vendored files differ, the resume wins** (it is newer): titles, dates, numbers and the
grouping of skills.

`knowledge/michael.md` is built only from these files. To refresh the five vendored files, follow
`docs/plans/2026-10-21-V3-knowledge-v2.md` ("Re-vendoring the sources"), record the new commit here, and rebuild
`knowledge/michael.md` in a reviewed session.
