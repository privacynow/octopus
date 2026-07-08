"""Bot-side structured browser journey runner for protocol runtimes."""

from __future__ import annotations

import time
import shutil
from urllib.parse import urljoin, urlparse
import uuid

from octopus_sdk.protocols import ProtocolRuntimeJourneyResultRecord, ProtocolRuntimeJourneySpecRecord
from octopus_sdk.registry.models import RegistryJsonRecord


def _origin(url: str) -> str:
    parsed = urlparse(str(url or ""))
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _step_payload(value: object) -> dict[str, object]:
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if isinstance(value, dict):
        return dict(value)
    return {}


def _hook_selector(spec: ProtocolRuntimeJourneySpecRecord, hook: str) -> str:
    key = str(hook or "").strip()
    item = spec.hooks.get(key)
    selector = str(getattr(item, "selector", "") or "").strip()
    if not selector:
        raise ValueError(f"Journey references unknown hook: {key}")
    return selector


def _headers_for_origin(*, request_origin: str, target_origin: str, bearer_token: str) -> dict[str, str]:
    if str(request_origin or "").rstrip("/") != str(target_origin or "").rstrip("/") or not str(bearer_token or "").strip():
        return {}
    return {"authorization": f"Bearer {bearer_token}"}


def _artifact_api_url(spec: ProtocolRuntimeJourneySpecRecord, *, target_origin: str, path: str) -> str:
    normalized = str(path or "/").strip()
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    api_base = (
        f"{str(target_origin or '').rstrip('/')}/runtime/protocol-runs/"
        f"{spec.protocol_run_id}/artifacts/{spec.artifact_key}/api/"
    )
    return urljoin(api_base, normalized.lstrip("/"))


