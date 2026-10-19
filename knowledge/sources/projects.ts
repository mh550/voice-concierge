// Import cycle (approach.ts imports from here): use methodSteps only inside functions, never at module load.
import { methodSteps } from './approach';

export type ProjectCategory = 'integration' | 'full-stack' | 'ai' | 'education' | 'systems' | 'process';

/** A key that maps a project to an authored, theme-styled diagram component. */
export type DiagramKey =
  | 'ghl-jobtread'
  | 'ringcentral'
  | 'linear-flow'
  | 'paint-hierarchy'
  | 'calendar-sync'
  | 'agent-harness'
  | 'harness-evolution'
  | 'media-server'
  | 'hit-list'
  | 'form-simplification';

export interface ProjectMedia {
  type: 'image' | 'video';
  src: string;
  alt: string;
  caption?: string;
  /** Intrinsic pixel size. With both set, the gallery shows the image uncropped at its own ratio (D29). */
  width?: number;
  height?: number;
}

/** A big-number impact callout, e.g. { value: '~80%', label: 'less bug-filing time' }. */
export interface Metric {
  value: string;
  label: string;
}

export interface CodeSnippet {
  title: string;
  language: string;
  code: string;
}

/** A recorded choice in a case study: what was chosen, over what, why, and what it cost. */
export interface Decision {
  id: string;
  title: string;
  chose: string;
  over?: string;
  because: string;
  cost?: string;
}

/** One step in how a project evolved. */
export interface Iteration {
  when: string;
  label: string;
  what: string;
  why: string;
  /** The diagram's line for this stage (≤ 8 words); set where the project has an evolution diagram. */
  short?: string;
}

/** Something that broke and the rule it left behind. */
export interface Lesson {
  broke: string;
  rule: string;
}

export interface ProjectLink {
  label: string;
  href: string;
  kind: 'repo' | 'live' | 'doc' | 'demo';
}

/** The case-study body (spec M3). A project with one renders the case-study page order (D16). */
export interface CaseStudy {
  role: string;
  timeframe: string;
  method: { diagnose: string; decide: string; build: string; verify: string; simplify: string };
  decisions: Decision[];
  iterations?: Iteration[];
  lessons: Lesson[];
  links: ProjectLink[];
  /** The honest one-line "how it was built" (D10). */
  builtWith?: string;
  /** Diagrams rendered after the iteration timeline (D17). */
  extraDiagrams?: DiagramKey[];
}

export interface Project {
  slug: string;
  title: string;
  company: string;
  shortDescription: string;
  categories: ProjectCategory[];
  techStack: string[];
  githubUrl?: string;
  demoUrl?: string;
  featured: boolean;
  /** Display order across the site, lower first (spec D12). Unique per project. */
  order: number;
  /** Card preview + detail-page hero image/video. Optional until assets are captured. */
  thumbnail?: ProjectMedia;
  /** Impact callouts surfaced on the card and at the top of the detail page. */
  metrics?: Metric[];
  detail: {
    problem: string;
    approach: string;
    challenges: string;
    outcome: string;
    /** Authored architecture/process diagram rendered after "The Approach". */
    architectureDiagram?: DiagramKey;
    /** Screenshot / screen-recording gallery (filled once assets exist). */
    media?: ProjectMedia[];
    /** Inline code/config excerpts that prove the engineering is real. */
    codeSnippets?: CodeSnippet[];
  };
  caseStudy?: CaseStudy;
}

