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

import copy
from unittest import mock

from neutronclient.common import exceptions as neutron_exceptions
from oslo_config import cfg
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import neutron as neutron_common
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers import base as drivers_base
from ironic.drivers.modules.network import neutron
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils

CONF = cfg.CONF
CLIENT_ID1 = '20:00:55:04:01:fe:80:00:00:00:00:00:00:00:02:c9:02:00:23:13:92'
CLIENT_ID2 = '20:00:55:04:01:fe:80:00:00:00:00:00:00:00:02:c9:02:00:23:13:93'
VIFMIXINPATH = 'ironic.drivers.modules.network.common.NeutronVIFPortIDMixin'


class NeutronInterfaceTestCase(db_base.DbTestCase):

    def setUp(self):
        super(NeutronInterfaceTestCase, self).setUp()
        self.config(enabled_hardware_types=['fake-hardware'])
        for iface in drivers_base.ALL_INTERFACES:
            name = 'fake'
            if iface == 'network':
                name = 'neutron'
            config_kwarg = {'enabled_%s_interfaces' % iface: [name],
                            'default_%s_interface' % iface: name}
            self.config(**config_kwarg)

        self.interface = neutron.NeutronNetwork()
        self.node = utils.create_test_node(self.context,
                                           driver='fake-hardware',
                                           network_interface='neutron')
        self.port = utils.create_test_port(
            self.context, node_id=self.node.id,
            address='52:54:00:cf:2d:32',
            extra={'vif_port_id': uuidutils.generate_uuid()})
        self.neutron_port = {'id': '132f871f-eaec-4fed-9475-0d54465e0f00',
                             'mac_address': '52:54:00:cf:2d:32'}

    @mock.patch('%s.vif_list' % VIFMIXINPATH, autospec=True)
    def test_vif_list(self, mock_vif_list):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_list(task)
            mock_vif_list.assert_called_once_with(self.interface, task)

    @mock.patch('%s.vif_attach' % VIFMIXINPATH, autospec=True)
    def test_vif_attach(self, mock_vif_attach):
        vif = mock.MagicMock()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_attach(task, vif)
            mock_vif_attach.assert_called_once_with(self.interface, task, vif)

    @mock.patch('%s.vif_detach' % VIFMIXINPATH, autospec=True)
    def test_vif_detach(self, mock_vif_detach):
        vif_id = "vif"
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_detach(task, vif_id)
            mock_vif_detach.assert_called_once_with(
                self.interface, task, vif_id)

    @mock.patch('%s.port_changed' % VIFMIXINPATH, autospec=True)
    def test_vif_port_changed(self, mock_p_changed):
        port = mock.MagicMock()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.port_changed(task, port)
            mock_p_changed.assert_called_once_with(self.interface, task, port)

    def test_init_incorrect_provisioning_net(self):
        self.config(provisioning_network=None, group='neutron')
        self.assertRaises(exception.DriverLoadError, neutron.NeutronNetwork)
        self.config(provisioning_network=uuidutils.generate_uuid(),
                    group='neutron')
        self.config(cleaning_network=None, group='neutron')
        self.assertRaises(exception.DriverLoadError, neutron.NeutronNetwork)

    @mock.patch.object(neutron_common, 'validate_network', autospec=True)
    def test_validate(self, validate_mock):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.validate(task)
            self.assertEqual([mock.call(CONF.neutron.cleaning_network,
                                        'cleaning network',
                                        context=task.context),
                              mock.call(CONF.neutron.provisioning_network,
                                        'provisioning network',
                                        context=task.context)],
                             validate_mock.call_args_list)

    @mock.patch.object(neutron_common, 'validate_network', autospec=True)
    def test_validate_boot_option_netboot(self, validate_mock):
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = True
        self.node.driver_internal_info = driver_internal_info
        boot_option = {'capabilities': '{"boot_option": "netboot"}'}
        self.node.instance_info = boot_option
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegex(
                exception.InvalidParameterValue,
                'cannot perform "local" boot for whole disk image',
                self.interface.validate, task)
            self.assertEqual([mock.call(CONF.neutron.cleaning_network,
                                        'cleaning network',
                                        context=task.context),
                              mock.call(CONF.neutron.provisioning_network,
                                        'provisioning network',
                                        context=task.context)],
                             validate_mock.call_args_list)

    @mock.patch.object(neutron_common, 'validate_network', autospec=True)
    def test_validate_boot_option_netboot_no_exc(self, validate_mock):
        CONF.set_override('default_boot_option', 'netboot', 'deploy')
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = True
        self.node.driver_internal_info = driver_internal_info
        self.node.provision_state = states.AVAILABLE
        self.node.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.validate(task)
            self.assertEqual([mock.call(CONF.neutron.cleaning_network,
                                        'cleaning network',
                                        context=task.context),
                              mock.call(CONF.neutron.provisioning_network,
                                        'provisioning network',
                                        context=task.context)],
                             validate_mock.call_args_list)

    @mock.patch.object(neutron_common, 'validate_network', autospec=True)
    def test_validate_boot_option_local(self, validate_mock):
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = True
        self.node.driver_internal_info = driver_internal_info
        boot_option = {'capabilities': '{"boot_option": "local"}'}
        self.node.instance_info = boot_option
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.validate(task)
            self.assertEqual([mock.call(CONF.neutron.cleaning_network,
                                        'cleaning network',
                                        context=task.context),
                              mock.call(CONF.neutron.provisioning_network,
                                        'provisioning network',
                                        context=task.context)],
                             validate_mock.call_args_list)

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    @mock.patch.object(neutron_common, 'rollback_ports', autospec=True)
    @mock.patch.object(neutron_common, 'add_ports_to_network', autospec=True)
    def test_add_provisioning_network(self, add_ports_mock, rollback_mock,
                                      validate_mock):
        self.port.internal_info = {'provisioning_vif_port_id': 'vif-port-id'}
        self.port.save()
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_provisioning_network(task)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.provisioning_network)
            add_ports_mock.assert_called_once_with(
                task, CONF.neutron.provisioning_network,
                security_groups=[])
            validate_mock.assert_called_once_with(
                CONF.neutron.provisioning_network,
                'provisioning network', context=task.context)
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['provisioning_vif_port_id'])

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    @mock.patch.object(neutron_common, 'rollback_ports', autospec=True)
    @mock.patch.object(neutron_common, 'add_ports_to_network', autospec=True)
    def test_add_provisioning_network_from_node(self, add_ports_mock,
                                                rollback_mock, validate_mock):
        self.port.internal_info = {'provisioning_vif_port_id': 'vif-port-id'}
        self.port.save()
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        # Make sure that changing the network UUID works
        for provisioning_network_uuid in [
                '3aea0de6-4b92-44da-9aa0-52d134c83fdf',
                '438be438-6aae-4fb1-bbcb-613ad7a38286']:
            validate_mock.reset_mock()
            driver_info = self.node.driver_info
            driver_info['provisioning_network'] = provisioning_network_uuid
            self.node.driver_info = driver_info
            self.node.save()
            with task_manager.acquire(self.context, self.node.id) as task:
                self.interface.add_provisioning_network(task)
                rollback_mock.assert_called_with(
                    task, provisioning_network_uuid)
                add_ports_mock.assert_called_with(
                    task, provisioning_network_uuid,
                    security_groups=[])
                validate_mock.assert_called_once_with(
                    provisioning_network_uuid,
                    'provisioning network', context=task.context)
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['provisioning_vif_port_id'])

    @mock.patch.object(neutron_common, 'validate_network',
                       lambda n, t, context=None: n)
    @mock.patch.object(neutron_common, 'rollback_ports', autospec=True)
    @mock.patch.object(neutron_common, 'add_ports_to_network', autospec=True)
    def test_add_provisioning_network_with_sg(self, add_ports_mock,
                                              rollback_mock):
        sg_ids = []
        for i in range(2):
            sg_ids.append(uuidutils.generate_uuid())

        self.config(provisioning_network_security_groups=sg_ids,
                    group='neutron')
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_provisioning_network(task)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.provisioning_network)
            add_ports_mock.assert_called_once_with(
                task, CONF.neutron.provisioning_network,
                security_groups=(
                    CONF.neutron.provisioning_network_security_groups))
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['provisioning_vif_port_id'])

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    @mock.patch.object(neutron_common, 'remove_ports_from_network',
                       autospec=True)
    def test_remove_provisioning_network(self, remove_ports_mock,
                                         validate_mock):
        self.port.internal_info = {'provisioning_vif_port_id': 'vif-port-id'}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_provisioning_network(task)
            remove_ports_mock.assert_called_once_with(
                task, CONF.neutron.provisioning_network)
            validate_mock.assert_called_once_with(
                CONF.neutron.provisioning_network,
                'provisioning network', context=task.context)
        self.port.refresh()
        self.assertNotIn('provisioning_vif_port_id', self.port.internal_info)

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    @mock.patch.object(neutron_common, 'remove_ports_from_network',
                       autospec=True)
    def test_remove_provisioning_network_from_node(self, remove_ports_mock,
                                                   validate_mock):
        self.port.internal_info = {'provisioning_vif_port_id': 'vif-port-id'}
        self.port.save()
        provisioning_network_uuid = '3aea0de6-4b92-44da-9aa0-52d134c83f9c'
        driver_info = self.node.driver_info
        driver_info['provisioning_network'] = provisioning_network_uuid
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_provisioning_network(task)
            remove_ports_mock.assert_called_once_with(
                task, provisioning_network_uuid)
            validate_mock.assert_called_once_with(
                provisioning_network_uuid,
                'provisioning network', context=task.context)
        self.port.refresh()
        self.assertNotIn('provisioning_vif_port_id', self.port.internal_info)

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    @mock.patch.object(neutron_common, 'rollback_ports', autospec=True)
    @mock.patch.object(neutron_common, 'add_ports_to_network', autospec=True)
    def test_add_cleaning_network(self, add_ports_mock, rollback_mock,
                                  validate_mock):
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.id) as task:
            res = self.interface.add_cleaning_network(task)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network)
            self.assertEqual(res, add_ports_mock.return_value)
            validate_mock.assert_called_once_with(
                CONF.neutron.cleaning_network,
                'cleaning network', context=task.context)
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['cleaning_vif_port_id'])

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    @mock.patch.object(neutron_common, 'rollback_ports', autospec=True)
    @mock.patch.object(neutron_common, 'add_ports_to_network', autospec=True)
    def test_add_cleaning_network_from_node(self, add_ports_mock,
                                            rollback_mock, validate_mock):
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        # Make sure that changing the network UUID works
        for cleaning_network_uuid in ['3aea0de6-4b92-44da-9aa0-52d134c83fdf',
                                      '438be438-6aae-4fb1-bbcb-613ad7a38286']:
            validate_mock.reset_mock()
            driver_info = self.node.driver_info
            driver_info['cleaning_network'] = cleaning_network_uuid
            self.node.driver_info = driver_info
            self.node.save()
            with task_manager.acquire(self.context, self.node.id) as task:
                res = self.interface.add_cleaning_network(task)
                rollback_mock.assert_called_with(task, cleaning_network_uuid)
                self.assertEqual(res, add_ports_mock.return_value)
                validate_mock.assert_called_once_with(
                    cleaning_network_uuid,
                    'cleaning network', context=task.context)
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['cleaning_vif_port_id'])

    @mock.patch.object(neutron_common, 'validate_network',
                       lambda n, t, context=None: n)
    @mock.patch.object(neutron_common, 'rollback_ports', autospec=True)
    @mock.patch.object(neutron_common, 'add_ports_to_network', autospec=True)
    def test_add_cleaning_network_with_sg(self, add_ports_mock, rollback_mock):
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        sg_ids = []
        for i in range(2):
            sg_ids.append(uuidutils.generate_uuid())
        self.config(cleaning_network_security_groups=sg_ids, group='neutron')
        with task_manager.acquire(self.context, self.node.id) as task:
            res = self.interface.add_cleaning_network(task)
            add_ports_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network,
                security_groups=CONF.neutron.cleaning_network_security_groups)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network)
            self.assertEqual(res, add_ports_mock.return_value)
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['cleaning_vif_port_id'])

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    @mock.patch.object(neutron_common, 'remove_ports_from_network',
                       autospec=True)
    def test_remove_cleaning_network(self, remove_ports_mock,
                                     validate_mock):
        self.port.internal_info = {'cleaning_vif_port_id': 'vif-port-id'}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_cleaning_network(task)
            remove_ports_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network)
            validate_mock.assert_called_once_with(
                CONF.neutron.cleaning_network,
                'cleaning network', context=task.context)
        self.port.refresh()
        self.assertNotIn('cleaning_vif_port_id', self.port.internal_info)

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    @mock.patch.object(neutron_common, 'remove_ports_from_network',
                       autospec=True)
    def test_remove_cleaning_network_from_node(self, remove_ports_mock,
                                               validate_mock):
        self.port.internal_info = {'cleaning_vif_port_id': 'vif-port-id'}
        self.port.save()
        cleaning_network_uuid = '3aea0de6-4b92-44da-9aa0-52d134c83fdf'
        driver_info = self.node.driver_info
        driver_info['cleaning_network'] = cleaning_network_uuid
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_cleaning_network(task)
            remove_ports_mock.assert_called_once_with(
                task, cleaning_network_uuid)
            validate_mock.assert_called_once_with(
                cleaning_network_uuid,
                'cleaning network', context=task.context)
        self.port.refresh()
        self.assertNotIn('cleaning_vif_port_id', self.port.internal_info)

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    def test_validate_rescue(self, validate_mock):
        rescuing_network_uuid = '3aea0de6-4b92-44da-9aa0-52d134c83fdf'
        driver_info = self.node.driver_info
        driver_info['rescuing_network'] = rescuing_network_uuid
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.validate_rescue(task)
            validate_mock.assert_called_once_with(
                rescuing_network_uuid, 'rescuing network',
                context=task.context),

    def test_validate_rescue_exc(self):
        self.config(rescuing_network="", group='neutron')
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegex(exception.MissingParameterValue,
                                   'rescuing network is not set',
                                   self.interface.validate_rescue, task)

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    @mock.patch.object(neutron_common, 'rollback_ports', autospec=True)
    @mock.patch.object(neutron_common, 'add_ports_to_network', autospec=True)
    def test_add_rescuing_network(self, add_ports_mock, rollback_mock,
                                  validate_mock):
        other_port = utils.create_test_port(
            self.context, node_id=self.node.id,
            address='52:54:00:cf:2d:33',
            uuid=uuidutils.generate_uuid(),
            extra={'vif_port_id': uuidutils.generate_uuid()})
        neutron_other_port = {'id': uuidutils.generate_uuid(),
                              'mac_address': '52:54:00:cf:2d:33'}
        add_ports_mock.return_value = {
            other_port.uuid: neutron_other_port['id']}
        with task_manager.acquire(self.context, self.node.id) as task:
            res = self.interface.add_rescuing_network(task)
            add_ports_mock.assert_called_once_with(
                task, CONF.neutron.rescuing_network,
                security_groups=[])
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.rescuing_network)
            self.assertEqual(add_ports_mock.return_value, res)
            validate_mock.assert_called_once_with(
                CONF.neutron.rescuing_network,
                'rescuing network', context=task.context)
        other_port.refresh()
        self.assertEqual(neutron_other_port['id'],
                         other_port.internal_info['rescuing_vif_port_id'])
        self.assertNotIn('rescuing_vif_port_id', self.port.internal_info)

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    @mock.patch.object(neutron_common, 'rollback_ports', autospec=True)
    @mock.patch.object(neutron_common, 'add_ports_to_network', autospec=True)
    def test_add_rescuing_network_from_node(self, add_ports_mock,
                                            rollback_mock, validate_mock):
        other_port = utils.create_test_port(
            self.context, node_id=self.node.id,
            address='52:54:00:cf:2d:33',
            uuid=uuidutils.generate_uuid(),
            extra={'vif_port_id': uuidutils.generate_uuid()})
        neutron_other_port = {'id': uuidutils.generate_uuid(),
                              'mac_address': '52:54:00:cf:2d:33'}
        add_ports_mock.return_value = {
            other_port.uuid: neutron_other_port['id']}
        rescuing_network_uuid = '3aea0de6-4b92-44da-9aa0-52d134c83fdf'
        driver_info = self.node.driver_info
        driver_info['rescuing_network'] = rescuing_network_uuid
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            res = self.interface.add_rescuing_network(task)
            add_ports_mock.assert_called_once_with(
                task, rescuing_network_uuid,
                security_groups=[])
            rollback_mock.assert_called_once_with(
                task, rescuing_network_uuid)
            self.assertEqual(add_ports_mock.return_value, res)
            validate_mock.assert_called_once_with(
                rescuing_network_uuid,
                'rescuing network', context=task.context)
        other_port.refresh()
        self.assertEqual(neutron_other_port['id'],
                         other_port.internal_info['rescuing_vif_port_id'])
        self.assertNotIn('rescuing_vif_port_id', self.port.internal_info)

    @mock.patch.object(neutron_common, 'validate_network',
                       lambda n, t, context=None: n)
    @mock.patch.object(neutron_common, 'rollback_ports', autospec=True)
    @mock.patch.object(neutron_common, 'add_ports_to_network', autospec=True)
    def test_add_rescuing_network_with_sg(self, add_ports_mock, rollback_mock):
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        sg_ids = []
        for i in range(2):
            sg_ids.append(uuidutils.generate_uuid())
        self.config(rescuing_network_security_groups=sg_ids, group='neutron')
        with task_manager.acquire(self.context, self.node.id) as task:
            res = self.interface.add_rescuing_network(task)
            add_ports_mock.assert_called_once_with(
                task, CONF.neutron.rescuing_network,
                security_groups=CONF.neutron.rescuing_network_security_groups)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.rescuing_network)
            self.assertEqual(add_ports_mock.return_value, res)
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['rescuing_vif_port_id'])

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    @mock.patch.object(neutron_common, 'remove_ports_from_network',
                       autospec=True)
    def test_remove_rescuing_network(self, remove_ports_mock,
                                     validate_mock):
        other_port = utils.create_test_port(
            self.context, node_id=self.node.id,
            address='52:54:00:cf:2d:33',
            uuid=uuidutils.generate_uuid(),
            extra={'vif_port_id': uuidutils.generate_uuid()})
        other_port.internal_info = {'rescuing_vif_port_id': 'vif-port-id'}
        other_port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_rescuing_network(task)
            remove_ports_mock.assert_called_once_with(
                task, CONF.neutron.rescuing_network)
            validate_mock.assert_called_once_with(
                CONF.neutron.rescuing_network,
                'rescuing network', context=task.context)
        other_port.refresh()
        self.assertNotIn('rescuing_vif_port_id', self.port.internal_info)
        self.assertNotIn('rescuing_vif_port_id', other_port.internal_info)

    @mock.patch.object(neutron_common, 'unbind_neutron_port', autospec=True)
    def test_unconfigure_tenant_networks(self, mock_unbind_port):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.unconfigure_tenant_networks(task)
            mock_unbind_port.assert_called_once_with(
                self.port.extra['vif_port_id'], context=task.context)

    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    @mock.patch.object(neutron_common, 'wait_for_host_agent', autospec=True)
    @mock.patch.object(neutron_common, 'unbind_neutron_port', autospec=True)
    def test_unconfigure_tenant_networks_smartnic(
            self, mock_unbind_port, wait_agent_mock, client_mock):
        nclient = mock.MagicMock()
        client_mock.return_value = nclient
        local_link_connection = self.port.local_link_connection
        local_link_connection['hostname'] = 'hostname'
        self.port.local_link_connection = local_link_connection
        self.port.is_smartnic = True
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.unconfigure_tenant_networks(task)
            mock_unbind_port.assert_called_once_with(
                self.port.extra['vif_port_id'], context=task.context)
            wait_agent_mock.assert_called_once_with(nclient, 'hostname')

    def test_configure_tenant_networks_no_ports_for_node(self):
        n = utils.create_test_node(self.context, network_interface='neutron',
                                   uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, n.id) as task:
            self.assertRaisesRegex(
                exception.NetworkError, 'No ports are associated',
                self.interface.configure_tenant_networks, task)

    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_configure_tenant_networks_no_vif_id(self, log_mock, client_mock):
        self.port.extra = {}
        self.port.save()
        upd_mock = mock.Mock()
        client_mock.return_value.update_port = upd_mock
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegex(exception.NetworkError,
                                   'No neutron ports or portgroups are '
                                   'associated with node',
                                   self.interface.configure_tenant_networks,
                                   task)
            client_mock.assert_called_once_with(context=task.context)
        upd_mock.assert_not_called()
        self.assertIn('No neutron ports or portgroups are associated with',
                      log_mock.error.call_args[0][0])

    @mock.patch.object(neutron_common, 'wait_for_host_agent', autospec=True)
    @mock.patch.object(neutron_common, 'update_neutron_port', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_configure_tenant_networks_multiple_ports_one_vif_id(
            self, log_mock, client_mock, update_mock, wait_agent_mock):
        expected_body = {
            'port': {
                'binding:vnic_type': 'baremetal',
                'binding:host_id': self.node.uuid,
                'binding:profile': {'local_link_information':
                                    [self.port.local_link_connection]},
                'mac_address': '52:54:00:cf:2d:32'
            }
        }
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.configure_tenant_networks(task)
            client_mock.assert_called_once_with(context=task.context)
        update_mock.assert_called_once_with(self.context,
                                            self.port.extra['vif_port_id'],
                                            expected_body)

    @mock.patch.object(neutron_common, 'wait_for_host_agent', autospec=True)
    @mock.patch.object(neutron_common, 'update_neutron_port', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    def test_configure_tenant_networks_update_fail(self, client_mock,
                                                   update_mock,
                                                   wait_agent_mock):
        update_mock.side_effect = neutron_exceptions.ConnectionFailed(
            reason='meow')
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegex(
                exception.NetworkError, 'Could not add',
                self.interface.configure_tenant_networks, task)
            client_mock.assert_called_once_with(context=task.context)

    @mock.patch.object(neutron_common, 'wait_for_host_agent', autospec=True)
    @mock.patch.object(neutron_common, 'update_neutron_port', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    def _test_configure_tenant_networks(self, client_mock, update_mock,
                                        wait_agent_mock,
                                        is_client_id=False,
                                        vif_int_info=False):
        if vif_int_info:
            kwargs = {'internal_info': {
                'tenant_vif_port_id': uuidutils.generate_uuid()}}
            self.port.internal_info = {
                'tenant_vif_port_id': self.port.extra['vif_port_id']}
            self.port.extra = {}
        else:
            kwargs = {'extra': {'vif_port_id': uuidutils.generate_uuid()}}
        second_port = utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:33',
            uuid=uuidutils.generate_uuid(),
            local_link_connection={'switch_id': '0a:1b:2c:3d:4e:ff',
                                   'port_id': 'Ethernet1/1',
                                   'switch_info': 'switch2'},
            **kwargs
        )
        if is_client_id:
            client_ids = (CLIENT_ID1, CLIENT_ID2)
            ports = (self.port, second_port)
            for port, client_id in zip(ports, client_ids):
                extra = port.extra
                extra['client-id'] = client_id
                port.extra = extra
                port.save()

        expected_body = {
            'port': {
                'binding:vnic_type': 'baremetal',
                'binding:host_id': self.node.uuid,
            }
        }
        port1_body = copy.deepcopy(expected_body)
        port1_body['port']['binding:profile'] = {
            'local_link_information': [self.port.local_link_connection]
        }
        port1_body['port']['mac_address'] = '52:54:00:cf:2d:32'
        port2_body = copy.deepcopy(expected_body)
        port2_body['port']['binding:profile'] = {
            'local_link_information': [second_port.local_link_connection]
        }
        port2_body['port']['mac_address'] = '52:54:00:cf:2d:33'
        if is_client_id:
            port1_body['port']['extra_dhcp_opts'] = (
                [{'opt_name': '61', 'opt_value': client_ids[0]}])
            port2_body['port']['extra_dhcp_opts'] = (
                [{'opt_name': '61', 'opt_value': client_ids[1]}])
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.configure_tenant_networks(task)
            client_mock.assert_called_once_with(context=task.context)
        if vif_int_info:
            portid1 = self.port.internal_info['tenant_vif_port_id']
            portid2 = second_port.internal_info['tenant_vif_port_id']
        else:
            portid1 = self.port.extra['vif_port_id']
            portid2 = second_port.extra['vif_port_id']
        update_mock.assert_has_calls(
            [mock.call(self.context, portid1, port1_body),
             mock.call(self.context, portid2, port2_body)],
            any_order=True
        )

    def test_configure_tenant_networks_vif_extra(self):
        self.node.instance_uuid = uuidutils.generate_uuid()
        self.node.save()
        self._test_configure_tenant_networks()

    def test_configure_tenant_networks_vif_int_info(self):
        self.node.instance_uuid = uuidutils.generate_uuid()
        self.node.save()
        self._test_configure_tenant_networks(vif_int_info=True)

    def test_configure_tenant_networks_no_instance_uuid(self):
        self._test_configure_tenant_networks()

    def test_configure_tenant_networks_with_client_id(self):
        self.node.instance_uuid = uuidutils.generate_uuid()
        self.node.save()
        self._test_configure_tenant_networks(is_client_id=True)

    @mock.patch.object(neutron_common, 'wait_for_host_agent', autospec=True)
    @mock.patch.object(neutron_common, 'update_neutron_port', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    @mock.patch.object(neutron_common, 'get_local_group_information',
                       autospec=True)
    def test_configure_tenant_networks_with_portgroups(
            self, glgi_mock, client_mock, update_mock, wait_agent_mock):
        pg = utils.create_test_portgroup(
            self.context, node_id=self.node.id, address='ff:54:00:cf:2d:32',
            extra={'vif_port_id': uuidutils.generate_uuid()})
        port1 = utils.create_test_port(
            self.context, node_id=self.node.id, address='ff:54:00:cf:2d:33',
            uuid=uuidutils.generate_uuid(),
            portgroup_id=pg.id,
            local_link_connection={'switch_id': '0a:1b:2c:3d:4e:ff',
                                   'port_id': 'Ethernet1/1',
                                   'switch_info': 'switch2'}
        )
        port2 = utils.create_test_port(
            self.context, node_id=self.node.id, address='ff:54:00:cf:2d:34',
            uuid=uuidutils.generate_uuid(),
            portgroup_id=pg.id,
            local_link_connection={'switch_id': '0a:1b:2c:3d:4e:ff',
                                   'port_id': 'Ethernet1/2',
                                   'switch_info': 'switch2'}
        )
        local_group_info = {'a': 'b'}
        glgi_mock.return_value = local_group_info
        expected_body = {
            'port': {
                'binding:vnic_type': 'baremetal',
                'binding:host_id': self.node.uuid,
            }
        }
        call1_body = copy.deepcopy(expected_body)
        call1_body['port']['binding:profile'] = {
            'local_link_information': [self.port.local_link_connection],
        }
        call1_body['port']['mac_address'] = '52:54:00:cf:2d:32'
        call2_body = copy.deepcopy(expected_body)
        call2_body['port']['binding:profile'] = {
            'local_link_information': [port1.local_link_connection,
                                       port2.local_link_connection],
            'local_group_information': local_group_info
        }
        call2_body['port']['mac_address'] = 'ff:54:00:cf:2d:32'
        with task_manager.acquire(self.context, self.node.id) as task:
            # Override task.portgroups here, to have ability to check
            # that mocked get_local_group_information was called with
            # this portgroup object.
            task.portgroups = [pg]
            self.interface.configure_tenant_networks(task)
            client_mock.assert_called_once_with(context=task.context)
            glgi_mock.assert_called_once_with(task, pg)
        update_mock.assert_has_calls(
            [mock.call(self.context, self.port.extra['vif_port_id'],
                       call1_body),
             mock.call(self.context, pg.extra['vif_port_id'],
                       call2_body)]
        )

    def test_need_power_on_true(self):
        self.port.is_smartnic = True
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertTrue(self.interface.need_power_on(task))

    def test_need_power_on_false(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertFalse(self.interface.need_power_on(task))

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    @mock.patch.object(neutron_common, 'rollback_ports', autospec=True)
    @mock.patch.object(neutron_common, 'add_ports_to_network', autospec=True)
    def test_add_inspection_network(self, add_ports_mock, rollback_mock,
                                    validate_mock):
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.id) as task:
            res = self.interface.add_inspection_network(task)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.inspection_network)
            self.assertEqual(res, add_ports_mock.return_value)
            validate_mock.assert_called_once_with(
                CONF.neutron.inspection_network,
                'inspection network', context=task.context)
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['inspection_vif_port_id'])

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    @mock.patch.object(neutron_common, 'rollback_ports', autospec=True)
    @mock.patch.object(neutron_common, 'add_ports_to_network', autospec=True)
    def test_add_inspection_network_from_node(self, add_ports_mock,
                                              rollback_mock, validate_mock):
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        # Make sure that changing the network UUID works
        for inspection_network_uuid in [
                '3aea0de6-4b92-44da-9aa0-52d134c83fdf',
                '438be438-6aae-4fb1-bbcb-613ad7a38286']:
            validate_mock.reset_mock()
            driver_info = self.node.driver_info
            driver_info['inspection_network'] = inspection_network_uuid
            self.node.driver_info = driver_info
            self.node.save()
            with task_manager.acquire(self.context, self.node.id) as task:
                res = self.interface.add_inspection_network(task)
                rollback_mock.assert_called_with(task, inspection_network_uuid)
                self.assertEqual(res, add_ports_mock.return_value)
                validate_mock.assert_called_once_with(
                    inspection_network_uuid,
                    'inspection network', context=task.context)
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['inspection_vif_port_id'])

    @mock.patch.object(neutron_common, 'validate_network',
                       lambda n, t, context=None: n)
    @mock.patch.object(neutron_common, 'rollback_ports', autospec=True)
    @mock.patch.object(neutron_common, 'add_ports_to_network', autospec=True)
    def test_add_inspection_network_with_sg(self, add_ports_mock,
                                            rollback_mock):
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        sg_ids = []
        for i in range(2):
            sg_ids.append(uuidutils.generate_uuid())
        self.config(inspection_network_security_groups=sg_ids, group='neutron')
        sg = CONF.neutron.inspection_network_security_groups
        with task_manager.acquire(self.context, self.node.id) as task:
            res = self.interface.add_inspection_network(task)
            add_ports_mock.assert_called_once_with(
                task, CONF.neutron.inspection_network,
                security_groups=sg)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.inspection_network)
            self.assertEqual(res, add_ports_mock.return_value)
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['inspection_vif_port_id'])

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t, context=None: n, autospec=True)
    def test_validate_inspection(self, validate_mock):
        inspection_network_uuid = '3aea0de6-4b92-44da-9aa0-52d134c83fdf'
        driver_info = self.node.driver_info
        driver_info['inspection_network'] = inspection_network_uuid
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.validate_inspection(task)
            validate_mock.assert_called_once_with(
                inspection_network_uuid, 'inspection network',
                context=task.context),

    def test_validate_inspection_exc(self):
        self.config(inspection_network="", group='neutron')
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.UnsupportedDriverExtension,
                              self.interface.validate_inspection, task)

    def test_get_node_network_data(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            network_data = self.interface.get_node_network_data(task)

        self.assertEqual({}, network_data)
