from __future__ import annotations

import random

from octopus_sdk.protocols import (
    protocol_document_from_text,
    protocol_document_to_text,
    validate_protocol_document,
)
from tests.test_protocols import _generated_linear_protocol


def test_generated_protocol_documents_round_trip_through_json_and_yaml() -> None:
    for seed in range(30):
        validated = validate_protocol_document(_generated_linear_protocol(seed))
        assert validated.ok is True
        document = validated.normalized_document
        assert document is not None
        for format_name in ("json", "yaml"):
            text = protocol_document_to_text(document, format=format_name)
            reloaded = protocol_document_from_text(text, format=format_name)
            assert reloaded.model_dump(mode="json") == document.model_dump(mode="json")


def test_generated_protocol_completed_paths_reach_a_terminal_without_revisiting_stages() -> None:
    for seed in range(50):
        validated = validate_protocol_document(_generated_linear_protocol(seed))
        assert validated.ok is True
        document = validated.normalized_document
        assert document is not None

        seen: set[str] = set()
        stage_key = document.first_stage_key
        while not stage_key.startswith("__"):
            assert stage_key not in seen, f"completed path looped for seed={seed}"
            seen.add(stage_key)
            stage = document.stage(stage_key)
            stage_key = stage.transitions.as_dict()["completed"]
        assert stage_key == "__complete__"


def test_protocol_document_fuzz_preserves_result_shape_across_random_payloads() -> None:
    for seed in range(100):
        rng = random.Random(seed)
        payload = _generated_linear_protocol(seed % 10)
        if rng.random() < 0.5:
            payload["metadata"]["slug"] = f" fuzz-{seed} ".strip()
        if rng.random() < 0.5:
            payload["policies"]["max_review_rounds"] = rng.randint(1, 7)
        result = validate_protocol_document(payload)
        assert isinstance(result.ok, bool)
        assert isinstance(result.errors, list)
