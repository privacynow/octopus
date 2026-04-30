"""SDK-owned workflow composition helpers."""

from __future__ import annotations

from typing import cast

from octopus_sdk.bot_runtime import (
    ConversationWorkflows,
    CredentialWorkflows,
    PendingWorkflows,
    ProviderGuidanceWorkflows,
    RecoveryWorkflows,
    RuntimeSkillWorkflows,
    SessionRuntimePort,
    WorkflowComposition,
)
from octopus_sdk.config import BotConfigBase
from octopus_sdk.content_store import ContentStorePort
from octopus_sdk.deferred_notifications import DeferredNotificationPort
from octopus_sdk.formatting import TextFormattingPort
from octopus_sdk.messages import MessageTemplatePort
from octopus_sdk.work_queue import WorkQueuePort
from octopus_sdk.webhooks import CompletionWebhookPort
from octopus_sdk.workflows.conversation_control import ConversationControlUseCases
from octopus_sdk.workflows.conversation_settings import ConversationSettingsUseCases
from octopus_sdk.workflows.conversation import ApprovalModeGuard
from octopus_sdk.workflows.credential_management import CredentialManagementUseCases
from octopus_sdk.workflows.credentials import CredentialServicePort, CredentialValidatorPort
from octopus_sdk.workflows.pending_requests import PendingRequestUseCases
from octopus_sdk.workflows.provider_guidance import ProviderGuidanceServicePort
from octopus_sdk.workflows.provider_guidance_management import ProviderGuidanceManagementUseCases
from octopus_sdk.workflows.provider_guidance_preview import ProviderGuidanceUseCases
from octopus_sdk.workflows.recovery_replay import RecoveryUseCases
from octopus_sdk.workflows.runtime_skill_activation import RuntimeSkillActivationUseCases
from octopus_sdk.workflows.runtime_skill_approval import RuntimeSkillApprovalUseCases
from octopus_sdk.workflows.runtime_skill_authoring import RuntimeSkillAuthoringUseCases
from octopus_sdk.workflows.runtime_skill_catalog import RuntimeSkillCatalogUseCases
from octopus_sdk.workflows.runtime_skill_importing import RuntimeSkillImportUseCases
from octopus_sdk.workflows.runtime_skill_setup import RuntimeSkillSetupUseCases
from octopus_sdk.workflows.skills import (
    SkillActivationServicePort,
    SkillCatalogServicePort,
    SkillImportServicePort,
)
from octopus_sdk.authorization import TrustTierResolverPort


class WorkflowComposerError(RuntimeError):
    """Workflow composition cannot be completed."""


class NotConfiguredError(WorkflowComposerError):
    """A requested workflow dependency is not wired into the runtime."""


WorkflowNotConfiguredError = NotConfiguredError


def _require[T](name: str, value: T | None) -> T:
    if value is None:
        raise WorkflowComposerError(f"{name} must be provided to WorkflowComposer")
    return value


def _is_test_implementation(value: object | None) -> bool:
    if value is None:
        return False
    module = type(value).__module__
    return module == "octopus_sdk.testing" or module.startswith("octopus_sdk.testing.")


class _UnavailablePort:
    """Loud placeholder for optional workflow ports.

    Note: ``hasattr(port, "method")`` returns True because ``__getattr__``
    produces a callable that raises ``NotConfiguredError`` at call time rather
    than raising ``AttributeError``. No current runtime code uses ``hasattr``
    for workflow-port feature detection; revisit only if that changes.
    """

    def __init__(self, dependency: str) -> None:
        self._dependency = dependency

    def _raise(self) -> None:
        raise NotConfiguredError(f"{self._dependency} not configured for workflow composition")

    def __call__(self, *args, **kwargs):
        del args, kwargs
        self._raise()

    def __getattr__(self, name: str):
        def _missing(*args, **kwargs):
            del args, kwargs
            self._raise()

        return _missing