export const projects: Project[] = [
  {
    slug: 'agent-harness',
    title: 'Agent Harness: overnight software delivery with verification gates',
    company: 'Personal · open source',
    shortDescription:
      'A driver that runs coding agents overnight, one fresh session per feature, and merges only work an independent session has verified.',
    categories: ['systems', 'process', 'ai'],
    techStack: ['Bash', 'Node.js', 'Git', 'tmux', 'jq', 'GitHub CLI', 'Claude Code'],
    githubUrl: 'https://github.com/mh550/agent-harness',
    featured: true,
    order: 1,
    metrics: [
      { value: '55', label: 'features passing in one day' },
      { value: '52', label: 'verified and merged, 12 PRs' },
      { value: '+374', label: 'tests added' },
      { value: '≈ $2.53', label: 'per passing feature' },
    ],
    detail: {
      problem:
        'I have about 10 hours a week and several personal projects. I wanted coding agents to build overnight while I slept, and to steer them from my phone. Every approach that lived inside one session hit one of three walls: the model\'s context limit, my plan\'s usage limit, or the auto-mode permission classifier.',
      approach:
        'A fresh agent session per feature with its state on disk, a deterministic driver for the bookkeeping, and independent verification before anything merges.',
      challenges:
        'Usage limits, the permission classifier and thin verification each broke something before they became rules.',
      outcome:
        'On Oct 17 the harness ran two projects, starting overnight on v2 and finishing on v3 that day: 71 features planned, 55 passing, 52 verified and merged through 12 PRs, and 374 tests added (1,242 → 1,616). It cost $139.34 in total, about $2.53 per passing feature, across 127 sessions and 13.9 hours of run time. The update to this site is a v3 run too: its pull requests are linked below.',
      codeSnippets: [
        {
          title: 'lib/driver.sh · the merge gate: only the verified tree lands on main',
          language: 'bash',
          code: String.raw`# Merge one verified milestone (its tag) into main through a PR. The invariant: the tree that lands on main is the
# tree that was verified. 0 = merged or proposed · 1 = needs Michael (conflict, refusal) · 3 = held: main has content
# this milestone wasn't verified with (the next milestone's verify includes it, and its merge carries this one)
merge_one() {
  local m=$1 tag=run/$RUN_ID/$1 c head url tree
  head=harness-merge/$RUN_ID-$m
  c=$(git rev-list -n1 "$tag") || return 1
  git fetch -q origin "$MAIN_BRANCH" || return 1
  if git merge-base --is-ancestor "$c" "origin/$MAIN_BRANCH"; then touch "$STATE/merged-$m"; note "$m merged into $MAIN_BRANCH (already there)"; return 0; fi
  if ! tree=$(git merge-tree --write-tree "origin/$MAIN_BRANCH" "$c" 2>/dev/null | head -1); then
    note "$m conflicts with $MAIN_BRANCH; not merged (needs Michael)"; notify "$m needs Michael: conflicts with $MAIN_BRANCH"; return 1
  fi
  [[ $tree == "$(git rev-parse "$c^{tree}")" ]] || return 3`,
        },
      ],
      architectureDiagram: 'agent-harness',
    },
    caseStudy: {
      role: 'Designer and operator',
      timeframe: 'Sep – Oct 2026',
      method: {
        diagnose:
          'Every single-session approach hit one of three walls: the context limit, the usage limit, or the permission classifier. One night three loops shared one plan and every repo went silent from 00:12 to 07:19; a long thread ran out of context; the classifier blocked merges.',
        decide:
          'I gave each feature a fresh session and put all state on disk: a feature list, a progress log and git. Agents do the judgment; a deterministic bash driver does the bookkeeping.',
        build:
          'Harness v1 was a ~60-line script inside one project. v2 became its own repo: a worktree per run, repair and continue, an independent verify per milestone, steering from my phone. v3 merged verified milestones itself, waited out usage limits and queued runs.',
        verify:
          'A red suite un-passes a feature. Each finished milestone gets an independent verify session that re-runs every step and writes one evidence row per step. Nothing merges unless the tree that lands on main is byte-for-byte the tree that was verified.',
        simplify:
          'I went from three parallel loops to one serial queue under one usage limit for the whole machine, and from a human tap on every merge to a gated merge. A PR-only mode stays for projects where I still merge, like this site.',
      },
      decisions: [
        {
          id: 'D-H1',
          title: 'A fresh session per feature',
          chose: 'a new headless session for every feature, with its state on disk,',
          over: 'one long loop session or an orchestrator with subagents',
          because: 'every single-session approach hit the context limit eventually; subagents only delayed it.',
          cost: 'Every piece of state has to be written down, which is also what makes it inspectable.',
        },
        {
          id: 'D-H2',
          title: 'Models by role',
          chose: 'the most capable model for the one-time initializer, Opus to build and review, and Sonnet to verify,',
          over: 'one model for everything',
          because:
            'the initializer runs once and decides the quality of the whole night, while verification can run on a cheaper model.',
        },
        {
          id: 'D-H4',
          title: 'Guard against false passes',
          chose: 'a red suite that un-passes the feature, plus an independent verify session per milestone,',
          over: 'trusting the session\'s own "passes"',
          because:
            'the expensive failure is a feature marked done that isn\'t, and a second agent re-running the steps cold is the cheapest independent check.',
          cost: 'One more session per milestone, capped at two rounds after a stub test showed the coder and verifier ping-ponging.',
        },
        {
          id: 'D-H5',
          title: 'The driver does the git bookkeeping',
          chose: 'a deterministic driver for sync, push, tag, PR and cleanup',
          over: 'letting agents merge and clean up',
          because: 'these steps must happen every time and the same way: a script does that; a prompt might not.',
        },
        {
          id: 'D-H11',
          title: 'Detect limits from structure, test against the real message',
          chose:
            'reading the structured error fields first, with a regex only as a fallback, and never counting a $0 session as an attempt,',
          over: 'a wider regex',
          because:
            'structure doesn\'t change its wording between releases, and the $0 rule catches the next unknown error too.',
        },
        {
          id: 'D-H17',
          title: 'The harness merges, under one invariant',
          chose: 'one PR per verified milestone, opened and merged by the driver in milestone order,',
          over: 'a human tap on every merge',
          because:
            'mornings shouldn\'t be a merge queue, and the tree that lands on main is byte-for-byte a tree that was verified, after its own review, an independent verify and a green suite.',
          cost: 'Human review moved from every merge to policy and permissions; a PR-only setting restores the tap, and this site\'s run uses it.',
        },
      ],
      iterations: [
        {
          when: 'Sep 2026',
          label: 'Long sessions',
          what: 'Long interactive sessions, with spec, research and decisions files for each idea.',
          why: 'It worked, but it needed me at the keyboard.',
          short: 'Needed me at the keyboard',
        },
        {
          when: 'Oct 13–15',
          label: 'Runbook + loop',
          what: 'A written runbook as the agent\'s memory and an overnight loop; later one fresh thread per milestone, each ending with a handoff file.',
          why: 'Three loops ran on one plan and every repo went silent from 00:12 to 07:19 on usage limits. A long thread hit "context usage too high".',
          short: 'Hit usage and context limits',
        },
        {
          when: 'Oct 15–16',
          label: 'Orchestrator + subagents',
          what: 'One session orchestrated by role: Sonnet wrote failing tests, Opus implemented, Opus reviewed.',
          why: 'It delivered (one app gained 154 tests in about 2.5 hours), then hit a new wall: the permission classifier blocked a rebuild as a "production deploy", and blocked merges.',
          short: 'Blocked by the permission classifier',
        },
        {
          when: 'Oct 16 eve',
          label: 'Harness v1',
          what: 'After Anthropic\'s "Effective harnesses for long-running agents": an initializer turned the spec into a feature list, then one fresh session ran per feature, from a ~60-line script.',
          why: 'It lived inside one project, ran in place, and one guard trip stopped the whole night.',
          short: 'One guard trip stopped the night',
        },
        {
          when: 'Oct 16 night',
          label: 'Harness v2',
          what: 'Its own repo. "Agents do judgment; the driver does bookkeeping." A worktree per run, repair and continue, an independent verify per milestone, tag + PR, steering from my phone through INBOX.md, metrics.',
          why: 'Merges still needed a human, and each run handled usage limits on its own.',
          short: 'Merges still needed a human',
        },
        {
          when: 'Oct 17',
          label: 'Harness v3',
          what: 'Merges verified milestones itself, waits out usage limits for the whole machine, queues runs, and writes a retro and a ledger entry per run.',
          why: 'The current version. The run that built this site update is a v3 run.',
          short: 'Current: it built this update',
        },
      ],
      lessons: [
        {
          broke:
            'The harness broke its own rule. I had tested the usage-limit detector against a message I made up; the real one said "You\'ve hit your session limit", so 45 sessions were counted as failed attempts in 6 minutes, with 5 hours of budget left.',
          rule: 'Fakes mirror the live API: read the structured error first, and test against output captured from the real CLI.',
        },
        {
          broke: 'Two runs in parallel used up the 5-hour usage window in 2 h 49 min.',
          rule: 'One usage limit for the whole machine, and runs go one at a time by default.',
        },
        {
          broke: 'On one project, verify sessions took 29–40 s, and review found the real defects later.',
          rule: 'A verify writes one evidence row per step; with rows missing, it runs again on Opus.',
        },
        {
          broke:
            'An independent review of v3 before its first run found 2 critical and 8 important bugs, including a verify refused by a usage limit that counted as "holds" and would have merged code with zero evidence.',
          rule: 'The harness gets reviewed before it drives a real night, like any other code.',
        },
        {
          broke: 'One feature waiting on a human stopped a whole run: 14 independent features never ran behind it.',
          rule: 'Independent work has to be declared. The initializer can give a feature an after list so it doesn\'t wait on a blocked one, but by default a feature still waits on everything before it; blocking only on declared dependencies is the next proposed change.',
        },
      ],
      links: [
        { label: 'agent-harness on GitHub', href: 'https://github.com/mh550/agent-harness', kind: 'repo' },
        {
          label: 'This site update, built by the harness',
          href: 'https://github.com/mh550/portfolio_site/pulls?q=is%3Apr+harness',
          kind: 'repo',
        },
      ],
      extraDiagrams: ['harness-evolution'],
      builtWith:
        'I designed the process, the specs, the decision log and the verification gates, and I ran each night and reviewed its results. Claude Code agents wrote much of the harness code under that direction.',
    },
  },
  {
    slug: 'ghl-jobtread-integration',
    title: 'GoHighLevel ↔ JobTread Integration',
    company: 'Builder Clarity',
    shortDescription:
      'Multi-tenant, bidirectional integration between GoHighLevel CRM and JobTread project management — purpose-built for contractors.',
    categories: ['integration'],
    techStack: ['Pipedream', 'Supabase', 'JavaScript', 'OAuth', 'REST APIs', 'Webhooks'],
    featured: true,
    order: 5,
    metrics: [
      { value: '2 days → ~6 hrs', label: 'client onboarding time' },
      { value: 'Bidirectional', label: 'GHL ↔ JobTread sync' },
      { value: '0', label: 'manual re-entry of leads' },
    ],
    detail: {
      problem:
        'Contractors were managing jobs in JobTread and leads/clients in GoHighLevel with zero data flow between them — double entry, missed follow-ups, and no unified view of a customer journey. The core challenge was an ETL problem across two platforms paired with a deduplication problem: the same human exists in both systems, under different schemas, and must never be created twice.',
      approach:
        'I mapped the full entity model of each platform, then designed a bidirectional sync keyed on a waterfall match (phone → email → name). On a GoHighLevel pipeline-stage change, the integration finds-or-creates down JobTread\'s hierarchy in dependency order — customer, then contact, then location, then job — wiring each record to the ones above it. Built on Pipedream with custom JavaScript at nearly every step, Supabase bridging state between the platforms, and GoHighLevel\'s native automations driving the proof-of-concept triggers.',
      challenges:
        'JobTread and GoHighLevel model the same business differently — in JobTread a location belongs to a customer and carries one contact; in GoHighLevel an opportunity carries one contact and moves through tenant-specific pipeline stages. I originally matched a GHL contact to a JobTread customer, then refined mid-milestone to match contact-to-contact for robustness. Multi-tenant auth added real complexity: an Agency OAuth token with per-subaccount logic for GoHighLevel, and Connected Organizations for JobTread.',
      outcome:
        'Delivered a scalable, multi-tenant integration that became the foundation of Builder Clarity\'s productized offering — replacing per-client buildouts and cutting onboarding from roughly two days to about six hours, with leads flowing straight into job records and no manual re-entry.',
      architectureDiagram: 'ghl-jobtread',
      codeSnippets: [
        {
          title: 'Waterfall find-or-create (phone → email → name)',
          language: 'javascript',
          code: `// Match an incoming GHL contact to an existing JobTread record
// in priority order, so the same person is never created twice.
async function findOrCreateContact(ghlContact, jobtread) {
  const candidates = [
    () => jobtread.findContactByPhone(ghlContact.phone),
    () => jobtread.findContactByEmail(ghlContact.email),
    () => jobtread.findContactByName(ghlContact.name),
  ];

  for (const lookup of candidates) {
    const match = await lookup();
    if (match) return match; // first hit wins — phone is strongest
  }

  // No match anywhere in the waterfall → safe to create.
  return jobtread.createContact(ghlContact);
}`,
        },
      ],
    },
  },
  {
    slug: 'linear-ai-workflow',
    title: 'Linear Adoption + Agentic Bug Workflow',
    company: 'MAXX Potential',
    shortDescription:
      'Replaced scattered per-person QA spreadsheets with Linear and an AI-agent workflow that automates bug filing, triage, and deduplication.',
    categories: ['integration', 'ai'],
    techStack: ['Linear', 'MCP', 'Claude Code', 'AI Agents', 'Git'],
    featured: true,
    order: 2,
    metrics: [
      { value: '2×', label: 'sprint throughput' },
      { value: '~80%', label: 'less bug-filing time' },
      { value: 'Automated', label: 'triage & dedup' },
    ],
    detail: {
      problem:
        'QA ran on a patchwork of Google Sheets — each team member kept their own sheet with their own columns. Issues had no status history, no categories or tags, and no record of when anything moved between states. The lead engineer wasn\'t marking issues complete, so the team had to manually re-test each build to figure out what had actually been fixed.',
      approach:
        'I championed Linear as a single source of truth, chosen specifically for its strong API, Git integration, full issue timeline, and — critically — its MCP server and community CLI tooling. Since the lead engineer was already using Claude Code to convert spreadsheet rows into markdown for triage, I wired Linear directly into that agentic workflow so the AI could fetch and update issues in place instead of copy-pasting.',
      challenges:
        'The win wasn\'t just adopting a tool — it was redesigning the bug lifecycle around automation. Filing and triage are now hands-off: duplicates are detected automatically and appended as comments to the existing issue rather than spawning new ones, and triage surfaces a likely root cause plus the context a developer needs to decide how to approach the fix.',
      outcome:
        'The team went from fragmented sheets to an organized, automated pipeline across filing, triage, and implementation — roughly doubling sprint throughput and cutting bug-filing time by about 80%.',
      architectureDiagram: 'linear-flow',
    },
  },
  {
    slug: 'home-media-server',
    title: 'Self-hosted music library & DJ crate pipeline',
    company: 'Personal · home server',
    shortDescription:
      'A music library I host at home and stream to my phone, with a crate pipeline that checks each file\'s real quality and never deletes from the library.',
    categories: ['systems', 'full-stack'],
    techStack: ['Python', 'SQLite', 'Docker Compose', 'Navidrome', 'beets', 'ffmpeg', 'JavaScript', 'restic'],
    githubUrl: 'https://github.com/mh550/dj-crate-streaming',
    featured: true,
    order: 3,
    metrics: [
      { value: '831', label: 'songs, self-hosted, identical copies removed' },
      { value: '1,405', label: 'playlist entries kept intact through the retag and dedupe' },
      { value: '1,359', label: 'tests, all offline against fakes' },
      { value: 'Trash, not delete', label: 'code never deletes a library file; every removal is a reversible move' },
    ],
    detail: {
      problem:
        'I wanted to stop depending on Spotify and stream my own music library from a box at home to my phone. I also wanted to flip any playlist into a DJ crate, where every track gets a DJ-quality file that is found, verified and filed automatically. And all of it had to be safe to run unattended on the one server that holds my only organised library.',
      approach:
        'Navidrome owns the library, a small crates service owns the crate flags and the queue, and a worker container verifies and files each approved download.',
      challenges:
        'A guessed fake, a tool that rewrote every tag and a trash folder that overwrote itself each broke something before they became rules.',
      outcome:
        'Since Oct 13 the library has run on a desktop at home: 831 songs, about 22 GB, streamed to my phone over a private network and backed up every night, encrypted, to a second disk. The cleanup retagged 376 files, moved 359 out of "Compilations" and trashed 28 duplicates, and all 1,405 playlist entries came through intact. A check of the whole library found 22 of 831 files that fail the crate check, 17 of them upscaled from ~128 kbps sources: that is the upgrade list. MusicBrainz ids for 485 files are ready to apply, and 16 went in as a reversible trial. As of Oct 17 the download path had run only in tests; the first real download is mine to start.',
      codeSnippets: [
        {
          title: 'verify · a "FLAC" upscaled from a lossy source is rejected (the docs\' example)',
          language: 'text',
          code: `BAD  incoming/…/03 - Good Times.flac  (tier crate)
     flac 44100 Hz / 16 bit / 2 ch / 501.0 s  [flac-streaminfo]
     · cutoff ≈16 kHz
     · band dB vs full: >11k -24.8  >13k -26.7  >15k -30.4  >16k -35.0  >17k -82.7  >18k -84.7 …
     · decoded 501.0 s · bits used 16 · peak -9.31 dBFS · flat factor 0.0
     ✗ cutoff ≈16 kHz (energy stops above 16 kHz) for a lossless file: lossless or 320 kbps reaches 19–20 kHz, so this likely came from ≤128 kbps`,
        },
      ],
      media: [
        {
          type: 'image',
          src: '/projects/home-media-server/01-playlists.png',
          alt: 'The crates web client on a phone: three playlists, one marked as a crate with 1 of 3 tracks crate-ready.',
          caption:
            'Playlists, with one flagged as a crate. Demo data from the September prototype, running against a fake Navidrome.',
          width: 840,
          height: 1720,
        },
        {
          type: 'image',
          src: '/projects/home-media-server/02-crate-toggled.png',
          alt: 'A playlist switched to a crate: two tracks marked ok, one marked needs source.',
          caption:
            'A playlist toggled into a crate: each track shows its format and whether it met the crate rule of the time. Demo data.',
          width: 840,
          height: 1720,
        },
        {
          type: 'image',
          src: '/projects/home-media-server/03-wanted.png',
          alt: 'The wanted queue: two tracks whose library file does not meet the crate rule, each with the reason.',
          caption:
            'The wanted queue: what still needs a better file, and why. Demo data from the prototype, before the one-rule simplification.',
          width: 840,
          height: 1720,
        },
      ],
      architectureDiagram: 'media-server',
    },
    caseStudy: {
      role: 'Designer and operator',
      timeframe: 'Sep – Oct 2026',
      method: {
        diagnose:
          'My music was about 22 GB of files with no good way to play it away from home. After the first night live, the counts matched while 92 titles were still wrong on my phone, 28 files were second copies of the same audio, and nothing could yet tell a real lossless file from one upscaled from a low-bitrate mp3.',
        decide:
          'Navidrome owns the songs and playlists. A small crates service owns only the crate flags, the wanted queue and approvals, in its own SQLite database, and a stream is a redirect to Navidrome, so audio never passes through it. Downloads run in their own worker container, and nothing downloads until I have approved the first one by hand.',
        build:
          'I built it offline first, against a fake Navidrome, then took it live on Oct 13. Next came playlist import from Spotify, tag cleanup, dedupe, download validation, and a worker that searches a peer-to-peer network, Soulseek, through a VPN, verifies each file and files it with beets.',
        verify:
          'Every download is checked by one decode for the spectral cutoff, the bits actually used, truncation, silence and clipping, plus flac -t, and by an acoustic fingerprint when it replaces a library copy. The same check ran over the whole library in about 75 minutes, 6 files at a time. The 1,359 tests run offline against fakes built from captured live responses, and each milestone ends with me looking at the phone, not the counts.',
        simplify:
          'After using it, I replaced four quality tiers with one rule, lossless or 256 kbps and up, and left streaming quality to Navidrome and the phone app. "Prefer the 12-inch mix" became "source the exact track", the crate flag moved out of playlist comments into the app, and I deleted 35 cluttered playlists and kept 10; every one can be restored.',
      },
      decisions: [
        {
          id: 'D7',
          title: 'The first real download is mine',
          chose: 'no automatic downloads until I had approved one by hand and said go,',
          over: 'letting the queue download on its own from day one',
          because:
            'the chain from download to library had only run in tests, so its first real run should be one file I watch.',
          cost: 'As of Oct 17 the download path had not run live: copy replacement and play-now wait on that first approval.',
        },
        {
          id: 'D3',
          title: 'Duplicates go to the trash, not away',
          chose:
            'moving each second copy to a dated trash folder with a logged reverse move, and repointing its playlists,',
          over: 'deleting duplicates',
          because: 'a wrong call should be one move from undone, and these 28 were copies that decoded to identical audio.',
          cost: 'Code never empties the trash; it grows until I empty it by hand, and a status command reports its size and age.',
        },
        {
          id: 'D24',
          title: 'One download quality',
          chose:
            'one rule, lossless or lossy at 256 kbps or more, with streaming quality left to Navidrome and the phone app,',
          over: 'the four quality tiers I had built and tested',
          because:
            'a downloaded file is kept for years and every stream is transcoded from it, so that one file\'s quality is the only one that matters.',
          cost: 'The tier work became four tier names with the same rule in a config file.',
        },
        {
          id: 'D27',
          title: 'The app owns the crate flag',
          chose: 'keeping which playlists are crates in the crates app\'s own database',
          over: 'a #crate tag written into each playlist\'s comment',
          because: 'playlist names and comments stay clean in every app that shows them, and one place holds the answer.',
        },
        {
          id: 'D18',
          title: 'Downloads run in their own container',
          chose: 'a separate worker container that has no open port and handles only approved downloads,',
          over: 'running downloads from a script on the host',
          because:
            'the web-facing service keeps a read-only view of the library, and credentials stay inside the containers.',
        },
        {
          id: 'D38/39',
          title: 'A green backup means a fresh backup',
          chose: 'all-or-nothing database snapshots, and a nightly backup that fails when a snapshot fails,',
          over: 'refreshing each snapshot on its own and logging a warning',
          because:
            'the monitoring heartbeat should be green only when the backup really holds fresh copies of both databases.',
          cost: 'A broken snapshot turns the whole night red, even though the music itself was backed up.',
        },
      ],
      iterations: [
        {
          when: 'Sep 17–18',
          label: 'Offline prototype',
          what: 'A candidate scorer, the crate layer, a fake Navidrome and a web client, all tested offline: 37 tests.',
          why: 'I wanted the design proven against fakes before it touched the real library.',
        },
        {
          when: 'Oct 13',
          label: 'Live, night one',
          what: 'The stack went live: 917 original files became 859 tracks in 35 genre playlists, with the nightly backup job already running. Tests went from 37 to 80.',
          why: 'Every count matched, but my phone still showed 92 wrong titles.',
        },
        {
          when: 'Oct 13–15',
          label: 'Library hygiene',
          what: 'Playlist import from Spotify, tag cleanup, dedupe, quality tiers and download validation; tests reached 249.',
          why: 'Downloads needed a place that could write to the library while the web-facing service stayed read-only.',
        },
        {
          when: 'Oct 15–16',
          label: 'Worker + identity',
          what: 'A worker container that files downloads with beets, a model of songs, versions and copies, copy replacement and play-now; about 1,100 tests by the end.',
          why: 'After using it, the tiers and the version rules were more machinery than the job needed.',
        },
        {
          when: 'Oct 17',
          label: 'The simplification',
          what: 'One download quality, the exact track, the app owns the crate flag. An overnight run of my agent harness then built duplicate-cleanup tooling, health checks and lock-protected backups: 1,359 tests.',
          why: 'The current version. The first real download waits for my go.',
        },
      ],
      lessons: [
        {
          broke:
            'A guessed fake hid 3 critical bugs in the download client: the tests passed against a fake written from a guess at the API.',
          rule: 'Fakes mirror the live API: they are built from captured real responses.',
        },
        {
          broke: 'After the first night every count matched, 859 = 859 = 859, while 92 titles were still wrong on my phone.',
          rule: 'Every milestone ends by looking at the screen itself, not the counts. This site\'s build ends its milestones the same way.',
        },
        {
          broke:
            'beets rewrote every tag on the live library and collapsed multi-valued genres. Review caught it, and the genres were repaired from the original files.',
          rule: 'No tool rewrites the whole library. beets writes full tags only on a fresh download with a confident MusicBrainz match.',
        },
        {
          broke:
            'On Oct 15 the dedupe moved copies into trash paths where an earlier repair had kept damaged copies, and 18 of them were overwritten.',
          rule: 'The trash never overwrites: a name that is already there gets a numbered suffix.',
        },
        {
          broke:
            'Verification would have thrown away good files: embedded webp cover art makes ffmpeg print "[error]" lines about audio that is fine.',
          rule: 'For FLAC, flac -t decides. A few ffmpeg complaints are a warning; only 10 or more, audio that won\'t decode, or digital silence fail.',
        },
        {
          broke: 'beets matched a 412 s 12-inch mix to a 403 s 90s mix.',
          rule: 'The id backfill doesn\'t use beets\' matching: it proposes ids, I review them, and every apply can be reverted.',
        },
        {
          broke:
            'Backups of the app\'s SQLite database were inconsistent: the main file was 4 KB and the data sat in the -wal file beside it.',
          rule: 'Databases are copied only with sqlite3 .backup. The new nightly job also takes the lock first; it is built and waits for my one-time install.',
        },
      ],
      links: [{ label: 'dj-crate-streaming on GitHub', href: 'https://github.com/mh550/dj-crate-streaming', kind: 'repo' }],
      builtWith:
        'I designed the system, set the specs, decided or approved every entry in the decision log, and decided every change to the live library. Claude Code agents wrote much of the code under that direction; the Oct 17 work was an overnight run of my agent harness.',
    },
  },
  {
    slug: 'hit-list',
    title: 'HitList: offline-first street-spot scouting app',
    company: 'Personal · iOS (Expo)',
    shortDescription:
      'An iPhone app for logging street snowboard and skate spots with cold hands and no signal: capture first, add the details later, everything stored on the phone.',
    categories: ['full-stack', 'process'],
    techStack: ['React Native', 'Expo', 'TypeScript', 'expo-router', 'zustand', 'SQLite', 'react-native-maps', 'Jest', 'GitHub Actions'],
    githubUrl: 'https://github.com/mh550/hit-list',
    featured: true,
    order: 4,
    metrics: [
      { value: '374', label: 'tests in 37 suites, and the phone still found a crash' },
      { value: '20+ → 7', label: 'fields on a spot, specified Oct 16 after using it, not yet built' },
      { value: 'SDK 54 → 57', label: 'Expo upgrade in three one-version hops, each one green' },
    ],
    detail: {
      problem:
        'I ride street spots on a snowboard and a skateboard. A spot is one rideable feature, a rail, a ledge or a bank, at one place. I scout with cold hands, little time and often no signal, and a spot I don\'t log is easy to forget. I wanted an app on my phone that saves a spot in seconds, lets me add the details later, works offline and keeps my spots to myself.',
      approach:
        'An Expo app with expo-router screens, zustand stores and an offline-first SQLite database, with every photo copied into the app\'s own storage.',
      challenges:
        'A green test suite hid a crash, a foreign-key difference and layout bugs that only the phone, or the framework\'s source, could show.',
      outcome:
        'When the second session wrapped up on the evening of Oct 15, the app worked end to end in tests and bundled for iOS: Quick Add, batch import grouped by place, the list and the Apple Maps view, search and sort, all offline-first. The suite stood at 374 tests in 37 suites with CI green, expo-doctor at 21/21 and a 4.1 MB iOS bundle. Then, on my iPhone in Expo Go, importing several photos crashed. Once that was fixed I used it, and on Oct 16 my feedback became a spec for the cut to seven fields. As of Oct 18 that simplification is specified, not yet built. The app still loads in Expo Go from my desktop; a TestFlight build comes later.',
      architectureDiagram: 'hit-list',
    },
    caseStudy: {
      role: 'Product owner and user',
      timeframe: 'Feb – Oct 2026',
      method: {
        diagnose:
          'In February I wrote the product spec, and four interactive sprints built every screen but the map; then it stalled: nothing had ever run on a phone. When I picked it up again in October, the first job was getting it onto my iPhone, and Expo Go runs only the newest SDK.',
        decide:
          'The overnight spec fixed the big calls: upgrade the SDK one version at a time inside a 2-hour box, Apple Maps over Mapbox, and photos copied into the app, never written to the camera roll. When the agent put batch import on the Profile tab, I moved it to the Spots tab.',
        build:
          'One overnight agent loop took it from compiling to ready for my phone: SDK 54 to 57, the first green CI, real SQLite migrations, photos in app storage, Apple Maps and named untitled spots. A second session ran as an orchestrator: Sonnet wrote the failing tests, Opus implemented and Opus reviewed. Tests went from 115 to 220 to 374.',
        verify:
          'Every feature and fix started as a failing test, and from M3 on the database code ran against real SQLite, not mocks. Every milestone got an independent review, and every one that touched a screen ended with a table of what the screen would show, row by row. Then I used it on my iPhone, which found what 374 tests could not.',
        simplify:
          'After using it, I wrote a spec that cuts a 20+ field form in five sections to seven fields: name, location, photos, feature types, skate stopped, natural speed and notes. In it, stars become a five-step speed scale, gear and drafts go, and the old details are archived, not deleted. This is specified, not yet built.',
      },
      decisions: [
        {
          id: 'D1',
          title: 'One SDK version at a time',
          chose:
            'upgrading Expo from SDK 54 to 57 one version per step inside a 2-hour box, falling back to the last green step,',
          over: 'a single jump to 57',
          because: 'Expo Go on my phone runs only the newest SDK, and a failed step should cost one hop, not the night.',
          cost: 'Each hop broke something different, from a nested module to a router change and a dependency conflict, so each was fixed and tested on its own before any feature work.',
        },
        {
          id: 'D2',
          title: 'Apple Maps now, Mapbox later',
          chose: 'Apple Maps through react-native-maps',
          over: 'Mapbox',
          because: 'Apple Maps needs no API key and no custom build, so it runs in Expo Go today.',
          cost: 'No offline map tiles until a custom build makes Mapbox possible.',
        },
        {
          id: 'D3',
          title: 'Photos stay inside the app',
          chose: 'copying every photo into the app\'s own storage and saving only its relative path,',
          over: 'keeping the camera\'s cache file, which iOS can purge,',
          because:
            'a photo survives iOS clearing its cache, my camera roll stays untouched, and deleting a spot never takes a photo with it.',
          cost: 'Code never deletes a photo file, so a deleted spot\'s photos stay on the phone.',
        },
        {
          id: 'D12',
          title: 'Import lives on the Spots tab',
          chose: 'a second button on the Spots tab, beside the + for a new spot,',
          over: 'the Profile tab, where the agent first put it,',
          because: 'new spots start on the Spots tab, in List and Map, and an import button on Profile is bad UX.',
          cost: 'Found late: until the phone guide was written, batch import had no way in at all.',
        },
        {
          id: 'D21',
          title: 'Natural speed in words, not stars',
          chose: 'a labelled five-step scale (None · Little · Some · Enough · Too much)',
          over: 'a row of five stars',
          because: 'stars read as "how good", and five identical stars say nothing about what is being measured.',
          cost: 'Specified, not yet built. Old star ratings move down one step to fit the 0–4 scale.',
        },
        {
          id: 'D22',
          title: 'Gear removed entirely',
          chose: 'removing gear from the app',
          over: 'a "gear I have" filter',
          because:
            'filtering by what I own was the wrong way round, a spot that takes either of two setups makes any gear list ambiguous, and what gear really meant was "needs extra speed", which the speed scale already says.',
          cost: 'Specified, not yet built. Old setup options are archived, not deleted.',
        },
      ],
      iterations: [
        {
          when: 'Feb 12–14',
          label: 'Spec and sprints',
          what: 'I wrote the product spec, and four interactive sprints built every screen but the map.',
          why: 'The loop never closed on a device, and the project stalled for eight months.',
        },
        {
          when: 'Oct 13',
          label: 'The revival',
          what: 'A planning session read the repo as it stood and wrote the overnight spec: the decisions, the milestones and a 2-hour box for the SDK upgrade.',
          why: 'I wanted it on my phone, and that meant three SDK versions first.',
        },
        {
          when: 'Oct 14–15',
          label: 'Overnight loop',
          what: 'One agent loop worked milestones M0 to M7: SDK 57, the first green CI, real SQLite tests, photos, the map, named untitled spots and a reachable import. Tests went from 115 to 220.',
          why: 'It ran end to end in tests and bundled for iOS; clustering, search and the edit screen were next.',
        },
        {
          when: 'Oct 15',
          label: 'Orchestrator session',
          what: 'A second session split the work: Sonnet wrote the failing tests, Opus implemented, Opus reviewed. Clustering, sort and search, edit fixes and foreign keys landed: 374 tests in 37 suites, CI green.',
          why: 'Every gate was green. The phone had not had its turn yet.',
        },
        {
          when: 'Oct 15',
          label: 'On the phone',
          what: 'Importing several photos crashed on my iPhone, a failure no test could see. Ids moved to expo-crypto, and a lint rule now blocks the old import.',
          why: 'Every test had passed; the phone found what they could not.',
        },
        {
          when: 'Oct 16',
          label: 'Simplification spec',
          what: 'After using it, my feedback became a spec: from 20+ fields to seven, a five-step speed scale instead of stars, no drafts and no gear, with the old details archived, not deleted.',
          why: 'It is specified, not yet built: the next agent run builds it from that spec.',
        },
      ],
      lessons: [
        {
          broke:
            'All 374 tests passed, and importing several photos crashed on my iPhone: the uuid package needs crypto.getRandomValues(), which Node and Jest have and the phone\'s Hermes engine does not.',
          rule: 'The test environment is not the device. Ids now come from expo-crypto, and a lint rule blocks the uuid import.',
        },
        {
          broke:
            'The test database enforced foreign keys and the phone\'s did not: node:sqlite turns them on by default, expo-sqlite starts with them off. Review then found that a future table rebuild with them on would have deleted every photo record.',
          rule: 'Test fakes start the way the device starts. Foreign keys are off during migrations and on afterwards.',
        },
        {
          broke:
            'A spot saved without GPS showed as "7679.1 mi" away in the list. No test failed; a table of what the screen would show, row by row, exposed it.',
          rule: 'A spot with no location shows no distance. The table stayed: every milestone that touches a screen ends with one, on this site\'s build too.',
        },
        {
          broke:
            'A row of sort chips inherited React Native\'s default flexGrow: 1 and would have filled about half the Spots screen. Jest can\'t see layout; a reviewer caught it by reading the React Native source.',
          rule: 'Passing tests say nothing about layout. Layout gets checked against the framework\'s source and on the phone.',
        },
        {
          broke:
            'Saving a spot in Edit silently wiped its skate-stop details, rounded untouched dimensions on every save, and stored "abc" as NaN.',
          rule: 'A save keeps every field it did not touch. A failing test reproduces the loss before the fix.',
        },
      ],
      extraDiagrams: ['form-simplification'],
      links: [{ label: 'hit-list on GitHub', href: 'https://github.com/mh550/hit-list', kind: 'repo' }],
      builtWith:
        'I wrote the product spec, made or answered the calls on this page (keeping notes, the speed-scale words and the archive are defaults I can still overrule), and tested the app on my phone. Claude Code agents wrote much of the code under that direction: one overnight loop, then a session where Sonnet wrote the failing tests, Opus implemented and Opus reviewed.',
    },
  },
  {
    slug: 'ringcentral-jobtread-integration',
    title: 'RingCentral ↔ JobTread Integration',
    company: 'Builder Clarity',
    shortDescription:
      'Synced calls and texts from RingCentral VoIP into JobTread contact threads — establishing a single source of truth for contractor communications.',
    categories: ['integration'],
    techStack: ['n8n', 'Zapier', 'REST APIs', 'Webhooks', 'JavaScript'],
    featured: true,
    order: 7,
    metrics: [
      { value: '1 thread', label: 'per customer' },
      { value: 'Zapier → n8n', label: 'platform migration' },
    ],
    detail: {
      problem:
        'Contractors\' phone calls and texts in RingCentral were siloed from their project communication in JobTread, making it impossible to see the full picture of a client relationship from one place.',
      approach:
        'I matched the phone number on every inbound and outbound call or text to JobTread contacts, logging the event to each contact that matched. Communications land in JobTread\'s comment-thread API as a single per-customer thread, with call summaries, transcriptions, and action items appended as comments.',
      challenges:
        'Started on Zapier and hit platform limits around conditional logic and API rate handling. I led the technical migration to n8n, which gave us robust workflow control and reduced operational overhead.',
      outcome:
        'Contractors gained one unified communication history per customer — no more cross-referencing two platforms to reconstruct a client\'s history.',
      architectureDiagram: 'ringcentral',
    },
  },
  {
    slug: 'paint-estimator',
    title: 'React Native Paint Estimator',
    company: 'MAXX Potential',
    shortDescription:
      'Full-stack mobile app that lets paint estimators price a job by breaking it down into areas, features, and tasks.',
    categories: ['full-stack'],
    techStack: ['React Native', 'TypeScript', 'Node.js'],
    featured: true,
    order: 6,
    metrics: [
      { value: '3 levels', label: 'job → area → feature → task' },
      { value: 'Go-live', label: 'joined at launch' },
    ],
    detail: {
      problem:
        'Estimators needed a fast, structured way to price a paint job on-site. Pricing isn\'t one number — a job is a hierarchy of areas (rooms), each with multiple features (paint, carpentry, and so on), each broken into individual tasks.',
      approach:
        'I built the estimator around that exact hierarchy — job → areas → features → tasks — so an estimator can decompose a walkthrough into priced line items quickly. I joined at go-live with limited React Native experience and established the team\'s development paradigms, consolidating overlapping features into simpler, reusable modules.',
      challenges:
        'React Native\'s cross-platform quirks were the real learning curve — concepts like KeyboardAvoidingView need different implementations on iOS and Android. Wrapping my head around those while shipping at launch pace pushed me to design for reuse instead of duplicating screen logic.',
      outcome:
        'Delivered a working estimator that turns an on-site walkthrough into a structured, itemized quote — and leveled up my React Native fluency from a single side project to production paradigms the team could build on.',
      architectureDiagram: 'paint-hierarchy',
    },
  },
  {
    slug: 'mirrored-google-calendars',
    title: 'Mirrored Google Calendars',
    company: 'Freelance',
    shortDescription:
      'Rebuilt a broken Google Calendar sync app from scratch — mirrors events across calendars for availability blocking.',
    categories: ['full-stack', 'integration'],
    techStack: ['Next.js', 'Supabase', 'Pipedream', 'Google Calendar API', 'TypeScript'],
    featured: false,
    order: 8,
    detail: {
      problem:
        'A client needed a working Google Calendar mirroring tool but had inherited a codebase with fundamental architectural flaws that made it unreliable and unmaintainable.',
      approach:
        'Diagnosed the root cause of the breakage — mismatched event ownership logic and lack of idempotency. Rebuilt from scratch with a clean architecture: Next.js + Supabase backend for state management, Pipedream Connect API for managed OAuth, and event-driven sync triggers.',
      challenges:
        'Inheriting broken code without documentation required careful forensic analysis before any rebuilding could begin. Designing idempotent sync logic for Google Calendar\'s eventual-consistency model required several iterations.',
      outcome:
        'Delivered a stable, maintainable sync tool the client could rely on. The rebuild also served as a case study in diagnosing architectural failures and designing for reliability over speed.',
      architectureDiagram: 'calendar-sync',
    },
  },
  {
    slug: 'cherished',
    title: 'Cherished',
    company: 'Duke University',
    shortDescription:
      'Wellness-centered social media platform built in an AGILE team — featuring messaging, profiles, search, and email notifications.',
    categories: ['full-stack', 'education'],
    techStack: ['Next.js', 'MongoDB', 'TypeScript', 'AGILE/Scrum'],
    featured: false,
    order: 9,
    detail: {
      problem:
        'Course project: design and build a social platform centered on positive, wellness-focused interactions rather than engagement-maximizing mechanics.',
      approach:
        'Worked in a cross-functional AGILE team with two-week sprints tracked in a shared backlog. Implemented core social features: real-time messaging, user profile management, search, and transactional email notifications.',
      challenges:
        'Coordinating feature development across multiple engineers required clear API contracts and regular integration testing. Balancing UX quality with sprint velocity was an ongoing challenge.',
      outcome:
        'Delivered a functional social platform with a polished UX, receiving strong marks for both technical execution and product design. Reinforced AGILE collaboration patterns that carried forward into professional work.',
    },
  },
];

