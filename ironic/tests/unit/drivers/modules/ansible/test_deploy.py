# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
from unittest import mock

from ironic_lib import utils as irlib_utils
from oslo_concurrency import processutils

from ironic.common import exception
from ironic.common import states
from ironic.common import utils as com_utils
from ironic.conductor import steps
from ironic.conductor import task_manager
from ironic.conductor import utils
from ironic.drivers.modules.ansible import deploy as ansible_deploy
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import fake
from ironic.drivers.modules.network import flat as flat_network
from ironic.drivers.modules import pxe
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as object_utils

INSTANCE_INFO = {
    'image_source': 'fake-image',
    'image_url': 'http://image',
    'image_checksum': 'checksum',
    'image_disk_format': 'qcow2',
    'root_mb': 5120,
    'swap_mb': 0,
    'ephemeral_mb': 0
}

DRIVER_INFO = {
    'deploy_kernel': 'glance://deploy_kernel_uuid',
    'deploy_ramdisk': 'glance://deploy_ramdisk_uuid',
    'ansible_username': 'test',
    'ansible_key_file': '/path/key',
    'ipmi_address': '127.0.0.1',
}
DRIVER_INTERNAL_INFO = {
    'is_whole_disk_image': True,
    'clean_steps': []
}


class AnsibleDeployTestCaseBase(db_base.DbTestCase):

    def setUp(self):
        super(AnsibleDeployTestCaseBase, self).setUp()

        self.config(enabled_hardware_types=['manual-management'],
                    enabled_deploy_interfaces=['ansible'],
                    enabled_power_interfaces=['fake'],
                    enabled_management_interfaces=['fake'])
        node = {
            'driver': 'manual-management',
            'instance_info': INSTANCE_INFO,
            'driver_info': DRIVER_INFO,
            'driver_internal_info': DRIVER_INTERNAL_INFO,
        }
        self.node = object_utils.create_test_node(self.context, **node)


