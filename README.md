# voice-concierge

A voice agent that remembers returning visitors, built on LiveKit Agents. Being built; the design is in
[`docs/spec.md`](docs/spec.md).

## How to run

Michael runs the worker on his home box with `scripts/run-worker.sh` (added in C7), which reads the env file
`~/.config/voice-concierge/env` and starts `python -m concierge.worker start`. That file holds `LIVEKIT_URL`,
`LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` and `ANTHROPIC_API_KEY` (plus `OPENROUTER_API_KEY` only with
`CONCIERGE_LLM_PROVIDER=openrouter` and `DEEPGRAM_API_KEY` only with the speech fallback); the names are listed, empty, in `.env.example`, and no values are ever committed. The offline suite needs no
keys: `.harness/check.sh`.
