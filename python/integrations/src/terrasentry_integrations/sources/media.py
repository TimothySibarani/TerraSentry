"""Adverse-media context from a web-search model (Perplexity Sonar on SAP AI Core).

This layer is **context only**. Its output is kept out of the evidence ledger, the findings and the
fingerprint, so the rubric verdict stays deterministic; the agent may quote it with URLs and the
cockpit shows it beside the assessment. Every finding must carry at least one source URL; findings
without one are dropped. Results are cached like the other sources so a rehearsal replays offline.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from terrasentry_integrations.cache import CacheBackend, CacheEntry, geometry_hash
from terrasentry_integrations.errors import IntegrationError

SOURCE = "adverse_media"
PROMPT_REVISION = "adverse-media-1"
DEFAULT_TIMEOUT_SECONDS = 45.0

_MAX_FINDINGS = 8
_MAX_SUMMARY = 1200
_MAX_CLAIM = 400
_MAX_TITLE = 200
_SIMULATED = "Simulated adverse-media result; no web search was performed."

SYSTEM_PROMPT = (
    "You are a due-diligence research assistant for EU deforestation-regulation (EUDR) compliance. "
    "Search the web for credible, recent reporting that links the named company to illegal logging, "
    "deforestation, land-rights disputes, forced labour, sanctions, or corruption. Report only what "
    "sources actually say; never speculate and never invent URLs. Reply with a single JSON object and "
    'nothing else: {"summary": str, "findings": [{"claim": str, "sources": '
    '[{"url": str, "title": str, "published": str|null}]}]}. Use an empty findings list when you find '
    "nothing credible."
)


class MediaCitation(BaseModel):
    url: str
    title: str = ""
    published: str | None = None


class MediaFinding(BaseModel):
    claim: str
    citations: list[MediaCitation] = Field(min_length=1)


class AdverseMediaReport(BaseModel):
    """Cited adverse-media findings for one subject. Context only; never a scoring input."""

    subject: str
    country: str | None = None
    status: Literal["success", "unavailable"] = "unavailable"
    summary: str = ""
    findings: list[MediaFinding] = Field(default_factory=list)
    model: str = ""
    prompt_revision: str = PROMPT_REVISION
    query_hash: str = ""
    synthetic: bool = False
    disclosure: str | None = None
    #: Number of response-level citations/search results the provider returned (diagnostic).
    response_citations: int = 0
    fetched_at: datetime | None = None
    cached: bool = False
    error: str | None = None


class MediaSearch(Protocol):
    """Adverse-media lookup contract shared by the live client and the stub."""

    async def search(
        self,
        subject: str,
        country: str | None,
        *,
        as_of: date | None = None,
        refresh: bool = False,
    ) -> AdverseMediaReport: ...


Completion = Callable[..., Awaitable[Any]]


def _query_hash(subject: str, country: str | None, model: str) -> str:
    return geometry_hash(
        {
            "subject": " ".join(subject.lower().split()),
            "country": (country or "").upper(),
            "model": model,
            "revision": PROMPT_REVISION,
        }
    )


def _http_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value.strip())
    return value.strip() if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _field(source: object, name: str) -> Any:
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


def response_sources(response: object) -> dict[str, MediaCitation]:
    """Collect provider-level citations (``citations`` / ``search_results``), keyed by URL."""
    found: dict[str, MediaCitation] = {}
    for name in ("search_results", "citations"):
        for item in _field(response, name) or []:
            raw = item if isinstance(item, str) else _field(item, "url")
            url = _http_url(raw)
            if url is None:
                continue
            found[url] = MediaCitation(
                url=url,
                title=str(_field(item, "title") or "")[:_MAX_TITLE] if not isinstance(item, str) else "",
                published=_field(item, "date") if not isinstance(item, str) else None,
            )
    return found


def _extract_json(text: str) -> dict[str, Any]:
    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = fenced.find("{"), fenced.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model reply contained no JSON object")
    parsed = json.loads(fenced[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model reply was not a JSON object")
    return parsed


def parse_report(text: str, known: dict[str, MediaCitation]) -> tuple[str, list[MediaFinding]]:
    """Parse a model reply into cited findings; uncited findings and non-http URLs are dropped."""
    payload = _extract_json(text)
    findings: list[MediaFinding] = []
    for item in payload.get("findings") or []:
        if not isinstance(item, dict) or not isinstance(item.get("claim"), str):
            continue
        citations: list[MediaCitation] = []
        for source in item.get("sources") or []:
            url = _http_url(_field(source, "url"))
            if url is None:
                continue
            enriched = known.get(url)
            title = str(_field(source, "title") or (enriched.title if enriched else ""))[:_MAX_TITLE]
            published = _field(source, "published") or (enriched.published if enriched else None)
            citations.append(MediaCitation(url=url, title=title, published=published))
        if citations:
            findings.append(MediaFinding(claim=item["claim"].strip()[:_MAX_CLAIM], citations=citations))
        if len(findings) == _MAX_FINDINGS:
            break
    summary = payload.get("summary")
    return (summary.strip()[:_MAX_SUMMARY] if isinstance(summary, str) else ""), findings


async def _litellm_completion(**kwargs: Any) -> Any:
    from litellm import acompletion

    return await acompletion(**kwargs)


class AdverseMediaClient:
    """Live adverse-media lookup through LiteLLM's ``sap/`` route (Sonar on AI Core)."""

    def __init__(
        self,
        *,
        credentials: str,
        model: str,
        cache: CacheBackend,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        completion: Completion | None = None,
    ) -> None:
        self._credentials = credentials
        self._model = model
        self._cache = cache
        self._timeout = timeout
        self._completion = completion or _litellm_completion

    async def search(
        self,
        subject: str,
        country: str | None,
        *,
        as_of: date | None = None,
        refresh: bool = False,
    ) -> AdverseMediaReport:
        digest = _query_hash(subject, country, self._model)
        window = f"sonar:{PROMPT_REVISION}:{as_of.isoformat() if as_of else 'latest'}"
        base = AdverseMediaReport(subject=subject, country=country, model=self._model, query_hash=digest)
        try:
            if not refresh:
                entry = await self._cache.get(SOURCE, digest, window)
                if entry is not None:
                    return AdverseMediaReport.model_validate(entry.payload).model_copy(
                        update={"cached": True}
                    )
            where = f" operating in {country}" if country else ""
            response = await self._completion(
                model=f"sap/{self._model}",
                api_key=self._credentials,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Company: {subject}{where}."},
                ],
                temperature=0.2,
                timeout=self._timeout,
                num_retries=1,
            )
            known = response_sources(response)
            content = response.choices[0].message.content or ""
            summary, findings = parse_report(content, known)
            timestamp = datetime.now(tz=UTC)
            result = base.model_copy(
                update={
                    "status": "success",
                    "summary": summary,
                    "findings": findings,
                    "response_citations": len(known),
                    "fetched_at": timestamp,
                }
            )
            await self._cache.set(
                CacheEntry(
                    source=SOURCE,
                    geometry_hash=digest,
                    date_window=window,
                    request={"model": self._model, "prompt_revision": PROMPT_REVISION},
                    fetched_at=timestamp,
                    payload=result.model_dump(mode="json"),
                )
            )
            return result
        except (IntegrationError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            return base.model_copy(update={"error": f"{type(exc).__name__}: {exc}"})
        except Exception as exc:
            # Provider errors (auth, rate limit, timeout) come from litellm; never fail a run on context.
            return base.model_copy(update={"error": f"{type(exc).__name__}: {exc}"[:300]})


class StubMediaClient:
    """Deterministic, clearly simulated adverse-media result for offline demos and tests."""

    async def search(
        self,
        subject: str,
        country: str | None,
        *,
        as_of: date | None = None,
        refresh: bool = False,
    ) -> AdverseMediaReport:
        return AdverseMediaReport(
            subject=subject,
            country=country,
            status="success",
            summary=f"Simulated media scan for {subject}: one illustrative finding.",
            findings=[
                MediaFinding(
                    claim=f"Simulated report of a land-use dispute involving {subject}.",
                    citations=[
                        MediaCitation(
                            url="https://example.org/simulated-adverse-media",
                            title="Simulated source (not a real article)",
                        )
                    ],
                )
            ],
            model="stub",
            query_hash=_query_hash(subject, country, "stub"),
            synthetic=True,
            disclosure=_SIMULATED,
        )


__all__ = [
    "PROMPT_REVISION",
    "SYSTEM_PROMPT",
    "AdverseMediaClient",
    "AdverseMediaReport",
    "MediaCitation",
    "MediaFinding",
    "MediaSearch",
    "StubMediaClient",
    "parse_report",
    "response_sources",
]