class TestAnsibleMethods(AnsibleDeployTestCaseBase):

    def test__parse_ansible_driver_info(self):
        self.node.driver_info['ansible_deploy_playbook'] = 'spam.yaml'
        playbook, user, key = ansible_deploy._parse_ansible_driver_info(
            self.node, 'deploy')
        self.assertEqual('spam.yaml', playbook)
        self.assertEqual('test', user)
        self.assertEqual('/path/key', key)

    def test__parse_ansible_driver_info_defaults(self):
        self.node.driver_info.pop('ansible_username')
        self.node.driver_info.pop('ansible_key_file')
        self.config(group='ansible',
                    default_username='spam',
                    default_key_file='/ham/eggs',
                    default_deploy_playbook='parrot.yaml')
        playbook, user, key = ansible_deploy._parse_ansible_driver_info(
            self.node, 'deploy')
        # testing absolute path to the playbook
        self.assertEqual('parrot.yaml', playbook)
        self.assertEqual('spam', user)
        self.assertEqual('/ham/eggs', key)

    def test__parse_ansible_driver_info_no_playbook(self):
        self.assertRaises(exception.IronicException,
                          ansible_deploy._parse_ansible_driver_info,
                          self.node, 'test')

    def test__get_node_ip(self):
        di_info = self.node.driver_internal_info
        di_info['agent_url'] = 'http://1.2.3.4:5678'
        self.node.driver_internal_info = di_info
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual('1.2.3.4',
                             ansible_deploy._get_node_ip(task))

    @mock.patch.object(com_utils, 'execute', return_value=('out', 'err'),
                       autospec=True)
    def test__run_playbook(self, execute_mock):
        self.config(group='ansible', playbooks_path='/path/to/playbooks')
        self.config(group='ansible', config_file_path='/path/to/config')
        self.config(group='ansible', verbosity=3)
        self.config(group='ansible', ansible_extra_args='--timeout=100')
        extra_vars = {'foo': 'bar'}

        ansible_deploy._run_playbook(self.node, 'deploy',
                                     extra_vars, '/path/to/key',
                                     tags=['spam'], notags=['ham'])

        execute_mock.assert_called_once_with(
            'env', 'ANSIBLE_CONFIG=/path/to/config',
            'ansible-playbook', '/path/to/playbooks/deploy', '-i',
            '/path/to/playbooks/inventory', '-e', '{"ironic": {"foo": "bar"}}',
            '--tags=spam', '--skip-tags=ham',
            '--private-key=/path/to/key', '-vvv', '--timeout=100')

    @mock.patch.object(com_utils, 'execute', return_value=('out', 'err'),
                       autospec=True)
    def test__run_playbook_default_verbosity_nodebug(self, execute_mock):
        self.config(group='ansible', playbooks_path='/path/to/playbooks')
        self.config(group='ansible', config_file_path='/path/to/config')
        self.config(debug=False)
        extra_vars = {'foo': 'bar'}

        ansible_deploy._run_playbook(self.node, 'deploy', extra_vars,
                                     '/path/to/key')

        execute_mock.assert_called_once_with(
            'env', 'ANSIBLE_CONFIG=/path/to/config',
            'ansible-playbook', '/path/to/playbooks/deploy', '-i',
            '/path/to/playbooks/inventory', '-e', '{"ironic": {"foo": "bar"}}',
            '--private-key=/path/to/key')

    @mock.patch.object(com_utils, 'execute', return_value=('out', 'err'),
                       autospec=True)
    def test__run_playbook_default_verbosity_debug(self, execute_mock):
        self.config(group='ansible', playbooks_path='/path/to/playbooks')
        self.config(group='ansible', config_file_path='/path/to/config')
        self.config(debug=True)
        extra_vars = {'foo': 'bar'}

        ansible_deploy._run_playbook(self.node, 'deploy', extra_vars,
                                     '/path/to/key')

        execute_mock.assert_called_once_with(
            'env', 'ANSIBLE_CONFIG=/path/to/config',
            'ansible-playbook', '/path/to/playbooks/deploy', '-i',
            '/path/to/playbooks/inventory', '-e', '{"ironic": {"foo": "bar"}}',
            '--private-key=/path/to/key', '-vvvv')

    @mock.patch.object(com_utils, 'execute', return_value=('out', 'err'),
                       autospec=True)
    def test__run_playbook_ansible_interpreter_python3(self, execute_mock):
        self.config(group='ansible', playbooks_path='/path/to/playbooks')
        self.config(group='ansible', config_file_path='/path/to/config')
        self.config(group='ansible', verbosity=3)
        self.config(group='ansible',
                    default_python_interpreter='/usr/bin/python3')
        self.config(group='ansible', ansible_extra_args='--timeout=100')
        extra_vars = {'foo': 'bar'}

        ansible_deploy._run_playbook(self.node, 'deploy',
                                     extra_vars, '/path/to/key',
                                     tags=['spam'], notags=['ham'])

        execute_mock.assert_called_once_with(
            'env', 'ANSIBLE_CONFIG=/path/to/config',
            'ansible-playbook', '/path/to/playbooks/deploy', '-i',
            '/path/to/playbooks/inventory', '-e',
            mock.ANY, '--tags=spam', '--skip-tags=ham',
            '--private-key=/path/to/key', '-vvv', '--timeout=100')

        all_vars = execute_mock.call_args[0][7]
        self.assertEqual({"ansible_python_interpreter": "/usr/bin/python3",
                          "ironic": {"foo": "bar"}},
                         json.loads(all_vars))

    @mock.patch.object(com_utils, 'execute', return_value=('out', 'err'),
                       autospec=True)
    def test__run_playbook_ansible_interpreter_override(self, execute_mock):
        self.config(group='ansible', playbooks_path='/path/to/playbooks')
        self.config(group='ansible', config_file_path='/path/to/config')
        self.config(group='ansible', verbosity=3)
        self.config(group='ansible',
                    default_python_interpreter='/usr/bin/python3')
        self.config(group='ansible', ansible_extra_args='--timeout=100')
        self.node.driver_info['ansible_python_interpreter'] = (
            '/usr/bin/python4')
        extra_vars = {'foo': 'bar'}

        ansible_deploy._run_playbook(self.node, 'deploy',
                                     extra_vars, '/path/to/key',
                                     tags=['spam'], notags=['ham'])

        execute_mock.assert_called_once_with(
            'env', 'ANSIBLE_CONFIG=/path/to/config',
            'ansible-playbook', '/path/to/playbooks/deploy', '-i',
            '/path/to/playbooks/inventory', '-e',
            mock.ANY, '--tags=spam', '--skip-tags=ham',
            '--private-key=/path/to/key', '-vvv', '--timeout=100')

        all_vars = execute_mock.call_args[0][7]
        self.assertEqual({"ansible_python_interpreter": "/usr/bin/python4",
                          "ironic": {"foo": "bar"}},
                         json.loads(all_vars))

    @mock.patch.object(com_utils, 'execute',
                       side_effect=processutils.ProcessExecutionError(
                           description='VIKINGS!'),
                       autospec=True)
    def test__run_playbook_fail(self, execute_mock):
        self.config(group='ansible', playbooks_path='/path/to/playbooks')
        self.config(group='ansible', config_file_path='/path/to/config')
        self.config(debug=False)
        extra_vars = {'foo': 'bar'}

        exc = self.assertRaises(exception.InstanceDeployFailure,
                                ansible_deploy._run_playbook,
                                self.node, 'deploy', extra_vars,
                                '/path/to/key')
        self.assertIn('VIKINGS!', str(exc))
        execute_mock.assert_called_once_with(
            'env', 'ANSIBLE_CONFIG=/path/to/config',
            'ansible-playbook', '/path/to/playbooks/deploy', '-i',
            '/path/to/playbooks/inventory', '-e', '{"ironic": {"foo": "bar"}}',
            '--private-key=/path/to/key')

    def test__parse_partitioning_info_root_msdos(self):
        expected_info = {
            'partition_info': {
                'label': 'msdos',
                'partitions': {
                    'root':
                        {'number': 1,
                         'part_start': '1MiB',
                         'part_end': '5121MiB',
                         'flags': ['boot']}
                }}}

        i_info = ansible_deploy._parse_partitioning_info(self.node)

        self.assertEqual(expected_info, i_info)

    def test__parse_partitioning_info_all_gpt(self):
        in_info = dict(INSTANCE_INFO)
        in_info['swap_mb'] = 128
        in_info['ephemeral_mb'] = 256
        in_info['ephemeral_format'] = 'ext4'
        in_info['preserve_ephemeral'] = True
        in_info['configdrive'] = 'some-fake-user-data'
        in_info['capabilities'] = {'disk_label': 'gpt'}
        self.node.instance_info = in_info
        self.node.save()

        expected_info = {
            'partition_info': {
                'label': 'gpt',
                'ephemeral_format': 'ext4',
                'preserve_ephemeral': 'yes',
                'partitions': {
                    'bios':
                        {'number': 1,
                         'name': 'bios',
                         'part_start': '1MiB',
                         'part_end': '2MiB',
                         'flags': ['bios_grub']},
                    'ephemeral':
                        {'number': 2,
                         'part_start': '2MiB',
                         'part_end': '258MiB',
                         'name': 'ephemeral'},
                    'swap':
                        {'number': 3,
                         'part_start': '258MiB',
                         'part_end': '386MiB',
                         'name': 'swap'},
                    'configdrive':
                        {'number': 4,
                         'part_start': '386MiB',
                         'part_end': '450MiB',
                         'name': 'configdrive'},
                    'root':
                        {'number': 5,
                         'part_start': '450MiB',
                         'part_end': '5570MiB',
                         'name': 'root'}
                }}}

        i_info = ansible_deploy._parse_partitioning_info(self.node)

        self.assertEqual(expected_info, i_info)

    @mock.patch.object(ansible_deploy.images, 'download_size', autospec=True)
    def test__calculate_memory_req(self, image_mock):
        self.config(group='ansible', extra_memory=1)
        image_mock.return_value = 2000000  # < 2MiB

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(2, ansible_deploy._calculate_memory_req(task))
            image_mock.assert_called_once_with(task.context, 'fake-image')

    def test__get_python_interpreter(self):
        self.config(group='ansible',
                    default_python_interpreter='/usr/bin/python3')
        self.node.driver_info['ansible_python_interpreter'] = (
            '/usr/bin/python4')

        python_interpreter = ansible_deploy._get_python_interpreter(self.node)

        self.assertEqual('/usr/bin/python4', python_interpreter)

    def test__get_configdrive_path(self):
        self.config(tempdir='/path/to/tmpdir')
        self.assertEqual('/path/to/tmpdir/spam.cndrive',
                         ansible_deploy._get_configdrive_path('spam'))

    def test__prepare_extra_vars(self):
        host_list = [('fake-uuid', '1.2.3.4', 'spam', 'ham'),
                     ('other-uuid', '5.6.7.8', 'eggs', 'vikings')]
        ansible_vars = {"foo": "bar"}
        self.assertEqual(
            {"nodes": [
                {"name": "fake-uuid", "ip": '1.2.3.4',
                 "user": "spam", "extra": "ham"},
                {"name": "other-uuid", "ip": '5.6.7.8',
                 "user": "eggs", "extra": "vikings"}],
                "foo": "bar"},
            ansible_deploy._prepare_extra_vars(host_list, ansible_vars))

    def test__parse_root_device_hints(self):
        hints = {"wwn": "fake wwn", "size": "12345", "rotational": True,
                 "serial": "HELLO"}
        expected = {"wwn": "fake wwn", "size": 12345, "rotational": True,
                    "serial": "hello"}
        props = self.node.properties
        props['root_device'] = hints
        self.node.properties = props
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(
                expected, ansible_deploy._parse_root_device_hints(task.node))

    def test__parse_root_device_hints_iinfo(self):
        hints = {"wwn": "fake wwn", "size": "12345", "rotational": True,
                 "serial": "HELLO"}
        expected = {"wwn": "fake wwn", "size": 12345, "rotational": True,
                    "serial": "hello"}
        iinfo = self.node.instance_info
        iinfo['root_device'] = hints
        self.node.instance_info = iinfo
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(
                expected, ansible_deploy._parse_root_device_hints(task.node))

    def test__parse_root_device_hints_override(self):
        hints = {"wwn": "fake wwn", "size": "12345", "rotational": True,
                 "serial": "HELLO"}
        expected = {"wwn": "fake wwn", "size": 12345, "rotational": True,
                    "serial": "hello"}
        props = self.node.properties
        props['root_device'] = {'size': 'no idea'}
        self.node.properties = props
        iinfo = self.node.instance_info
        iinfo['root_device'] = hints
        self.node.instance_info = iinfo
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(
                expected, ansible_deploy._parse_root_device_hints(task.node))

    def test__parse_root_device_hints_fail_advanced(self):
        hints = {"wwn": "s!= fake wwn",
                 "size": ">= 12345",
                 "name": "<or> spam <or> ham",
                 "rotational": True}
        expected = {"wwn": "s!= fake%20wwn",
                    "name": "<or> spam <or> ham",
                    "size": ">= 12345"}
        props = self.node.properties
        props['root_device'] = hints
        self.node.properties = props
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            exc = self.assertRaises(
                exception.InvalidParameterValue,
                ansible_deploy._parse_root_device_hints, task.node)
            for key, value in expected.items():
                self.assertIn(str(key), str(exc))
                self.assertIn(str(value), str(exc))

    def test__prepare_variables(self):
        i_info = self.node.instance_info
        i_info['image_mem_req'] = 3000
        i_info['image_whatever'] = 'hello'
        self.node.instance_info = i_info
        self.node.save()

        expected = {"image": {"url": "http://image",
                              "validate_certs": "yes",
                              "source": "fake-image",
                              "mem_req": 3000,
                              "disk_format": "qcow2",
                              "checksum": "md5:checksum",
                              "whatever": "hello"}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(expected,
                             ansible_deploy._prepare_variables(task))

    def test__prepare_variables_root_device_hints(self):
        props = self.node.properties
        props['root_device'] = {"wwn": "fake-wwn"}
        self.node.properties = props
        self.node.save()
        expected = {"image": {"url": "http://image",
                              "validate_certs": "yes",
                              "source": "fake-image",
                              "disk_format": "qcow2",
                              "checksum": "md5:checksum"},
                    "root_device_hints": {"wwn": "fake-wwn"}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(expected,
                             ansible_deploy._prepare_variables(task))

    def test__prepare_variables_insecure_activated(self):
        self.config(image_store_insecure=True, group='ansible')
        i_info = self.node.instance_info
        i_info['image_checksum'] = 'sha256:checksum'
        self.node.instance_info = i_info
        self.node.save()
        expected = {"image": {"url": "http://image",
                              "validate_certs": "no",
                              "source": "fake-image",
                              "disk_format": "qcow2",
                              "checksum": "sha256:checksum"}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(expected,
                             ansible_deploy._prepare_variables(task))

    def test__prepare_variables_configdrive_url(self):
        i_info = self.node.instance_info
        i_info['configdrive'] = 'http://configdrive_url'
        self.node.instance_info = i_info
        self.node.save()
        expected = {"image": {"url": "http://image",
                              "validate_certs": "yes",
                              "source": "fake-image",
                              "disk_format": "qcow2",
                              "checksum": "md5:checksum"},
                    'configdrive': {'type': 'url',
                                    'location': 'http://configdrive_url'}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(expected,
                             ansible_deploy._prepare_variables(task))

    def test__prepare_variables_configdrive_file(self):
        i_info = self.node.instance_info
        i_info['configdrive'] = 'fake-content'
        self.node.instance_info = i_info
        self.node.save()
        configdrive_path = ('%(tempdir)s/%(node)s.cndrive' %
                            {'tempdir': ansible_deploy.CONF.tempdir,
                             'node': self.node.uuid})
        expected = {"image": {"url": "http://image",
                              "validate_certs": "yes",
                              "source": "fake-image",
                              "disk_format": "qcow2",
                              "checksum": "md5:checksum"},
                    'configdrive': {'type': 'file',
                                    'location': configdrive_path}}
        with mock.patch.object(ansible_deploy, 'open', mock.mock_open(),
                               create=True) as open_mock:
            with task_manager.acquire(self.context, self.node.uuid) as task:
                self.assertEqual(expected,
                                 ansible_deploy._prepare_variables(task))
            open_mock.assert_has_calls((
                mock.call(configdrive_path, 'w'),
                mock.call().__enter__(),
                mock.call().write('fake-content'),
                mock.call().__exit__(None, None, None)))

    def test__validate_clean_steps(self):
        steps = [{"interface": "deploy",
                  "name": "foo",
                  "args": {"spam": {"required": True, "value": "ham"}}},
                 {"name": "bar",
                  "interface": "deploy"}]
        self.assertIsNone(ansible_deploy._validate_clean_steps(
            steps, self.node.uuid))

    def test__validate_clean_steps_missing(self):
        steps = [{"name": "foo",
                  "interface": "deploy",
                  "args": {"spam": {"value": "ham"},
                           "ham": {"required": True}}},
                 {"name": "bar"},
                 {"interface": "deploy"}]
        exc = self.assertRaises(exception.NodeCleaningFailure,
                                ansible_deploy._validate_clean_steps,
                                steps, self.node.uuid)
        self.assertIn("name foo, field ham.value", str(exc))
        self.assertIn("name bar, field interface", str(exc))
        self.assertIn("name undefined, field name", str(exc))

    def test__validate_clean_steps_names_not_unique(self):
        steps = [{"name": "foo",
                  "interface": "deploy"},
                 {"name": "foo",
                  "interface": "deploy"}]
        exc = self.assertRaises(exception.NodeCleaningFailure,
                                ansible_deploy._validate_clean_steps,
                                steps, self.node.uuid)
        self.assertIn("unique names", str(exc))

    @mock.patch.object(ansible_deploy.yaml, 'safe_load', autospec=True)
    def test__get_clean_steps(self, load_mock):
        steps = [{"interface": "deploy",
                  "name": "foo",
                  "args": {"spam": {"required": True, "value": "ham"}}},
                 {"name": "bar",
                  "interface": "deploy",
                  "priority": 100}]
        load_mock.return_value = steps
        expected = [{"interface": "deploy",
                     "step": "foo",
                     "priority": 10,
                     "abortable": False,
                     "argsinfo": {"spam": {"required": True}},
                     "args": {"spam": "ham"}},
                    {"interface": "deploy",
                     "step": "bar",
                     "priority": 100,
                     "abortable": False,
                     "argsinfo": {},
                     "args": {}}]
        d_info = self.node.driver_info
        d_info['ansible_clean_steps_config'] = 'custom_clean'
        self.node.driver_info = d_info
        self.node.save()
        self.config(group='ansible', playbooks_path='/path/to/playbooks')

        with mock.patch.object(ansible_deploy, 'open', mock.mock_open(),
                               create=True) as open_mock:
            self.assertEqual(
                expected,
                ansible_deploy._get_clean_steps(
                    self.node, interface="deploy",
                    override_priorities={"foo": 10}))
            open_mock.assert_has_calls((
                mock.call('/path/to/playbooks/custom_clean'),))
            load_mock.assert_called_once_with(
                open_mock().__enter__.return_value)


class TestAnsibleDeploy(AnsibleDeployTestCaseBase):
    def setUp(self):
        super(TestAnsibleDeploy, self).setUp()
        self.driver = ansible_deploy.AnsibleDeploy()

    def test_get_properties(self):
        self.assertEqual(
            set(list(ansible_deploy.COMMON_PROPERTIES)
                + ['deploy_forces_oob_reboot']),
            set(self.driver.get_properties()))

    @mock.patch.object(deploy_utils, 'check_for_missing_params',
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate(self, pxe_boot_validate_mock, check_params_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.driver.validate(task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)
            check_params_mock.assert_called_once_with(
                {'instance_info.image_source': INSTANCE_INFO['image_source']},
                mock.ANY)

    @mock.patch.object(deploy_utils, 'get_boot_option',
                       return_value='netboot', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_not_iwdi_netboot(self, pxe_boot_validate_mock,
                                       get_boot_mock):
        driver_internal_info = dict(DRIVER_INTERNAL_INFO)
        driver_internal_info['is_whole_disk_image'] = False
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.driver.validate, task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)
            get_boot_mock.assert_called_once_with(task.node)

    @mock.patch.object(ansible_deploy, '_calculate_memory_req', autospec=True,
                       return_value=2000)
    @mock.patch.object(utils, 'node_power_action', autospec=True)
    def test_deploy(self, power_mock, mem_req_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            driver_return = self.driver.deploy(task)
            self.assertEqual(driver_return, states.DEPLOYWAIT)
            power_mock.assert_called_once_with(task, states.REBOOT)
            mem_req_mock.assert_called_once_with(task)
            i_info = task.node.instance_info
            self.assertEqual(i_info['image_mem_req'], 2000)

    @mock.patch.object(utils, 'node_power_action', autospec=True)
    def test_tear_down(self, power_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            driver_return = self.driver.tear_down(task)
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            self.assertEqual(driver_return, states.DELETED)

    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    @mock.patch('ironic.drivers.modules.deploy_utils.build_agent_options',
                return_value={'op1': 'test1'}, autospec=True)
    @mock.patch('ironic.drivers.modules.deploy_utils.'
                'build_instance_info_for_deploy',
                return_value={'test': 'test'}, autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    def test_prepare(self, pxe_prepare_ramdisk_mock,
                     build_instance_info_mock, build_options_mock,
                     power_action_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYING

            with mock.patch.object(task.driver.network,
                                   'add_provisioning_network',
                                   autospec=True) as net_mock:
                self.driver.prepare(task)

                net_mock.assert_called_once_with(task)
            power_action_mock.assert_called_once_with(task,
                                                      states.POWER_OFF)
            build_instance_info_mock.assert_called_once_with(task)
            build_options_mock.assert_called_once_with(task.node)
            pxe_prepare_ramdisk_mock.assert_called_once_with(
                task.driver.boot, task, {'op1': 'test1'})

        self.node.refresh()
        self.assertEqual('test', self.node.instance_info['test'])

    @mock.patch.object(ansible_deploy, '_get_configdrive_path',
                       return_value='/path/test', autospec=True)
    @mock.patch.object(irlib_utils, 'unlink_without_raise', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    def test_clean_up(self, pxe_clean_up_mock, unlink_mock,
                      get_cfdrive_path_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.driver.clean_up(task)
            pxe_clean_up_mock.assert_called_once_with(task.driver.boot, task)
            get_cfdrive_path_mock.assert_called_once_with(self.node['uuid'])
            unlink_mock.assert_called_once_with('/path/test')

    @mock.patch.object(ansible_deploy, '_get_clean_steps', autospec=True)
    def test_get_clean_steps(self, get_clean_steps_mock):
        mock_steps = [{'priority': 10, 'interface': 'deploy',
                       'step': 'erase_devices'},
                      {'priority': 99, 'interface': 'deploy',
                       'step': 'erase_devices_metadata'},
                      ]
        get_clean_steps_mock.return_value = mock_steps
        with task_manager.acquire(self.context, self.node.uuid) as task:
            steps = self.driver.get_clean_steps(task)
            get_clean_steps_mock.assert_called_once_with(
                task.node, interface='deploy',
                override_priorities={
                    'erase_devices': None,
                    'erase_devices_metadata': None})
        self.assertEqual(mock_steps, steps)

    @mock.patch.object(ansible_deploy, '_get_clean_steps', autospec=True)
    def test_get_clean_steps_priority(self, mock_get_clean_steps):
        self.config(erase_devices_priority=9, group='deploy')
        self.config(erase_devices_metadata_priority=98, group='deploy')
        mock_steps = [{'priority': 9, 'interface': 'deploy',
                       'step': 'erase_devices'},
                      {'priority': 98, 'interface': 'deploy',
                       'step': 'erase_devices_metadata'},
                      ]
        mock_get_clean_steps.return_value = mock_steps

        with task_manager.acquire(self.context, self.node.uuid) as task:
            steps = self.driver.get_clean_steps(task)
            mock_get_clean_steps.assert_called_once_with(
                task.node, interface='deploy',
                override_priorities={'erase_devices': 9,
                                     'erase_devices_metadata': 98})
        self.assertEqual(mock_steps, steps)

    @mock.patch.object(ansible_deploy, '_run_playbook', autospec=True)
    @mock.patch.object(ansible_deploy, '_prepare_extra_vars', autospec=True)
    @mock.patch.object(ansible_deploy, '_parse_ansible_driver_info',
                       return_value=('test_pl', 'test_u', 'test_k'),
                       autospec=True)
    def test_execute_clean_step(self, parse_driver_info_mock,
                                prepare_extra_mock, run_playbook_mock):

        step = {'priority': 10, 'interface': 'deploy',
                'step': 'erase_devices', 'args': {'tags': ['clean']}}
        ironic_nodes = {
            'ironic_nodes': [(self.node['uuid'], '127.0.0.1', 'test_u', {})]}
        prepare_extra_mock.return_value = ironic_nodes
        di_info = self.node.driver_internal_info
        di_info['agent_url'] = 'http://127.0.0.1'
        self.node.driver_internal_info = di_info
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.execute_clean_step(task, step)

            parse_driver_info_mock.assert_called_once_with(
                task.node, action='clean')
            prepare_extra_mock.assert_called_once_with(
                ironic_nodes['ironic_nodes'])
            run_playbook_mock.assert_called_once_with(
                task.node, 'test_pl', ironic_nodes, 'test_k', tags=['clean'])

    @mock.patch.object(ansible_deploy, '_parse_ansible_driver_info',
                       return_value=('test_pl', 'test_u', 'test_k'),
                       autospec=True)
    @mock.patch.object(ansible_deploy, '_run_playbook', autospec=True)
    @mock.patch.object(ansible_deploy, 'LOG', autospec=True)
    def test_execute_clean_step_no_success_log(
            self, log_mock, run_mock, parse_driver_info_mock):

        run_mock.side_effect = exception.InstanceDeployFailure('Boom')
        step = {'priority': 10, 'interface': 'deploy',
                'step': 'erase_devices', 'args': {'tags': ['clean']}}
        di_info = self.node.driver_internal_info
        di_info['agent_url'] = 'http://127.0.0.1'
        self.node.driver_internal_info = di_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InstanceDeployFailure,
                              self.driver.execute_clean_step,
                              task, step)
            self.assertFalse(log_mock.info.called)

    @mock.patch.object(ansible_deploy, '_run_playbook', autospec=True)
    @mock.patch.object(steps, 'set_node_cleaning_steps', autospec=True)
    @mock.patch.object(utils, 'node_power_action', autospec=True)
    @mock.patch('ironic.drivers.modules.deploy_utils.build_agent_options',
                return_value={'op1': 'test1'}, autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    def test_prepare_cleaning(
            self, prepare_ramdisk_mock, buid_options_mock, power_action_mock,
            set_node_cleaning_steps, run_playbook_mock):
        step = {'priority': 10, 'interface': 'deploy',
                'step': 'erase_devices', 'tags': ['clean']}
        driver_internal_info = dict(DRIVER_INTERNAL_INFO)
        driver_internal_info['clean_steps'] = [step]
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.network.add_cleaning_network = mock.Mock()

            state = self.driver.prepare_cleaning(task)

            set_node_cleaning_steps.assert_called_once_with(task)
            task.driver.network.add_cleaning_network.assert_called_once_with(
                task)
            buid_options_mock.assert_called_once_with(task.node)
            prepare_ramdisk_mock.assert_called_once_with(
                task.driver.boot, task, {'op1': 'test1'})
            power_action_mock.assert_called_once_with(task, states.REBOOT)
            self.assertFalse(run_playbook_mock.called)
            self.assertEqual(states.CLEANWAIT, state)

    @mock.patch.object(steps, 'set_node_cleaning_steps', autospec=True)
    def test_prepare_cleaning_callback_no_steps(self,
                                                set_node_cleaning_steps):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.network.add_cleaning_network = mock.Mock()

            self.driver.prepare_cleaning(task)

            set_node_cleaning_steps.assert_called_once_with(task)
            self.assertFalse(task.driver.network.add_cleaning_network.called)

    @mock.patch.object(utils, 'node_power_action', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    def test_tear_down_cleaning(self, clean_ramdisk_mock, power_action_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.network.remove_cleaning_network = mock.Mock()

            self.driver.tear_down_cleaning(task)

            power_action_mock.assert_called_once_with(task, states.POWER_OFF)
            clean_ramdisk_mock.assert_called_once_with(task.driver.boot, task)
            (task.driver.network.remove_cleaning_network
                .assert_called_once_with(task))

    @mock.patch.object(ansible_deploy, '_run_playbook', autospec=True)
    @mock.patch.object(ansible_deploy, '_prepare_extra_vars', autospec=True)
    @mock.patch.object(ansible_deploy, '_parse_ansible_driver_info',
                       return_value=('test_pl', 'test_u', 'test_k'),
                       autospec=True)
    @mock.patch.object(ansible_deploy, '_parse_partitioning_info',
                       autospec=True)
    @mock.patch.object(ansible_deploy, '_prepare_variables', autospec=True)
    def test__ansible_deploy(self, prepare_vars_mock, parse_part_info_mock,
                             parse_dr_info_mock, prepare_extra_mock,
                             run_playbook_mock):
        ironic_nodes = {
            'ironic_nodes': [(self.node['uuid'], '127.0.0.1', 'test_u')]}
        prepare_extra_mock.return_value = ironic_nodes
        _vars = {
            'url': 'image_url',
            'checksum': 'aa'}
        prepare_vars_mock.return_value = _vars

        driver_internal_info = dict(DRIVER_INTERNAL_INFO)
        driver_internal_info['is_whole_disk_image'] = False
        self.node.driver_internal_info = driver_internal_info
        self.node.extra = {'ham': 'spam'}
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver._ansible_deploy(task, '127.0.0.1')

            prepare_vars_mock.assert_called_once_with(task)
            parse_part_info_mock.assert_called_once_with(task.node)
            parse_dr_info_mock.assert_called_once_with(task.node)
            prepare_extra_mock.assert_called_once_with(
                [(self.node['uuid'], '127.0.0.1', 'test_u', {'ham': 'spam'})],
                variables=_vars)
            run_playbook_mock.assert_called_once_with(
                task.node, 'test_pl', ironic_nodes, 'test_k')

    @mock.patch.object(ansible_deploy, '_run_playbook', autospec=True)
    @mock.patch.object(ansible_deploy, '_prepare_extra_vars', autospec=True)
    @mock.patch.object(ansible_deploy, '_parse_ansible_driver_info',
                       return_value=('test_pl', 'test_u', 'test_k'),
                       autospec=True)
    @mock.patch.object(ansible_deploy, '_parse_partitioning_info',
                       autospec=True)
    @mock.patch.object(ansible_deploy, '_prepare_variables', autospec=True)
    def test__ansible_deploy_iwdi(self, prepare_vars_mock,
                                  parse_part_info_mock, parse_dr_info_mock,
                                  prepare_extra_mock, run_playbook_mock):
        ironic_nodes = {
            'ironic_nodes': [(self.node['uuid'], '127.0.0.1', 'test_u')]}
        prepare_extra_mock.return_value = ironic_nodes
        _vars = {
            'url': 'image_url',
            'checksum': 'aa'}
        prepare_vars_mock.return_value = _vars
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = True
        instance_info = self.node.instance_info
        del instance_info['root_mb']
        self.node.driver_internal_info = driver_internal_info
        self.node.instance_info = instance_info
        self.node.extra = {'ham': 'spam'}
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver._ansible_deploy(task, '127.0.0.1')

            prepare_vars_mock.assert_called_once_with(task)
            self.assertFalse(parse_part_info_mock.called)
            parse_dr_info_mock.assert_called_once_with(task.node)
            prepare_extra_mock.assert_called_once_with(
                [(self.node['uuid'], '127.0.0.1', 'test_u', {'ham': 'spam'})],
                variables=_vars)
            run_playbook_mock.assert_called_once_with(
                task.node, 'test_pl', ironic_nodes, 'test_k')

    @mock.patch.object(fake.FakePower, 'get_power_state',
                       return_value=states.POWER_OFF, autospec=True)
    @mock.patch.object(utils, 'node_power_action', autospec=True)
    def test_tear_down_agent_force_reboot(
            self, power_action_mock, get_pow_state_mock):
        d_info = self.node.driver_info
        d_info['deploy_forces_oob_reboot'] = True
        self.node.driver_info = d_info
        self.node.save()
        self.config(group='ansible',
                    post_deploy_get_power_state_retry_interval=0)
        self.node.provision_state = states.DEPLOYING
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.tear_down_agent(task)
            power_action_mock.assert_called_once_with(task, states.POWER_OFF)
        get_pow_state_mock.assert_not_called()

    @mock.patch.object(ansible_deploy, '_run_playbook', autospec=True)
    @mock.patch.object(utils, 'node_power_action', autospec=True)
    def test_tear_down_agent_soft_poweroff_retry(
            self, power_action_mock, run_playbook_mock):
        self.config(group='ansible',
                    post_deploy_get_power_state_retry_interval=0)
        self.config(group='ansible',
                    post_deploy_get_power_state_retries=1)
        self.node.provision_state = states.DEPLOYING
        di_info = self.node.driver_internal_info
        di_info['agent_url'] = 'http://127.0.0.1'
        self.node.driver_internal_info = di_info
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            with mock.patch.object(task.driver.power,
                                   'get_power_state',
                                   return_value=states.POWER_ON,
                                   autospec=True) as p_mock:
                self.driver.tear_down_agent(task)
                p_mock.assert_called_with(task)
                self.assertEqual(2, len(p_mock.mock_calls))
            power_action_mock.assert_called_once_with(task, states.POWER_OFF)
            run_playbook_mock.assert_called_once_with(
                task.node, 'shutdown.yaml', mock.ANY, mock.ANY)

    @mock.patch.object(utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(ansible_deploy, '_get_node_ip', autospec=True,
                       return_value='1.2.3.4')
    def test_write_image(self, getip_mock, bootdev_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            with mock.patch.multiple(self.driver, autospec=True,
                                     _ansible_deploy=mock.DEFAULT,
                                     reboot_to_instance=mock.DEFAULT):
                result = self.driver.write_image(task)
                self.assertIsNone(result)
                getip_mock.assert_called_once_with(task)
                self.driver._ansible_deploy.assert_called_once_with(
                    task, '1.2.3.4')
                bootdev_mock.assert_called_once_with(task, 'disk',
                                                     persistent=True)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)

    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       autospec=True)
    @mock.patch.object(utils, 'restore_power_state_if_needed', autospec=True)
    @mock.patch.object(utils, 'power_on_node_if_needed', autospec=True)
    @mock.patch.object(utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy',
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    def test_prepare_with_smartnic_port(
            self, pxe_prepare_ramdisk_mock,
            build_instance_info_mock, build_options_mock,
            power_action_mock, power_on_node_if_needed_mock,
            restore_power_state_mock, net_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            build_instance_info_mock.return_value = {'test': 'test'}
            build_options_mock.return_value = {'op1': 'test1'}
            power_on_node_if_needed_mock.return_value = states.POWER_OFF
            self.driver.prepare(task)
            power_action_mock.assert_called_once_with(
                task, states.POWER_OFF)
            build_instance_info_mock.assert_called_once_with(task)
            build_options_mock.assert_called_once_with(task.node)
            pxe_prepare_ramdisk_mock.assert_called_once_with(
                task.driver.boot, task, {'op1': 'test1'})
            power_on_node_if_needed_mock.assert_called_once_with(task)
            restore_power_state_mock.assert_called_once_with(
                task, states.POWER_OFF)

        self.node.refresh()
        self.assertEqual('test', self.node.instance_info['test'])

    @mock.patch.object(utils, 'restore_power_state_if_needed', autospec=True)
    @mock.patch.object(utils, 'power_on_node_if_needed', autospec=True)
    @mock.patch.object(ansible_deploy, '_run_playbook', autospec=True)
    @mock.patch.object(steps, 'set_node_cleaning_steps', autospec=True)
    @mock.patch.object(utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    def test_prepare_cleaning_with_smartnic_port(
            self, prepare_ramdisk_mock, build_options_mock, power_action_mock,
            set_node_cleaning_steps, run_playbook_mock,
            power_on_node_if_needed_mock, restore_power_state_mock):
        step = {'priority': 10, 'interface': 'deploy',
                'step': 'erase_devices', 'tags': ['clean']}
        driver_internal_info = dict(DRIVER_INTERNAL_INFO)
        driver_internal_info['clean_steps'] = [step]
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.network.add_cleaning_network = mock.Mock()
            build_options_mock.return_value = {'op1': 'test1'}
            power_on_node_if_needed_mock.return_value = states.POWER_OFF
            state = self.driver.prepare_cleaning(task)
            set_node_cleaning_steps.assert_called_once_with(task)
            task.driver.network.add_cleaning_network.assert_called_once_with(
                task)
            build_options_mock.assert_called_once_with(task.node)
            prepare_ramdisk_mock.assert_called_once_with(
                task.driver.boot, task, {'op1': 'test1'})
            power_action_mock.assert_called_once_with(task, states.REBOOT)
            self.assertFalse(run_playbook_mock.called)
            self.assertEqual(states.CLEANWAIT, state)
            power_on_node_if_needed_mock.assert_called_once_with(task)
            restore_power_state_mock.assert_called_once_with(
                task, states.POWER_OFF)

    @mock.patch.object(utils, 'restore_power_state_if_needed', autospec=True)
    @mock.patch.object(utils, 'power_on_node_if_needed', autospec=True)
    @mock.patch.object(utils, 'node_power_action', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    def test_tear_down_cleaning_with_smartnic_port(
            self, clean_ramdisk_mock, power_action_mock,
            power_on_node_if_needed_mock, restore_power_state_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.network.remove_cleaning_network = mock.Mock()
            power_on_node_if_needed_mock.return_value = states.POWER_OFF
            self.driver.tear_down_cleaning(task)
            power_action_mock.assert_called_once_with(task, states.POWER_OFF)
            power_action_mock.assert_called_once_with(task, states.POWER_OFF)
            clean_ramdisk_mock.assert_called_once_with(task.driver.boot, task)
            (task.driver.network.remove_cleaning_network
                .assert_called_once_with(task))
            power_on_node_if_needed_mock.assert_called_once_with(task)
            restore_power_state_mock.assert_called_once_with(
                task, states.POWER_OFF)
