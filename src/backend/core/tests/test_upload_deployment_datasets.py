"""Tests for the deployment datasets upload: the task and its management command."""

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError

import pytest

from core.tasks.datagouv import (
    DATASET_TASKS,
    run_dataset_uploads,
    upload_deployment_datasets,
)


def _patch_tasks(failing=()):
    """Replace every upload task with a mock, the ``failing`` ones raising."""
    mocks = {}
    for name in DATASET_TASKS:
        side_effect = ValueError("boom") if name in failing else None
        mocks[name] = mock.Mock(
            return_value={"status": "success"}, side_effect=side_effect
        )
    return mock.patch.multiple("core.tasks.datagouv", **mocks), mocks


def test_run_dataset_uploads_runs_every_dataset_in_order():
    """Without names, every dataset is uploaded, in the declared order."""
    patcher, mocks = _patch_tasks()
    calls = []
    for name, task in mocks.items():
        task.side_effect = lambda name=name: calls.append(name) or {"status": "ok"}

    with patcher:
        results, failed = run_dataset_uploads()

    assert calls == DATASET_TASKS
    assert not failed
    assert results == {name: {"status": "ok"} for name in DATASET_TASKS}


def test_run_dataset_uploads_keeps_going_after_a_failure():
    """A failing upload does not stop the others, and is reported."""
    patcher, mocks = _patch_tasks(failing=["upload_deployment_operators_dataset"])
    reported = []
    with patcher:
        results, failed = run_dataset_uploads(
            report=lambda name, outcome: reported.append((name, outcome))
        )

    for task in mocks.values():
        task.assert_called_once_with()
    assert failed == ["upload_deployment_operators_dataset"]
    assert "upload_deployment_operators_dataset" not in results
    assert len(results) == len(DATASET_TASKS) - 1
    assert [name for name, _ in reported] == DATASET_TASKS
    assert isinstance(dict(reported)["upload_deployment_operators_dataset"], ValueError)


def test_task_fails_when_an_upload_failed():
    """The scheduled task raises at the end, so the run is marked failed."""
    patcher, _mocks = _patch_tasks(failing=["upload_deployment_metrics_dataset"])
    with patcher, pytest.raises(RuntimeError, match="1 upload\\(s\\) failed"):
        upload_deployment_datasets()


def test_task_returns_the_results():
    """All good: the task returns the result of every upload."""
    patcher, _mocks = _patch_tasks()
    with patcher:
        assert upload_deployment_datasets() == {
            name: {"status": "success"} for name in DATASET_TASKS
        }


def test_command_uploads_only_the_given_datasets():
    """Task names given as arguments restrict the run to those."""
    patcher, mocks = _patch_tasks()
    out = StringIO()
    with patcher:
        call_command(
            "upload_deployment_datasets",
            "upload_deployment_metrics_dataset",
            "upload_deployment_services_dataset",
            stdout=out,
        )

    mocks["upload_deployment_metrics_dataset"].assert_called_once_with()
    mocks["upload_deployment_services_dataset"].assert_called_once_with()
    for name in DATASET_TASKS:
        if name not in (
            "upload_deployment_metrics_dataset",
            "upload_deployment_services_dataset",
        ):
            mocks[name].assert_not_called()
    assert "upload_deployment_metrics_dataset: {'status': 'success'}" in out.getvalue()


def test_command_fails_at_the_end_when_an_upload_failed():
    """The command exits non-zero, naming the failed uploads."""
    patcher, mocks = _patch_tasks(failing=["upload_deployment_operators_dataset"])
    err = StringIO()
    with patcher, pytest.raises(CommandError, match="1 upload\\(s\\) failed"):
        call_command("upload_deployment_datasets", stdout=StringIO(), stderr=err)

    for task in mocks.values():
        task.assert_called_once_with()
    assert "upload_deployment_operators_dataset failed: boom" in err.getvalue()


def test_command_rejects_an_unknown_dataset():
    """An unknown task name is rejected by argparse before anything runs."""
    patcher, mocks = _patch_tasks()
    with patcher, pytest.raises(CommandError, match="invalid choice"):
        call_command("upload_deployment_datasets", "not_a_dataset", stdout=StringIO())

    for task in mocks.values():
        task.assert_not_called()
