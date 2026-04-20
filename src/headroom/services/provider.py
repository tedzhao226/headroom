import asyncio
import random
from typing import Protocol, TypedDict

from litellm import acompletion

from headroom.core.params import GcpModelParams


class LLMRequest(TypedDict):
    model: str
    messages: list[dict]
    parameters: dict | GcpModelParams


class LLMResponse(TypedDict):
    output: str
    actual_token_count: int


class Provider(Protocol):
    async def call(self, request: LLMRequest) -> LLMResponse: ...


class VertexPTClient:
    def __init__(
        self,
        project: str,
        region: str,
        credentials,
        num_retries: int = 3,
    ) -> None:
        self._project = project
        self._region = region
        self._credentials = credentials
        self._num_retries = num_retries

    async def call(self, request: LLMRequest) -> LLMResponse:
        raw = request["parameters"]
        params = raw if isinstance(raw, GcpModelParams) else GcpModelParams.from_dict(raw)
        response = await acompletion(
            model=f"vertex_ai/{request['model']}",
            messages=request["messages"],
            num_retries=self._num_retries,
            vertex_project=self._project,
            vertex_location=self._region,
            extra_headers={"X-Vertex-AI-LLM-Request-Type": "dedicated"},
            **params.to_litellm_kwargs(),
        )
        content = response.choices[0].message.content
        output = content if content is not None else ""
        usage = response.usage
        actual_tokens = (usage.prompt_tokens or 0) + (usage.completion_tokens or 0)
        return LLMResponse(output=output, actual_token_count=actual_tokens)


class MockProvider:
    def __init__(
        self,
        latency_ms: tuple[int, int] = (100, 500),
        failure_rate: float = 0.0,
        output_tokens_per_input: float = 1.5,
    ) -> None:
        self._latency_ms = latency_ms
        self._failure_rate = failure_rate
        self._output_tokens_per_input = output_tokens_per_input

    async def call(self, request: LLMRequest) -> LLMResponse:
        lo, hi = self._latency_ms
        if hi > 0:
            await asyncio.sleep(random.uniform(lo, hi) / 1000)
        if random.random() < self._failure_rate:
            raise RuntimeError("mock provider error")
        input_tokens = sum(len(m.get("content", "")) for m in request["messages"])
        output_tokens = int(input_tokens * self._output_tokens_per_input)
        return LLMResponse(
            output="mock response",
            actual_token_count=input_tokens + output_tokens,
        )
