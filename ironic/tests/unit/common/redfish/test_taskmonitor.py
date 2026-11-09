# Copyright (c) 2021 Dell, Inc. or its subsidiaries
# Copyright 2024 Red Hat, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Unit tests for async Redfish task monitor."""

import asyncio
import contextlib
from http import client as http_client
import json
from unittest import mock

from ironic.common.redfish import connector
from ironic.common.redfish import exceptions
from ironic.common.redfish import taskmonitor
from ironic.tests import base


@contextlib.contextmanager
def virtual_clock(sleeps):
    """Run wait() against a virtual clock instead of wall time.

    Every sleep is recorded in ``sleeps`` and advances the clock the
    monitor reads, so the polling schedule can be asserted exactly
    without the test spending that time.

    :param sleeps: list the sleep durations are appended to
    :returns: dict whose 'now' key holds the elapsed virtual time
    """
    clock = {'now': 0.0}

    class FakeLoop:
        @staticmethod
        def time():
            return clock['now']

    async def fake_sleep(duration):
        sleeps.append(duration)
        clock['now'] += duration

    with mock.patch.object(taskmonitor.asyncio, 'get_event_loop',
                           autospec=True, return_value=FakeLoop), \
            mock.patch.object(taskmonitor.asyncio, 'sleep', fake_sleep):
        yield clock


