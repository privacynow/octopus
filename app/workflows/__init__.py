"""Workflow package root.

`app.workflows` is the target namespace for concern-owned workflow modules.
Existing transport/recovery state-machine exports remain here temporarily while
the repo is migrated into the new package layout in-place.

Rules:

- workflow packages own typed requests/outcomes in local `contracts.py`
- workflow code must not depend on channel packages
- workflow code may depend on ports, domain services, and stores
- this package must not split into parallel legacy and v2 namespaces
"""

from app.workflows.pending_request import (
    PendingRequestDisposition,
    PendingRequestMachine,
    PendingRequestTransitionResult,
    PendingRequestWorkflowModel,
    run_pending_request_event,
)
from app.workflows.results import (
    TransitionResult,
    TransportDisposition,
)
from app.workflows.transport_recovery import (
    TransportRecoveryMachine,
    TransportWorkflowModel,
    run_transport_event,
)

__all__ = [
    "PendingRequestDisposition",
    "PendingRequestMachine",
    "PendingRequestTransitionResult",
    "PendingRequestWorkflowModel",
    "run_pending_request_event",
    "TransitionResult",
    "TransportDisposition",
    "TransportRecoveryMachine",
    "TransportWorkflowModel",
    "run_transport_event",
]
