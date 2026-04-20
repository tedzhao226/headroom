import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from headroom.services.provider import LLMRequest, MockProvider, VertexPTClient


def make_request(**overrides) -> LLMRequest:
    base: LLMRequest = {
        "model": "gemini-2.5-flash",
        "messages": [{"role": "user", "content": "hello"}],
        "parameters": {},
    }
    base.update(overrides)
    return base


def make_litellm_response(content: str | None, prompt_tokens: int, completion_tokens: int) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.usage.prompt_tokens = prompt_tokens
    response.usage.completion_tokens = completion_tokens
    return response


async def test_mock_provider_returns_response() -> None:
    provider = MockProvider(latency_ms=(0, 0))
    request = make_request(messages=[{"role": "user", "content": "hi"}])
    result = await provider.call(request)
    assert result["output"] == "mock response"
    assert result["actual_token_count"] == int(2 + 2 * 1.5)


async def test_mock_provider_token_multiplier() -> None:
    provider = MockProvider(latency_ms=(0, 0), output_tokens_per_input=2.0)
    request = make_request(messages=[{"role": "user", "content": "abcd"}])
    result = await provider.call(request)
    assert result["actual_token_count"] == 4 + int(4 * 2.0)


async def test_mock_provider_always_fails() -> None:
    provider = MockProvider(latency_ms=(0, 0), failure_rate=1.0)
    with pytest.raises(RuntimeError, match="mock provider error"):
        await provider.call(make_request())


async def test_mock_provider_zero_failure_rate() -> None:
    provider = MockProvider(latency_ms=(0, 0), failure_rate=0.0)
    for _ in range(10):
        result = await provider.call(make_request())
        assert result["output"] == "mock response"


async def test_mock_provider_latency() -> None:
    provider = MockProvider(latency_ms=(50, 100))
    start = time.monotonic()
    await provider.call(make_request())
    elapsed_ms = (time.monotonic() - start) * 1000
    assert elapsed_ms >= 40


async def test_mock_provider_empty_messages() -> None:
    provider = MockProvider(latency_ms=(0, 0))
    result = await provider.call(make_request(messages=[]))
    assert result["actual_token_count"] == 0


@patch("headroom.services.provider.acompletion", new_callable=AsyncMock)
async def test_vertex_calls_acompletion_correctly(mock_acompletion: AsyncMock) -> None:
    mock_acompletion.return_value = make_litellm_response("reply", 5, 10)
    client = VertexPTClient(project="my-proj", region="us-central1", credentials=None, num_retries=2)
    request = make_request(parameters={"temperature": 0.7})
    await client.call(request)
    mock_acompletion.assert_awaited_once()
    kwargs = mock_acompletion.call_args.kwargs
    assert kwargs["model"] == "vertex_ai/gemini-2.5-flash"
    assert kwargs["vertex_project"] == "my-proj"
    assert kwargs["vertex_location"] == "us-central1"
    assert kwargs["num_retries"] == 2
    assert kwargs["extra_headers"] == {"X-Vertex-AI-LLM-Request-Type": "dedicated"}
    assert kwargs["temperature"] == 0.7


@patch("headroom.services.provider.acompletion", new_callable=AsyncMock)
async def test_vertex_extracts_output_and_tokens(mock_acompletion: AsyncMock) -> None:
    mock_acompletion.return_value = make_litellm_response("hello world", 10, 20)
    client = VertexPTClient(project="p", region="r", credentials=None)
    result = await client.call(make_request())
    assert result["output"] == "hello world"
    assert result["actual_token_count"] == 30


@patch("headroom.services.provider.acompletion", new_callable=AsyncMock)
async def test_vertex_handles_none_content(mock_acompletion: AsyncMock) -> None:
    mock_acompletion.return_value = make_litellm_response(None, 5, 0)
    client = VertexPTClient(project="p", region="r", credentials=None)
    result = await client.call(make_request())
    assert result["output"] == ""


@patch("headroom.services.provider.acompletion", new_callable=AsyncMock)
async def test_vertex_propagates_exception(mock_acompletion: AsyncMock) -> None:
    mock_acompletion.side_effect = RuntimeError("upstream error")
    client = VertexPTClient(project="p", region="r", credentials=None)
    with pytest.raises(RuntimeError, match="upstream error"):
        await client.call(make_request())
