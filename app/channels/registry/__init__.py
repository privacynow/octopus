"""Bot-side registry transport package.

This package is the bot client path to the registry management plane. It owns
registry channel refs, registry-scoped transport wiring, delivery polling, and
registry egress for connected bots.

The registry server itself now lives in ``octopus_registry/``.
"""