async def run_browser_journey(
    spec: ProtocolRuntimeJourneySpecRecord,
    *,
    registry_url: str,
    bearer_token: str,
    journey_run_id: str = "",
) -> ProtocolRuntimeJourneyResultRecord:
    run_id = str(journey_run_id or "").strip() or uuid.uuid4().hex
    started = time.monotonic()
    assertions: list[RegistryJsonRecord] = []
    console_errors: list[str] = []
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        return ProtocolRuntimeJourneyResultRecord(
            protocol_run_id=spec.protocol_run_id,
            artifact_key=spec.artifact_key,
            journey_key=spec.journey_key,
            journey_run_id=run_id,
            ok=False,
            status="failed",
            summary=f"Playwright is not available in the bot image: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    target_url = str(spec.target_url or "").strip()
    if not target_url:
        target_url = f"/runtime/protocol-runs/{spec.protocol_run_id}/artifacts/{spec.artifact_key}/app/"
    if not urlparse(target_url).scheme:
        target_url = urljoin(str(registry_url or "").rstrip("/") + "/", target_url.lstrip("/"))
    target_origin = _origin(target_url)
    allowed_origins = {target_origin, *[str(item or "").strip().rstrip("/") for item in spec.allowed_external_origins if str(item or "").strip()]}

    try:
        async with async_playwright() as playwright:
            executable_path = shutil.which("chromium") or shutil.which("chromium-browser")
            launch_kwargs = {"headless": True}
            if executable_path:
                launch_kwargs["executable_path"] = executable_path
            browser = await playwright.chromium.launch(**launch_kwargs)
            context = await browser.new_context()
            page = await context.new_page()

            page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: console_errors.append(str(error)))

            async def route_guard(route, request):
                request_url = str(request.url or "")
                request_origin = _origin(request_url)
                if request_url.startswith(("data:", "blob:", "about:")):
                    await route.continue_()
                    return
                if request_origin == target_origin:
                    headers = dict(request.headers)
                    headers.update(
                        _headers_for_origin(
                            request_origin=request_origin,
                            target_origin=target_origin,
                            bearer_token=bearer_token,
                        )
                    )
                    await route.continue_(headers=headers)
                    return
                if request_origin in allowed_origins:
                    await route.continue_()
                    return
                await route.abort()

            await page.route("**/*", route_guard)
            await page.goto(target_url, wait_until="domcontentloaded", timeout=int(spec.timeout_ms))
            if _origin(page.url) != target_origin:
                raise RuntimeError("Journey navigation left the routed artifact origin.")

            for raw_step in spec.steps:
                step = _step_payload(raw_step)
                action = str(step.get("action", "") or "").strip().lower()
                hook = str(step.get("hook", "") or "").strip()
                timeout_ms = int(step.get("timeout_ms", 0) or spec.timeout_ms)
                selector = _hook_selector(spec, hook) if hook else ""
                if action == "click":
                    await page.locator(selector).click(timeout=timeout_ms)
                    assertions.append(RegistryJsonRecord({"action": action, "hook": hook, "ok": True}))
                elif action == "fill":
                    await page.locator(selector).fill(str(step.get("value", "") or ""), timeout=timeout_ms)
                    assertions.append(RegistryJsonRecord({"action": action, "hook": hook, "ok": True}))
                elif action in {"assert_visible", "wait_for_hook"}:
                    await page.locator(selector).wait_for(state="visible", timeout=timeout_ms)
                    assertions.append(RegistryJsonRecord({"action": action, "hook": hook, "ok": True}))
                elif action == "assert_text":
                    expected = str(step.get("text", "") or step.get("contains", "") or "")
                    text = await page.locator(selector).inner_text(timeout=timeout_ms)
                    ok = expected in text if expected else bool(text.strip())
                    assertions.append(RegistryJsonRecord({"action": action, "hook": hook, "ok": ok, "expected": expected, "actual": text[:500]}))
                    if not ok:
                        raise AssertionError(f"Hook {hook} text did not contain expected value.")
                elif action == "assert_value":
                    expected = str(step.get("value", "") or "")
                    value = await page.locator(selector).input_value(timeout=timeout_ms)
                    ok = value == expected if expected else bool(value)
                    assertions.append(RegistryJsonRecord({"action": action, "hook": hook, "ok": ok, "expected": expected, "actual": value[:500]}))
                    if not ok:
                        raise AssertionError(f"Hook {hook} value did not match expected value.")
                elif action == "api_status":
                    path = str(step.get("path", "") or "/").strip()
                    headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}
                    response = await page.request.get(_artifact_api_url(spec, target_origin=target_origin, path=path), headers=headers)
                    expected_status = int(step.get("status", 200) or 200)
                    ok = int(response.status) == expected_status
                    assertions.append(RegistryJsonRecord({"action": action, "path": path, "ok": ok, "status": response.status, "expected_status": expected_status}))
                    if not ok:
                        raise AssertionError(f"API status for {path} was {response.status}, expected {expected_status}.")
                elif action == "no_console_errors":
                    ok = not console_errors
                    assertions.append(RegistryJsonRecord({"action": action, "ok": ok, "console_errors": list(console_errors)}))
                    if not ok:
                        raise AssertionError("Console errors were recorded during the journey.")
                else:
                    raise ValueError(f"Unsupported journey action: {action}")

            for raw_assertion in spec.assertions:
                assertion = _step_payload(raw_assertion)
                action = str(assertion.get("action", "") or "").strip().lower()
                if action == "no_console_errors":
                    ok = not console_errors
                    assertions.append(RegistryJsonRecord({"action": action, "ok": ok, "console_errors": list(console_errors)}))
                    if not ok:
                        raise AssertionError("Console errors were recorded during the journey.")
                elif action in {"assert_visible", "assert_text", "assert_value"}:
                    hook = str(assertion.get("hook", "") or "").strip()
                    selector = _hook_selector(spec, hook)
                    timeout_ms = int(assertion.get("timeout_ms", 0) or spec.timeout_ms)
                    if action == "assert_visible":
                        await page.locator(selector).wait_for(state="visible", timeout=timeout_ms)
                        assertions.append(RegistryJsonRecord({"action": action, "hook": hook, "ok": True}))
                    elif action == "assert_text":
                        expected = str(assertion.get("text", "") or assertion.get("contains", "") or "")
                        text = await page.locator(selector).inner_text(timeout=timeout_ms)
                        ok = expected in text if expected else bool(text.strip())
                        assertions.append(RegistryJsonRecord({"action": action, "hook": hook, "ok": ok, "expected": expected, "actual": text[:500]}))
                        if not ok:
                            raise AssertionError(f"Hook {hook} text did not contain expected value.")
                    else:
                        expected = str(assertion.get("value", "") or "")
                        value = await page.locator(selector).input_value(timeout=timeout_ms)
                        ok = value == expected if expected else bool(value)
                        assertions.append(RegistryJsonRecord({"action": action, "hook": hook, "ok": ok, "expected": expected, "actual": value[:500]}))
                        if not ok:
                            raise AssertionError(f"Hook {hook} value did not match expected value.")

            await context.close()
            await browser.close()
    except Exception as exc:
        return ProtocolRuntimeJourneyResultRecord(
            protocol_run_id=spec.protocol_run_id,
            artifact_key=spec.artifact_key,
            journey_key=spec.journey_key,
            journey_run_id=run_id,
            ok=False,
            status="failed",
            summary=str(exc),
            assertions=assertions,
            console_errors=console_errors,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    return ProtocolRuntimeJourneyResultRecord(
        protocol_run_id=spec.protocol_run_id,
        artifact_key=spec.artifact_key,
        journey_key=spec.journey_key,
        journey_run_id=run_id,
        ok=True,
        status="passed",
        summary="Journey completed successfully.",
        assertions=assertions,
        console_errors=console_errors,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
