# coding=utf-8

# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
"""
Unit Tests for :py:class:`ironic.conductor.rpcapi.ConductorAPI`.
"""

import copy
from unittest import mock

from oslo_config import cfg
import oslo_messaging as messaging
from oslo_messaging import _utils as messaging_utils

from ironic.common import boot_devices
from ironic.common import components
from ironic.common import exception
from ironic.common import indicator_states
from ironic.common import release_mappings
from ironic.common import states
from ironic.conductor import manager as conductor_manager
from ironic.conductor import rpcapi as conductor_rpcapi
from ironic import objects
from ironic.tests import base as tests_base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils

CONF = cfg.CONF


class ConductorRPCAPITestCase(tests_base.TestCase):

    def test_versions_in_sync(self):
        self.assertEqual(
            conductor_manager.ConductorManager.RPC_API_VERSION,
            conductor_rpcapi.ConductorAPI.RPC_API_VERSION)

    @mock.patch('ironic.common.rpc.get_client', autospec=True)
    def test_version_cap(self, mock_get_client):
        conductor_rpcapi.ConductorAPI()
        self.assertEqual(conductor_rpcapi.ConductorAPI.RPC_API_VERSION,
                         mock_get_client.call_args[1]['version_cap'])

    @mock.patch('ironic.common.release_mappings.RELEASE_MAPPING',
                autospec=True)
    @mock.patch('ironic.common.rpc.get_client', autospec=True)
    def test_version_capped(self, mock_get_client, mock_release_mapping):
        CONF.set_override('pin_release_version',
                          release_mappings.RELEASE_VERSIONS[0])
        mock_release_mapping.get.return_value = {'rpc': '3'}
        conductor_rpcapi.ConductorAPI()
        self.assertEqual('3', mock_get_client.call_args[1]['version_cap'])


