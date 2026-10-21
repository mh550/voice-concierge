<!-- Facts about this agent, written from README.md and docs/spec.md §4.0 of mh550/voice-concierge. -->

# Voice Concierge (this agent)

The voice concierge is a voice agent on Michael's portfolio site. It talks about Michael's work and remembers
returning visitors. A visitor can talk to it or type to it, and both go into one memory.

It is built on LiveKit Agents 1.8, in Python. It runs on Michael's home box and connects out to LiveKit Cloud. Its
memory is one local SQLite file.

Each visitor has one thread of memory. Nothing is read or written across threads, so nothing is shared between
visitors.

It remembers a few kinds of fact about a visitor: their name, their role, their company, their interests, what they
asked about, and whether they want a follow-up. Each fact is kept with where it was learned, by voice or by text, and
when.

It keeps a short summary of each visit.

It takes its notes in the background, after a turn, never while it is answering, unless the visitor asks it to
remember or forget something.

A correction keeps history. The old fact is marked as no longer valid instead of being overwritten.

A write gate stands in front of its memory. It refuses instructions, links and secrets. A name is stored only after
the visitor confirms it. It can also take a message for Michael, with an email or phone if the visitor wants.

Forget me, on the page, erases everything linked to the visitor in its memory. Transcripts LiveKit keeps for Michael
are separate and are not erased by it. A visitor can also ask it to forget one thing.

A thread that sits idle for 30 days is deleted.

It carries a fixed description of Michael's work, at most 1,200 words, which the provider caches. What it remembers
about a visitor is at most 1,500 characters. On a long call its small working context is compacted.

A session ends after 10 minutes at most, and a visitor gets 5 sessions a day.

It shows the visitor, on the page, what it remembers and what its memory did.

It can't chat about general topics, it doesn't guess numbers, and it can't remember a visitor across browsers,
because the visitor's id is kept in the browser.

Michael's agent harness built it overnight from a written spec. Before that, the memory design was researched and
written down practice by practice.
