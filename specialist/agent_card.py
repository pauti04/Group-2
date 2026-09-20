"""Agent Card — how the Specialist describes itself to other agents.

Owner: person 1.

The A2A protocol's discovery convention is that an agent publishes a card at a
well-known URL saying who it is, what it can do, and how to talk to it, so a
client does not need the details hardcoded. We serve one at

    /.well-known/agent-card.json

Our Requester is hardcoded to this one Specialist, so nothing strictly needs
the card today. It is here because it is what makes this an A2A-style system
rather than just two services with a REST API between them, and because it is
the seam that a second Specialist (extension idea: multiple experts with
different knowledge bases) would plug into — the Requester would read the cards
and route by skill instead of by hostname.
"""

from __future__ import annotations

from specialist.tasks import PROTOCOL_VERSION

AGENT_CARD = {
    "protocol_version": PROTOCOL_VERSION,
    "name": "Support Knowledge Specialist",
    "description": (
        "Answers IT support questions using retrieval-augmented generation over "
        "the company support knowledge base. Returns a ticket category and a "
        "recommended resolution, with the source documents used."
    ),
    "version": "1.0.0",
    "capabilities": {
        "streaming": False,
        "push_notifications": False,
        "cancellation": True,
        "state_transition_history": True,
    },
    "default_input_modes": ["text/plain"],
    "default_output_modes": ["application/json"],
    "skills": [
        {
            "id": "classify_and_resolve",
            "name": "Classify and resolve a support issue",
            "description": (
                "Given a user's description of an IT problem, returns the ticket "
                "category it belongs to and the resolution steps, grounded in the "
                "support knowledge base."
            ),
            "tags": ["support", "rag", "classification"],
            "input_fields": ["question", "needs"],
            "output_fields": ["category", "resolution", "sources", "confidence"],
            "examples": [
                "I forgot my password and cannot log into my account.",
                "My laptop won't connect to Wi-Fi.",
            ],
        }
    ],
    "endpoints": {
        "submit": {"method": "POST", "path": "/tasks"},
        "get": {"method": "GET", "path": "/tasks/{task_id}"},
        "cancel": {"method": "POST", "path": "/tasks/{task_id}/cancel"},
    },
    "task_states": ["submitted", "working", "completed", "failed", "canceled"],
}
