"""Tests for reading durable issue outcomes from graph state."""

import pytest

from scripts.verify_issue_persistence import completed_issue, issue_reference


def test_completed_issue_reads_current_action_state() -> None:
    issue = {"id": "issue-1", "identifier": "OPS-12", "title": "Review margin"}
    values = {
        "status": "created_verified",
        "approved": True,
        "created_issue": issue,
    }

    assert completed_issue(values) == issue
    assert issue_reference(issue) == "OPS-12"


def test_completed_issue_survives_later_turn_state() -> None:
    issue = {"id": "issue-1", "identifier": "OPS-12", "title": "Review margin"}
    values = {
        "status": "analysis_pending",
        "approved": None,
        "created_issue": None,
        "action_outcomes": [
            {
                "status": "created_verified",
                "approved": True,
                "issue": issue,
            }
        ],
    }

    assert completed_issue(values) == issue


def test_completed_issue_rejects_thread_without_successful_write() -> None:
    with pytest.raises(AssertionError, match="No verified issue creation"):
        completed_issue({"status": "rejected", "action_outcomes": []})
