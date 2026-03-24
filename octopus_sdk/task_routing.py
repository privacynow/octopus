"""Shared control-plane port for routed-task submission and reporting."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from octopus_sdk.registry.models import RoutedTaskRequest, RoutedTaskResult, RoutedTaskUpdate


class TaskSubmissionResult(BaseModel):
    status: str
    routed_task_id: str = ""
    delivery_id: str = ""
    error: str = ""


class TaskResultReport(BaseModel):
    status: str
    routed_task_id: str = ""
    error: str = ""


@runtime_checkable
class TaskRoutingPort(Protocol):
    async def submit_routed_task(
        self,
        *,
        request: RoutedTaskRequest,
        authority_ref: str,
    ) -> TaskSubmissionResult: ...

    async def report_routed_task_result(
        self,
        *,
        routed_task_id: str,
        authority_ref: str,
        result: RoutedTaskResult,
    ) -> TaskResultReport: ...

    async def update_routed_task_status(
        self,
        *,
        update: RoutedTaskUpdate,
        authority_ref: str,
    ) -> None: ...


class NoOpTaskRouting:
    async def submit_routed_task(
        self,
        *,
        request: RoutedTaskRequest,
        authority_ref: str,
    ) -> TaskSubmissionResult:
        del request, authority_ref
        return TaskSubmissionResult(status="unavailable", error="no control plane")

    async def report_routed_task_result(
        self,
        *,
        routed_task_id: str,
        authority_ref: str,
        result: RoutedTaskResult,
    ) -> TaskResultReport:
        del routed_task_id, authority_ref, result
        return TaskResultReport(status="unavailable", error="no control plane")

    async def update_routed_task_status(
        self,
        *,
        update: RoutedTaskUpdate,
        authority_ref: str,
    ) -> None:
        del update, authority_ref
        return None
