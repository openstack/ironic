# coding=utf-8

# Copyright 2013 Hewlett-Packard Development Company, L.P.
# Copyright 2013 International Business Machines Corporation
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

"""Test class for Ironic ManagerService."""

from unittest import mock

from oslo_config import cfg

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as conductor_utils
from ironic.conductor import verify
from ironic import objects
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF


@mgr_utils.mock_record_keepalive
class DoNodeVerifyTestCase(mgr_utils.ServiceSetUpMixin, db_base.DbTestCase):
    @mock.patch.object(conductor_utils, 'node_cache_vendor', autospec=True)
    @mock.patch('ironic.objects.node.NodeCorrectedPowerStateNotification',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.get_power_state',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    def test__do_node_verify(self, mock_validate, mock_get_power_state,
                             mock_notif, mock_cache_vendor):
        self._start_service()
        mock_get_power_state.return_value = states.POWER_OFF
        # Required for exception handling
        mock_notif.__name__ = 'NodeCorrectedPowerStateNotification'
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.VERIFYING,
            target_provision_state=states.MANAGEABLE,
            last_error=None,
            power_state=states.NOSTATE)

        with task_manager.acquire(
                self.context, node['id'], shared=False) as task:
            verify.do_node_verify(task)

        self._stop_service()

        # 1 notification should be sent -
        # baremetal.node.power_state_corrected.success
        mock_notif.assert_called_once_with(publisher=mock.ANY,
                                           event_type=mock.ANY,
                                           level=mock.ANY,
                                           payload=mock.ANY)
        mock_notif.return_value.emit.assert_called_once_with(mock.ANY)

        node.refresh()

        mock_validate.assert_called_once_with(mock.ANY, task)
        mock_get_power_state.assert_called_once_with(mock.ANY, task)

        self.assertEqual(states.MANAGEABLE, node.provision_state)
        self.assertIsNone(node.target_provision_state)
        self.assertIsNone(node.last_error)
        self.assertEqual(states.POWER_OFF, node.power_state)

    @mock.patch('ironic.drivers.modules.fake.FakePower.get_power_state',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    def test__do_node_verify_validation_fails(self, mock_validate,
                                              mock_get_power_state):
        self._start_service()
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.VERIFYING,
            target_provision_state=states.MANAGEABLE,
            last_error=None,
            power_state=states.NOSTATE)

        mock_validate.side_effect = RuntimeError("boom")

        with task_manager.acquire(
                self.context, node['id'], shared=False) as task:
            verify.do_node_verify(task)

        self._stop_service()
        node.refresh()

        mock_validate.assert_called_once_with(mock.ANY, task)

        self.assertEqual(states.ENROLL, node.provision_state)
        self.assertIsNone(node.target_provision_state)
        self.assertTrue(node.last_error)
        self.assertFalse(mock_get_power_state.called)

    @mock.patch('ironic.drivers.modules.fake.FakePower.get_power_state',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    def test__do_node_verify_get_state_fails(self, mock_validate,
                                             mock_get_power_state):
        self._start_service()
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.VERIFYING,
            target_provision_state=states.MANAGEABLE,
            last_error=None,
            power_state=states.NOSTATE)

        mock_get_power_state.side_effect = RuntimeError("boom")

        with task_manager.acquire(
                self.context, node['id'], shared=False) as task:
            verify.do_node_verify(task)

        self._stop_service()
        node.refresh()

        mock_get_power_state.assert_called_once_with(mock.ANY, task)

        self.assertEqual(states.ENROLL, node.provision_state)
        self.assertIsNone(node.target_provision_state)
        self.assertTrue(node.last_error)
        history = objects.NodeHistory.list_by_node_id(self.context,
                                                      node.id)
        entry = history[0]
        self.assertEqual('verify', entry['event_type'])
        self.assertEqual('ERROR', entry['severity'])

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeBIOS.cache_bios_settings',
                autospec=True)
    def _test__do_node_cache_bios(self, mock_bios, mock_validate,
                                  mock_log,
                                  enable_unsupported=False,
                                  enable_exception=False):
        if enable_unsupported:
            mock_bios.side_effect = exception.UnsupportedDriverExtension('')
        elif enable_exception:
            mock_bios.side_effect = exception.IronicException('test')
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.VERIFYING,
            target_provision_state=states.MANAGEABLE)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            verify.do_node_verify(task)
            mock_bios.assert_called_once_with(mock.ANY, task)
            mock_validate.assert_called_once_with(mock.ANY, task)
            if enable_exception:
                mock_log.exception.assert_called_once_with(
                    'Caching of bios settings failed on node {}.'
                    .format(node.uuid))

    def test__do_node_cache_bios(self):
        self._test__do_node_cache_bios()

    def test__do_node_cache_bios_exception(self):
        self._test__do_node_cache_bios(enable_exception=True)

    def test__do_node_cache_bios_unsupported(self):
        self._test__do_node_cache_bios(enable_unsupported=True)
