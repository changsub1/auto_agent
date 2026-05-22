"""FastAPI adapter for the local multi-agent app services."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app_services import (
    ActiveStepInfo,
    AgentPromptConfig,
    AgentPromptOverride,
    ArtifactContent,
    ArtifactInfo,
    ArtifactService,
    ConfigService,
    ConfigSnapshot,
    EventService,
    LocalAppSettings,
    LogFileInfo,
    LogTail,
    ObservationService,
    OperatorActionRequest,
    PromptCatalog,
    PromptService,
    ProviderCliStatus,
    ProviderModelCatalog,
    ProviderService,
    RunCreateRequest,
    RunDetail,
    RunService,
    RunSummary,
    RuntimeHealthSnapshot,
    RuntimeUsageSnapshot,
    SettingsService,
    TimelineEvent,
)
from run_worker import RunWorker


PROJECT_ROOT = Path(__file__).resolve().parent


def create_app(project_root: Path | None = None) -> FastAPI:
    root = Path(project_root or PROJECT_ROOT)
    worker = RunWorker(root)
    run_service = RunService(root, worker=worker)
    event_service = EventService(root)
    artifact_service = ArtifactService(root)
    observation_service = ObservationService(root)
    config_service = ConfigService(root)
    provider_service = ProviderService(root)
    settings_service = SettingsService(root)
    prompt_service = PromptService(root)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await worker.start()
        app.state.run_worker = worker
        try:
            yield
        finally:
            await worker.stop()

    app = FastAPI(
        title="Orchestra Local API",
        version="15.0.0",
        description="Local-only API for the Codex multi-agent desktop app.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:1420",
            "http://localhost:1420",
            "tauri://localhost",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "scope": "local"}

    @app.get("/config", response_model=ConfigSnapshot)
    def config() -> ConfigSnapshot:
        return config_service.get_config()

    @app.get("/settings", response_model=LocalAppSettings)
    def settings() -> LocalAppSettings:
        return settings_service.get_settings()

    @app.put("/settings", response_model=LocalAppSettings)
    def save_settings(payload: LocalAppSettings) -> LocalAppSettings:
        return settings_service.save_settings(payload)

    @app.get("/prompts", response_model=PromptCatalog)
    def prompt_catalog() -> PromptCatalog:
        return prompt_service.catalog()

    @app.get("/prompts/{agent_id}", response_model=AgentPromptConfig)
    def get_prompt(agent_id: str) -> AgentPromptConfig:
        return prompt_service.get_prompt(agent_id)

    @app.put("/prompts/{agent_id}", response_model=AgentPromptConfig)
    def save_prompt(agent_id: str, payload: AgentPromptOverride) -> AgentPromptConfig:
        if payload.agent_id != agent_id:
            raise HTTPException(status_code=400, detail="payload agent_id must match path")
        return prompt_service.save_prompt(payload)

    @app.post("/prompts/{agent_id}/reset", response_model=AgentPromptConfig)
    def reset_prompt(agent_id: str) -> AgentPromptConfig:
        return prompt_service.reset_prompt(agent_id)

    @app.get("/providers", response_model=list[ProviderCliStatus])
    def providers() -> list[ProviderCliStatus]:
        return provider_service.list_providers()

    @app.get("/providers/codex/status", response_model=ProviderCliStatus)
    def codex_status() -> ProviderCliStatus:
        return provider_service.get_codex_status()

    @app.get("/providers/codex/models", response_model=ProviderModelCatalog)
    def codex_models(bundled: bool = False) -> ProviderModelCatalog:
        return provider_service.get_codex_models(bundled=bundled)

    @app.get("/providers/claude/status", response_model=ProviderCliStatus)
    def claude_status() -> ProviderCliStatus:
        return provider_service.get_claude_status()

    @app.get("/runtime/health", response_model=RuntimeHealthSnapshot)
    def runtime_health() -> RuntimeHealthSnapshot:
        return provider_service.get_runtime_health()

    @app.get("/runtime/usage", response_model=RuntimeUsageSnapshot)
    def runtime_usage() -> RuntimeUsageSnapshot:
        return provider_service.get_runtime_usage()

    @app.get("/runtime/usages", response_model=list[RuntimeUsageSnapshot])
    def runtime_usages() -> list[RuntimeUsageSnapshot]:
        return provider_service.get_runtime_usages()

    @app.get("/runs", response_model=list[RunSummary])
    def list_runs(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[RunSummary]:
        return run_service.list_runs(limit=limit)

    @app.post("/runs", response_model=RunDetail)
    async def create_run(payload: RunCreateRequest) -> RunDetail:
        try:
            return await run_service.create_run_and_enqueue(payload)
        except Exception as exc:  # noqa: BLE001 - convert service errors to HTTP.
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/runs/{run_id}", response_model=RunDetail)
    def get_run(run_id: str) -> RunDetail:
        try:
            return run_service.get_run(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/events", response_model=list[TimelineEvent])
    def get_events(run_id: str) -> list[TimelineEvent]:
        try:
            return event_service.list_events(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/active-step", response_model=ActiveStepInfo)
    def get_active_step(run_id: str) -> ActiveStepInfo:
        try:
            return observation_service.get_active_step(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/logs", response_model=list[LogFileInfo])
    def get_logs(run_id: str) -> list[LogFileInfo]:
        try:
            return observation_service.list_logs(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/logs/tail", response_model=LogTail)
    def get_log_tail(
        run_id: str,
        path: Annotated[str, Query(min_length=1)],
        lines: Annotated[int, Query(ge=1, le=1000)] = 200,
    ) -> LogTail:
        try:
            return observation_service.read_log_tail(run_id, path, lines=lines)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/artifacts", response_model=list[ArtifactInfo])
    def get_artifacts(run_id: str) -> list[ArtifactInfo]:
        try:
            return artifact_service.list_artifacts(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/artifacts/content", response_model=ArtifactContent)
    def get_artifact_content(run_id: str, path: Annotated[str, Query(min_length=1)]) -> ArtifactContent:
        try:
            return artifact_service.read_artifact(run_id, path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/approve", response_model=RunDetail)
    async def approve_run(
        run_id: str,
        payload: OperatorActionRequest | None = None,
    ) -> RunDetail:
        try:
            return await run_service.approve_and_enqueue(run_id, payload or OperatorActionRequest())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/request-changes", response_model=RunDetail)
    async def request_changes(
        run_id: str,
        payload: OperatorActionRequest | None = None,
    ) -> RunDetail:
        try:
            return await run_service.request_changes_and_enqueue(run_id, payload or OperatorActionRequest())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/cancel", response_model=RunDetail)
    async def cancel_run(
        run_id: str,
        payload: OperatorActionRequest | None = None,
    ) -> RunDetail:
        try:
            return await run_service.cancel_and_enqueue(run_id, payload or OperatorActionRequest())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/qa/approve", response_model=RunDetail)
    def approve_qa(
        run_id: str,
        payload: OperatorActionRequest | None = None,
    ) -> RunDetail:
        try:
            return run_service.approve_qa(run_id, payload or OperatorActionRequest())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/qa/request-fix", response_model=RunDetail)
    async def request_qa_fix(
        run_id: str,
        payload: OperatorActionRequest | None = None,
    ) -> RunDetail:
        try:
            return await run_service.request_qa_fix_and_enqueue(run_id, payload or OperatorActionRequest())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app


app = create_app()
