"""Laptop ``live`` profile adapters: the one local open-weight model, nothing else.

The ``live`` profile is the ``local`` stack with ONE port rebound: ``llm`` calls the laptop's
local model server through the fleet's shared client, :mod:`hex_service_kit.localmodel`. Every
other port binds the same in-process adapter ``local`` binds (see ``config/settings.yaml``), and
the profile keeps the ``local`` posture (loopback bind, seeded personas, localhost CORS).
"""