class AsyncTaskMonitorTestCase(base.TestCase):
    """Test AsyncTaskMonitor class."""

    def setUp(self):
        super().setUp()
        self.mock_connector = mock.AsyncMock()
        self.task_uri = '/redfish/v1/TaskService/Tasks/1'

        self.task_json = {
            '@odata.id': '/redfish/v1/TaskService/Tasks/1',
            'Id': '1',
            'Name': 'Task 1',
            'TaskState': 'Running',
            'TaskStatus': 'OK',
            'PercentComplete': 50
        }

    def test_init_with_response_accepted(self):
        """Test initialization with 202 Accepted response."""
        mock_response = mock.MagicMock()
        mock_response.status_code = http_client.ACCEPTED
        mock_response.content = json.dumps(self.task_json).encode('utf-8')
        mock_response.json.return_value = self.task_json
        mock_response.headers = {
            'Location': self.task_uri,
            'Retry-After': '5'
        }

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri,
                mock_response
            )
            await monitor._initialize()

            self.assertEqual(self.task_uri, monitor.task_monitor_uri)
            self.assertTrue(monitor.is_processing)
            self.assertIsNotNone(monitor.task_resource)

        asyncio.run(run_test())

    def test_init_with_response_no_content(self):
        """Test initialization with 202 Accepted but no content."""
        mock_response = mock.MagicMock()
        mock_response.status_code = http_client.ACCEPTED
        mock_response.content = None
        mock_response.headers = {
            'Location': self.task_uri
        }

        self.mock_connector.get = mock.AsyncMock(return_value=mock_response)

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri,
                mock_response
            )
            await monitor._initialize()

            self.assertIsNone(monitor.task_resource)

        asyncio.run(run_test())

    def test_init_no_response(self):
        """Test initialization without initial response."""
        mock_response = mock.MagicMock()
        mock_response.status_code = http_client.ACCEPTED
        mock_response.content = json.dumps(self.task_json).encode('utf-8')
        mock_response.json.return_value = self.task_json
        mock_response.headers = {}

        self.mock_connector.get = mock.AsyncMock(return_value=mock_response)

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri
            )
            await monitor._initialize()

            self.mock_connector.get.assert_called_once_with(
                path=self.task_uri
            )
            self.assertIsNotNone(monitor.task_resource)

        asyncio.run(run_test())

    def test_refresh_still_processing(self):
        """Test refresh when task is still processing."""
        mock_response = mock.MagicMock()
        mock_response.status_code = http_client.ACCEPTED
        mock_response.content = json.dumps(self.task_json).encode('utf-8')
        mock_response.json.return_value = self.task_json
        mock_response.headers = {}

        self.mock_connector.get = mock.AsyncMock(return_value=mock_response)

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri,
                mock_response
            )
            await monitor._initialize()

            # Update progress
            updated_json = self.task_json.copy()
            updated_json['PercentComplete'] = 75
            mock_response.json.return_value = updated_json

            await monitor.refresh()

            self.assertTrue(monitor.is_processing)
            self.assertIsNotNone(monitor.task_resource)
            self.assertEqual(75,
                             monitor.task_resource.json['PercentComplete'])

        asyncio.run(run_test())

    def test_refresh_completed(self):
        """Test refresh when task has completed."""
        mock_response = mock.MagicMock()
        mock_response.status_code = http_client.ACCEPTED
        mock_response.content = json.dumps(self.task_json).encode('utf-8')
        mock_response.json.return_value = self.task_json
        mock_response.headers = {}

        completed_response = mock.MagicMock()
        completed_response.status_code = http_client.OK
        completed_response.headers = {}

        self.mock_connector.get = mock.AsyncMock(
            return_value=completed_response
        )

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri,
                mock_response
            )
            await monitor._initialize()

            # Change mock to return completed
            self.mock_connector.get.return_value = completed_response

            await monitor.refresh()

            self.assertFalse(monitor.is_processing)
            self.assertIsNone(monitor.task_resource)

        asyncio.run(run_test())

    def test_is_processing(self):
        """Test is_processing property."""
        mock_response = mock.MagicMock()
        mock_response.status_code = http_client.ACCEPTED
        mock_response.content = json.dumps(self.task_json).encode('utf-8')
        mock_response.json.return_value = self.task_json

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri,
                mock_response
            )
            await monitor._initialize()

            self.assertTrue(monitor.is_processing)

            # Change to completed
            monitor._response.status_code = http_client.OK
            self.assertFalse(monitor.is_processing)

        asyncio.run(run_test())

    def test_check_is_processing(self):
        """Test check_is_processing method."""
        mock_response = mock.MagicMock()
        mock_response.status_code = http_client.ACCEPTED
        mock_response.content = json.dumps(self.task_json).encode('utf-8')
        mock_response.json.return_value = self.task_json

        completed_response = mock.MagicMock()
        completed_response.status_code = http_client.OK

        self.mock_connector.get = mock.AsyncMock(
            return_value=completed_response
        )

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri,
                mock_response
            )
            await monitor._initialize()

            # Should refresh and return False
            result = await monitor.check_is_processing()

            self.assertFalse(result)
            self.mock_connector.get.assert_called_with(path=self.task_uri)

        asyncio.run(run_test())

    def test_sleep_for_default(self):
        """Test sleep_for with no Retry-After header."""
        mock_response = mock.MagicMock()
        mock_response.status_code = http_client.ACCEPTED
        mock_response.headers = {}

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri,
                mock_response
            )

            self.assertEqual(1, monitor.sleep_for)

        asyncio.run(run_test())

    def test_sleep_for_integer(self):
        """Test sleep_for with integer Retry-After."""
        mock_response = mock.MagicMock()
        mock_response.status_code = http_client.ACCEPTED
        mock_response.headers = {'Retry-After': '10'}

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri,
                mock_response
            )

            self.assertEqual(10, monitor.sleep_for)

        asyncio.run(run_test())

    def test_cancellable_true(self):
        """Test cancellable property when DELETE is allowed."""
        mock_response = mock.MagicMock()
        mock_response.status_code = http_client.ACCEPTED
        mock_response.headers = {'Allow': 'DELETE'}

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri,
                mock_response
            )

            self.assertTrue(monitor.cancellable)

        asyncio.run(run_test())

    def test_cancellable_false(self):
        """Test cancellable property when DELETE is not allowed."""
        mock_response = mock.MagicMock()
        mock_response.status_code = http_client.ACCEPTED
        mock_response.headers = {'Allow': 'GET'}

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri,
                mock_response
            )

            self.assertFalse(monitor.cancellable)

        asyncio.run(run_test())

    def test_wait_completes(self):
        """Test wait method when task completes."""
        processing_response = mock.MagicMock()
        processing_response.status_code = http_client.ACCEPTED
        processing_response.content = json.dumps(self.task_json).encode(
            'utf-8'
        )
        processing_response.json.return_value = self.task_json
        processing_response.headers = {'Retry-After': '0'}

        completed_response = mock.MagicMock()
        completed_response.status_code = http_client.OK
        completed_response.headers = {}

        # First call returns processing, second returns completed
        self.mock_connector.get = mock.AsyncMock(
            side_effect=[processing_response, completed_response]
        )

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri,
                processing_response
            )
            await monitor._initialize()

            await monitor.wait(timeout_sec=10)

            # Should have called refresh once during wait
            self.assertEqual(2, self.mock_connector.get.call_count)

        asyncio.run(run_test())

    def test_wait_timeout(self):
        """Test wait method timeout."""
        processing_response = mock.MagicMock()
        processing_response.status_code = http_client.ACCEPTED
        processing_response.content = json.dumps(self.task_json).encode(
            'utf-8'
        )
        processing_response.json.return_value = self.task_json
        processing_response.headers = {'Retry-After': '0'}

        # Always return processing
        self.mock_connector.get = mock.AsyncMock(
            return_value=processing_response
        )

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri,
                processing_response
            )
            await monitor._initialize()

            try:
                await monitor.wait(timeout_sec=1)
                return None  # Should not reach here
            except exceptions.ConnectionError as e:
                return e

        exception = asyncio.run(run_test())
        self.assertIsNotNone(exception)
        self.assertIsInstance(exception, exceptions.ConnectionError)
        self.assertIn('Timeout', str(exception))

    def _processing_response(self, retry_after):
        """Build a 202 response carrying a task body and a Retry-After."""
        response = mock.MagicMock()
        response.status_code = http_client.ACCEPTED
        response.content = json.dumps(self.task_json).encode('utf-8')
        response.json.return_value = self.task_json
        response.headers = {'Retry-After': retry_after}
        return response

    def _wait(self, monitor_response, get_response, timeout_sec):
        """Run wait() on a virtual clock, returning sleeps and outcome."""
        self.mock_connector.get = mock.AsyncMock(return_value=get_response)
        sleeps = []

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri,
                monitor_response
            )
            await monitor._initialize()

            with virtual_clock(sleeps) as clock:
                try:
                    await monitor.wait(timeout_sec=timeout_sec)
                    return None, clock['now']
                except exceptions.ConnectionError as e:
                    return e, clock['now']

        exception, elapsed = asyncio.run(run_test())
        return sleeps, exception, elapsed

    def test_wait_honours_retry_after_before_first_poll(self):
        """The Retry-After already held is waited out before polling.

        The monitor starts with a 202 asking for 30 seconds, so the first
        poll must come after that sleep, not immediately.
        """
        completed_response = mock.MagicMock()
        completed_response.status_code = http_client.OK
        completed_response.headers = {}

        sleeps, exception, elapsed = self._wait(
            self._processing_response('30'),
            completed_response,
            timeout_sec=300)

        self.assertIsNone(exception)
        self.assertEqual([30], sleeps)
        self.assertEqual(1, self.mock_connector.get.call_count)

    def test_wait_caps_sleep_at_remaining_timeout(self):
        """A Retry-After longer than the timeout cannot stretch the wait.

        With a 60 second Retry-After and a 1 second budget the monitor
        sleeps 1 second, spends the deadline on a final poll, and gives
        up - it does not return after 60 seconds.
        """
        sleeps, exception, elapsed = self._wait(
            self._processing_response('60'),
            self._processing_response('60'),
            timeout_sec=1)

        self.assertIsInstance(exception, exceptions.ConnectionError)
        self.assertIn('Timeout', str(exception))
        self.assertEqual([1], sleeps)
        self.assertEqual(1, elapsed)
        self.assertEqual(1, self.mock_connector.get.call_count)

    def test_wait_polls_until_timeout_is_spent(self):
        """Successive Retry-After waits are bounded by the whole budget."""
        sleeps, exception, elapsed = self._wait(
            self._processing_response('2'),
            self._processing_response('2'),
            timeout_sec=5)

        self.assertIsInstance(exception, exceptions.ConnectionError)
        self.assertEqual([2, 2, 1], sleeps)
        self.assertEqual(5, elapsed)
        self.assertEqual(3, self.mock_connector.get.call_count)

    def test_wait_gives_up_on_a_poll_that_never_answers(self):
        """An unresponsive BMC cannot stretch the wait past the budget.

        The sleep spends the whole budget, so the final poll is floored at
        MIN_POLL_TIMEOUT. A BMC that never answers it is given up on,
        instead of the poll occupying the connector's whole retry chain.
        """
        sleeps = []

        async def never_answers(*args, **kwargs):
            # A future nothing ever resolves: the poll hangs until the
            # bound in wait() cancels it.
            await asyncio.get_running_loop().create_future()

        self.mock_connector.get = mock.AsyncMock(side_effect=never_answers)

        async def run_test():
            monitor = taskmonitor.AsyncTaskMonitor(
                self.mock_connector,
                self.task_uri,
                self._processing_response('60')
            )
            # The 202 carries a body, so this costs no GET.
            await monitor._initialize()

            with virtual_clock(sleeps) as clock:
                try:
                    await monitor.wait(timeout_sec=1)
                    return None, clock['now']
                except exceptions.ConnectionError as e:
                    return e, clock['now']

        # Keep the floor short so the test does not wait it out for real.
        with mock.patch.object(taskmonitor, 'MIN_POLL_TIMEOUT', 0.01):
            exception, elapsed = asyncio.run(run_test())

        self.assertIsInstance(exception, exceptions.ConnectionError)
        self.assertIn('Timeout', str(exception))
        self.assertEqual([1], sleeps)
        self.assertEqual(1, elapsed)
        self.assertEqual(1, self.mock_connector.get.call_count)

    def test_wait_does_not_poll_when_already_completed(self):
        """A monitor that is not processing returns without sleeping."""
        completed_response = mock.MagicMock()
        completed_response.status_code = http_client.OK
        completed_response.content = b''
        completed_response.headers = {}

        sleeps, exception, elapsed = self._wait(
            completed_response, completed_response, timeout_sec=10)

        self.assertIsNone(exception)
        self.assertEqual([], sleeps)
        # Only the refresh _initialize does for a non-202 response.
        self.assertEqual(1, self.mock_connector.get.call_count)

    def test_from_response_with_location(self):
        """Test from_response with Location header."""
        mock_response = mock.MagicMock()
        mock_response.status_code = http_client.ACCEPTED
        mock_response.content = json.dumps(self.task_json).encode('utf-8')
        mock_response.json.return_value = self.task_json
        mock_response.headers = {'Location': self.task_uri}

        async def run_test():
            monitor = await taskmonitor.AsyncTaskMonitor.from_response(
                self.mock_connector,
                mock_response,
                '/redfish/v1/Systems/1'
            )

            self.assertEqual(self.task_uri, monitor.task_monitor_uri)
            self.assertTrue(monitor.is_processing)

        asyncio.run(run_test())

    def test_from_response_with_odata_id(self):
        """Test from_response with @odata.id in body."""
        mock_response = mock.MagicMock()
        mock_response.status_code = http_client.ACCEPTED
        mock_response.content = json.dumps(self.task_json).encode('utf-8')
        mock_response.json.return_value = self.task_json
        mock_response.headers = {}

        async def run_test():
            monitor = await taskmonitor.AsyncTaskMonitor.from_response(
                self.mock_connector,
                mock_response,
                '/redfish/v1/Systems/1'
            )

            self.assertEqual(self.task_uri, monitor.task_monitor_uri)

        asyncio.run(run_test())

    def test_from_response_missing_location(self):
        """Test from_response without Location header."""
        mock_response = mock.MagicMock()
        mock_response.status_code = http_client.ACCEPTED
        mock_response.content = json.dumps({}).encode('utf-8')
        mock_response.json.return_value = {}
        mock_response.headers = {}

        async def run_test():
            try:
                await taskmonitor.AsyncTaskMonitor.from_response(
                    self.mock_connector,
                    mock_response,
                    '/redfish/v1/Systems/1'
                )
                return None  # Should not reach here
            except exceptions.MissingHeaderError as e:
                return e

        exception = asyncio.run(run_test())
        self.assertIsNotNone(exception)
        self.assertIsInstance(exception, exceptions.MissingHeaderError)


