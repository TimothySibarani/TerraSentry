"""Make LiteLLM's ``sap/`` provider usable for agent runs.

Two problems show up with the real service, and ``prepare_litellm`` fixes both:

1. **Streamed tool calls crash.** The OpenAI SDK types LiteLLM puts inside a streamed chunk
   (``CompletionTokensDetails``, ``PromptTokensDetails``, ``ChoiceLogprobs``) are filled from the
   wire without validation, so pydantic never builds their serializers, and LiteLLM's
   ``chunk.model_dump()`` fails with ``'MockValSer' object is not an instance of 'SchemaSerializer'``.
   Strands streams every call, so every live agent run would fail. ``rebuild_openai_models`` builds
   those classes up front (about 60 ms). Seen on the live Claude and GPT deployments with LiteLLM
   1.96.0, openai 2.54.0 and pydantic 2.13.5; a plain, non-streaming call was unaffected.
2. **Per-call overhead.** See below.

LiteLLM's ``sap/`` provider builds a fresh config object for every completion. Each one
re-parses the service key, requests OAuth tokens (three of them in the measured replay), lists
``/lm/deployments`` and reads the orchestration configuration before it sends the real request.
An agent run makes dozens of calls, so that is roughly five wasted round trips per call and a lot
of pressure on the shared hackathon token endpoint.

``install_resolution_cache`` makes two changes to that config class, nothing else:

* the token creator (which caches the bearer token itself) and the base URL / resource group are
  resolved once per service key;
* the orchestration deployment URL is looked up once per ``(base URL, resource group)``.

It touches LiteLLM internals, so it is guarded: if the class or attributes it expects are not
there (a LiteLLM upgrade), it logs a warning, leaves LiteLLM untouched and returns ``False``.
``tests/test_sap_ai_core.py`` pins the request counts against a local fake AI Core server.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import threading
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

#: LiteLLM refreshes a token when less than this many minutes of life remain. Its own default
#: is 60, which refetches on every call whenever the issued token lives an hour or less.
TOKEN_REFRESH_BUFFER_MINUTES = 1

_lock = threading.Lock()
_installed = False
_resolved: dict[str | None, tuple[Callable[[], str], str, str]] = {}
_deployments: dict[tuple[str, str], str] = {}


def install_resolution_cache() -> bool:
    """Patch LiteLLM's SAP config once. Returns whether the cache is active."""
    global _installed
    with _lock:
        if _installed:
            return True
        try:
            from litellm.llms.sap.chat.handler import GenAIHubOrchestrationError
            from litellm.llms.sap.chat.transformation import GenAIHubOrchestrationConfig
            from litellm.llms.sap.credentials import get_token_creator

            config: Any = GenAIHubOrchestrationConfig
            find_deployment = config.__dict__["deployment_url"].func
            create_token_creator = get_token_creator
            error_class = GenAIHubOrchestrationError
        except (ImportError, AttributeError, KeyError) as exc:
            logger.warning("SAP AI Core resolution cache not installed (%s: %s)", type(exc).__name__, exc)
            return False

        def run_env_setup(self: Any, service_key: str | None = None) -> None:
            with _lock:
                resolved = _resolved.get(service_key)
            if resolved is None:
                try:
                    resolved = create_token_creator(
                        service_key, expiry_buffer_minutes=TOKEN_REFRESH_BUFFER_MINUTES
                    )
                except ValueError as err:
                    raise error_class(status_code=400, message=err.args[0]) from err
                with _lock:
                    _resolved[service_key] = resolved
            self.token_creator, self._base_url, self._resource_group = resolved

        def deployment_url(self: Any) -> str:
            key = (self.base_url, self.resource_group)
            with _lock:
                cached = _deployments.get(key)
            if cached is None:
                cached = find_deployment(self)
                with _lock:
                    _deployments[key] = cached
            return cached

        config.run_env_setup = run_env_setup
        config.deployment_url = property(deployment_url)
        _installed = True
        return True


#: OpenAI SDK modules whose models appear inside chat completions and their streamed chunks.
_OPENAI_CHAT_MODULES = (
    "openai.types.completion_usage",
    "openai.types.completion_choice",
    "openai.types.chat.chat_completion",
    "openai.types.chat.chat_completion_chunk",
    "openai.types.chat.chat_completion_message",
    "openai.types.chat.chat_completion_message_tool_call",
    "openai.types.chat.chat_completion_token_logprob",
)


def rebuild_openai_models() -> int:
    """Build the OpenAI SDK models LiteLLM leaves unbuilt; returns how many were rebuilt."""
    rebuilt = 0
    for name in _OPENAI_CHAT_MODULES:
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, BaseModel) and cls.__module__ == name and not cls.__pydantic_complete__:
                try:
                    cls.model_rebuild()
                    rebuilt += 1
                except Exception as exc:  # pydantic raises several types here; never block a run
                    logger.warning("could not rebuild %s.%s (%s)", name, cls.__name__, exc)
    return rebuilt


def prepare_litellm() -> bool:
    """Apply both fixes; call it before the first ``sap/`` completion. Returns the cache state."""
    rebuild_openai_models()
    return install_resolution_cache()


def reset_resolution_cache() -> None:
    """Forget resolved credentials and deployments (tests, or after rotating the key)."""
    with _lock:
        _resolved.clear()
        _deployments.clear()


__all__ = [
    "TOKEN_REFRESH_BUFFER_MINUTES",
    "install_resolution_cache",
    "prepare_litellm",
    "rebuild_openai_models",
    "reset_resolution_cache",
]
