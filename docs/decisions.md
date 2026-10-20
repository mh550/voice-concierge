# Decisions

Michael's decisions (10-19) are D1–D6 and the builder's calls are B1–B12, both in `docs/spec.md` §3. New ones go here,
numbered from D7, as `D<n> *default*` when a session takes a default Michael hasn't confirmed: the finding, the
choice, what was rejected.

## D7 *default*: turn detection is silero VAD only (2026-10-20, C1-01)

**Finding.** B1 leaves the builder a choice between LiveKit's turn-detector model and VAD-only turn detection. In the
installed livekit-agents 1.8.8, `AgentSession` defaults to `turn_detection=inference.TurnDetector()` and
`vad=inference.VAD(model="silero")` (`voice/agent_session.py:576`, `:642`). Off LiveKit Cloud hosting, the detector
resolves to the local `turn-detector-v1-mini`, whose weights ship inside the `livekit-local-inference` wheel. It
needs no `download-files` step, and building it offline works with no keys. The cloud `v1` detector is used only
when hosted or in dev mode with keys, which spends the Build plan's development allowance.

**Choice.** VAD only: `vad=silero.VAD.load()` (the model ships in the plugin wheel, so there's no download at
import or in the suite) and `turn_handling={"turn_detection": "vad"}`, set explicitly because omitting it selects
the model detector. Reasons: it's the simplest and most predictable mode for the offline suite and the first
morning test, it never touches the hosted allowance, and there's no extra model in memory.

**Rejected (for now).** The turn-detector model (`inference.TurnDetector()`, or the separate turn-detector plugin).
It's better at not cutting people off mid-thought, and in 1.8.8 it needs no download. Switching is one line in
`concierge/worker.py` (drop the `turn_detection` key or pass `inference.TurnDetector()`). If the morning test shows
the agent interrupting pauses, switch.

**Question for Michael.** Keep VAD only, or switch to the local turn-detector model now that it needs no download?