class TaskMonitorConnectorContractTestCase(base.TestCase):
    """Pin the contract between AsyncConnector and AsyncTaskMonitor.

    Every other test here mocks the connector, which hides whether what
    it really returns matches what the monitor expects. refresh() reads
    .status_code, .content and .json() off the value returned by
    connector.get(); when get() returned a parsed dict instead of the
    response, that was an unconditional AttributeError that the mocks
    masked. These tests drive a real AsyncConnector with only the httpx
    transport mocked.
    """

    def setUp(self):
        super().setUp()
        self.task_uri = '/redfish/v1/TaskService/Tasks/1'
        self.task_json = {
            '@odata.id': self.task_uri,
            'Id': '1',
            'TaskState': 'Running',
            'PercentComplete': 50,
        }

    @staticmethod
    def _mock_client(status_code, body, headers):
        content = b'' if body is None else json.dumps(body).encode('utf-8')

        class FakeResponse:
            def __init__(self):
                self.status_code = status_code
                self.headers = headers
                self.content = content

            def json(self):
                if body is None:
                    raise ValueError('no content')
                return body

            def raise_for_status(self):
                pass

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                self.auth = None
                self.headers = {}

            async def request(self, *args, **kwargs):
                return FakeResponse()

            async def aclose(self):
                pass

        return MockAsyncClient

    def _refresh(self, status_code, body, headers=None):
        client = self._mock_client(status_code, body, headers or {})

        async def run_test():
            with mock.patch('httpx.AsyncClient', client):
                async with connector.AsyncConnector('https://bmc') as conn:
                    monitor = taskmonitor.AsyncTaskMonitor(
                        conn, self.task_uri)
                    await monitor.refresh()
                    return monitor

        return asyncio.run(run_test())

    def test_refresh_processing_through_real_connector(self):
        """A 202 with a body yields a populated task resource."""
        monitor = self._refresh(http_client.ACCEPTED, self.task_json)

        self.assertTrue(monitor.is_processing)
        self.assertIsNotNone(monitor.task_resource)
        self.assertEqual(50, monitor.task_resource.json['PercentComplete'])

    def test_refresh_empty_body_through_real_connector(self):
        """A 202 with no body is not an error, it just has no resource."""
        monitor = self._refresh(http_client.ACCEPTED, None)

        self.assertTrue(monitor.is_processing)
        self.assertIsNone(monitor.task_resource)

    def test_refresh_completed_through_real_connector(self):
        """A non-202 means the task finished and carries no resource."""
        monitor = self._refresh(http_client.OK, self.task_json)

        self.assertFalse(monitor.is_processing)
        self.assertIsNone(monitor.task_resource)

    def test_sleep_for_reads_retry_after_header(self):
        """Retry-After is reachable, so headers survive the connector."""
        monitor = self._refresh(http_client.ACCEPTED, self.task_json,
                                headers={'Retry-After': '7'})

        self.assertEqual(7, monitor.sleep_for)

    def test_cancellable_reads_allow_header(self):
        """Allow is reachable, so headers survive the connector."""
        monitor = self._refresh(http_client.ACCEPTED, self.task_json,
                                headers={'Allow': 'GET, DELETE'})

        self.assertTrue(monitor.cancellable)


