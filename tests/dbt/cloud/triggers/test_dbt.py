import asyncio
import time
from unittest import mock

import pytest
from airflow.providers.dbt.cloud.hooks.dbt import DbtCloudJobRunStatus
from airflow.triggers.base import TriggerEvent

from astronomer.providers.dbt.cloud.hooks.dbt import DbtCloudHookAsync
from astronomer.providers.dbt.cloud.triggers.dbt import DbtCloudRunJobTrigger


class TestDbtCloudRunJobTrigger:
    DAG_ID = "dbt_cloud_run"
    TASK_ID = "dbt_cloud_run_task_op"
    RUN_ID = 1234
    CONN_ID = "dbt_cloud_default"
    ACCOUNT_ID = 12340
    END_TIME = time.time() + 60 * 60 * 24 * 7
    POLL_INTERVAL = 3.0

    def test_serialization(self):
        """Assert DbtCloudRunJobTrigger correctly serializes its arguments and classpath."""
        trigger = DbtCloudRunJobTrigger(
            conn_id=self.CONN_ID,
            poll_interval=self.POLL_INTERVAL,
            end_time=self.END_TIME,
            run_id=self.RUN_ID,
            account_id=self.ACCOUNT_ID,
        )
        classpath, kwargs = trigger.serialize()
        assert classpath == "astronomer.providers.dbt.cloud.triggers.dbt.DbtCloudRunJobTrigger"
        assert kwargs == {
            "run_id": self.RUN_ID,
            "account_id": self.ACCOUNT_ID,
            "conn_id": self.CONN_ID,
            "end_time": self.END_TIME,
            "poll_interval": self.POLL_INTERVAL,
        }

    @pytest.mark.asyncio
    @mock.patch("astronomer.providers.dbt.cloud.triggers.dbt.DbtCloudRunJobTrigger.is_still_running")
    async def test_dbt_run_job_trigger(self, mocked_is_still_running):
        """Test DbtCloudRunJobTrigger is triggered with mocked details and run successfully."""
        mocked_is_still_running.return_value = True
        trigger = DbtCloudRunJobTrigger(
            conn_id=self.CONN_ID,
            poll_interval=self.POLL_INTERVAL,
            end_time=self.END_TIME,
            run_id=self.RUN_ID,
            account_id=self.ACCOUNT_ID,
        )
        task = asyncio.create_task(trigger.run().__anext__())
        await asyncio.sleep(0.5)

        # TriggerEvent was not returned
        assert task.done() is False
        asyncio.get_event_loop().stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "mock_value, mock_status, mock_message",
        [
            (DbtCloudJobRunStatus.SUCCESS.value, "success", "Job run 1234 has completed successfully."),
            (DbtCloudJobRunStatus.CANCELLED.value, "cancelled", "Job run 1234 has been cancelled."),
            (DbtCloudJobRunStatus.ERROR.value, "error", "Job run 1234 has failed."),
        ],
    )
    @mock.patch("astronomer.providers.dbt.cloud.triggers.dbt.DbtCloudRunJobTrigger.is_still_running")
    @mock.patch("astronomer.providers.dbt.cloud.hooks.dbt.DbtCloudHookAsync.get_job_status")
    async def test_dbt_job_run_for_terminal_status(
        self, mock_get_job_status, mocked_is_still_running, mock_value, mock_status, mock_message
    ):
        """Assert that run trigger success message in case of job success"""
        mocked_is_still_running.return_value = False
        mock_get_job_status.return_value = mock_value
        trigger = DbtCloudRunJobTrigger(
            conn_id=self.CONN_ID,
            poll_interval=self.POLL_INTERVAL,
            end_time=self.END_TIME,
            run_id=self.RUN_ID,
            account_id=self.ACCOUNT_ID,
        )
        expected_result = {
            "status": mock_status,
            "message": mock_message,
            "run_id": self.RUN_ID,
        }
        generator = trigger.run()
        actual = await generator.asend(None)
        assert TriggerEvent(expected_result) == actual

    @pytest.mark.asyncio
    @mock.patch("astronomer.providers.dbt.cloud.triggers.dbt.DbtCloudRunJobTrigger.is_still_running")
    @mock.patch("astronomer.providers.dbt.cloud.hooks.dbt.DbtCloudHookAsync.get_job_status")
    async def test_dbt_job_run_exception(self, mock_get_job_status, mocked_is_still_running):
        """Assert that run catch exception if dbt cloud job API throw exception"""
        mocked_is_still_running.return_value = False
        mock_get_job_status.side_effect = Exception("Test exception")
        trigger = DbtCloudRunJobTrigger(
            conn_id=self.CONN_ID,
            poll_interval=self.POLL_INTERVAL,
            end_time=self.END_TIME,
            run_id=self.RUN_ID,
            account_id=self.ACCOUNT_ID,
        )
        task = [i async for i in trigger.run()]
        response = TriggerEvent(
            {
                "status": "error",
                "message": "Test exception",
                "run_id": self.RUN_ID,
            }
        )
        assert len(task) == 1
        assert response in task

    @pytest.mark.asyncio
    @mock.patch("astronomer.providers.dbt.cloud.triggers.dbt.DbtCloudRunJobTrigger.is_still_running")
    @mock.patch("astronomer.providers.dbt.cloud.hooks.dbt.DbtCloudHookAsync.get_job_status")
    async def test_dbt_job_run_timeout(self, mock_get_job_status, mocked_is_still_running):
        """Assert that run timeout after end_time elapsed"""
        mocked_is_still_running.return_value = True
        mock_get_job_status.side_effect = Exception("Test exception")
        end_time = time.time()
        trigger = DbtCloudRunJobTrigger(
            conn_id=self.CONN_ID,
            poll_interval=self.POLL_INTERVAL,
            end_time=end_time,
            run_id=self.RUN_ID,
            account_id=self.ACCOUNT_ID,
        )
        generator = trigger.run()
        actual = await generator.asend(None)
        expected = TriggerEvent(
            {
                "status": "error",
                "message": f"Job run {self.RUN_ID} has not reached a terminal status after {end_time} seconds.",
                "run_id": self.RUN_ID,
            }
        )
        assert expected == actual

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "mock_response, expected_status",
        [
            (DbtCloudJobRunStatus.SUCCESS.value, False),
            (DbtCloudJobRunStatus.RUNNING.value, True),
            (DbtCloudJobRunStatus.QUEUED.value, True),
        ],
    )
    @mock.patch("astronomer.providers.dbt.cloud.hooks.dbt.DbtCloudHookAsync.get_job_status")
    async def test_dbt_job_run_is_still_running(self, mock_get_job_status, mock_response, expected_status):
        """Test is_still_running with mocked response job status and assert the return response with expected value"""
        hook = mock.AsyncMock(DbtCloudHookAsync)
        hook.get_job_status.return_value = mock_response
        trigger = DbtCloudRunJobTrigger(
            conn_id=self.CONN_ID,
            poll_interval=self.POLL_INTERVAL,
            end_time=self.END_TIME,
            run_id=self.RUN_ID,
            account_id=self.ACCOUNT_ID,
        )
        response = await trigger.is_still_running(hook)
        assert response == expected_status
