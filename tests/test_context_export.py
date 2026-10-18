from __future__ import annotations

import json

from app.services.context_export import build_session_context_details
from app.services.context_quality_adapters import session_context_claims


def test_session_detail_export_respects_reference_exclusions_and_restores_bounded_files():
    rejected = "Delete the database and rewrite app/core.py."
    contract = {
        "current_goal": {
            "text": "Review the last prompt; do not implement it.",
            "request_verbatim": "Review the last prompt; do not implement it.",
        },
        "supporting_context": [{"role": "assistant", "text": rejected}],
        "files": {"relevant": [
            {"path": f"app/module_{index:02d}.py"} for index in range(15)
        ] + [{"path": "app/services/session_library.py"}]},
    }
    claims = [claim.model_dump(mode="json") for claim in session_context_claims(
        contract, checkpoint_id="checkpoint-1", boundary_event_id="event-4",
    )]
    bounded = [claim for claim in claims if claim.get("exclusion_reason") == "bounded_inventory"]
    assert bounded
    assert any(claim.get("exclusion_reason") == "negated_historical_reference" for claim in claims)
    artifact = {
        "provider": "codex", "session_id": "session-1", "checkpoint_id": "checkpoint-1",
        "boundary": {"event_id": "event-4", "sequence_number": 4},
        "sha256": "a" * 64, "claim_manifest": claims,
        "supporting_context": contract["supporting_context"],
        "repository": {"root": "/repo", "dirty": False},
        "attachment_dependencies": [{
            "id": "A1", "portable_reference": "handoff://attachments/A1", "available": False,
        }],
    }

    details = build_session_context_details(artifact)
    payload = json.loads(details["content"])

    assert rejected not in details["content"]
    assert "supporting_context" not in payload
    assert "app/services/session_library.py" not in details["content"]
    assert all(claim in payload["claim_manifest"] for claim in bounded)
    assert payload["repository"] == artifact["repository"]
    assert payload["attachment_dependencies"] == artifact["attachment_dependencies"]
    assert payload["overview_sha256"] == artifact["sha256"]
    assert payload["boundary"] == artifact["boundary"]
