"""Adverse media is cited context: uncited findings are dropped and failures are never cached."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any

from terrasentry_integrations.cache import MemoryCache
from terrasentry_integrations.sources.media import (
    AdverseMediaClient,
    StubMediaClient,
    parse_report,
    response_sources,
)

REPLY = {
    "summary": "One report of a land dispute.",
    "findings": [
        {
            "claim": "Villagers disputed a concession.",
            "sources": [
                {"url": "https://news.example/a", "title": "Land dispute", "published": "2026-01-02"}
            ],
        },
        {"claim": "Uncited rumour.", "sources": []},
        {"claim": "Bad scheme.", "sources": [{"url": "javascript:alert(1)"}]},
    ],
}


def fake_completion(content: str, *, search_results: list[Any] | None = None) -> Any:
    calls: list[dict[str, Any]] = []

    async def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], search_results=search_results)

    completion.calls = calls  # type: ignore[attr-defined]
    return completion


def client(completion: Any, cache: MemoryCache | None = None) -> AdverseMediaClient:
    return AdverseMediaClient(
        credentials='{"clientid":"x"}', model="sonar", cache=cache or MemoryCache(), completion=completion
    )


async def test_search_keeps_only_cited_findings_and_calls_the_sap_route() -> None:
    completion = fake_completion(json.dumps(REPLY))
    report = await client(completion).search("PT Sumber", "ID", as_of=date(2026, 10, 1))

    assert report.status == "success"
    assert [finding.claim for finding in report.findings] == ["Villagers disputed a concession."]
    assert report.findings[0].citations[0].url == "https://news.example/a"
    assert report.synthetic is False
    call = completion.calls[0]
    assert call["model"] == "sap/sonar"
    assert call["api_key"] == '{"clientid":"x"}'


async def test_provider_search_results_enrich_titles() -> None:
    reply = {"summary": "", "findings": [{"claim": "c", "sources": [{"url": "https://news.example/a"}]}]}
    completion = fake_completion(
        json.dumps(reply),
        search_results=[{"url": "https://news.example/a", "title": "From provider", "date": "2026-02-03"}],
    )
    report = await client(completion).search("PT Sumber", "ID")

    citation = report.findings[0].citations[0]
    assert (citation.title, citation.published) == ("From provider", "2026-02-03")
    assert report.response_citations == 1


async def test_fenced_json_is_parsed() -> None:
    fenced = "```json\n" + json.dumps(REPLY) + "\n```"
    summary, findings = parse_report(fenced, {})
    assert summary == "One report of a land dispute."
    assert len(findings) == 1


async def test_cache_replay_makes_no_second_call() -> None:
    cache = MemoryCache()
    completion = fake_completion(json.dumps(REPLY))
    first = await client(completion, cache).search("PT Sumber", "ID")
    cache.offline = True
    second = await client(completion, cache).search("pt  sumber", "id")

    assert (first.cached, second.cached) == (False, True)
    assert second.findings == first.findings
    assert len(completion.calls) == 1


async def test_refresh_bypasses_the_cache() -> None:
    cache = MemoryCache()
    completion = fake_completion(json.dumps(REPLY))
    await client(completion, cache).search("PT Sumber", "ID")
    await client(completion, cache).search("PT Sumber", "ID", refresh=True)
    assert len(completion.calls) == 2


async def test_failures_become_unavailable_and_are_not_cached() -> None:
    cache = MemoryCache()

    async def boom(**_: Any) -> Any:
        raise RuntimeError("provider down")

    report = await client(boom, cache).search("PT Sumber", "ID")
    assert report.status == "unavailable"
    assert "provider down" in (report.error or "")
    assert cache.stats().writes == 0


async def test_unparseable_reply_is_unavailable() -> None:
    report = await client(fake_completion("sorry, no json")).search("PT Sumber", "ID")
    assert report.status == "unavailable"
    assert report.error is not None


async def test_offline_miss_is_unavailable() -> None:
    cache = MemoryCache(offline=True)
    completion = fake_completion(json.dumps(REPLY))
    report = await client(completion, cache).search("PT Sumber", "ID")
    assert report.status == "unavailable"
    assert completion.calls == []


async def test_stub_is_deterministic_and_labelled_synthetic() -> None:
    first = await StubMediaClient().search("PT Sumber", "ID")
    second = await StubMediaClient().search("PT Sumber", "ID")
    assert first == second
    assert first.synthetic is True
    assert first.disclosure
    assert first.findings[0].citations


def test_response_sources_accepts_plain_url_lists() -> None:
    found = response_sources(SimpleNamespace(citations=["https://a.example/x", "ftp://bad", 3]))
    assert list(found) == ["https://a.example/x"]
