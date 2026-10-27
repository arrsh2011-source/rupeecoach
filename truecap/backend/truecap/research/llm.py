"""Thin wrapper over the Anthropic SDK with cost accounting.

The pipeline depends on the `LLM` protocol, so tests run with a fake and no network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from truecap.config import MODEL_PRICES_USD, WEB_SEARCH_USD

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    web_searches: int = 0

    def cost_usd(self) -> float:
        price_in, price_out = MODEL_PRICES_USD.get(self.model, (0.0, 0.0))
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1e6 + self.web_searches * WEB_SEARCH_USD


@dataclass
class Citation:
    url: str
    title: str | None
    cited_text: str


@dataclass
class Finding:
    """A passage the model wrote, with the verbatim source snippets it cited."""

    text: str
    citations: list[Citation] = field(default_factory=list)


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    def web_research(self, system: str, prompt: str, max_searches: int) -> tuple[list[Finding], Usage]: ...

    def structured(self, system: str, prompt: str, schema: type[T], model: str) -> tuple[T, Usage]: ...


def _usage(model: str, raw: Any) -> Usage:
    u = getattr(raw, "usage", None)
    if u is None:
        return Usage(model=model)
    stu = getattr(u, "server_tool_use", None)
    return Usage(
        model=model,
        input_tokens=(u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
        + (getattr(u, "cache_creation_input_tokens", 0) or 0),
        output_tokens=u.output_tokens or 0,
        web_searches=(getattr(stu, "web_search_requests", 0) or 0) if stu else 0,
    )


class AnthropicLLM:
    """Production implementation. Reads ANTHROPIC_API_KEY (or the key passed in)."""

    MAX_PAUSE_RESUMES = 3

    def __init__(self, api_key: str | None, research_model: str, timeout: float = 300.0) -> None:
        import anthropic  # imported lazily so tests don't need the SDK configured

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2)
        self.research_model = research_model

    def web_research(self, system: str, prompt: str, max_searches: int) -> tuple[list[Finding], Usage]:
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        total = Usage(model=self.research_model)
        findings: list[Finding] = []
        for _ in range(self.MAX_PAUSE_RESUMES + 1):
            try:
                # Server-side fallback re-runs a declined request on another model inside the same call.
                resp = self.client.beta.messages.create(
                    model=self.research_model,
                    max_tokens=16000,
                    system=system,
                    messages=messages,
                    tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches,
                            "user_location": {"type": "approximate", "country": "IN"}}],
                    output_config={"effort": "medium"},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            except self._anthropic.APIError as e:
                raise LLMError(f"web research request failed: {e}") from e
            u = _usage(self.research_model, resp)
            total.input_tokens += u.input_tokens
            total.output_tokens += u.output_tokens
            total.web_searches += u.web_searches
            findings += _findings(resp.content)
            if resp.stop_reason == "refusal":
                raise LLMError("the model declined the research request")
            if resp.stop_reason != "pause_turn":
                break
            # Resume a paused server-tool loop: resend with the assistant turn, no extra user message.
            messages = [messages[0], {"role": "assistant", "content": resp.content}]
        return findings, total

    def structured(self, system: str, prompt: str, schema: type[T], model: str) -> tuple[T, Usage]:
        try:
            resp = self.client.messages.parse(
                model=model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            )
        except self._anthropic.APIError as e:
            raise LLMError(f"structured request failed: {e}") from e
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            raise LLMError(f"no structured output (stop_reason={resp.stop_reason})")
        return resp.parsed_output, _usage(model, resp)


def _findings(content: list[Any]) -> list[Finding]:
    out = []
    for block in content:
        if getattr(block, "type", None) != "text":
            continue
        cites = [
            Citation(url=c.url, title=getattr(c, "title", None), cited_text=c.cited_text)
            for c in (getattr(block, "citations", None) or [])
            if getattr(c, "type", "") == "web_search_result_location" and getattr(c, "cited_text", None)
        ]
        text = (block.text or "").strip()
        if text:
            out.append(Finding(text=text, citations=cites))
    return out
