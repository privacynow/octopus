"""Small assertion helper for script-style test suites."""

from dataclasses import dataclass


@dataclass
class Checks:
    passed: int = 0
    failed: int = 0

    def check(self, name, got, expected):
        if got == expected:
            print(f"  PASS  {name}")
            self.passed += 1
        else:
            print(f"  FAIL  {name}")
            print(f"    expected: {expected!r}")
            print(f"    got:      {got!r}")
            self.failed += 1

    def check_true(self, name, val):
        self.check(name, bool(val), True)

    def check_false(self, name, val):
        self.check(name, bool(val), False)

    def check_in(self, name, needle, haystack):
        if needle in haystack:
            print(f"  PASS  {name}")
            self.passed += 1
        else:
            print(f"  FAIL  {name}")
            print(f"    {needle!r} not in {haystack!r}")
            self.failed += 1

    def check_not_in(self, name, needle, haystack):
        if needle not in haystack:
            print(f"  PASS  {name}")
            self.passed += 1
        else:
            print(f"  FAIL  {name}")
            print(f"    {needle!r} unexpectedly in {haystack!r}")
            self.failed += 1

    def check_contains(self, name, haystack, *needles):
        missing = [needle for needle in needles if needle not in haystack]
        if not missing:
            print(f"  PASS  {name}")
            self.passed += 1
        else:
            print(f"  FAIL  {name}")
            print(f"    missing: {missing!r}")
            self.failed += 1