class WorkflowComposer:
    """Builder for a fully wired SDK workflow graph."""

    def __init__(self) -> None:
        self._messages: MessageTemplatePort | None = None
        self._sessions: SessionRuntimePort | None = None
        self._config: BotConfigBase | None = None
        self._catalog_service: SkillCatalogServicePort | None = None
        self._import_service: SkillImportServicePort | None = None
        self._activation_service: SkillActivationServicePort | None = None
        self._credential_service: CredentialServicePort | None = None
        self._guidance_service: ProviderGuidanceServicePort | None = None
        self._content_store: ContentStorePort | None = None
        self._validator: CredentialValidatorPort | None = None
        self._work_queue: WorkQueuePort | None = None
        self._trust_tier_resolver: TrustTierResolverPort | None = None
        self._text_formatting: TextFormattingPort | None = None
        self._completion_webhook: CompletionWebhookPort | None = None
        self._deferred_notifications: DeferredNotificationPort | None = None
        self._prompt_size_warning_threshold: int = 0
        self._approval_mode_guard: ApprovalModeGuard | None = None

    def with_messages(self, messages: MessageTemplatePort) -> "WorkflowComposer":
        self._messages = messages
        return self

    def with_sessions(self, sessions: SessionRuntimePort) -> "WorkflowComposer":
        self._sessions = sessions
        return self

    def with_config(self, config: BotConfigBase) -> "WorkflowComposer":
        self._config = config
        return self

    def with_catalog_service(self, catalog_service: SkillCatalogServicePort) -> "WorkflowComposer":
        self._catalog_service = catalog_service
        return self

    def with_import_service(self, import_service: SkillImportServicePort) -> "WorkflowComposer":
        self._import_service = import_service
        return self

    def with_skill_activation(self, activation_service: SkillActivationServicePort) -> "WorkflowComposer":
        self._activation_service = activation_service
        return self

    def with_credentials(self, credential_service: CredentialServicePort) -> "WorkflowComposer":
        self._credential_service = credential_service
        return self

    def with_provider_guidance(self, guidance_service: ProviderGuidanceServicePort) -> "WorkflowComposer":
        self._guidance_service = guidance_service
        return self

    def with_content_store(self, content_store: ContentStorePort) -> "WorkflowComposer":
        self._content_store = content_store
        return self

    def with_credential_validator(self, validator: CredentialValidatorPort) -> "WorkflowComposer":
        self._validator = validator
        return self

    def with_work_queue(self, work_queue: WorkQueuePort) -> "WorkflowComposer":
        self._work_queue = work_queue
        return self

    def with_trust_tier_resolver(self, trust_tier_resolver: TrustTierResolverPort) -> "WorkflowComposer":
        self._trust_tier_resolver = trust_tier_resolver
        return self

    def with_text_formatting(self, text_formatting: TextFormattingPort) -> "WorkflowComposer":
        self._text_formatting = text_formatting
        return self

    def with_completion_webhook(self, completion_webhook: CompletionWebhookPort) -> "WorkflowComposer":
        self._completion_webhook = completion_webhook
        return self

    def with_deferred_notifications(
        self,
        deferred_notifications: DeferredNotificationPort,
    ) -> "WorkflowComposer":
        self._deferred_notifications = deferred_notifications
        return self

    def with_prompt_size_warning_threshold(self, threshold: int) -> "WorkflowComposer":
        self._prompt_size_warning_threshold = threshold
        return self

    def with_approval_mode_guard(self, guard: ApprovalModeGuard) -> "WorkflowComposer":
        self._approval_mode_guard = guard
        return self

    def _reject_test_implementations(self) -> None:
        candidates = {
            "messages": self._messages,
            "sessions": self._sessions,
            "config": self._config,
            "work_queue": self._work_queue,
            "catalog_service": self._catalog_service,
            "import_service": self._import_service,
            "activation_service": self._activation_service,
            "credential_service": self._credential_service,
            "guidance_service": self._guidance_service,
            "content_store": self._content_store,
            "validator": self._validator,
            "trust_tier_resolver": self._trust_tier_resolver,
            "text_formatting": self._text_formatting,
            "completion_webhook": self._completion_webhook,
            "deferred_notifications": self._deferred_notifications,
        }
        for name, value in candidates.items():
            if _is_test_implementation(value):
                raise WorkflowComposerError(
                    f"WorkflowComposer.build() rejects test-only {name}. "
                    "Use build_for_testing() explicitly for SDK wiring verification."
                )

    def build(self) -> WorkflowComposition:
        self._reject_test_implementations()
        return self._build(test_only=False)

    def build_for_testing(self) -> WorkflowComposition:
        return self._build(test_only=True)

    def _build(self, *, test_only: bool) -> WorkflowComposition:
        messages = _require("messages", self._messages)
        sessions = _require("sessions", self._sessions)
        config = _require("config", self._config)
        work_queue = _require("work_queue", self._work_queue)
        catalog_service = self._catalog_service or cast(
            SkillCatalogServicePort,
            _UnavailablePort("skill catalog service"),
        )
        import_service = self._import_service or cast(
            SkillImportServicePort,
            _UnavailablePort("skill import service"),
        )
        activation_service = self._activation_service or cast(
            SkillActivationServicePort,
            _UnavailablePort("skill activation service"),
        )
        credential_service = self._credential_service or cast(
            CredentialServicePort,
            _UnavailablePort("credential service"),
        )
        guidance_service = self._guidance_service or cast(
            ProviderGuidanceServicePort,
            _UnavailablePort("provider guidance service"),
        )
        content_store = self._content_store or cast(
            ContentStorePort,
            _UnavailablePort("content store"),
        )
        validator = self._validator or cast(
            CredentialValidatorPort,
            _UnavailablePort("credential validator"),
        )
        trust_tier_resolver = self._trust_tier_resolver or cast(
            TrustTierResolverPort,
            _UnavailablePort("trust tier resolver"),
        )
        text_formatting = self._text_formatting or cast(
            TextFormattingPort,
            _UnavailablePort("text formatting"),
        )
        completion_webhook = self._completion_webhook or cast(
            CompletionWebhookPort,
            _UnavailablePort("completion webhook"),
        )
        deferred_notifications = self._deferred_notifications or cast(
            DeferredNotificationPort,
            _UnavailablePort("deferred notifications"),
        )

        supported_admin_operations: list[str] = []
        if self._catalog_service is not None and self._import_service is not None:
            supported_admin_operations.extend([
                "list_catalog_skills",
                "search_catalog_skills",
                "catalog_skill_detail",
                "install_catalog_skill",
                "uninstall_catalog_skill",
                "update_catalog_skill",
                "diff_catalog_skill",
            ])
        if self._catalog_service is not None and self._content_store is not None:
            supported_admin_operations.extend([
                "catalog_skill_lifecycle_detail",
                "edit_catalog_skill_draft",
                "export_catalog_skill_package",
                "import_catalog_skill_package",
                "submit_catalog_skill",
                "approve_catalog_skill",
                "reject_catalog_skill",
                "publish_catalog_skill",
                "archive_catalog_skill",
            ])
        if self._guidance_service is not None and self._content_store is not None:
            supported_admin_operations.extend([
                "preview_provider_guidance",
                "provider_guidance_detail",
                "edit_provider_guidance_draft",
                "submit_provider_guidance",
                "approve_provider_guidance",
                "reject_provider_guidance",
                "publish_provider_guidance",
                "archive_provider_guidance",
            ])
        if (
            self._catalog_service is not None
            and self._activation_service is not None
            and self._credential_service is not None
            and self._guidance_service is not None
        ):
            supported_admin_operations.extend([
                "conversation_skill_state",
                "activate_conversation_skill",
                "deactivate_conversation_skill",
                "clear_conversation_skills",
                "submit_conversation_skill_credential",
            ])
        if self._catalog_service is not None:
            supported_admin_operations.extend([
                "conversation_settings_state",
                "set_conversation_setting",
                "reset_conversation",
            ])

        catalog = RuntimeSkillCatalogUseCases(
            catalog_service=catalog_service,
            import_service=import_service,
            default_skills=config.default_skills,
        )
        setup = RuntimeSkillSetupUseCases(
            catalog=catalog,
            credentials=credential_service,
            activation=activation_service,
            default_validator=validator,
        )
        authoring = RuntimeSkillAuthoringUseCases(
            store=content_store,
            catalog_service=catalog_service,
        )

        return WorkflowComposition(
            runtime_skills=RuntimeSkillWorkflows(
                catalog=catalog,
                activation=RuntimeSkillActivationUseCases(
                    catalog=catalog,
                    activation=activation_service,
                    credentials=credential_service,
                    guidance=guidance_service,
                    setup=setup,
                    prompt_size_warning_threshold=self._prompt_size_warning_threshold,
                ),
                imports=RuntimeSkillImportUseCases(
                    import_service=import_service,
                    guidance_service=guidance_service,
                    catalog=catalog,
                ),
                setup=setup,
                authoring=authoring,
                approval=RuntimeSkillApprovalUseCases(
                    store=content_store,
                    catalog_service=catalog_service,
                    authoring=authoring,
                ),
            ),
            credentials=CredentialWorkflows(
                management=CredentialManagementUseCases(
                    credentials=credential_service,
                    setup=setup,
                ),
            ),
            conversation=ConversationWorkflows(
                control=ConversationControlUseCases(
                    messages=messages,
                    setup=setup,
                    work_queue=work_queue,
                ),
                settings=ConversationSettingsUseCases(
                    messages=messages,
                    catalog=catalog,
                    approval_mode_guard=self._approval_mode_guard,
                ),
            ),
            pending=PendingWorkflows(
                requests=PendingRequestUseCases(
                    messages=messages,
                    catalog=catalog,
                ),
            ),
            recovery=RecoveryWorkflows(
                replay=RecoveryUseCases(
                    messages=messages,
                    work_queue=work_queue,
                    trust_tier_resolver=trust_tier_resolver,
                ),
            ),
            provider_guidance=ProviderGuidanceWorkflows(
                preview=ProviderGuidanceUseCases(guidance_service=guidance_service),
                management=ProviderGuidanceManagementUseCases(store=content_store),
            ),
            messages=messages,
            config=config,
            sessions=sessions,
            supported_admin_operations=tuple(supported_admin_operations),
            text_formatting=text_formatting,
            completion_webhook=completion_webhook,
            trust_tier_resolver=trust_tier_resolver,
            deferred_notifications=deferred_notifications,
            test_only=test_only,
        )
