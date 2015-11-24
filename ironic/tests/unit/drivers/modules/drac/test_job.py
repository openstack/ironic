#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
Test class for DRAC job specific methods
"""

from dracclient import exceptions as drac_exceptions
import mock

from ironic.common import exception
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_drac_info()


@mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                   autospec=True)
class DracJobTestCase(db_base.DbTestCase):

    def setUp(self):
        super(DracJobTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
                                               driver_info=INFO_DICT)

    def test_validate_job_queue(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_jobs.return_value = []

        drac_job.validate_job_queue(self.node)

        mock_client.list_jobs.assert_called_once_with(only_unfinished=True)

    def test_validate_job_queue_fail(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        exc = drac_exceptions.BaseClientException('boom')
        mock_client.list_jobs.side_effect = exc

        self.assertRaises(exception.DracOperationError,
                          drac_job.validate_job_queue, self.node)

    def test_validate_job_queue_invalid(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_jobs.return_value = [42]

        self.assertRaises(exception.DracOperationError,
                          drac_job.validate_job_queue, self.node)
