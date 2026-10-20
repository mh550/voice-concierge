"""The offline eval twin's extractor LLMs (plan C4 "Offline eval twin"): visit n's FakeLLM replies once, with the
script's recorded_ops[n] (an emit_ops call, or text). Kept here, with the other fakes, so concierge.evals loads no
test code."""

from __future__ import annotations

from livekit.agents import llm

from concierge.evals.script import MemoryScript
from concierge.extractor import EMIT_OPS
from concierge.testing.fake_llm import FakeLLM, FakeResponse, FakeToolCall


class Replay:
    """An llm_factory for run_script. `llms` keeps every FakeLLM it built, in visit order, so a test can read what
    the extractor was actually sent (FakeLLM.calls)."""

    def __init__(self, script: MemoryScript) -> None:
        self.script = script
        self.llms: list[FakeLLM] = []

    def __call__(self, n: int) -> llm.LLM:
        reply = self.script.recorded_ops[n]
        if reply.ops is None:
            fake = FakeLLM([FakeResponse(text=reply.text)])
        else:
            call = FakeToolCall(name=EMIT_OPS.info.name, arguments={"ops": reply.ops})
            fake = FakeLLM([FakeResponse(tool_call=call)])
        self.llms.append(fake)
        return fake
