"""The SAP AI Core resolution cache: one token and one deployment lookup per process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections import Counter
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

import pytest
from litellm import acompletion
from litellm.types.utils import ModelResponse
from terrasentry_integrations import sap_ai_core


class _FakeAiCore(ThreadingHTTPServer):
    """Just enough of AI Core's auth, deployment and orchestration endpoints."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.hits: Counter[str] = Counter()
        self.deployments_fail = False
        self.stream_tool_call = False

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"


class _Handler(BaseHTTPRequestHandler):
    server: Any  # the _FakeAiCore that owns this handler

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _reply(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("content-length", 0)))
        if self.path.endswith("/oauth/token"):
            self.server.hits["token"] += 1
            # One hour, which is where LiteLLM's own 60-minute refresh buffer refetches every call.
            return self._reply({"access_token": "T", "expires_in": 3600})
        self.server.hits["completion"] += 1
        if self.server.stream_tool_call:
            return self._stream_tool_call()
        message = {"role": "assistant", "content": "ok"}
        choice = {"index": 0, "finish_reason": "stop", "message": message}
        result = {"id": "x", "object": "chat.completion", "created": 1, "model": "m", "choices": [choice]}
        self._reply({"request_id": "r", "intermediate_results": {}, "final_result": result})

    def _stream_tool_call(self) -> None:
        """Replay what the live orchestration service streams for a tool call (captured 2026-10-13).

        An empty opening chunk, the tool call arriving in fragments with an empty ``logprobs``
        object on each, then a final chunk with ``finish_reason`` and detailed token usage.
        """
        base = {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "m"}
        empty = {
            "id": "",
            "object": "",
            "created": 0,
            "model": "",
            "choices": [{"index": 0, "delta": {"content": ""}}],
        }

        def fragment(call: dict[str, Any], **extra: Any) -> dict[str, Any]:
            delta = {"role": "assistant", "content": "", "tool_calls": [call]}
            return {**base, "choices": [{"index": 0, "delta": delta, **extra}]}

        start = {"index": 0, "id": "c1", "type": "function", "function": {"name": "report", "arguments": ""}}
        usage = {
            "prompt_tokens": 125,
            "completion_tokens": 16,
            "total_tokens": 141,
            "prompt_tokens_details": {"audio_tokens": 0, "cached_tokens": 0},
            "completion_tokens_details": {
                "accepted_prediction_tokens": 0,
                "audio_tokens": 0,
                "reasoning_tokens": 0,
                "rejected_prediction_tokens": 0,
            },
        }
        last = {**base, "usage": usage}
        last["choices"] = [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": ""},
                "logprobs": {},
                "finish_reason": "tool_calls",
            }
        ]
        finals = [empty, fragment(start)]
        for part in ('{"', "status", '":"', "ok", '"}'):
            call = {"index": 0, "function": {"arguments": part}}
            finals.append(fragment(call, logprobs={}))
        finals.append(last)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for final in finals:
            event = {"request_id": "r", "intermediate_results": {}, "final_result": final}
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def do_GET(self) -> None:
        if self.path.endswith("/v2/lm/deployments"):
            self.server.hits["deployments"] += 1
            if self.server.deployments_fail:
                return self._reply({"resources": []})
            url = f"{self.server.base}/v2/inference/deployments/d8c092efb8980093"
            created = "2026-10-01T00:00:00Z"
            deployment = {
                "scenarioId": "orchestration",
                "configurationId": "c1",
                "createdAt": created,
                "deploymentUrl": url,
            }
            return self._reply({"resources": [deployment]})
        if "/v2/lm/configurations/" in self.path:
            self.server.hits["configuration"] += 1
            return self._reply({"executableId": "orchestration"})
        self._reply({}, 404)


@pytest.fixture
def aicore() -> Iterator[_FakeAiCore]:
    server = _FakeAiCore()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    assert sap_ai_core.install_resolution_cache()
    sap_ai_core.reset_resolution_cache()
    yield server
    server.shutdown()
    server.server_close()
    sap_ai_core.reset_resolution_cache()


