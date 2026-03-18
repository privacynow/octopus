"""Runtime composition, admission, and dispatch.

The runtime package owns wiring and execution plumbing only:

- channel composition/bootstrap
- shared inbound/admission types
- queue/admission handling
- provider dispatch/runtime execution
- session/context preparation helpers

Runtime code must not become a replacement business-logic layer.
"""
