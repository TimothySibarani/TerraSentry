"""A2A server exposing the TerraSentry skills to SAP Joule (Pro-Code agent on Cloud Foundry)."""

from __future__ import annotations

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps.jsonrpc import A2AFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Artifact,
    Part,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from fastapi import FastAPI

from terrasentry_a2a.client import TerraSentryClient
from terrasentry_a2a.settings import A2ASettings, get_a2a_settings
from terrasentry_a2a.skills import Skills

_NO_INPUT = "Tell me which supplier to screen, for example `screen PT Sumber Sejahtera Sriwijaya`."


class TerraSentryExecutor(AgentExecutor):
    """Bridges the A2A task lifecycle to the TerraSentry skills."""

    def __init__(self, skills: Skills) -> None:
        self._skills = skills

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id, context_id = context.task_id or "", context.context_id or ""
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
            )
        )
        text = context.get_user_input().strip()
        reply = await self._skills.handle(text) if text else _NO_INPUT
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=Artifact(
                    artifact_id="terrasentry_reply",
                    name="terrasentry_reply",
                    parts=[Part(root=TextPart(text=reply))],
                ),
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.completed),
                final=True,
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id or "",
                context_id=context.context_id or "",
                status=TaskStatus(state=TaskState.canceled),
                final=True,
            )
        )


def build_agent_card(settings: A2ASettings) -> AgentCard:
    markdown = ["text/markdown"]
    return AgentCard(
        name="TerraSentry EUDR Assistant",
        description=(
            "Screens suppliers for EU Deforestation Regulation risk, starts AI-agent investigations, "
            "and reports run status. Verdicts come from a deterministic rubric, never from a model."
        ),
        url=settings.public_url,
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain"],
        default_output_modes=markdown,
        skills=[
            AgentSkill(
                id="screen",
                name="Screen a supplier",
                description="Deterministic EUDR screening of a supplier by name, supplier id, or record id.",
                tags=["eudr", "screening", "deforestation"],
                examples=["screen PT Sumber Sejahtera Sriwijaya", "screen SUP-001"],
                input_modes=["text/plain"],
                output_modes=markdown,
            ),
            AgentSkill(
                id="investigate",
                name="Investigate with AI agents",
                description="Starts a live multi-agent investigation and returns a link to follow it.",
                tags=["eudr", "agents", "investigation"],
                examples=["investigate SUP-001"],
                input_modes=["text/plain"],
                output_modes=markdown,
            ),
            AgentSkill(
                id="status",
                name="Check run status",
                description="Summarises a run or batch by id.",
                tags=["eudr", "status"],
                examples=["status run-1a2b3c4d5e6f"],
                input_modes=["text/plain"],
                output_modes=markdown,
            ),
        ],
    )


def create_app(settings: A2ASettings | None = None, client: TerraSentryClient | None = None) -> FastAPI:
    resolved = settings or get_a2a_settings()
    api = client or TerraSentryClient(resolved.terrasentry_api_url, resolved.terrasentry_api_token)
    handler = DefaultRequestHandler(
        agent_executor=TerraSentryExecutor(Skills(api, resolved)),
        task_store=InMemoryTaskStore(),
    )
    app = A2AFastAPIApplication(agent_card=build_agent_card(resolved), http_handler=handler).build()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
