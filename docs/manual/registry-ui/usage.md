# Registry UI: Usage

[← Manual home](../README.md) · [Prev: Skills catalog](skills-catalog.md) · [Next: Provider guidance →](guidance.md)

**Route:** `/ui/usage`

Usage is a compact rollup over provider-response usage data.

- **Today**, **7 days**, and **30 days** are segmented range shortcuts
- the summary rail shows total prompt tokens, completion tokens, and cost
- the table rolls those totals up by parent conversation

Delegated child work can contribute to the parent conversation totals when that
routed work reports usage data back through the task/result flow. A zero row is
still valid for conversations that produced events but no usage-bearing provider
response.

![Usage](../../assets/registry/ui/10-usage-annotated.png)
