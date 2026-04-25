"""In-process rehearsal bot and session manager.

A rehearsal run is a real protocol run whose ``entry_authority_ref`` is the
reserved :data:`REHEARSAL_AUTHORITY_REF` and whose stage dispatches target the
reserved agent with role ``rehearsal``. That agent is this module's concern:

- :func:`ensure_rehearsal_agent` idempotently enrolls a reserved ``rehearsal``
  agent (slug=``rehearsal``, role=``rehearsal``, broad routing skills) into
  the same registry store the rest of the control plane uses. It caches the
  resulting token in process memory so subsequent polls can authenticate.

- :class:`RehearsalSessionManager` polls routed tasks for that agent, buffers
  each ``protocol-stage:*`` task as a *pending session*, and completes it via
  ``submit_task_result`` when the author responds from the UI panel.

External egress is inherently gated: rehearsal agents never run outbound
transports, webhooks, or credentialed providers; the author-supplied response
text is the stage output verbatim. Real participant bots are never selected
for a rehearsal run because ``ProtocolRunEngine.dispatch_target_selector``
rewrites the selector to ``role=rehearsal`` for rehearsal runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from octopus_sdk.protocols import ProtocolArtifactObservationRecord, REHEARSAL_AUTHORITY_REF
from octopus_sdk.registry.models import AgentCard, utcnow_iso

from .artifact_paths import resolve_workspace_artifact_target
from .store_base import AbstractRegistryStore

log = logging.getLogger(__name__)

REHEARSAL_AGENT_SLUG = "rehearsal"
REHEARSAL_AGENT_ROLE = "rehearsal"
REHEARSAL_AGENT_BOT_KEY = "registry.rehearsal"
REHEARSAL_AGENT_DISPLAY_NAME = "Rehearsal"
REHEARSAL_POLL_INTERVAL_SECONDS = 1.5
REHEARSAL_POLL_LIMIT = 32


@dataclass(slots=True)
class RehearsalPendingSession:
    """One stage dispatch awaiting an author response."""

    protocol_run_id: str
    stage_execution_id: str
    routed_task_id: str
    stage_key: str
    participant_key: str
    stage_kind: str
    instructions: str
    created_at: str
    workspace_ref: str = ""
    require_output_verification: bool = False
    output_artifacts: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "protocol_run_id": self.protocol_run_id,
            "stage_execution_id": self.stage_execution_id,
            "routed_task_id": self.routed_task_id,
            "stage_key": self.stage_key,
            "participant_key": self.participant_key,
            "stage_kind": self.stage_kind,
            "instructions": self.instructions,
            "workspace_ref": self.workspace_ref,
            "require_output_verification": bool(self.require_output_verification),
            "output_artifacts": list(self.output_artifacts),
            "created_at": self.created_at,
        }


@dataclass
class RehearsalSessionManager:
    """Owns the reserved rehearsal agent and its in-process task handler."""

    store: AbstractRegistryStore
    _agent_id: str = ""
    _agent_token: str = ""
    _poll_cursor: str = "0"
    _pending: dict[str, RehearsalPendingSession] = field(default_factory=dict)
    _pending_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _stop_event: asyncio.Event | None = None
    _task: asyncio.Task[None] | None = None

    @staticmethod
    def _heartbeat_payload() -> dict[str, Any]:
        return {
            "connectivity_state": "connected",
            "current_capacity": 0,
            "max_capacity": 16,
        }

    def ensure_agent(self) -> tuple[str, str]:
        """Idempotently enroll the reserved rehearsal agent; cache the token."""
        if self._agent_id and self._agent_token:
            return self._agent_id, self._agent_token
        card = AgentCard(
            bot_key=REHEARSAL_AGENT_BOT_KEY,
            display_name=REHEARSAL_AGENT_DISPLAY_NAME,
            slug=REHEARSAL_AGENT_SLUG,
            role=REHEARSAL_AGENT_ROLE,
            registry_scope="full",
            routing_skills=[REHEARSAL_AUTHORITY_REF, "*"],
            tags=["rehearsal"],
            description="In-process rehearsal participant for dry-run protocol authoring.",
            provider="registry",
            mode="registry",
            connectivity_state="connected",
            current_capacity=0,
            max_capacity=16,
            version="dev",
        )
        enrollment = self.store.enroll(card.model_dump(mode="json"))
        self._agent_id = str(enrollment.agent_id or "")
        self._agent_token = str(enrollment.agent_token or "")
        try:
            self.store.heartbeat(self._agent_token, self._heartbeat_payload())
        except Exception:
            log.warning("Rehearsal bot initial heartbeat failed", exc_info=True)
        return self._agent_id, self._agent_token

    @property
    def agent_id(self) -> str:
        return self._agent_id

    async def start(self) -> None:
        if self._task is not None:
            return
        await asyncio.to_thread(self.ensure_agent)
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._poll_loop(), name="registry-rehearsal-bot")

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self._poll_once_sync)
            except Exception:
                log.warning("Rehearsal bot poll iteration failed", exc_info=True)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=REHEARSAL_POLL_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                continue

    def _poll_once_sync(self) -> None:
        if not self._agent_token:
            return
        try:
            self.store.heartbeat(self._agent_token, self._heartbeat_payload())
            result = self.store.poll(
                self._agent_token,
                cursor=int(self._poll_cursor or "0") if str(self._poll_cursor).isdigit() else 0,
                limit=REHEARSAL_POLL_LIMIT,
            )
        except PermissionError:
            log.warning("Rehearsal bot token rejected; re-enrolling")
            self._agent_id = ""
            self._agent_token = ""
            self.ensure_agent()
            return
        deliveries = list(result.deliveries or [])
        for delivery in deliveries:
            cursor = str(getattr(delivery, "cursor", "") or "")
            if cursor:
                self._poll_cursor = cursor
            raw_payload = getattr(delivery, "payload", None)
            payload = (
                raw_payload.as_dict()
                if hasattr(raw_payload, "as_dict")
                else (raw_payload if isinstance(raw_payload, dict) else {})
            )
            kind = str(getattr(delivery, "kind", "") or "")
            if kind == "routed_task":
                self._record_pending_task(payload)
        next_cursor = str(getattr(result, "next_cursor", "") or "")
        if next_cursor:
            self._poll_cursor = next_cursor
        if deliveries:
            try:
                self.store.ack(
                    self._agent_token,
                    delivery_ids=[str(d.delivery_id) for d in deliveries],
                    classification="accepted",
                )
            except Exception:
                log.warning("Rehearsal bot ack failed", exc_info=True)

    def _record_pending_task(self, payload: dict[str, Any]) -> None:
        routed_task_id = str(payload.get("routed_task_id", "") or "")
        if not routed_task_id or not routed_task_id.startswith("protocol-stage:"):
            return
        raw_ctx = payload.get("context")
        context = (
            raw_ctx.as_dict()
            if hasattr(raw_ctx, "as_dict")
            else (raw_ctx if isinstance(raw_ctx, dict) else {})
        )
        raw_internal = payload.get("internal_context")
        internal_context = (
            raw_internal.as_dict()
            if hasattr(raw_internal, "as_dict")
            else (raw_internal if isinstance(raw_internal, dict) else {})
        )
        contract = internal_context.get("protocol_stage_contract")
        if not isinstance(contract, dict):
            contract = {}
        session = RehearsalPendingSession(
            protocol_run_id=str(context.get("protocol_run_id", "") or ""),
            stage_execution_id=str(context.get("protocol_stage_execution_id", "") or ""),
            routed_task_id=routed_task_id,
            stage_key=str(context.get("stage_key", "") or ""),
            participant_key=str(context.get("participant_key", "") or ""),
            stage_kind=str(contract.get("stage_kind", "") or "work"),
            instructions=str(payload.get("instructions", "") or ""),
            workspace_ref=str(payload.get("project_id_override", "") or ""),
            require_output_verification=bool(contract.get("require_output_verification", False)),
            output_artifacts=list(contract.get("output_artifacts", []) or []),
            created_at=str(payload.get("created_at", "") or ""),
        )
        self._pending[routed_task_id] = session
        log.info(
            "Rehearsal bot queued pending stage run=%s stage=%s task=%s",
            session.protocol_run_id,
            session.stage_key,
            routed_task_id,
        )

    def list_pending(self, *, protocol_run_id: str = "") -> list[RehearsalPendingSession]:
        target = str(protocol_run_id or "").strip()
        if not target:
            return list(self._pending.values())
        return [
            session
            for session in self._pending.values()
            if session.protocol_run_id == target
        ]

    def respond(
        self,
        *,
        routed_task_id: str,
        response_text: str,
        decision: str = "",
        decision_summary: str = "",
        artifacts: list[dict[str, Any]] | None = None,
        artifact_contents: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Submit an author response, closing the pending stage task.

        ``decision`` is the protocol stage decision (``completed``, ``accept``,
        ``revise``, ``fail``). When omitted, ``completed`` is used — which is
        the only valid transition for work stages. Review / acceptance stages
        require an explicit decision.
        """
        token = str(routed_task_id or "").strip()
        session = self._pending.get(token)
        if session is None:
            return False
        if not self._agent_token:
            self.ensure_agent()
        decision_token = str(decision or "").strip() or "completed"
        summary_token = str(decision_summary or "").strip() or "Rehearsal response submitted."
        body_lines = [str(response_text or "")]
        if decision_token and decision_token != "completed":
            body_lines.append(f"PROTOCOL_DECISION: {decision_token}")
        body_lines.append(f"PROTOCOL_SUMMARY: {summary_token}")
        full_text = "\n".join(line for line in body_lines if line)
        inline_artifact_contents = self._normalized_artifact_contents(
            session=session,
            artifact_contents=artifact_contents or [],
        )
        artifact_observations = [
            ProtocolArtifactObservationRecord.model_validate(item).model_dump(mode="json")
            for item in (artifacts or [])
        ]
        explicit_keys = {
            str(item.get("artifact_key", "") or "").strip()
            for item in inline_artifact_contents
            if str(item.get("artifact_key", "") or "").strip()
        }
        if explicit_keys:
            artifact_observations.extend(
                self._artifact_observations_from_contents(
                    session=session,
                    artifact_contents=inline_artifact_contents,
                )
            )
        artifact_observations.extend(
            self._synthesized_artifact_observations(
                session=session,
                response_text=response_text,
                exclude_artifact_keys=explicit_keys,
            )
        )
        for item in inline_artifact_contents:
            self._materialize_workspace_artifact(session=session, artifact_content=item)
        payload = {
            "routed_task_id": token,
            "status": "completed",
            "transition_id": uuid.uuid4().hex,
            "summary": summary_token,
            "full_text": full_text,
            "artifacts": artifact_observations,
            "artifact_contents": inline_artifact_contents,
        }
        try:
            self.store.update_routed_task_result(self._agent_token, token, payload)
        except Exception:
            log.warning("Rehearsal bot failed to submit task result %s", token, exc_info=True)
            return False
        self._pending.pop(token, None)
        return True

    @staticmethod
    def _synthesized_artifact_observations(
        *,
        session: RehearsalPendingSession,
        response_text: str,
        exclude_artifact_keys: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        outputs = list(session.output_artifacts or [])
        if not outputs:
            return []
        observed_at = str(session.created_at or "").strip() or utcnow_iso()
        digest_source = str(response_text or "")
        excluded = {str(item or "").strip() for item in (exclude_artifact_keys or set()) if str(item or "").strip()}
        observations: list[dict[str, Any]] = []
        for item in outputs:
            artifact_key = str(item.get("artifact_key", "") or "").strip()
            if not artifact_key or artifact_key in excluded:
                continue
            hashed = hashlib.sha256(f"{artifact_key}\n{digest_source}".encode("utf-8")).hexdigest()
            observations.append(
                ProtocolArtifactObservationRecord(
                    artifact_key=artifact_key,
                    artifact_kind=str(item.get("artifact_kind", "") or "workspace_file"),
                    path=str(item.get("path", "") or ""),
                    exists=True,
                    size_bytes=len(digest_source.encode("utf-8")),
                    content_hash=hashed,
                    modified_at=observed_at,
                    observed_at=observed_at,
                    verification_state="verified" if session.require_output_verification else "available",
                ).model_dump(mode="json")
            )
        return observations

    @staticmethod
    def _normalized_artifact_contents(
        *,
        session: RehearsalPendingSession,
        artifact_contents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        definitions = {
            str(item.get("artifact_key", "") or "").strip(): item
            for item in (session.output_artifacts or [])
            if str(item.get("artifact_key", "") or "").strip()
        }
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in artifact_contents or []:
            if not isinstance(raw, dict):
                continue
            artifact_key = str(raw.get("artifact_key", "") or "").strip()
            if not artifact_key or artifact_key in seen:
                continue
            definition = definitions.get(artifact_key, {})
            normalized.append({
                "artifact_key": artifact_key,
                "artifact_kind": str(raw.get("artifact_kind", "") or definition.get("artifact_kind", "") or "workspace_file"),
                "path": str(raw.get("path", "") or definition.get("path", "") or ""),
                "content": str(raw.get("content", "") or ""),
            })
            seen.add(artifact_key)
        return normalized

    @staticmethod
    def _artifact_observations_from_contents(
        *,
        session: RehearsalPendingSession,
        artifact_contents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        observed_at = utcnow_iso()
        observations: list[dict[str, Any]] = []
        for item in artifact_contents:
            artifact_key = str(item.get("artifact_key", "") or "").strip()
            if not artifact_key:
                continue
            content = str(item.get("content", "") or "")
            hashed = hashlib.sha256(f"{artifact_key}\n{content}".encode("utf-8")).hexdigest()
            observations.append(
                ProtocolArtifactObservationRecord(
                    artifact_key=artifact_key,
                    artifact_kind=str(item.get("artifact_kind", "") or "workspace_file"),
                    path=str(item.get("path", "") or ""),
                    exists=True,
                    size_bytes=len(content.encode("utf-8")),
                    content_hash=hashed,
                    modified_at=observed_at,
                    observed_at=observed_at,
                    verification_state="verified" if session.require_output_verification else "available",
                ).model_dump(mode="json")
            )
        return observations

    @staticmethod
    def _materialize_workspace_artifact(
        *,
        session: RehearsalPendingSession,
        artifact_content: dict[str, Any],
    ) -> None:
        artifact_kind = str(artifact_content.get("artifact_kind", "") or "workspace_file").strip()
        artifact_path = str(artifact_content.get("path", "") or "").strip()
        if artifact_kind != "workspace_file" or not artifact_path:
            return
        target_path = resolve_workspace_artifact_target(
            workspace_ref=str(session.workspace_ref or "").strip(),
            artifact_path=artifact_path,
        )
        if target_path is None:
            return
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(str(artifact_content.get("content", "") or ""), encoding="utf-8")
        except OSError:
            log.warning(
                "Rehearsal bot failed to materialize artifact path=%s run=%s stage=%s",
                artifact_path,
                session.protocol_run_id,
                session.stage_key,
                exc_info=True,
            )
