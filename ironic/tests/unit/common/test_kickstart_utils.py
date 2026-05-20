# Copyright 2021 Verizon Media
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

import base64
import os
from unittest import mock

from oslo_config import cfg
import pycdlib

from ironic.common import kickstart_utils as ks_utils
from ironic.conductor import task_manager
from ironic.drivers.modules import ipxe
from ironic import tests as tests_root
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as object_utils


CONF = cfg.CONF
INST_INFO_DICT = db_utils.get_test_pxe_instance_info()
DRV_INFO_DICT = db_utils.get_test_pxe_driver_info()
DRV_INTERNAL_INFO_DICT = db_utils.get_test_pxe_driver_internal_info()

with open(
        os.path.join(
            os.path.dirname(tests_root.__file__),
            'unit/common/drive_samples', 'config_drive')) as f:
    CONFIG_DRIVE = f.read()


@mock.patch.object(ipxe.iPXEBoot, '__init__', lambda self: None)
class KSUtilsTestCase(db_base.DbTestCase):
    def setUp(self):
        super(KSUtilsTestCase, self).setUp()
        n = {
            'driver': 'fake-hardware',
            'boot_interface': 'ipxe',
            'instance_info': INST_INFO_DICT,
            'driver_info': DRV_INFO_DICT,
            'driver_internal_info': DRV_INTERNAL_INFO_DICT,
        }
        self.config(enabled_boot_interfaces=['ipxe'])
        self.config_temp_dir('http_root', group='deploy')
        self.node = object_utils.create_test_node(self.context, **n)
        self.config_drive_dict = {
            "openstack/content/0000": "net-data",
            "openstack/latest/meta-data.json": "{}",
            "openstack/latest/user_data": "test user_data",
            "openstack/latest/vendor_data.json": "{}"
        }

    def _get_expected_ks_config_drive(self, config_drive_dict):
        config_drive_ks_template = """\
\n%post\nDIRPATH=`/usr/bin/dirname {file_path}`\n\
/bin/mkdir -p $DIRPATH\n\
CONTENT='{content}'\n\
echo $CONTENT | /usr/bin/base64 --decode > {file_path}\n\
/bin/chmod 600 {file_path}\n\
%end\n\n"""

        target_path = '/var/lib/cloud/seed/config_drive'
        config_drive_ks = ''
        for key in sorted(config_drive_dict.keys()):
            config_drive_ks += config_drive_ks_template.format(
                file_path=os.path.join(target_path, key),
                content=base64.b64encode(str.encode(config_drive_dict[key]))
            )
        return config_drive_ks

    def test_prepare_config_drive(self):

        expected = self._get_expected_ks_config_drive(self.config_drive_dict)
        with task_manager.acquire(self.context, self.node.uuid) as task:
            i_info = task.node.instance_info
            i_info['configdrive'] = CONFIG_DRIVE
            task.node.instance_info = i_info
            task.node.save()
            self.assertEqual(expected, ks_utils.prepare_config_drive(task))

    @mock.patch('requests.get', autospec=True)
    def test_prepare_config_drive_in_swift(self, mock_get):
        expected = self._get_expected_ks_config_drive(self.config_drive_dict)
        mock_get.return_value = mock.MagicMock(content=CONFIG_DRIVE)
        with task_manager.acquire(self.context, self.node.uuid) as task:
            i_info = task.node.instance_info
            i_info['configdrive'] = 'http://server/fake-configdrive-url'
            task.node.instance_info = i_info
            task.node.save()
            self.assertEqual(expected, ks_utils.prepare_config_drive(task))
            mock_get.assert_called_with('http://server/fake-configdrive-url',
                                        timeout=60)

    @mock.patch.object(pycdlib, 'PyCdlib', autospec=True)
    def test_read_iso9600_config_drive(self, mock_pycdlib_cls):
        mock_iso = mock_pycdlib_cls.return_value
        mock_iso.walk.return_value = [
            ('/', [], ['FILE1.TXT;1']),
        ]
        mock_record = mock.Mock()
        mock_iso.get_record.return_value = mock_record
        mock_iso.full_path_from_dirrecord.return_value = (
            '/openstack/latest/user_data'
        )

        def fake_get_file(iso_path, outfp):
            outfp.write(b'test user_data')

        mock_iso.get_file_from_iso_fp.side_effect = fake_get_file

        result = ks_utils.read_iso9600_config_drive(b'fake-iso')

        mock_iso.open.assert_called_once()
        mock_iso.walk.assert_called_once_with(iso_path='/')
        mock_iso.get_record.assert_called_once_with(
            iso_path='/FILE1.TXT;1'
        )
        mock_iso.full_path_from_dirrecord.assert_called_once_with(
            mock_record, rockridge=True
        )
        mock_iso.get_file_from_iso_fp.assert_called_once()
        mock_iso.close.assert_called_once()

        expected_path = (
            '/var/lib/cloud/seed/config_drive'
            '/openstack/latest/user_data'
        )
        self.assertIn(expected_path, result)
        self.assertEqual('test user_data', result[expected_path])

    @mock.patch.object(pycdlib, 'PyCdlib', autospec=True)
    def test_read_iso9600_config_drive_pycdlib_exception(
          self, mock_pycdlib_cls):
        mock_iso = mock_pycdlib_cls.return_value
        mock_iso.open.side_effect = (
            pycdlib.pycdlibexception.PyCdlibInvalidInput(
                msg='bad iso'
            )
        )

        result = ks_utils.read_iso9600_config_drive(b'bad-data')

        mock_iso.open.assert_called_once()
        mock_iso.walk.assert_not_called()
        self.assertEqual({}, result)

    @mock.patch.object(pycdlib, 'PyCdlib', autospec=True)
    def test_read_iso9600_config_drive_invalid_file(self, mock_pycdlib_cls):
        mock_iso = mock_pycdlib_cls.return_value
        mock_iso.walk.return_value = [
            ('/', [], ['../E1.TXT;1']),
        ]
        mock_record = mock.Mock()
        mock_iso.get_record.return_value = mock_record
        mock_iso.full_path_from_dirrecord.return_value = (
            '../E1.TXT'
        )

        def fake_get_file(iso_path, outfp):
            outfp.write(b'test user_data')

        mock_iso.get_file_from_iso_fp.side_effect = fake_get_file

        returned = ks_utils.read_iso9600_config_drive(b'fake-iso')
        self.assertEqual({}, returned)
        mock_iso.open.assert_called_once()
        mock_iso.walk.assert_called_once_with(iso_path='/')
        mock_iso.get_record.assert_called_once_with(
            iso_path='/../E1.TXT;1'
        )
        mock_iso.full_path_from_dirrecord.assert_called_once_with(
            mock_record, rockridge=True
        )
        mock_iso.get_file_from_iso_fp.assert_not_called()