class RPCAPITestCase(db_base.DbTestCase):

    def setUp(self):
        super(RPCAPITestCase, self).setUp()
        self.fake_node = db_utils.get_test_node(driver='fake-driver')
        self.fake_node_obj = objects.Node._from_db_object(
            self.context, objects.Node(), self.fake_node)
        self.fake_portgroup = db_utils.get_test_portgroup()

    def test_serialized_instance_has_uuid(self):
        self.assertIn('uuid', self.fake_node)

    def test_get_topic_for_known_driver(self):
        CONF.set_override('host', 'fake-host')
        c = self.dbapi.register_conductor({'hostname': 'fake-host',
                                           'drivers': []})
        self.dbapi.register_conductor_hardware_interfaces(
            c.id,
            [{'hardware_type': 'fake-driver', 'interface_type': 'deploy',
              'interface_name': 'iscsi', 'default': True},
             {'hardware_type': 'fake-driver', 'interface_type': 'deploy',
              'interface_name': 'direct', 'default': False}]
        )

        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        expected_topic = 'fake-topic.fake-host'
        self.assertEqual(expected_topic,
                         rpcapi.get_topic_for(self.fake_node_obj))

    def test_get_topic_for_unknown_driver(self):
        CONF.set_override('host', 'fake-host')
        c = self.dbapi.register_conductor({'hostname': 'fake-host',
                                           'drivers': []})
        self.dbapi.register_conductor_hardware_interfaces(
            c.id,
            [{'hardware_type': 'other-driver', 'interface_type': 'deploy',
              'interface_name': 'iscsi', 'default': True},
             {'hardware_type': 'other-driver', 'interface_type': 'deploy',
              'interface_name': 'direct', 'default': False}]
        )

        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        self.assertRaises(exception.NoValidHost,
                          rpcapi.get_topic_for,
                          self.fake_node_obj)

    def test_get_topic_doesnt_cache(self):
        CONF.set_override('host', 'fake-host')

        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        self.assertRaises(exception.TemporaryFailure,
                          rpcapi.get_topic_for,
                          self.fake_node_obj)

        c = self.dbapi.register_conductor({'hostname': 'fake-host',
                                           'drivers': []})
        self.dbapi.register_conductor_hardware_interfaces(
            c.id,
            [{'hardware_type': 'fake-driver', 'interface_type': 'deploy',
              'interface_name': 'iscsi', 'default': True},
             {'hardware_type': 'fake-driver', 'interface_type': 'deploy',
              'interface_name': 'direct', 'default': False}]
        )

        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        expected_topic = 'fake-topic.fake-host'
        self.assertEqual(expected_topic,
                         rpcapi.get_topic_for(self.fake_node_obj))

    def test_get_topic_for_driver_known_driver(self):
        CONF.set_override('host', 'fake-host')
        c = self.dbapi.register_conductor({
            'hostname': 'fake-host',
            'drivers': [],
        })
        self.dbapi.register_conductor_hardware_interfaces(
            c.id,
            [{'hardware_type': 'fake-driver', 'interface_type': 'deploy',
              'interface_name': 'iscsi', 'default': True},
             {'hardware_type': 'fake-driver', 'interface_type': 'deploy',
              'interface_name': 'direct', 'default': False}]
        )
        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        self.assertEqual('fake-topic.fake-host',
                         rpcapi.get_topic_for_driver('fake-driver'))

    def test_get_topic_for_driver_unknown_driver(self):
        CONF.set_override('host', 'fake-host')
        c = self.dbapi.register_conductor({
            'hostname': 'fake-host',
            'drivers': [],
        })
        self.dbapi.register_conductor_hardware_interfaces(
            c.id,
            [{'hardware_type': 'fake-driver', 'interface_type': 'deploy',
              'interface_name': 'iscsi', 'default': True},
             {'hardware_type': 'fake-driver', 'interface_type': 'deploy',
              'interface_name': 'direct', 'default': False}]
        )
        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        self.assertRaises(exception.DriverNotFound,
                          rpcapi.get_topic_for_driver,
                          'fake-driver-2')

    def test_get_topic_for_driver_doesnt_cache(self):
        CONF.set_override('host', 'fake-host')
        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        self.assertRaises(exception.DriverNotFound,
                          rpcapi.get_topic_for_driver,
                          'fake-driver')

        c = self.dbapi.register_conductor({
            'hostname': 'fake-host',
            'drivers': [],
        })
        self.dbapi.register_conductor_hardware_interfaces(
            c.id,
            [{'hardware_type': 'fake-driver', 'interface_type': 'deploy',
              'interface_name': 'iscsi', 'default': True},
             {'hardware_type': 'fake-driver', 'interface_type': 'deploy',
              'interface_name': 'direct', 'default': False}]
        )
        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        self.assertEqual('fake-topic.fake-host',
                         rpcapi.get_topic_for_driver('fake-driver'))

    def test_get_conductor_for(self):
        CONF.set_override('host', 'fake-host')
        c = self.dbapi.register_conductor({'hostname': 'fake-host',
                                           'drivers': []})
        self.dbapi.register_conductor_hardware_interfaces(
            c.id,
            [{'hardware_type': 'fake-driver', 'interface_type': 'deploy',
              'interface_name': 'iscsi', 'default': True},
             {'hardware_type': 'fake-driver', 'interface_type': 'deploy',
              'interface_name': 'direct', 'default': False}]
        )
        rpcapi = conductor_rpcapi.ConductorAPI()
        self.assertEqual(rpcapi.get_conductor_for(self.fake_node_obj),
                         'fake-host')

    def test_get_random_topic(self):
        CONF.set_override('host', 'fake-host')
        self.dbapi.register_conductor({'hostname': 'fake-host', 'drivers': []})

        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        expected_topic = 'fake-topic.fake-host'
        self.assertEqual(expected_topic, rpcapi.get_random_topic())

    def test_get_random_topic_no_conductors(self):
        CONF.set_override('host', 'fake-host')

        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        self.assertRaises(exception.TemporaryFailure, rpcapi.get_random_topic)

    def _test_can_send_create_port(self, can_send):
        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        with mock.patch.object(rpcapi.client,
                               "can_send_version",
                               autospec=True) as mock_can_send_version:
            mock_can_send_version.return_value = can_send
            result = rpcapi.can_send_create_port()
            self.assertEqual(can_send, result)
            mock_can_send_version.assert_called_once_with("1.41")

    def test_can_send_create_port_True(self):
        self._test_can_send_create_port(True)

    def test_can_send_create_port_False(self):
        self._test_can_send_create_port(False)

    def _test_rpcapi(self, method, rpc_method, **kwargs):
        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')

        expected_retval = 'hello world' if rpc_method == 'call' else None

        expected_topic = 'fake-topic'
        if 'host' in kwargs:
            expected_topic += ".%s" % kwargs['host']

        target = {
            "topic": expected_topic,
            "version": kwargs.pop('version', rpcapi.RPC_API_VERSION)
        }
        expected_msg = copy.deepcopy(kwargs)

        self.fake_args = None
        self.fake_kwargs = None

        def _fake_can_send_version_method(version):
            return messaging_utils.version_is_compatible(
                rpcapi.RPC_API_VERSION, version)

        def _fake_prepare_method(*args, **kwargs):
            for kwd in kwargs:
                self.assertEqual(kwargs[kwd], target[kwd])
            return rpcapi.client

        def _fake_rpc_method(*args, **kwargs):
            self.fake_args = args
            self.fake_kwargs = kwargs
            if expected_retval:
                return expected_retval

        with mock.patch.object(rpcapi.client,
                               "can_send_version",
                               autospec=True) as mock_can_send_version:
            mock_can_send_version.side_effect = _fake_can_send_version_method
            with mock.patch.object(rpcapi.client, "prepare",
                                   autospec=True) as mock_prepared:
                mock_prepared.side_effect = _fake_prepare_method

                with mock.patch.object(rpcapi.client,
                                       rpc_method,
                                       autospec=True) as mock_method:
                    mock_method.side_effect = _fake_rpc_method
                    retval = getattr(rpcapi, method)(self.context, **kwargs)
                    self.assertEqual(retval, expected_retval)
                    expected_args = [self.context, method, expected_msg]
                    for arg, expected_arg in zip(self.fake_args,
                                                 expected_args):
                        self.assertEqual(arg, expected_arg)

    def test_update_node(self):
        self._test_rpcapi('update_node',
                          'call',
                          version='1.1',
                          node_obj=self.fake_node)

    def test_change_node_power_state(self):
        self._test_rpcapi('change_node_power_state',
                          'call',
                          version='1.39',
                          node_id=self.fake_node['uuid'],
                          new_state=states.POWER_ON)

    def test_vendor_passthru(self):
        self._test_rpcapi('vendor_passthru',
                          'call',
                          version='1.20',
                          node_id=self.fake_node['uuid'],
                          driver_method='test-driver-method',
                          http_method='test-http-method',
                          info={"test_info": "test_value"})

    def test_driver_vendor_passthru(self):
        self._test_rpcapi('driver_vendor_passthru',
                          'call',
                          version='1.20',
                          driver_name='test-driver-name',
                          driver_method='test-driver-method',
                          http_method='test-http-method',
                          info={'test_key': 'test_value'})

    def test_do_node_deploy(self):
        self._test_rpcapi('do_node_deploy',
                          'call',
                          version='1.22',
                          node_id=self.fake_node['uuid'],
                          rebuild=False,
                          configdrive=None)

    def test_do_node_deploy_with_deploy_steps(self):
        self._test_rpcapi('do_node_deploy',
                          'call',
                          version='1.52',
                          node_id=self.fake_node['uuid'],
                          rebuild=False,
                          configdrive=None,
                          deploy_steps={'key': 'value'})

    def test_do_node_tear_down(self):
        self._test_rpcapi('do_node_tear_down',
                          'call',
                          version='1.6',
                          node_id=self.fake_node['uuid'])

    def test_validate_driver_interfaces(self):
        self._test_rpcapi('validate_driver_interfaces',
                          'call',
                          version='1.5',
                          node_id=self.fake_node['uuid'])

    def test_destroy_node(self):
        self._test_rpcapi('destroy_node',
                          'call',
                          version='1.9',
                          node_id=self.fake_node['uuid'])

    def test_get_console_information(self):
        self._test_rpcapi('get_console_information',
                          'call',
                          version='1.11',
                          node_id=self.fake_node['uuid'])

    def test_set_console_mode(self):
        self._test_rpcapi('set_console_mode',
                          'call',
                          version='1.11',
                          node_id=self.fake_node['uuid'],
                          enabled=True)

    def test_create_port(self):
        fake_port = db_utils.get_test_port()
        self._test_rpcapi('create_port',
                          'call',
                          version='1.41',
                          port_obj=fake_port)

    def test_update_port(self):
        fake_port = db_utils.get_test_port()
        self._test_rpcapi('update_port',
                          'call',
                          version='1.13',
                          port_obj=fake_port)

    def test_get_driver_properties(self):
        self._test_rpcapi('get_driver_properties',
                          'call',
                          version='1.16',
                          driver_name='fake-driver')

    def test_set_boot_device(self):
        self._test_rpcapi('set_boot_device',
                          'call',
                          version='1.17',
                          node_id=self.fake_node['uuid'],
                          device=boot_devices.DISK,
                          persistent=False)

    def test_get_boot_device(self):
        self._test_rpcapi('get_boot_device',
                          'call',
                          version='1.17',
                          node_id=self.fake_node['uuid'])

    def test_inject_nmi(self):
        self._test_rpcapi('inject_nmi',
                          'call',
                          version='1.40',
                          node_id=self.fake_node['uuid'])

    def test_get_supported_boot_devices(self):
        self._test_rpcapi('get_supported_boot_devices',
                          'call',
                          version='1.17',
                          node_id=self.fake_node['uuid'])

    def test_set_indicator_state(self):
        self._test_rpcapi('set_indicator_state',
                          'call',
                          version='1.50',
                          node_id=self.fake_node['uuid'],
                          component=components.CHASSIS,
                          indicator='led',
                          state=indicator_states.ON)

    def test_get_indicator_state(self):
        self._test_rpcapi('get_indicator_state',
                          'call',
                          version='1.50',
                          node_id=self.fake_node['uuid'],
                          component=components.CHASSIS,
                          indicator='led')

    def test_get_supported_indicators(self):
        self._test_rpcapi('get_supported_indicators',
                          'call',
                          version='1.50',
                          node_id=self.fake_node['uuid'])

    def test_get_node_vendor_passthru_methods(self):
        self._test_rpcapi('get_node_vendor_passthru_methods',
                          'call',
                          version='1.21',
                          node_id=self.fake_node['uuid'])

    def test_get_driver_vendor_passthru_methods(self):
        self._test_rpcapi('get_driver_vendor_passthru_methods',
                          'call',
                          version='1.21',
                          driver_name='fake-driver')

    def test_inspect_hardware(self):
        self._test_rpcapi('inspect_hardware',
                          'call',
                          version='1.24',
                          node_id=self.fake_node['uuid'])

    def test_continue_node_clean(self):
        self._test_rpcapi('continue_node_clean',
                          'cast',
                          version='1.27',
                          node_id=self.fake_node['uuid'])

    def test_continue_node_deploy(self):
        self._test_rpcapi('continue_node_deploy',
                          'cast',
                          version='1.45',
                          node_id=self.fake_node['uuid'])

    def test_get_raid_logical_disk_properties(self):
        self._test_rpcapi('get_raid_logical_disk_properties',
                          'call',
                          version='1.30',
                          driver_name='fake-driver')

    def test_set_target_raid_config(self):
        self._test_rpcapi('set_target_raid_config',
                          'call',
                          version='1.30',
                          node_id=self.fake_node['uuid'],
                          target_raid_config='config')

    def test_do_node_clean(self):
        clean_steps = [{'step': 'upgrade_firmware', 'interface': 'deploy'},
                       {'step': 'upgrade_bmc', 'interface': 'management'}]
        self._test_rpcapi('do_node_clean',
                          'call',
                          version='1.32',
                          node_id=self.fake_node['uuid'],
                          clean_steps=clean_steps)

    def test_object_action(self):
        self._test_rpcapi('object_action',
                          'call',
                          version='1.31',
                          objinst='fake-object',
                          objmethod='foo',
                          args=tuple(),
                          kwargs=dict())

    def test_object_class_action_versions(self):
        self._test_rpcapi('object_class_action_versions',
                          'call',
                          version='1.31',
                          objname='fake-object',
                          objmethod='foo',
                          object_versions={'fake-object': '1.0'},
                          args=tuple(),
                          kwargs=dict())

    def test_object_backport_versions(self):
        self._test_rpcapi('object_backport_versions',
                          'call',
                          version='1.31',
                          objinst='fake-object',
                          object_versions={'fake-object': '1.0'})

    @mock.patch.object(messaging.RPCClient, 'can_send_version', autospec=True)
    def test_object_action_invalid_version(self, mock_send):
        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        mock_send.return_value = False
        self.assertRaises(NotImplementedError,
                          rpcapi.object_action, self.context,
                          objinst='fake-object', objmethod='foo',
                          args=tuple(), kwargs=dict())

    @mock.patch.object(messaging.RPCClient, 'can_send_version', autospec=True)
    def test_object_class_action_versions_invalid_version(self, mock_send):
        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        mock_send.return_value = False
        self.assertRaises(NotImplementedError,
                          rpcapi.object_class_action_versions, self.context,
                          objname='fake-object', objmethod='foo',
                          object_versions={'fake-object': '1.0'},
                          args=tuple(), kwargs=dict())

    @mock.patch.object(messaging.RPCClient, 'can_send_version', autospec=True)
    def test_object_backport_versions_invalid_version(self, mock_send):
        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        mock_send.return_value = False
        self.assertRaises(NotImplementedError,
                          rpcapi.object_backport_versions, self.context,
                          objinst='fake-object',
                          object_versions={'fake-object': '1.0'})

    def test_update_portgroup(self):
        self._test_rpcapi('update_portgroup',
                          'call',
                          version='1.33',
                          portgroup_obj=self.fake_portgroup)

    def test_destroy_portgroup(self):
        self._test_rpcapi('destroy_portgroup',
                          'call',
                          version='1.33',
                          portgroup=self.fake_portgroup)

    def test_heartbeat(self):
        self._test_rpcapi('heartbeat',
                          'call',
                          node_id='fake-node',
                          callback_url='http://ramdisk.url:port',
                          agent_version=None,
                          version='1.51')

    def test_heartbeat_agent_token(self):
        self._test_rpcapi('heartbeat',
                          'call',
                          node_id='fake-node',
                          callback_url='http://ramdisk.url:port',
                          agent_version=None,
                          agent_token='xyz1',
                          version='1.51')

    def test_destroy_volume_connector(self):
        fake_volume_connector = db_utils.get_test_volume_connector()
        self._test_rpcapi('destroy_volume_connector',
                          'call',
                          version='1.35',
                          connector=fake_volume_connector)

    def test_update_volume_connector(self):
        fake_volume_connector = db_utils.get_test_volume_connector()
        self._test_rpcapi('update_volume_connector',
                          'call',
                          version='1.35',
                          connector=fake_volume_connector)

    def test_create_node(self):
        self._test_rpcapi('create_node',
                          'call',
                          version='1.36',
                          node_obj=self.fake_node)

    def test_destroy_volume_target(self):
        fake_volume_target = db_utils.get_test_volume_target()
        self._test_rpcapi('destroy_volume_target',
                          'call',
                          version='1.37',
                          target=fake_volume_target)

    def test_update_volume_target(self):
        fake_volume_target = db_utils.get_test_volume_target()
        self._test_rpcapi('update_volume_target',
                          'call',
                          version='1.37',
                          target=fake_volume_target)

    def test_vif_attach(self):
        self._test_rpcapi('vif_attach',
                          'call',
                          node_id='fake-node',
                          vif_info={"id": "vif"},
                          version='1.38')

    def test_vif_detach(self):
        self._test_rpcapi('vif_detach',
                          'call',
                          node_id='fake-node',
                          vif_id="vif",
                          version='1.38')

    def test_vif_list(self):
        self._test_rpcapi('vif_list',
                          'call',
                          node_id='fake-node',
                          version='1.38')

    def test_do_node_rescue(self):
        self._test_rpcapi('do_node_rescue',
                          'call',
                          version='1.43',
                          node_id=self.fake_node['uuid'],
                          rescue_password="password")

    def test_do_node_unrescue(self):
        self._test_rpcapi('do_node_unrescue',
                          'call',
                          version='1.43',
                          node_id=self.fake_node['uuid'])

    def test_get_node_with_token(self):
        self._test_rpcapi('get_node_with_token',
                          'call',
                          version='1.49',
                          node_id=self.fake_node['uuid'])

    def _test_can_send_rescue(self, can_send):
        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        with mock.patch.object(rpcapi.client,
                               "can_send_version",
                               autospec=True) as mock_can_send_version:
            mock_can_send_version.return_value = can_send
            result = rpcapi.can_send_rescue()
            self.assertEqual(can_send, result)
            mock_can_send_version.assert_called_once_with("1.43")

    def test_can_send_rescue_true(self):
        self._test_can_send_rescue(True)

    def test_can_send_rescue_false(self):
        self._test_can_send_rescue(False)

    def test_add_node_traits(self):
        self._test_rpcapi('add_node_traits',
                          'call',
                          node_id='fake-node',
                          traits=['trait1'],
                          version='1.44')

    def test_add_node_traits_replace(self):
        self._test_rpcapi('add_node_traits',
                          'call',
                          node_id='fake-node',
                          traits=['trait1'],
                          replace=True,
                          version='1.44')

    def test_remove_node_traits(self):
        self._test_rpcapi('remove_node_traits',
                          'call',
                          node_id='fake-node',
                          traits=['trait1'],
                          version='1.44')

    def test_remove_node_traits_all(self):
        self._test_rpcapi('remove_node_traits',
                          'call',
                          node_id='fake-node',
                          traits=None,
                          version='1.44')

    def test_create_allocation(self):
        self._test_rpcapi('create_allocation',
                          'call',
                          allocation='fake-allocation',
                          version='1.48')

    def test_destroy_allocation(self):
        self._test_rpcapi('destroy_allocation',
                          'call',
                          allocation='fake-allocation',
                          version='1.48')
