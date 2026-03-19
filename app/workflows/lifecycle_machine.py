"""Explicit lifecycle transition inventory for reviewed draft content."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from typing import Literal

PublishedPointer = Literal["unchanged", "set_active", "clear"]
LifecycleAction = Literal["submit", "approve", "reject", "publish", "archive"]


@dataclass(frozen=True)
class LifecycleSnapshot:
    revision_status: str
    latest_action: str
    has_published_revision: bool
    published_revision_matches_active: bool


@dataclass(frozen=True)
class LifecycleEffects:
    set_status: str | None = None
    published_pointer: PublishedPointer = "unchanged"
    approval_action: str | None = None


@dataclass(frozen=True)
class LifecycleDecision:
    status: str
    ok: bool
    effects: LifecycleEffects = LifecycleEffects()


class _LifecycleRevisionLike(Protocol):
    status: str


class _LifecycleTrackLike(Protocol):
    active_revision_id: str
    published_revision_id: str
    revision: _LifecycleRevisionLike


def build_lifecycle_snapshot(track: _LifecycleTrackLike, latest_action: str) -> LifecycleSnapshot:
    published_revision_id = track.published_revision_id or ""
    return LifecycleSnapshot(
        revision_status=track.revision.status,
        latest_action=latest_action,
        has_published_revision=bool(published_revision_id),
        published_revision_matches_active=(
            published_revision_id == track.active_revision_id and bool(published_revision_id)
        ),
    )


def _published_repair(snapshot: LifecycleSnapshot) -> LifecycleDecision:
    pointer = "unchanged" if snapshot.published_revision_matches_active else "set_active"
    approval = None if snapshot.latest_action == "published" else "published"
    if pointer == "unchanged" and approval is None:
        return LifecycleDecision(status="already_published", ok=True)
    return LifecycleDecision(
        status="published",
        ok=True,
        effects=LifecycleEffects(
            published_pointer=pointer,
            approval_action=approval,
        ),
    )


def decide_lifecycle_action(snapshot: LifecycleSnapshot, action: LifecycleAction) -> LifecycleDecision:
    """Return the durable mutation required for one lifecycle action.

    The decision is explicit so retries can repair interrupted transitions
    instead of creating split durable state across status, publish pointer, and
    approval history.
    """

    status = snapshot.revision_status
    latest = snapshot.latest_action

    if action == "submit":
        if status == "draft":
            return LifecycleDecision(
                status="submitted",
                ok=True,
                effects=LifecycleEffects(set_status="review", approval_action="submitted"),
            )
        if status == "review":
            if latest == "submitted":
                return LifecycleDecision(status="already_submitted", ok=True)
            if latest == "approved":
                return LifecycleDecision(status="invalid_state", ok=False)
            return LifecycleDecision(
                status="submitted",
                ok=True,
                effects=LifecycleEffects(approval_action="submitted"),
            )
        return LifecycleDecision(status="invalid_state", ok=False)

    if action == "approve":
        if status == "review":
            if latest == "approved":
                return LifecycleDecision(status="already_approved", ok=True)
            return LifecycleDecision(
                status="approved",
                ok=True,
                effects=LifecycleEffects(approval_action="approved"),
            )
        return LifecycleDecision(status="invalid_state", ok=False)

    if action == "reject":
        if status == "review":
            return LifecycleDecision(
                status="rejected",
                ok=True,
                effects=LifecycleEffects(set_status="draft", approval_action="rejected"),
            )
        if status == "draft":
            if latest == "rejected":
                return LifecycleDecision(status="already_rejected", ok=True)
            if latest in {"submitted", "approved"}:
                return LifecycleDecision(
                    status="rejected",
                    ok=True,
                    effects=LifecycleEffects(approval_action="rejected"),
                )
        return LifecycleDecision(status="invalid_state", ok=False)

    if action == "publish":
        if status == "review" and latest == "approved":
            return LifecycleDecision(
                status="published",
                ok=True,
                effects=LifecycleEffects(
                    set_status="published",
                    published_pointer="set_active",
                    approval_action="published",
                ),
            )
        if status == "published" and latest in {"approved", "published"}:
            return _published_repair(snapshot)
        if status == "published" and snapshot.published_revision_matches_active:
            return LifecycleDecision(status="already_published", ok=True)
        if status in {"review", "published"}:
            return LifecycleDecision(status="approval_required", ok=False)
        return LifecycleDecision(status="invalid_state", ok=False)

    if action == "archive":
        pointer = "clear" if snapshot.has_published_revision else "unchanged"
        if status == "archived":
            if latest == "archived" and pointer == "unchanged":
                return LifecycleDecision(status="already_archived", ok=True)
            return LifecycleDecision(
                status="archived",
                ok=True,
                effects=LifecycleEffects(
                    published_pointer=pointer,
                    approval_action=None if latest == "archived" else "archived",
                ),
            )
        return LifecycleDecision(
            status="archived",
            ok=True,
            effects=LifecycleEffects(
                set_status="archived",
                published_pointer=pointer,
                approval_action="archived",
            ),
        )

    raise ValueError(f"Unknown lifecycle action: {action}")
