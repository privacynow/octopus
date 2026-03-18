import importlib


EXPECTED_MODULES = (
    "app.channels",
    "app.channels.telegram",
    "app.channels.registry",
    "app.ports",
    "app.runtime",
    "app.runtime.inbound_types",
    "app.workflows",
    "app.workflows.runtime_skills",
    "app.workflows.credentials",
    "app.workflows.conversation",
    "app.workflows.pending",
    "app.workflows.recovery",
    "app.workflows.provider_guidance",
)


def test_channel_architecture_skeleton_modules_exist() -> None:
    for module_name in EXPECTED_MODULES:
        module = importlib.import_module(module_name)
        assert module.__doc__
