from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class GcpModelParams:
    """Generation parameters for Vertex AI Gemini models.

    Field names match litellm's OpenAI-compatible kwargs so the dataclass
    can be spread directly into `acompletion(**params.to_litellm_kwargs())`.
    """

    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_tokens: int | None = None
    stop: list[str] | None = None
    seed: int | None = None
    n: int | None = None
    response_format: dict | None = None
    extra: dict = field(default_factory=dict)

    def to_litellm_kwargs(self) -> dict:
        data = {k: v for k, v in asdict(self).items() if k != "extra" and v is not None}
        data.update(self.extra)
        return data

    @classmethod
    def from_dict(cls, data: dict | None) -> GcpModelParams:
        if not data:
            return cls()
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        kwargs = {k: v for k, v in data.items() if k in known}
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(**kwargs, extra=extra)
