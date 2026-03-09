"""Small assertion helper for script-style test suites."""

import asyncio
import sys
import traceback
from dataclasses import dataclass, field


@dataclass
class Checks:
    passed: int = 0
    failed: int = 0
    _async_tests: list = field(default_factory=list, repr=False)

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

    # -- Test runner helpers --------------------------------------------------

    def add_test(self, name: str, coro_or_func) -> None:
        """Register a test (async coroutine or sync callable)."""
        self._async_tests.append((name, coro_or_func))

    async def _run_async_tests(self) -> None:
        for name, test in self._async_tests:
            print(f"\n=== {name} ===")
            try:
                if asyncio.iscoroutine(test):
                    await test
                elif callable(test):
                    test()
                else:
                    await test
            except Exception as exc:
                print(f"  FAIL  {name} (exception: {exc})")
                traceback.print_exc()
                self.failed += 1

    def _print_summary(self) -> int:
        print(f"\n{'=' * 40}")
        print(f"  {self.passed} passed, {self.failed} failed")
        print(f"{'=' * 40}")
        return 1 if self.failed else 0

    def run_and_exit(self) -> None:
        """Print summary and exit. For sync test files."""
        sys.exit(self._print_summary())

    def run_async_and_exit(self) -> None:
        """Run registered async tests, print summary, and exit."""
        async def _main():
            await self._run_async_tests()
            raise SystemExit(self._print_summary())
        asyncio.run(_main())