class UnpolledTaskMonitorTestCase(base.TestCase):
    """A monitor built from a URI alone has no response to read.

    ``response`` is optional, and sushy's TaskMonitor fills the gap by
    refreshing inside __init__ -- which is how Sushy.get_task_monitor()
    hands back a monitor for an operation already in flight, the way
    ironic picks one up again after a conductor restart. The refresh
    here is async, so it cannot happen in __init__, and every property
    that reads the response used to raise AttributeError until the
    first poll.
    """

    def setUp(self):
        super().setUp()
        self.mock_connector = mock.AsyncMock()
        self.task_uri = '/redfish/v1/TaskService/Tasks/1'
        self.monitor = taskmonitor.AsyncTaskMonitor(
            self.mock_connector, self.task_uri)

    def _response(self, status_code, headers=None):
        response = mock.MagicMock()
        response.status_code = status_code
        response.content = None
        response.headers = headers or {}
        return response

    def test_response_is_none(self):
        """The state the other tests here are about."""
        self.assertIsNone(self.monitor.response)

    def test_is_processing_assumes_the_task_is_still_running(self):
        """An unpolled task must not read as finished."""
        self.assertTrue(self.monitor.is_processing)

    def test_sleep_for_falls_back_to_the_default(self):
        self.assertEqual(1, self.monitor.sleep_for)

    def test_cancellable_is_false_until_the_bmc_says_otherwise(self):
        self.assertFalse(self.monitor.cancellable)

    def test_check_is_processing_polls_and_reports_the_bmc_answer(self):
        """The unknown state resolves on the first poll, not before."""
        self.mock_connector.get = mock.AsyncMock(
            return_value=self._response(http_client.OK))

        async def run_test():
            return await self.monitor.check_is_processing()

        self.assertFalse(asyncio.run(run_test()))
        self.mock_connector.get.assert_called_once_with(path=self.task_uri)

    def test_wait_polls_a_monitor_that_has_never_polled(self):
        """wait() has to work on a resumed monitor: it is the whole point."""
        self.mock_connector.get = mock.AsyncMock(
            return_value=self._response(http_client.OK))

        sleeps = []

        async def run_test():
            await self.monitor.wait(timeout_sec=10)

        with virtual_clock(sleeps):
            asyncio.run(run_test())

        self.assertEqual([1], sleeps)
        self.mock_connector.get.assert_called_once_with(path=self.task_uri)

    def test_wait_still_times_out_on_a_task_that_never_finishes(self):
        """The optimistic assumption must not become an endless wait."""
        self.mock_connector.get = mock.AsyncMock(
            return_value=self._response(http_client.ACCEPTED))

        sleeps = []

        async def run_test():
            try:
                await self.monitor.wait(timeout_sec=3)
            except exceptions.ConnectionError as e:
                return e

        with virtual_clock(sleeps):
            result = asyncio.run(run_test())

        self.assertIsInstance(result, exceptions.ConnectionError)
