# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

import builtins
import hashlib
import io
import os
import tempfile

from ironic_lib import utils as ironic_utils
import mock
from oslo_config import cfg
from oslo_utils import importutils
from oslo_utils import uuidutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import images
from ironic.common import swift
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_ilo_info()

ilo_client = importutils.try_import('proliantutils.ilo.client')
ilo_error = importutils.try_import('proliantutils.exception')

CONF = cfg.CONF


class BaseIloTest(db_base.DbTestCase):

    boot_interface = None

    def setUp(self):
        super(BaseIloTest, self).setUp()
        self.config(enabled_hardware_types=['ilo', 'fake-hardware'],
                    enabled_boot_interfaces=['ilo-pxe', 'ilo-virtual-media',
                                             'fake'],
                    enabled_bios_interfaces=['ilo', 'no-bios'],
                    enabled_power_interfaces=['ilo', 'fake'],
                    enabled_management_interfaces=['ilo', 'fake'],
                    enabled_inspect_interfaces=['ilo', 'fake', 'no-inspect'],
                    enabled_console_interfaces=['ilo', 'fake', 'no-console'],
                    enabled_vendor_interfaces=['ilo', 'fake', 'no-vendor'])
        self.info = INFO_DICT.copy()
        self.node = obj_utils.create_test_node(
            self.context, uuid=uuidutils.generate_uuid(),
            driver='ilo', boot_interface=self.boot_interface,
            bios_interface='ilo',
            driver_info=self.info)


