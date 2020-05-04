# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import subprocess
from unittest import mock

from ironic_lib import utils
from oslo_concurrency import processutils

from ironic.tests import base


class BlockExecuteTestCase(base.TestCase):
    """Test to ensure we block access to the 'execute' type functions"""

    def test_exception_raised_for_execute(self):
        execute_functions = (processutils.execute, subprocess.Popen,
                             subprocess.call, subprocess.check_call,
                             subprocess.check_output, utils.execute)

        for function_name in execute_functions:
            exc = self.assertRaises(
                Exception,
                function_name,
                ["echo", "%s" % function_name])  # noqa
            # Have to use 'noqa' as we are raising plain Exception and we will
            # get H202 error in 'pep8' check.

            self.assertEqual(
                "Don't call ironic_lib.utils.execute() / "
                "processutils.execute() or similar functions in tests!",
                "%s" % exc)

    @mock.patch.object(utils, "execute", autospec=True)
    def test_can_mock_execute(self, mock_exec):
        # NOTE(jlvillal): We had discovered an issue where mocking wasn't
        # working because we had used a mock to block access to the execute
        # functions. This caused us to "mock a mock" and didn't work correctly.
        # We want to make sure that we can mock our execute functions even with
        # our "block execute" code.
        utils.execute("ls")
        utils.execute("echo")
        self.assertEqual(2, mock_exec.call_count)

    @mock.patch.object(processutils, "execute", autospec=True)
    def test_exception_raised_for_execute_parent_mocked(self, mock_exec):
        # Make sure that even if we mock the parent execute function, that we
        # still get an exception for a child. So in this case
        # ironic_lib.utils.execute() calls processutils.execute(). Make sure an
        # exception is raised even though we mocked processutils.execute()
        exc = self.assertRaises(
            Exception,
            utils.execute,
            "ls")  # noqa
        # Have to use 'noqa' as we are raising plain Exception and we will get
        # H202 error in 'pep8' check.

        self.assertEqual(
            "Don't call ironic_lib.utils.execute() / "
            "processutils.execute() or similar functions in tests!",
            "%s" % exc)


class DontBlockExecuteTestCase(base.TestCase):
    """Ensure we can turn off blocking access to 'execute' type functions"""

    # Don't block the execute function
    block_execute = False

    @mock.patch.object(processutils, "execute", autospec=True)
    def test_no_exception_raised_for_execute(self, mock_exec):
        # Make sure we can call ironic_lib.utils.execute() even though we
        # didn't mock it. We do mock processutils.execute() so we don't
        # actually execute anything.
        utils.execute("ls")
        utils.execute("echo")
        self.assertEqual(2, mock_exec.call_count)
