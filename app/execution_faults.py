from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.agents.state import load_execution_state, save_execution_state
from app.provider_failures import classify_provider_failure
from octopus_sdk.bot_runtime import ExecutionFaultStatePort
from octopus_sdk.registry.models import ExecutionStateRecord
from octopus_sdk.time_utils import utc_now_iso


@dataclass(frozen=True)
class LocalExecutionFaultState(ExecutionFaultStatePort):
    data_dir: Path

    def load(self) -> ExecutionStateRecord:
        return load_execution_state(self.data_dir)

    def clear(self) -> ExecutionStateRecord:
        state = ExecutionStateRecord()
        save_execution_state(self.data_dir, state)
        return state

    def record_provider_failure(
        self,
        *,
        provider_name: str,
        error_text: str,
        returncode: int,
    ) -> ExecutionStateRecord | None:
        classification = classify_provider_failure(
            provider_name,
            error_text,
            returncode=returncode,
        )
        if not classification.is_irrecoverable:
            return None
        state = ExecutionStateRecord(
            state="faulted",
            provider=str(provider_name or "").strip(),
            fault_kind=classification.fault_kind,
            fault_code=classification.fault_code,
            detail=classification.detail,
            faulted_at=utc_now_iso(),
            resettable=True,
            last_returncode=returncode,
        )
        save_execution_state(self.data_dir, state)
        return state