class IloValidateParametersTestCase(BaseIloTest):

    @mock.patch.object(os.path, 'isfile', return_value=True, autospec=True)
    def _test_parse_driver_info(self, isFile_mock):

        info = ilo_common.parse_driver_info(self.node)

        self.assertEqual(INFO_DICT['ilo_address'], info['ilo_address'])
        self.assertEqual(INFO_DICT['ilo_username'], info['ilo_username'])
        self.assertEqual(INFO_DICT['ilo_password'], info['ilo_password'])
        self.assertEqual(60, info['client_timeout'])
        self.assertEqual(443, info['client_port'])
        self.assertEqual('/home/user/cafile.pem', info['ca_file'])
        self.assertEqual('user', info['snmp_auth_user'])
        self.assertEqual('1234', info['snmp_auth_prot_password'])
        self.assertEqual('4321', info['snmp_auth_priv_password'])
        self.assertEqual('SHA', info['snmp_auth_protocol'])
        self.assertEqual('AES', info['snmp_auth_priv_protocol'])

    @mock.patch.object(os.path, 'isfile', return_value=True, autospec=True)
    def test_parse_driver_info_snmp_inspection_false(self, isFile_mock):
        info = ilo_common.parse_driver_info(self.node)
        self.assertEqual(INFO_DICT['ilo_address'], info['ilo_address'])
        self.assertEqual(INFO_DICT['ilo_username'], info['ilo_username'])
        self.assertEqual(INFO_DICT['ilo_password'], info['ilo_password'])
        self.assertEqual(60, info['client_timeout'])
        self.assertEqual(443, info['client_port'])

    @mock.patch.object(os.path, 'isfile', return_value=True, autospec=True)
    def test_parse_driver_info_snmp_true_no_auth_priv_protocols(self,
                                                                isFile_mock):
        d_info = {'ca_file': '/home/user/cafile.pem',
                  'snmp_auth_prot_password': '1234',
                  'snmp_auth_user': 'user',
                  'snmp_auth_priv_password': '4321'}
        self.node.driver_info.update(d_info)
        info = ilo_common.parse_driver_info(self.node)
        self.assertEqual(INFO_DICT['ilo_address'], info['ilo_address'])
        self.assertEqual(INFO_DICT['ilo_username'], info['ilo_username'])
        self.assertEqual(INFO_DICT['ilo_password'], info['ilo_password'])
        self.assertEqual(60, info['client_timeout'])
        self.assertEqual(443, info['client_port'])
        self.assertEqual('/home/user/cafile.pem', info['ca_file'])
        self.assertEqual('user', info['snmp_auth_user'])
        self.assertEqual('1234', info['snmp_auth_prot_password'])
        self.assertEqual('4321', info['snmp_auth_priv_password'])

    def test_parse_driver_info_ca_file_and_snmp_inspection_true(self):
        d_info = {'ca_file': '/home/user/cafile.pem',
                  'snmp_auth_prot_password': '1234',
                  'snmp_auth_user': 'user',
                  'snmp_auth_priv_password': '4321',
                  'snmp_auth_protocol': 'SHA',
                  'snmp_auth_priv_protocol': 'AES'}
        self.node.driver_info.update(d_info)
        self._test_parse_driver_info()

    def test_parse_driver_info_snmp_true_invalid_auth_protocol(self):
        d_info = {'ca_file': '/home/user/cafile.pem',
                  'snmp_auth_prot_password': '1234',
                  'snmp_auth_user': 'user',
                  'snmp_auth_priv_password': '4321',
                  'snmp_auth_protocol': 'abc',
                  'snmp_auth_priv_protocol': 'AES'}
        self.node.driver_info.update(d_info)
        self.assertRaises(exception.InvalidParameterValue,
                          ilo_common.parse_driver_info, self.node)

    def test_parse_driver_info_snmp_true_invalid_priv_protocol(self):
        d_info = {'ca_file': '/home/user/cafile.pem',
                  'snmp_auth_prot_password': '1234',
                  'snmp_auth_user': 'user',
                  'snmp_auth_priv_password': '4321',
                  'snmp_auth_protocol': 'SHA',
                  'snmp_auth_priv_protocol': 'xyz'}
        self.node.driver_info.update(d_info)
        self.assertRaises(exception.InvalidParameterValue,
                          ilo_common.parse_driver_info, self.node)

    def test_parse_driver_info_snmp_true_integer_auth_protocol(self):
        d_info = {'ca_file': '/home/user/cafile.pem',
                  'snmp_auth_prot_password': '1234',
                  'snmp_auth_user': 'user',
                  'snmp_auth_priv_password': '4321',
                  'snmp_auth_protocol': 12,
                  'snmp_auth_priv_protocol': 'AES'}
        self.node.driver_info.update(d_info)
        self.assertRaises(exception.InvalidParameterValue,
                          ilo_common.parse_driver_info, self.node)

    def test_parse_driver_info_snmp_inspection_true_raises(self):
        self.node.driver_info['snmp_auth_user'] = 'abc'
        self.assertRaises(exception.MissingParameterValue,
                          ilo_common.parse_driver_info, self.node)

    def test_parse_driver_info_missing_address(self):
        del self.node.driver_info['ilo_address']
        self.assertRaises(exception.MissingParameterValue,
                          ilo_common.parse_driver_info, self.node)

    def test_parse_driver_info_missing_username(self):
        del self.node.driver_info['ilo_username']
        self.assertRaises(exception.MissingParameterValue,
                          ilo_common.parse_driver_info, self.node)

    def test_parse_driver_info_missing_password(self):
        del self.node.driver_info['ilo_password']
        self.assertRaises(exception.MissingParameterValue,
                          ilo_common.parse_driver_info, self.node)

    @mock.patch.object(os.path, 'isfile', return_value=False, autospec=True)
    def test_parse_driver_info_invalid_cafile(self, isFile_mock):
        self.node.driver_info['ca_file'] = '/home/missing.pem'
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'ca_file "/home/missing.pem" is not found.',
                               ilo_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_timeout(self):
        self.node.driver_info['client_timeout'] = 'qwe'
        self.assertRaises(exception.InvalidParameterValue,
                          ilo_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_port(self):
        self.node.driver_info['client_port'] = 'qwe'
        self.assertRaises(exception.InvalidParameterValue,
                          ilo_common.parse_driver_info, self.node)
        self.node.driver_info['client_port'] = '65536'
        self.assertRaises(exception.InvalidParameterValue,
                          ilo_common.parse_driver_info, self.node)
        self.node.driver_info['console_port'] = 'invalid'
        self.assertRaises(exception.InvalidParameterValue,
                          ilo_common.parse_driver_info, self.node)
        self.node.driver_info['console_port'] = '-1'
        self.assertRaises(exception.InvalidParameterValue,
                          ilo_common.parse_driver_info, self.node)

    def test_parse_driver_info_missing_multiple_params(self):
        del self.node.driver_info['ilo_password']
        del self.node.driver_info['ilo_address']
        e = self.assertRaises(exception.MissingParameterValue,
                              ilo_common.parse_driver_info, self.node)
        self.assertIn('ilo_password', str(e))
        self.assertIn('ilo_address', str(e))

    def test_parse_driver_info_invalid_multiple_params(self):
        self.node.driver_info['client_timeout'] = 'qwe'
        e = self.assertRaises(exception.InvalidParameterValue,
                              ilo_common.parse_driver_info, self.node)
        self.assertIn('client_timeout', str(e))


class IloCommonMethodsTestCase(BaseIloTest):

    @mock.patch.object(os.path, 'isfile', return_value=True, autospec=True)
    @mock.patch.object(ilo_client, 'IloClient', spec_set=True,
                       autospec=True)
    def _test_get_ilo_object(self, ilo_client_mock, isFile_mock, ca_file=None):
        self.info['client_timeout'] = 600
        self.info['client_port'] = 4433
        self.info['ca_file'] = ca_file
        self.node.driver_info = self.info
        ilo_client_mock.return_value = 'ilo_object'
        returned_ilo_object = ilo_common.get_ilo_object(self.node)
        ilo_client_mock.assert_called_with(
            self.info['ilo_address'],
            self.info['ilo_username'],
            self.info['ilo_password'],
            self.info['client_timeout'],
            self.info['client_port'],
            cacert=self.info['ca_file'],
            snmp_credentials=None)
        self.assertEqual('ilo_object', returned_ilo_object)

    @mock.patch.object(os.path, 'isfile', return_value=True, autospec=True)
    @mock.patch.object(ilo_client, 'IloClient', spec_set=True,
                       autospec=True)
    def test_get_ilo_object_snmp(self, ilo_client_mock, isFile_mock):
        info = {'auth_user': 'user',
                'auth_prot_pp': '1234',
                'auth_priv_pp': '4321',
                'auth_protocol': 'SHA',
                'priv_protocol': 'AES',
                'snmp_inspection': True}
        d_info = {'client_timeout': 600,
                  'client_port': 4433,
                  'ca_file': 'ca_file',
                  'snmp_auth_user': 'user',
                  'snmp_auth_prot_password': '1234',
                  'snmp_auth_priv_password': '4321',
                  'snmp_auth_protocol': 'SHA',
                  'snmp_auth_priv_protocol': 'AES'}
        self.info.update(d_info)
        self.node.driver_info = self.info
        ilo_client_mock.return_value = 'ilo_object'
        returned_ilo_object = ilo_common.get_ilo_object(self.node)
        ilo_client_mock.assert_called_with(
            self.info['ilo_address'],
            self.info['ilo_username'],
            self.info['ilo_password'],
            self.info['client_timeout'],
            self.info['client_port'],
            cacert=self.info['ca_file'],
            snmp_credentials=info)
        self.assertEqual('ilo_object', returned_ilo_object)

    def test_get_ilo_object_cafile(self):
        self._test_get_ilo_object(ca_file='/home/user/ilo.pem')

    def test_get_ilo_object_no_cafile(self):
        self._test_get_ilo_object()

    def test_update_ipmi_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ipmi_info = {
                "ipmi_address": "1.2.3.4",
                "ipmi_username": "admin",
                "ipmi_password": "fake",
                "ipmi_terminal_port": 60
            }
            self.info['console_port'] = 60
            task.node.driver_info = self.info
            ilo_common.update_ipmi_properties(task)
            actual_info = task.node.driver_info
            expected_info = dict(self.info, **ipmi_info)
            self.assertEqual(expected_info, actual_info)

    def test__get_floppy_image_name(self):
        image_name_expected = 'image-' + self.node.uuid
        image_name_actual = ilo_common._get_floppy_image_name(self.node)
        self.assertEqual(image_name_expected, image_name_actual)

    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    @mock.patch.object(images, 'create_vfat_image', spec_set=True,
                       autospec=True)
    @mock.patch.object(tempfile, 'NamedTemporaryFile', spec_set=True,
                       autospec=True)
    def test__prepare_floppy_image(self, tempfile_mock, fatimage_mock,
                                   swift_api_mock):
        mock_image_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_image_file_obj = mock.MagicMock(spec=io.BytesIO)
        mock_image_file_obj.name = 'image-tmp-file'
        mock_image_file_handle.__enter__.return_value = mock_image_file_obj

        tempfile_mock.return_value = mock_image_file_handle

        swift_obj_mock = swift_api_mock.return_value
        self.config(swift_ilo_container='ilo_cont', group='ilo')
        self.config(swift_object_expiry_timeout=1, group='ilo')
        deploy_args = {'arg1': 'val1', 'arg2': 'val2'}
        swift_obj_mock.get_temp_url.return_value = 'temp-url'
        timeout = CONF.ilo.swift_object_expiry_timeout
        object_headers = {'X-Delete-After': str(timeout)}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            temp_url = ilo_common._prepare_floppy_image(task, deploy_args)
            node_uuid = task.node.uuid

        object_name = 'image-' + node_uuid
        fatimage_mock.assert_called_once_with('image-tmp-file',
                                              parameters=deploy_args)

        swift_obj_mock.create_object.assert_called_once_with(
            'ilo_cont', object_name, 'image-tmp-file',
            object_headers=object_headers)
        swift_obj_mock.get_temp_url.assert_called_once_with(
            'ilo_cont', object_name, timeout)
        self.assertEqual('temp-url', temp_url)

    @mock.patch.object(deploy_utils, 'copy_image_to_web_server',
                       spec_set=True, autospec=True)
    @mock.patch.object(images, 'create_vfat_image', spec_set=True,
                       autospec=True)
    @mock.patch.object(tempfile, 'NamedTemporaryFile', spec_set=True,
                       autospec=True)
    def test__prepare_floppy_image_use_webserver(self, tempfile_mock,
                                                 fatimage_mock,
                                                 copy_mock):
        mock_image_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_image_file_obj = mock.MagicMock(spec=io.BytesIO)
        mock_image_file_obj.name = 'image-tmp-file'
        mock_image_file_handle.__enter__.return_value = mock_image_file_obj

        tempfile_mock.return_value = mock_image_file_handle
        self.config(use_web_server_for_images=True, group='ilo')
        deploy_args = {'arg1': 'val1', 'arg2': 'val2'}
        CONF.deploy.http_url = "http://abc.com/httpboot"
        CONF.deploy.http_root = "/httpboot"

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            node_uuid = task.node.uuid
            object_name = 'image-' + node_uuid
            http_url = CONF.deploy.http_url + '/' + object_name
            copy_mock.return_value = "http://abc.com/httpboot/" + object_name
            temp_url = ilo_common._prepare_floppy_image(task, deploy_args)

        fatimage_mock.assert_called_once_with('image-tmp-file',
                                              parameters=deploy_args)
        copy_mock.assert_called_once_with('image-tmp-file', object_name)
        self.assertEqual(http_url, temp_url)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_attach_vmedia(self, get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        insert_media_mock = ilo_mock_object.insert_virtual_media
        set_status_mock = ilo_mock_object.set_vm_status

        ilo_common.attach_vmedia(self.node, 'FLOPPY', 'url')
        insert_media_mock.assert_called_once_with('url', device='FLOPPY')
        set_status_mock.assert_called_once_with(
            device='FLOPPY', boot_option='CONNECT', write_protect='YES')

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_attach_vmedia_fails(self, get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        set_status_mock = ilo_mock_object.set_vm_status
        exc = ilo_error.IloError('error')
        set_status_mock.side_effect = exc
        self.assertRaises(exception.IloOperationError,
                          ilo_common.attach_vmedia, self.node,
                          'FLOPPY', 'url')

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_set_boot_mode(self, get_ilo_object_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        get_pending_boot_mode_mock = ilo_object_mock.get_pending_boot_mode
        set_pending_boot_mode_mock = ilo_object_mock.set_pending_boot_mode
        get_pending_boot_mode_mock.return_value = 'LEGACY'
        ilo_common.set_boot_mode(self.node, 'uefi')
        get_ilo_object_mock.assert_called_once_with(self.node)
        get_pending_boot_mode_mock.assert_called_once_with()
        set_pending_boot_mode_mock.assert_called_once_with('UEFI')

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_set_boot_mode_without_set_pending_boot_mode(self,
                                                         get_ilo_object_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        get_pending_boot_mode_mock = ilo_object_mock.get_pending_boot_mode
        get_pending_boot_mode_mock.return_value = 'LEGACY'
        ilo_common.set_boot_mode(self.node, 'bios')
        get_ilo_object_mock.assert_called_once_with(self.node)
        get_pending_boot_mode_mock.assert_called_once_with()
        self.assertFalse(ilo_object_mock.set_pending_boot_mode.called)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_set_boot_mode_with_IloOperationError(self,
                                                  get_ilo_object_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        get_pending_boot_mode_mock = ilo_object_mock.get_pending_boot_mode
        get_pending_boot_mode_mock.return_value = 'UEFI'
        set_pending_boot_mode_mock = ilo_object_mock.set_pending_boot_mode
        exc = ilo_error.IloError('error')
        set_pending_boot_mode_mock.side_effect = exc
        self.assertRaises(exception.IloOperationError,
                          ilo_common.set_boot_mode, self.node, 'bios')
        get_ilo_object_mock.assert_called_once_with(self.node)
        get_pending_boot_mode_mock.assert_called_once_with()

    @mock.patch.object(ilo_common, 'set_boot_mode', spec_set=True,
                       autospec=True)
    def test_update_boot_mode_instance_info_exists(self,
                                                   set_boot_mode_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.instance_info['deploy_boot_mode'] = 'bios'
            ilo_common.update_boot_mode(task)
            set_boot_mode_mock.assert_called_once_with(task.node, 'bios')

    @mock.patch.object(ilo_common, 'set_boot_mode', spec_set=True,
                       autospec=True)
    def test_update_boot_mode_capabilities_exist(self,
                                                 set_boot_mode_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['capabilities'] = 'boot_mode:bios'
            ilo_common.update_boot_mode(task)
            set_boot_mode_mock.assert_called_once_with(task.node, 'bios')

    @mock.patch.object(ilo_common, 'set_boot_mode', spec_set=True,
                       autospec=True)
    def test_update_boot_mode_use_def_boot_mode(self,
                                                set_boot_mode_mock):
        self.config(default_boot_mode='bios', group='ilo')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_common.update_boot_mode(task)
            set_boot_mode_mock.assert_called_once_with(task.node, 'bios')
            self.assertEqual('bios',
                             task.node.instance_info['deploy_boot_mode'])

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_update_boot_mode(self, get_ilo_object_mock):
        self.config(default_boot_mode="auto", group='ilo')
        ilo_mock_obj = get_ilo_object_mock.return_value
        ilo_mock_obj.get_pending_boot_mode.return_value = 'LEGACY'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_common.update_boot_mode(task)
            get_ilo_object_mock.assert_called_once_with(task.node)
            ilo_mock_obj.get_pending_boot_mode.assert_called_once_with()
            self.assertEqual('bios',
                             task.node.instance_info['deploy_boot_mode'])

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_update_boot_mode_unknown(self,
                                      get_ilo_object_mock):
        ilo_mock_obj = get_ilo_object_mock.return_value
        ilo_mock_obj.get_pending_boot_mode.return_value = 'UNKNOWN'
        set_pending_boot_mode_mock = ilo_mock_obj.set_pending_boot_mode

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_common.update_boot_mode(task)
            get_ilo_object_mock.assert_called_once_with(task.node)
            ilo_mock_obj.get_pending_boot_mode.assert_called_once_with()
            set_pending_boot_mode_mock.assert_called_once_with('UEFI')
            self.assertEqual('uefi',
                             task.node.instance_info['deploy_boot_mode'])

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_update_boot_mode_unknown_except(self,
                                             get_ilo_object_mock):
        ilo_mock_obj = get_ilo_object_mock.return_value
        ilo_mock_obj.get_pending_boot_mode.return_value = 'UNKNOWN'
        set_pending_boot_mode_mock = ilo_mock_obj.set_pending_boot_mode
        exc = ilo_error.IloError('error')
        set_pending_boot_mode_mock.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IloOperationError,
                              ilo_common.update_boot_mode, task)
            get_ilo_object_mock.assert_called_once_with(task.node)
            ilo_mock_obj.get_pending_boot_mode.assert_called_once_with()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_update_boot_mode_legacy(self,
                                     get_ilo_object_mock):
        ilo_mock_obj = get_ilo_object_mock.return_value
        exc = ilo_error.IloCommandNotSupportedError('error')
        ilo_mock_obj.get_pending_boot_mode.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_common.update_boot_mode(task)
            get_ilo_object_mock.assert_called_once_with(task.node)
            ilo_mock_obj.get_pending_boot_mode.assert_called_once_with()
            self.assertEqual('bios',
                             task.node.instance_info['deploy_boot_mode'])

    @mock.patch.object(ilo_common, 'set_boot_mode', spec_set=True,
                       autospec=True)
    def test_update_boot_mode_prop_boot_mode_exist(self,
                                                   set_boot_mode_mock):

        properties = {'capabilities': 'boot_mode:uefi'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties = properties
            ilo_common.update_boot_mode(task)
            set_boot_mode_mock.assert_called_once_with(task.node, 'uefi')

    @mock.patch.object(images, 'get_temp_url_for_glance_image', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'attach_vmedia', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, '_prepare_floppy_image', spec_set=True,
                       autospec=True)
    def test_setup_vmedia_for_boot_with_parameters(
            self, prepare_image_mock, attach_vmedia_mock, temp_url_mock):
        parameters = {'a': 'b'}
        boot_iso = '733d1c44-a2ea-414b-aca7-69decf20d810'
        prepare_image_mock.return_value = 'floppy_url'
        temp_url_mock.return_value = 'image_url'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_common.setup_vmedia_for_boot(task, boot_iso, parameters)
            prepare_image_mock.assert_called_once_with(task, parameters)
            attach_vmedia_mock.assert_any_call(task.node, 'FLOPPY',
                                               'floppy_url')

            temp_url_mock.assert_called_once_with(
                task.context, '733d1c44-a2ea-414b-aca7-69decf20d810')
            attach_vmedia_mock.assert_any_call(task.node, 'CDROM', 'image_url')

    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'attach_vmedia', spec_set=True,
                       autospec=True)
    def test_setup_vmedia_for_boot_with_swift(self, attach_vmedia_mock,
                                              swift_api_mock):
        swift_obj_mock = swift_api_mock.return_value
        boot_iso = 'swift:object-name'
        swift_obj_mock.get_temp_url.return_value = 'image_url'
        CONF.keystone_authtoken.auth_uri = 'http://authurl'
        CONF.ilo.swift_ilo_container = 'ilo_cont'
        CONF.ilo.swift_object_expiry_timeout = 1
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_common.setup_vmedia_for_boot(task, boot_iso)
            swift_obj_mock.get_temp_url.assert_called_once_with(
                'ilo_cont', 'object-name', 1)
            attach_vmedia_mock.assert_called_once_with(
                task.node, 'CDROM', 'image_url')

    @mock.patch.object(ilo_common, 'attach_vmedia', spec_set=True,
                       autospec=True)
    def test_setup_vmedia_for_boot_with_url(self, attach_vmedia_mock):
        boot_iso = 'http://abc.com/img.iso'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_common.setup_vmedia_for_boot(task, boot_iso)
            attach_vmedia_mock.assert_called_once_with(task.node, 'CDROM',
                                                       boot_iso)

    @mock.patch.object(ilo_common, 'eject_vmedia_devices',
                       spec_set=True, autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, '_get_floppy_image_name', spec_set=True,
                       autospec=True)
    def test_cleanup_vmedia_boot(self, get_name_mock, swift_api_mock,
                                 eject_mock):
        swift_obj_mock = swift_api_mock.return_value
        CONF.ilo.swift_ilo_container = 'ilo_cont'

        get_name_mock.return_value = 'image-node-uuid'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_common.cleanup_vmedia_boot(task)
            swift_obj_mock.delete_object.assert_called_once_with(
                'ilo_cont', 'image-node-uuid')
            eject_mock.assert_called_once_with(task)

    @mock.patch.object(ilo_common.LOG, 'exception', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'eject_vmedia_devices',
                       spec_set=True, autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, '_get_floppy_image_name', spec_set=True,
                       autospec=True)
    def test_cleanup_vmedia_boot_exc(self, get_name_mock, swift_api_mock,
                                     eject_mock, log_mock):
        exc = exception.SwiftOperationError('error')
        swift_obj_mock = swift_api_mock.return_value
        swift_obj_mock.delete_object.side_effect = exc
        CONF.ilo.swift_ilo_container = 'ilo_cont'

        get_name_mock.return_value = 'image-node-uuid'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_common.cleanup_vmedia_boot(task)
            swift_obj_mock.delete_object.assert_called_once_with(
                'ilo_cont', 'image-node-uuid')
            self.assertTrue(log_mock.called)
            eject_mock.assert_called_once_with(task)

    @mock.patch.object(ilo_common.LOG, 'info', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'eject_vmedia_devices',
                       spec_set=True, autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, '_get_floppy_image_name', spec_set=True,
                       autospec=True)
    def test_cleanup_vmedia_boot_exc_resource_not_found(self, get_name_mock,
                                                        swift_api_mock,
                                                        eject_mock, log_mock):
        exc = exception.SwiftObjectNotFoundError('error')
        swift_obj_mock = swift_api_mock.return_value
        swift_obj_mock.delete_object.side_effect = exc
        CONF.ilo.swift_ilo_container = 'ilo_cont'

        get_name_mock.return_value = 'image-node-uuid'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_common.cleanup_vmedia_boot(task)
            swift_obj_mock.delete_object.assert_called_once_with(
                'ilo_cont', 'image-node-uuid')
            self.assertTrue(log_mock.called)
            eject_mock.assert_called_once_with(task)

    @mock.patch.object(ilo_common, 'eject_vmedia_devices',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'destroy_floppy_image_from_web_server',
                       spec_set=True, autospec=True)
    def test_cleanup_vmedia_boot_for_webserver(self,
                                               destroy_image_mock,
                                               eject_mock):
        CONF.ilo.use_web_server_for_images = True

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_common.cleanup_vmedia_boot(task)
            destroy_image_mock.assert_called_once_with(task.node)
            eject_mock.assert_called_once_with(task)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_eject_vmedia_devices(self, get_ilo_object_mock):
        ilo_object_mock = mock.MagicMock(spec=['eject_virtual_media'])
        get_ilo_object_mock.return_value = ilo_object_mock
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_common.eject_vmedia_devices(task)
            ilo_object_mock.eject_virtual_media.assert_has_calls(
                [mock.call('FLOPPY'), mock.call('CDROM')])

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_eject_vmedia_devices_raises(
            self, get_ilo_object_mock):
        ilo_object_mock = mock.MagicMock(spec=['eject_virtual_media'])
        get_ilo_object_mock.return_value = ilo_object_mock
        exc = ilo_error.IloError('error')
        ilo_object_mock.eject_virtual_media.side_effect = exc
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IloOperationError,
                              ilo_common.eject_vmedia_devices,
                              task)

            ilo_object_mock.eject_virtual_media.assert_called_once_with(
                'FLOPPY')

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_get_secure_boot_mode(self,
                                  get_ilo_object_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        ilo_object_mock.get_current_boot_mode.return_value = 'UEFI'
        ilo_object_mock.get_secure_boot_mode.return_value = True
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ret = ilo_common.get_secure_boot_mode(task)
            ilo_object_mock.get_current_boot_mode.assert_called_once_with()
            ilo_object_mock.get_secure_boot_mode.assert_called_once_with()
            self.assertTrue(ret)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_get_secure_boot_mode_bios(self,
                                       get_ilo_object_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        ilo_object_mock.get_current_boot_mode.return_value = 'BIOS'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ret = ilo_common.get_secure_boot_mode(task)
            ilo_object_mock.get_current_boot_mode.assert_called_once_with()
            self.assertFalse(ilo_object_mock.get_secure_boot_mode.called)
            self.assertFalse(ret)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_get_secure_boot_mode_fail(self,
                                       get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        exc = ilo_error.IloError('error')
        ilo_mock_object.get_current_boot_mode.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IloOperationError,
                              ilo_common.get_secure_boot_mode,
                              task)
        ilo_mock_object.get_current_boot_mode.assert_called_once_with()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_get_secure_boot_mode_not_supported(self,
                                                ilo_object_mock):
        ilo_mock_object = ilo_object_mock.return_value
        exc = ilo_error.IloCommandNotSupportedError('error')
        ilo_mock_object.get_current_boot_mode.return_value = 'UEFI'
        ilo_mock_object.get_secure_boot_mode.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IloOperationNotSupported,
                              ilo_common.get_secure_boot_mode,
                              task)
        ilo_mock_object.get_current_boot_mode.assert_called_once_with()
        ilo_mock_object.get_secure_boot_mode.assert_called_once_with()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_set_secure_boot_mode(self,
                                  get_ilo_object_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_common.set_secure_boot_mode(task, True)
            ilo_object_mock.set_secure_boot_mode.assert_called_once_with(True)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_set_secure_boot_mode_fail(self,
                                       get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        exc = ilo_error.IloError('error')
        ilo_mock_object.set_secure_boot_mode.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IloOperationError,
                              ilo_common.set_secure_boot_mode,
                              task, False)
        ilo_mock_object.set_secure_boot_mode.assert_called_once_with(False)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_set_secure_boot_mode_not_supported(self,
                                                ilo_object_mock):
        ilo_mock_object = ilo_object_mock.return_value
        exc = ilo_error.IloCommandNotSupportedError('error')
        ilo_mock_object.set_secure_boot_mode.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IloOperationNotSupported,
                              ilo_common.set_secure_boot_mode,
                              task, False)
        ilo_mock_object.set_secure_boot_mode.assert_called_once_with(False)

    @mock.patch.object(ilo_common, 'ironic_utils', autospec=True)
    def test_remove_image_from_web_server(self, utils_mock):
        # | GIVEN |
        CONF.deploy.http_url = "http://x.y.z.a/webserver/"
        CONF.deploy.http_root = "/webserver"
        object_name = 'tmp_image_file'
        # | WHEN |
        ilo_common.remove_image_from_web_server(object_name)
        # | THEN |
        (utils_mock.unlink_without_raise.
         assert_called_once_with("/webserver/tmp_image_file"))

    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    def test_copy_image_to_swift(self, swift_api_mock):
        # | GIVEN |
        self.config(swift_ilo_container='ilo_container', group='ilo')
        self.config(swift_object_expiry_timeout=1, group='ilo')
        container = CONF.ilo.swift_ilo_container
        timeout = CONF.ilo.swift_object_expiry_timeout

        swift_obj_mock = swift_api_mock.return_value
        destination_object_name = 'destination_object_name'
        source_file_path = 'tmp_image_file'
        object_headers = {'X-Delete-After': str(timeout)}
        # | WHEN |
        ilo_common.copy_image_to_swift(source_file_path,
                                       destination_object_name)
        # | THEN |
        swift_obj_mock.create_object.assert_called_once_with(
            container, destination_object_name, source_file_path,
            object_headers=object_headers)
        swift_obj_mock.get_temp_url.assert_called_once_with(
            container, destination_object_name, timeout)

    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    def test_copy_image_to_swift_throws_error_if_swift_operation_fails(
            self, swift_api_mock):
        # | GIVEN |
        self.config(swift_ilo_container='ilo_container', group='ilo')
        self.config(swift_object_expiry_timeout=1, group='ilo')

        swift_obj_mock = swift_api_mock.return_value
        destination_object_name = 'destination_object_name'
        source_file_path = 'tmp_image_file'
        swift_obj_mock.create_object.side_effect = (
            exception.SwiftOperationError(operation='create_object',
                                          error='failed'))
        # | WHEN | & | THEN |
        self.assertRaises(exception.SwiftOperationError,
                          ilo_common.copy_image_to_swift,
                          source_file_path, destination_object_name)

    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    def test_remove_image_from_swift(self, swift_api_mock):
        # | GIVEN |
        self.config(swift_ilo_container='ilo_container', group='ilo')
        container = CONF.ilo.swift_ilo_container

        swift_obj_mock = swift_api_mock.return_value
        object_name = 'object_name'
        # | WHEN |
        ilo_common.remove_image_from_swift(object_name)
        # | THEN |
        swift_obj_mock.delete_object.assert_called_once_with(
            container, object_name)

    @mock.patch.object(ilo_common, 'LOG', spec_set=True, autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    def test_remove_image_from_swift_suppresses_notfound_exc(
            self, swift_api_mock, LOG_mock):
        # | GIVEN |
        self.config(swift_ilo_container='ilo_container', group='ilo')
        container = CONF.ilo.swift_ilo_container

        swift_obj_mock = swift_api_mock.return_value
        object_name = 'object_name'
        raised_exc = exception.SwiftObjectNotFoundError(
            operation='delete_object', obj=object_name, container=container)
        swift_obj_mock.delete_object.side_effect = raised_exc
        # | WHEN |
        ilo_common.remove_image_from_swift(object_name)
        # | THEN |
        LOG_mock.info.assert_called_once_with(
            mock.ANY, {'associated_with_msg': "", 'err': raised_exc})

    @mock.patch.object(ilo_common, 'LOG', spec_set=True, autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    def test_remove_image_from_swift_suppresses_operror_exc(
            self, swift_api_mock, LOG_mock):
        # | GIVEN |
        self.config(swift_ilo_container='ilo_container', group='ilo')
        container = CONF.ilo.swift_ilo_container

        swift_obj_mock = swift_api_mock.return_value
        object_name = 'object_name'
        raised_exc = exception.SwiftOperationError(operation='delete_object',
                                                   error='failed')
        swift_obj_mock.delete_object.side_effect = raised_exc
        # | WHEN |
        ilo_common.remove_image_from_swift(object_name, 'alice_in_wonderland')
        # | THEN |
        LOG_mock.exception.assert_called_once_with(
            mock.ANY, {'object_name': object_name, 'container': container,
                       'associated_with_msg': ("associated with "
                                               "alice_in_wonderland"),
                       'err': raised_exc})

    @mock.patch.object(ironic_utils, 'unlink_without_raise', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, '_get_floppy_image_name', spec_set=True,
                       autospec=True)
    def test_destroy_floppy_image_from_web_server(self, get_floppy_name_mock,
                                                  utils_mock):
        get_floppy_name_mock.return_value = 'image-uuid'
        CONF.deploy.http_root = "/webserver/"
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_common.destroy_floppy_image_from_web_server(task.node)
            get_floppy_name_mock.assert_called_once_with(task.node)
            utils_mock.assert_called_once_with('/webserver/image-uuid')

    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'setup_vmedia_for_boot', spec_set=True,
                       autospec=True)
    def test_setup_vmedia(self,
                          func_setup_vmedia_for_boot,
                          func_set_boot_device):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            parameters = {'a': 'b'}
            iso = '733d1c44-a2ea-414b-aca7-69decf20d810'
            ilo_common.setup_vmedia(task, iso, parameters)
            func_setup_vmedia_for_boot.assert_called_once_with(task, iso,
                                                               parameters)
            func_set_boot_device.assert_called_once_with(task,
                                                         boot_devices.CDROM)

    @mock.patch.object(deploy_utils, 'is_secure_boot_requested', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'set_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test_update_secure_boot_mode_passed_true(self,
                                                 func_set_secure_boot_mode,
                                                 func_is_secure_boot_req):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            func_is_secure_boot_req.return_value = True
            ilo_common.update_secure_boot_mode(task, True)
            func_set_secure_boot_mode.assert_called_once_with(task, True)

    @mock.patch.object(deploy_utils, 'is_secure_boot_requested', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'set_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test_update_secure_boot_mode_passed_false(self,
                                                  func_set_secure_boot_mode,
                                                  func_is_secure_boot_req):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            func_is_secure_boot_req.return_value = False
            ilo_common.update_secure_boot_mode(task, False)
            self.assertFalse(func_set_secure_boot_mode.called)

    @mock.patch.object(ironic_utils, 'unlink_without_raise', spec_set=True,
                       autospec=True)
    def test_remove_single_or_list_of_files_with_file_list(self, unlink_mock):
        # | GIVEN |
        file_list = ['/any_path1/any_file1',
                     '/any_path2/any_file2',
                     '/any_path3/any_file3']
        # | WHEN |
        ilo_common.remove_single_or_list_of_files(file_list)
        # | THEN |
        calls = [mock.call('/any_path1/any_file1'),
                 mock.call('/any_path2/any_file2'),
                 mock.call('/any_path3/any_file3')]
        unlink_mock.assert_has_calls(calls)

    @mock.patch.object(ironic_utils, 'unlink_without_raise', spec_set=True,
                       autospec=True)
    def test_remove_single_or_list_of_files_with_file_str(self, unlink_mock):
        # | GIVEN |
        file_path = '/any_path1/any_file'
        # | WHEN |
        ilo_common.remove_single_or_list_of_files(file_path)
        # | THEN |
        unlink_mock.assert_called_once_with('/any_path1/any_file')

    @mock.patch.object(builtins, 'open', autospec=True)
    def test_verify_image_checksum(self, open_mock):
        # | GIVEN |
        data = b'Yankee Doodle went to town riding on a pony;'
        file_like_object = io.BytesIO(data)
        open_mock().__enter__.return_value = file_like_object
        actual_hash = hashlib.md5(data).hexdigest()
        # | WHEN |
        ilo_common.verify_image_checksum(file_like_object, actual_hash)
        # | THEN |
        # no any exception thrown

    def test_verify_image_checksum_throws_for_nonexistent_file(self):
        # | GIVEN |
        invalid_file_path = '/some/invalid/file/path'
        # | WHEN | & | THEN |
        self.assertRaises(exception.ImageRefValidationFailed,
                          ilo_common.verify_image_checksum,
                          invalid_file_path, 'hash_xxx')

    @mock.patch.object(builtins, 'open', autospec=True)
    def test_verify_image_checksum_throws_for_failed_validation(self,
                                                                open_mock):
        # | GIVEN |
        data = b'Yankee Doodle went to town riding on a pony;'
        file_like_object = io.BytesIO(data)
        open_mock().__enter__.return_value = file_like_object
        invalid_hash = 'invalid_hash_value'
        # | WHEN | & | THEN |
        self.assertRaises(exception.ImageRefValidationFailed,
                          ilo_common.verify_image_checksum,
                          file_like_object,
                          invalid_hash)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_get_server_post_state(self,
                                   get_ilo_object_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        post_state = 'FinishedPost'
        ilo_object_mock.get_host_post_state.return_value = post_state
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ret = ilo_common.get_server_post_state(task.node)
            ilo_object_mock.get_host_post_state.assert_called_once_with()
            self.assertEqual(post_state, ret)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_get_server_post_state_fail(self,
                                        get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        exc = ilo_error.IloError('error')
        ilo_mock_object.get_host_post_state.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IloOperationError,
                              ilo_common.get_server_post_state, task.node)
        ilo_mock_object.get_host_post_state.assert_called_once_with()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_get_server_post_state_not_supported(self,
                                                 ilo_object_mock):
        ilo_mock_object = ilo_object_mock.return_value
        exc = ilo_error.IloCommandNotSupportedError('error')
        ilo_mock_object.get_host_post_state.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IloOperationNotSupported,
                              ilo_common.get_server_post_state,
                              task.node)
        ilo_mock_object.get_host_post_state.assert_called_once_with()
