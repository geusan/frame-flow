import pytest

from app.contexts.runs.domain import RunConflictError, is_terminal_run_status, require_successful_baseline
from app.contexts.workflows.domain import WorkflowValidationError, require_runnable_workflow


def test_run_baseline_policy_is_independent_of_persistence() -> None:
    require_successful_baseline("SUCCEEDED")
    with pytest.raises(RunConflictError, match="only successful"):
        require_successful_baseline("FAILED")
    assert is_terminal_run_status("CANCELED") is True
    assert is_terminal_run_status("RUNNING") is False


def test_workflow_run_policy_is_independent_of_persistence() -> None:
    require_runnable_workflow("ACTIVE")
    with pytest.raises(WorkflowValidationError, match="Archived Workflow"):
        require_runnable_workflow("ARCHIVED")
