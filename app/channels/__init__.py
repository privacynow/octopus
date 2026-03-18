"""Concrete external channel packages.

Channels are the external boundary of the app. Each channel owns:

- ingress: native input admission and translation
- egress: native output/rendering behavior
- presenters: channel-specific presentation shaping
- bootstrap: channel startup/wiring

Channel code may depend on `app.workflows`, `app.ports`, and narrow helpers in
`app.runtime` where justified. Channel code must not own business workflow
logic.
"""
