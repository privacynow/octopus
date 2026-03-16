# Changelog

## M10
- Added versioned SQLite migrations for the bot and registry stores, plus an operator upgrade guide and repo version marker.

## M9
- Polished first-run setup, provider login UX, guided setup flow, and the Registry UI presentation.

## M8
- Added Registry UI delegation approve/cancel actions and completed delegation summaries on the originating surface.

## M7
- Added registry-backed conversation timelines and Registry UI conversation creation/detail views.

## M6
- Added degraded polling backoff, stronger `/doctor` diagnostics, and aligned operator documentation with shipped behavior.

## M5
- Added specialist discovery, delegation planning, approval before fan-out, and routed-task submission.

## M4
- Routed registry deliveries and delegated work through the same local worker-owned execution path as Telegram.

## M3
- Introduced the registry service, SQLite-backed control-plane store, and the first Registry UI shell.

## M2
- Added registry-first guided setup, multi-instance Docker support, and operator instance scripts.

## M1
- Established shared conversation/surface abstractions and one authoritative execution path across surfaces.
