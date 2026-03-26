# Registry UI: Mobile quick look

[← Manual home](../README.md) · [Prev: Deep links](deep-links.md) · [Next: Telegram →](../04-product-telegram.md)

The mobile UI is the same SPA, not a separate product. The shell changes in
these ways:

- the left rail becomes a working drawer
- segmented controls stay horizontal and scroll instead of wrapping
- summary rails and list sections stack into one column
- conversation detail keeps the composer inside the main workspace

## Dashboard

- summary cards collapse into a single vertical rail
- attention sections stay list-first rather than turning into large empty panels

![Mobile dashboard](../../assets/registry/ui/14-mobile-dashboard.png)

## Approvals

- approval cards stay action-first
- approve/reject/open remain reachable without extra drill-in

![Mobile approvals](../../assets/registry/ui/15-mobile-approvals.png)

## Conversation detail

- title, metadata, status, and tabs stack cleanly
- Conversation / Tasks / Full activity stay on the same route
- the composer remains inside the conversation workspace rather than dropping
  below it
- the drawer/hamburger remains the route switcher on small screens

![Mobile conversation detail](../../assets/registry/ui/16-mobile-conversation.png)