def _key(server: _FakeAiCore, client_id: str = "cid") -> str:
    service_urls = {"AI_API_URL": server.base}
    return json.dumps(
        {"clientid": client_id, "clientsecret": "secret", "url": server.base, "serviceurls": service_urls}
    )


async def _call(key: str) -> str:
    response = await acompletion(
        model="sap/gpt-5.4", messages=[{"role": "user", "content": "ok?"}], api_key=key, num_retries=0
    )
    completion = cast(ModelResponse, response)
    return str(completion.choices[0].message.content)


async def test_repeated_calls_reuse_one_token_and_one_deployment_lookup(aicore: _FakeAiCore) -> None:
    key = _key(aicore)

    replies = [await _call(key) for _ in range(4)]

    assert replies == ["ok"] * 4
    assert aicore.hits["completion"] == 4
    assert aicore.hits["token"] == 1
    assert aicore.hits["deployments"] == 1
    assert aicore.hits["configuration"] == 1


async def test_a_different_service_key_resolves_on_its_own(aicore: _FakeAiCore) -> None:
    await _call(_key(aicore, "team-a"))
    await _call(_key(aicore, "team-b"))
    await _call(_key(aicore, "team-a"))

    assert aicore.hits["token"] == 2
    assert aicore.hits["deployments"] == 1


async def test_a_failed_deployment_lookup_is_not_cached(aicore: _FakeAiCore) -> None:
    key = _key(aicore)
    aicore.deployments_fail = True
    # LiteLLM wraps the missing-deployment IndexError in its own error type.
    with pytest.raises(Exception):  # noqa: B017
        await _call(key)

    aicore.deployments_fail = False
    assert await _call(key) == "ok"
    assert aicore.hits["deployments"] == 2


def test_the_cache_stays_off_when_litellm_internals_change(monkeypatch: pytest.MonkeyPatch) -> None:
    from litellm.llms.sap.chat import transformation

    monkeypatch.setattr(sap_ai_core, "_installed", False)
    monkeypatch.setattr(transformation, "GenAIHubOrchestrationConfig", object)

    assert sap_ai_core.install_resolution_cache() is False


_STREAM_SCRIPT = """
import asyncio, os, sys
import litellm
from terrasentry_integrations import sap_ai_core

if os.environ["PREPARE"] == "1":
    sap_ai_core.prepare_litellm()
tools = [{"type": "function", "function": {"name": "report", "description": "d",
          "parameters": {"type": "object", "properties": {"status": {"type": "string"}}}}}]

async def main():
    stream = await litellm.acompletion(
        model="sap/gpt-5.4", messages=[{"role": "user", "content": "go"}], tools=tools,
        api_key=os.environ["KEY"], stream=True, num_retries=0,
    )
    names, arguments = [], ""
    async for chunk in stream:
        for call in chunk.choices[0].delta.tool_calls or []:
            if call.function.name:
                names.append(call.function.name)
            arguments += call.function.arguments or ""
    print("tool calls:", names, arguments)

asyncio.run(main())
"""


def _stream_in_fresh_interpreter(aicore: _FakeAiCore, *, prepare: bool) -> subprocess.CompletedProcess[str]:
    aicore.stream_tool_call = True
    env = {**os.environ, "KEY": _key(aicore), "PREPARE": "1" if prepare else "0"}
    return subprocess.run(
        [sys.executable, "-c", _STREAM_SCRIPT], env=env, capture_output=True, text=True, timeout=120
    )


def test_streamed_tool_calls_survive_unbuilt_openai_models(aicore: _FakeAiCore) -> None:
    """A fresh interpreter, because pydantic builds these classes lazily and once per process."""
    result = _stream_in_fresh_interpreter(aicore, prepare=True)

    assert result.returncode == 0, result.stderr[-800:]
    assert """tool calls: ['report'] {"status":"ok"}""" in result.stdout
