"""Tests for summarize.py — ring buffer and summarization."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.summarize import _RING_SIZE, _SHORT_THRESHOLD, load_raw, save_raw

passed = 0
failed = 0


def check(name, got, expected):
    global passed, failed
    if got == expected:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}")
        print(f"    expected: {expected!r}")
        print(f"    got:      {got!r}")
        failed += 1


def check_contains(name, got, *needles):
    global passed, failed
    ok = all(n in got for n in needles)
    if ok:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}")
        print(f"    missing: {[n for n in needles if n not in got]}")
        failed += 1


# -- ring buffer --
print("\n=== ring buffer ===")

with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp)

    # Empty buffer
    check("load empty returns None", load_raw(data_dir, 1), None)

    # Save and load
    save_raw(data_dir, 1, "prompt one", "response one")
    check("load latest", load_raw(data_dir, 1, 1), "response one")

    save_raw(data_dir, 1, "prompt two", "response two")
    check("load latest after two", load_raw(data_dir, 1, 1), "response two")
    check("load second most recent", load_raw(data_dir, 1, 2), "response one")

    # Out of range
    check("load out of range", load_raw(data_dir, 1, 99), None)
    check("load zero", load_raw(data_dir, 1, 0), None)

    # Different chat IDs are isolated
    save_raw(data_dir, 2, "other chat", "other response")
    check("chat isolation", load_raw(data_dir, 2, 1), "other response")
    check("original chat unchanged", load_raw(data_dir, 1, 1), "response two")

# -- ring buffer rotation --
print("\n=== ring buffer rotation ===")

with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp)

    # Fill beyond capacity
    for i in range(_RING_SIZE + 3):
        save_raw(data_dir, 1, f"prompt {i}", f"response {i}")

    # Should only have _RING_SIZE entries
    ring_dir = data_dir / "raw" / "1"
    entries = list(ring_dir.glob("*.json"))
    check("rotation keeps max entries", len(entries), _RING_SIZE)

    # Latest should be the last one saved
    check("latest after rotation", load_raw(data_dir, 1, 1), f"response {_RING_SIZE + 2}")

    # Oldest available should be offset by 3
    oldest = load_raw(data_dir, 1, _RING_SIZE)
    check("oldest after rotation", oldest, f"response 3")

# -- ring buffer JSON format --
print("\n=== ring buffer JSON format ===")

with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp)
    save_raw(data_dir, 1, "test prompt preview", "test raw text")
    ring_dir = data_dir / "raw" / "1"
    entry = next(ring_dir.glob("*.json"))
    payload = json.loads(entry.read_text())
    check("has timestamp", "timestamp" in payload, True)
    check("has prompt_preview", payload["prompt_preview"], "test prompt preview")
    check("has raw_text", payload["raw_text"], "test raw text")

# -- short threshold constant --
print("\n=== short threshold ===")
check("short threshold is 800", _SHORT_THRESHOLD, 800)

# -- Summary --
print(f"\n{'='*40}")
print(f"  {passed} passed, {failed} failed")
print(f"{'='*40}")
sys.exit(1 if failed else 0)
