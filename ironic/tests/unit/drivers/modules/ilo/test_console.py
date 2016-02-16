# Copyright 2015 Hewlett-Packard Development Company, L.P.
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

"""Test class for common methods used by iLO modules."""

import mock
import six

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules import ipmitool
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


if six.PY3:
    import io
    file = io.BytesIO

INFO_DICT = db_utils.get_test_ilo_info()


class IloConsoleInterfaceTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloConsoleInterfaceTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="iscsi_ilo")
        self.node = obj_utils.create_test_node(
            self.context, driver='iscsi_ilo', driver_info=INFO_DICT)

    @mock.patch.object(ipmitool.IPMIShellinaboxConsole, 'validate',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_ipmi_properties', spec_set=True,
                       autospec=True)
    def test_validate(self, update_ipmi_mock,
                      ipmi_validate_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_info['console_port'] = 60
            task.driver.console.validate(task)
            update_ipmi_mock.assert_called_once_with(task)
            ipmi_validate_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(ipmitool.IPMIShellinaboxConsole, 'validate',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_ipmi_properties', spec_set=True,
                       autospec=True)
    def test_validate_exc(self, update_ipmi_mock,
                          ipmi_validate_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.console.validate, task)
            self.assertEqual(0, update_ipmi_mock.call_count)
            self.assertEqual(0, ipmi_validate_mock.call_count)
