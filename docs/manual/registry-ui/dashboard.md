# Registry UI: Dashboard

[← Manual home](../README.md) · [Prev: Sign in](sign-in.md) · [Next: Approvals →](approvals.md)

**Route:** `/ui` or `/ui/` — the dashboard is the default landing page after sign-in.

This screen starts with the operator’s next decision instead of a wall of telemetry. The top section highlights:

- the **primary action** to take next
- an **attention grid** for approvals, agent health, and failed work
- a calmer **health summary** for agents, conversations, tasks, and 24h cost
- preview lists for **ready for review**, **ongoing conversations**, and **recent failures**

The dashboard still draws its totals from the canonical **`GET /v1/summary`** payload, but it now combines those aggregates with the approvals, conversations, and tasks resources so the home screen answers “what should I do now?” instead of only “what numbers exist?”

![Dashboard](../../assets/registry/ui/01-dashboard-annotated.png)
