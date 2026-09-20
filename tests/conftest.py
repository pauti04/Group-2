"""Spins the real Specialist up on a random port for the protocol tests.

We test against a live server over real HTTP rather than Flask's test client,
because the thing under test is the protocol — the acknowledgment, the polling,
the retries — not the view functions.
"""

from __future__ import annotations

import threading

import pytest
from werkzeug.serving import make_server

from specialist import server as specialist_server


@pytest.fixture
def specialist():
    """Yields (base_url, store). Reset per test, so delays do not leak."""
    srv = make_server("127.0.0.1", 0, specialist_server.app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    store = specialist_server.store
    store.work_delay_s = 0.0
    store._tasks.clear()

    try:
        yield f"http://127.0.0.1:{srv.server_port}", store
    finally:
        srv.shutdown()
        thread.join(timeout=5)
