"""Shared test setup.

The one thing enforced here is that no test reaches the network. This is not
hypothetical: when the Gemini SDK was swapped, several agent tests started
making real calls to generativelanguage.googleapis.com. They still passed,
because the code turns an API failure into a user-facing error string, and the
assertions were about that string. A mock that stops matching should fail
loudly, not quietly become an integration test that depends on the CI runner
having a network and a valid key.
"""

import socket

import pytest


class NetworkUsedInTest(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise NetworkUsedInTest(
            "a test tried to open a socket - a mock is missing or no longer matches "
            "the code it stands in for"
        )

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