export function getProjectBySlug(slug: string): Project | undefined {
  return projects.find((p) => p.slug === slug);
}

export function getProjectsByCategory(category: ProjectCategory): Project[] {
  return projects.filter((p) => p.categories.includes(category));
}

/** A sorted copy of `list` in display order (D12), lowest `order` first. */
export function sortByOrder(list: readonly Project[] = projects): Project[] {
  return [...list].sort((a, b) => a.order - b.order);
}

/** The first `n` featured projects, lowest `order` first. */
export function getTopProjects(n: number): Project[] {
  return sortByOrder(projects.filter((p) => p.featured)).slice(0, Math.max(0, n));
}

/** Every anchor id a project's case-study page renders (the five method steps first); [] without one. M7's link test uses it. */
export function getCaseStudyAnchors(project: Project): string[] {
  const cs = project.caseStudy;
  if (!cs) return [];
  return [
    'problem',
    ...methodSteps.map((step) => step.id),
    'method',
    ...(cs.decisions.length > 0 ? ['decisions'] : []),
    ...(cs.iterations && cs.iterations.length > 0 ? ['iterations'] : []),
    ...(cs.lessons.length > 0 ? ['lessons'] : []),
    'outcome',
    ...(cs.links.length > 0 ? ['links'] : []),
  ];
}

/** A link into `slug`'s page as this branch renders it: null when the project is missing, and the anchor kept only
 *  when the page renders it. `resolvedExamples` (/approach) and `resolvedItems` (/evidence) both go through it. */
export function resolveProjectLink(slug: string, anchor?: string): { slug: string; anchor?: string } | null {
  const project = getProjectBySlug(slug);
  if (!project) return null;
  return anchor && getCaseStudyAnchors(project).includes(anchor) ? { slug, anchor } : { slug };
}
