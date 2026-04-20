from headroom.core.params import GcpModelParams


def test_empty_params_produces_empty_kwargs() -> None:
    assert GcpModelParams().to_litellm_kwargs() == {}


def test_known_fields_round_trip() -> None:
    params = GcpModelParams(temperature=0.7, top_p=0.9, max_tokens=1024)
    assert params.to_litellm_kwargs() == {
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 1024,
    }


def test_none_fields_are_dropped() -> None:
    params = GcpModelParams(temperature=0.5, top_k=None)
    kwargs = params.to_litellm_kwargs()
    assert "top_k" not in kwargs
    assert kwargs["temperature"] == 0.5


def test_from_dict_splits_known_and_extra() -> None:
    params = GcpModelParams.from_dict({"temperature": 0.2, "custom_flag": "x"})
    assert params.temperature == 0.2
    assert params.extra == {"custom_flag": "x"}


def test_extra_passes_through_to_kwargs() -> None:
    params = GcpModelParams(temperature=0.1, extra={"tool_choice": "auto"})
    kwargs = params.to_litellm_kwargs()
    assert kwargs == {"temperature": 0.1, "tool_choice": "auto"}


def test_from_dict_handles_none() -> None:
    assert GcpModelParams.from_dict(None) == GcpModelParams()
    assert GcpModelParams.from_dict({}) == GcpModelParams()
