from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderFailureClassification:
    recoverability: str = "transient"
    fault_kind: str = ""
    fault_code: str = ""
    detail: str = ""

    @property
    def is_irrecoverable(self) -> bool:
        return self.recoverability == "irrecoverable"


def classify_provider_failure(
    provider_name: str,
    error_text: str,
    *,
    returncode: int = 0,
) -> ProviderFailureClassification:
    del returncode
    text = str(error_text or "").strip()
    lowered = text.lower()
    provider = str(provider_name or "").strip().lower()

    if not lowered:
        return ProviderFailureClassification()

    if (
        ("session id" in lowered and "already in use" in lowered)
        or ("another request is in progress" in lowered)
    ):
        return ProviderFailureClassification(
            recoverability="transient",
            fault_kind="concurrency",
            fault_code="session_busy",
            detail=text,
        )

    transient_markers = (
        "rate limit",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "connection reset",
        "connection refused",
        "network",
        "econn",
        "eai_again",
        "service unavailable",
        "internal server error",
    )
    if any(marker in lowered for marker in transient_markers):
        return ProviderFailureClassification(
            recoverability="transient",
            fault_kind="provider_runtime",
            fault_code="temporary_unavailable",
            detail=text,
        )

    auth_markers = (
        "not logged in",
        "please run /login",
        "authentication_failed",
        "authentication failed",
        "invalid api key",
        "unauthorized",
        "forbidden",
        "access denied",
        "please run codex login",
        "run 'codex login'",
        "run codex login",
    )
    if any(marker in lowered for marker in auth_markers):
        return ProviderFailureClassification(
            recoverability="irrecoverable",
            fault_kind="provider_auth",
            fault_code="authentication_required",
            detail=text,
        )

    account_markers = (
        "payment required",
        "subscription",
        "insufficient credits",
        "credit balance",
        "billing",
        "quota exceeded",
        "account suspended",
        "account disabled",
    )
    if any(marker in lowered for marker in account_markers):
        return ProviderFailureClassification(
            recoverability="irrecoverable",
            fault_kind="provider_account",
            fault_code="account_action_required",
            detail=text,
        )

    return ProviderFailureClassification(
        recoverability="transient",
        fault_kind="provider_runtime",
        fault_code=f"{provider or 'provider'}_request_failed",
        detail=text,
    )
