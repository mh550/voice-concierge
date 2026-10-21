# Michael Herron

## Positioning and contact
Source: resume-v4.md
Source: profile.ts

Michael Herron is an Agentic Systems Engineer based in Durham, NC. His line:
"I build the harnesses, memory and verification around AI agents, and the integrations they run on."
His tagline: "I build simple, elegant systems that fit the humans who run them." Email: mherron734@gmail.com.
LinkedIn: https://www.linkedin.com/in/mherron734/. GitHub: https://github.com/mh550. Website: www.mherron.dev. He
lists no phone number.

## About
Source: Bio.md
Source: resume-v4.md

Michael has a B.S. in Computer Science from Duke University. He is a full-stack engineer building agentic systems:
harness and context engineering, durable agent memory, and verification that agents can't bypass, on top of production
multi-tenant integrations. He has integrated platforms like JobTread, QuickBooks and GoHighLevel and has a strong
foundation in PostgreSQL. He uses Claude Code while keeping ownership of the code he ships. Outside of work he enjoys
snowboarding, skateboarding and wakeboarding.

## Experience
Source: resume-v4.md
Source: experience.ts

- Full-Stack Software Engineer at MAXX Potential, February 2026 to present. He ships React Native, Next.js,
  edge-function and Postgres features for a contractor estimating app, ~8 issues/week, and turned recurring UI
  fixes into a knowledge source agents load as procedural memory. He replaced spreadsheet bug tracking with Linear
  and an agentic bug-fix workflow: 2× sprint throughput and ~80% less bug-filing time, with no new software costs. He
  designed enterprise Copilot Studio agents, splitting an over-scoped job-description agent into one agent for
  managers and one for HR, so each holds only its own data.
- Founding Full-Stack Software Engineer at Builder Clarity, March 2025 to November 2025. He architected a
  multi-tenant JobTread ↔ GoHighLevel integration platform with managed multi-org OAuth, replacing per-client builds:
  3 clients, and onboarding cut from ~2 days to ~6 hours. He integrated CRM, VoIP through RingCentral, and internal
  systems, saving ~8 hrs/week per client, and built ETL normalizing 4+ sources into Postgres. As first engineer he led
  the move from Zapier to n8n and Pipedream.
- AI Workflow Engineer at Tahoma Films, February 2025: AI image generation workflows and trained LoRAs.
- Snowboard Coach at High Cascade Snowboard Camp, Summers 2023 & 2024, mentoring 12–18-year-old snowboarders.

## Education
Source: resume-v4.md

B.S. Computer Science, Visual & Media Studies Minor, at Duke University, graduated December 2024. Coursework included
Database Systems, Algorithm Design & Analysis, Computer Security, Server-side Web Apps and Computer Systems.

## Skills
Source: resume-v4.md

- Agentic AI: harness and context engineering, agent memory, durable state, eval gates, Claude Code.
- Languages & Web: TypeScript, Python, Bash, SQL, Java, C++, React, React Native, Next.js, Node.js.
- Data & Integration: PostgreSQL, Supabase, SQLite, REST, webhooks, OAuth 2.0, ETL, n8n, Pipedream.
- Infra & Tools: Docker Compose, Linux, Git and GitHub, CI/CD, Vercel, edge functions, Tailscale, Linear.

## Project: Voice Concierge (this agent)
Source: concierge.md

This is me: the voice agent on Michael's site. I talk about Michael's work and remember returning visitors, whether
they talk or type. I'm built on LiveKit Agents 1.8, in Python. I run on Michael's home box and connect out to LiveKit
Cloud, and my memory is one local SQLite file. Each visitor has one thread of memory, and nothing is shared between
visitors. I remember a few kinds of fact about a visitor: their name, role, company, interests, what they asked about,
and whether they want a follow-up. Each fact is kept with where I learned it, by voice or by text, and when. I keep a
short summary of each visit. I take my notes in the background, after a turn, never while I'm answering, unless a
visitor asks me to remember or forget something. A correction keeps history: the old fact is marked no longer valid
instead of being overwritten. A write gate refuses instructions, links and secrets, and I store a name only after the
visitor confirms it. I can also take a message for Michael, with an email or phone if the visitor wants. Forget me, on
the page, erases everything linked to the visitor in my memory. Transcripts LiveKit keeps for Michael are separate
and are not erased by it. A visitor can also ask me to forget one thing. A thread idle for 30 days is deleted. I
carry a fixed description of Michael's work, at most 1,200 words, which the provider caches, and what I remember
about a visitor is at most 1,500 characters. On a long call my small working context is compacted. A session ends
after 10 minutes at most, and a visitor gets 5 sessions a day. The page shows what I remember and what my memory did.
I can't chat about general topics, I don't guess numbers, and I can't remember a visitor across browsers. Michael's
agent harness built me overnight from a written spec, after the memory design was researched and written down
practice by practice.

## Project: Agent Harness
Source: projects.ts
Source: resume-v4.md

Personal and open source (https://github.com/mh550/agent-harness), October 2026 to present. A deterministic Bash
harness that runs Claude Code agents in isolated git worktrees and takes tests, verification and merges out of the
agent's hands, merging only verified trees. Each feature gets a fresh context window, rebuilt from state on disk,
with project rules as procedural memory and run retros as episodic memory. It runs on his home server, steered from
laptop or phone, and 189 features passed in 4 days at ~$3 each.

## Project: Self-hosted music library & DJ crate pipeline
Source: projects.ts
Source: resume-v4.md

Personal (https://github.com/mh550/dj-crate-streaming), November 2025 to present. A music library he hosts at home
and streams to his phone, with Docker Compose behind Tailscale. Flagging a playlist as a crate queues its missing
tracks; a worker downloads, verifies and files them. Only decode-identical audio is deduped, and the pipeline never
deletes from the library.

## Project: Linear Adoption + Agentic Bug Workflow
Source: projects.ts

At MAXX Potential. He moved QA from per-person spreadsheets to Linear, chosen partly for its MCP server, and wired it
into the team's Claude Code workflow, so bug filing, triage and duplicate detection became automated.

## Project: GoHighLevel ↔ JobTread Integration
Source: projects.ts

At Builder Clarity. A bidirectional integration between GoHighLevel CRM and JobTread for contractors, matching
people by phone, then email, then name so no one is created twice. It became the foundation of Builder Clarity's
productized offering.

## Project: HitList: offline-first street-spot scouting app
Source: projects.ts

Personal, an iPhone app built with Expo (https://github.com/mh550/hit-list). It logs street snowboard and skate
spots with cold hands and no signal: capture first, add the details later, everything stored on the phone. React
Native, TypeScript and SQLite, with 374 tests in 37 suites.

## Project: React Native Paint Estimator
Source: projects.ts

At MAXX Potential. A mobile app that lets paint estimators price a job by breaking it into areas, features and tasks.
He established the team's development paradigms and reusable modules.

## Project: RingCentral ↔ JobTread Integration
Source: projects.ts

At Builder Clarity. Synced calls and texts from RingCentral into JobTread, giving contractors one communication
history per customer. He led its migration from Zapier to n8n.
