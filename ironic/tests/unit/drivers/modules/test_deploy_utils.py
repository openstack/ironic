#    Copyright (c) 2012 NTT DOCOMO, INC.
#    Copyright 2011 OpenStack Foundation
#    Copyright 2011 Ilya Alekseyev
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

import os
import tempfile
from unittest import mock

import fixtures
from oslo_config import cfg
from oslo_utils import fileutils
from oslo_utils import uuidutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import faults
from ironic.common import image_service
from ironic.common import states
from ironic.common import utils as common_utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import deploy_utils as utils
from ironic.drivers.modules import fake
from ironic.drivers.modules import image_cache
from ironic.drivers.modules import pxe
from ironic.drivers.modules.storage import cinder
from ironic.drivers import utils as driver_utils
from ironic.tests import base as tests_base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INST_INFO_DICT = db_utils.get_test_pxe_instance_info()
DRV_INFO_DICT = db_utils.get_test_pxe_driver_info()
DRV_INTERNAL_INFO_DICT = db_utils.get_test_pxe_driver_internal_info()

_PXECONF_DEPLOY = b"""
default deploy

label deploy
kernel deploy_kernel
append initrd=deploy_ramdisk
ipappend 3

label boot_partition
kernel kernel
append initrd=ramdisk root={{ ROOT }}

label boot_whole_disk
COM32 chain.c32
append mbr:{{ DISK_IDENTIFIER }}

label trusted_boot
kernel mboot
append tboot.gz --- kernel root={{ ROOT }} --- ramdisk
"""

_PXECONF_BOOT_PARTITION = """
default boot_partition

label deploy
kernel deploy_kernel
append initrd=deploy_ramdisk
ipappend 3

label boot_partition
kernel kernel
append initrd=ramdisk root=UUID=12345678-1234-1234-1234-1234567890abcdef

label boot_whole_disk
COM32 chain.c32
append mbr:{{ DISK_IDENTIFIER }}

label trusted_boot
kernel mboot
append tboot.gz --- kernel root=UUID=12345678-1234-1234-1234-1234567890abcdef \
--- ramdisk
"""

_PXECONF_BOOT_WHOLE_DISK = """
default boot_whole_disk

label deploy
kernel deploy_kernel
append initrd=deploy_ramdisk
ipappend 3

label boot_partition
kernel kernel
append initrd=ramdisk root={{ ROOT }}

label boot_whole_disk
COM32 chain.c32
append mbr:0x12345678

label trusted_boot
kernel mboot
append tboot.gz --- kernel root={{ ROOT }} --- ramdisk
"""

_PXECONF_TRUSTED_BOOT = """
default trusted_boot

label deploy
kernel deploy_kernel
append initrd=deploy_ramdisk
ipappend 3

label boot_partition
kernel kernel
append initrd=ramdisk root=UUID=12345678-1234-1234-1234-1234567890abcdef

label boot_whole_disk
COM32 chain.c32
append mbr:{{ DISK_IDENTIFIER }}

label trusted_boot
kernel mboot
append tboot.gz --- kernel root=UUID=12345678-1234-1234-1234-1234567890abcdef \
--- ramdisk
"""

_IPXECONF_DEPLOY = b"""
#!ipxe

dhcp

goto deploy

:deploy
kernel deploy_kernel
initrd deploy_ramdisk
boot

:boot_partition
kernel kernel
append initrd=ramdisk root={{ ROOT }}
boot

:boot_whole_disk
kernel chain.c32
append mbr:{{ DISK_IDENTIFIER }}
boot
"""

_IPXECONF_BOOT_PARTITION = """
#!ipxe

dhcp

goto boot_partition

:deploy
kernel deploy_kernel
initrd deploy_ramdisk
boot

:boot_partition
kernel kernel
append initrd=ramdisk root=UUID=12345678-1234-1234-1234-1234567890abcdef
boot

:boot_whole_disk
kernel chain.c32
append mbr:{{ DISK_IDENTIFIER }}
boot
"""

_IPXECONF_BOOT_WHOLE_DISK = """
#!ipxe

dhcp

goto boot_whole_disk

:deploy
kernel deploy_kernel
initrd deploy_ramdisk
boot

:boot_partition
kernel kernel
append initrd=ramdisk root={{ ROOT }}
boot

:boot_whole_disk
kernel chain.c32
append mbr:0x12345678
boot
"""

_IPXECONF_BOOT_ISCSI_NO_CONFIG = """
#!ipxe

dhcp

goto boot_iscsi

:deploy
kernel deploy_kernel
initrd deploy_ramdisk
boot

:boot_partition
kernel kernel
append initrd=ramdisk root=UUID=0x12345678
boot

:boot_whole_disk
kernel chain.c32
append mbr:{{ DISK_IDENTIFIER }}
boot
"""

_UEFI_PXECONF_DEPLOY = b"""
default=deploy

image=deploy_kernel
        label=deploy
        initrd=deploy_ramdisk
        append="ro text"

image=kernel
        label=boot_partition
        initrd=ramdisk
        append="root={{ ROOT }}"

image=chain.c32
        label=boot_whole_disk
        append="mbr:{{ DISK_IDENTIFIER }}"
"""

_UEFI_PXECONF_BOOT_PARTITION = """
default=boot_partition

image=deploy_kernel
        label=deploy
        initrd=deploy_ramdisk
        append="ro text"

image=kernel
        label=boot_partition
        initrd=ramdisk
        append="root=UUID=12345678-1234-1234-1234-1234567890abcdef"

image=chain.c32
        label=boot_whole_disk
        append="mbr:{{ DISK_IDENTIFIER }}"
"""

_UEFI_PXECONF_BOOT_WHOLE_DISK = """
default=boot_whole_disk

image=deploy_kernel
        label=deploy
        initrd=deploy_ramdisk
        append="ro text"

image=kernel
        label=boot_partition
        initrd=ramdisk
        append="root={{ ROOT }}"

image=chain.c32
        label=boot_whole_disk
        append="mbr:0x12345678"
"""

_UEFI_PXECONF_DEPLOY_GRUB = b"""
set default=deploy
set timeout=5
set hidden_timeout_quiet=false

menuentry "deploy"  {
    linuxefi deploy_kernel "ro text"
    initrdefi deploy_ramdisk
}

menuentry "boot_partition"  {
    linuxefi kernel "root=(( ROOT ))"
    initrdefi ramdisk
}

menuentry "boot_whole_disk"  {
    linuxefi chain.c32 mbr:(( DISK_IDENTIFIER ))
}
"""

_UEFI_PXECONF_BOOT_PARTITION_GRUB = """
set default=boot_partition
set timeout=5
set hidden_timeout_quiet=false

menuentry "deploy"  {
    linuxefi deploy_kernel "ro text"
    initrdefi deploy_ramdisk
}

menuentry "boot_partition"  {
    linuxefi kernel "root=UUID=12345678-1234-1234-1234-1234567890abcdef"
    initrdefi ramdisk
}

menuentry "boot_whole_disk"  {
    linuxefi chain.c32 mbr:(( DISK_IDENTIFIER ))
}
"""

_UEFI_PXECONF_BOOT_WHOLE_DISK_GRUB = """
set default=boot_whole_disk
set timeout=5
set hidden_timeout_quiet=false

menuentry "deploy"  {
    linuxefi deploy_kernel "ro text"
    initrdefi deploy_ramdisk
}

menuentry "boot_partition"  {
    linuxefi kernel "root=(( ROOT ))"
    initrdefi ramdisk
}

menuentry "boot_whole_disk"  {
    linuxefi chain.c32 mbr:0x12345678
}
"""


class SwitchPxeConfigTestCase(tests_base.TestCase):

    # NOTE(TheJulia): Remove elilo support after the deprecation period,
    # in the Queens release.
    def _create_config(self, ipxe=False, boot_mode=None, boot_loader='elilo'):
        (fd, fname) = tempfile.mkstemp()
        if boot_mode == 'uefi' and not ipxe:
            if boot_loader == 'grub':
                pxe_cfg = _UEFI_PXECONF_DEPLOY_GRUB
            else:
                pxe_cfg = _UEFI_PXECONF_DEPLOY
        else:
            pxe_cfg = _IPXECONF_DEPLOY if ipxe else _PXECONF_DEPLOY
        os.write(fd, pxe_cfg)
        os.close(fd)
        self.addCleanup(os.unlink, fname)
        return fname

    def test_switch_pxe_config_partition_image(self):
        boot_mode = 'bios'
        fname = self._create_config()
        utils.switch_pxe_config(fname,
                                '12345678-1234-1234-1234-1234567890abcdef',
                                boot_mode,
                                False)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_PXECONF_BOOT_PARTITION, pxeconf)

    def test_switch_pxe_config_whole_disk_image(self):
        boot_mode = 'bios'
        fname = self._create_config()
        utils.switch_pxe_config(fname,
                                '0x12345678',
                                boot_mode,
                                True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_PXECONF_BOOT_WHOLE_DISK, pxeconf)

    def test_switch_pxe_config_trusted_boot(self):
        boot_mode = 'bios'
        fname = self._create_config()
        utils.switch_pxe_config(fname,
                                '12345678-1234-1234-1234-1234567890abcdef',
                                boot_mode,
                                False, True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_PXECONF_TRUSTED_BOOT, pxeconf)

    def test_switch_ipxe_config_partition_image(self):
        boot_mode = 'bios'
        fname = self._create_config(ipxe=True)
        utils.switch_pxe_config(fname,
                                '12345678-1234-1234-1234-1234567890abcdef',
                                boot_mode,
                                False,
                                ipxe_enabled=True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_IPXECONF_BOOT_PARTITION, pxeconf)

    def test_switch_ipxe_config_whole_disk_image(self):
        boot_mode = 'bios'
        fname = self._create_config(ipxe=True)
        utils.switch_pxe_config(fname,
                                '0x12345678',
                                boot_mode,
                                True,
                                ipxe_enabled=True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_IPXECONF_BOOT_WHOLE_DISK, pxeconf)

    # NOTE(TheJulia): Remove elilo support after the deprecation period,
    # in the Queens release.
    def test_switch_uefi_elilo_pxe_config_partition_image(self):
        boot_mode = 'uefi'
        fname = self._create_config(boot_mode=boot_mode)
        utils.switch_pxe_config(fname,
                                '12345678-1234-1234-1234-1234567890abcdef',
                                boot_mode,
                                False)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_UEFI_PXECONF_BOOT_PARTITION, pxeconf)

    # NOTE(TheJulia): Remove elilo support after the deprecation period,
    # in the Queens release.
    def test_switch_uefi_elilo_config_whole_disk_image(self):
        boot_mode = 'uefi'
        fname = self._create_config(boot_mode=boot_mode)
        utils.switch_pxe_config(fname,
                                '0x12345678',
                                boot_mode,
                                True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_UEFI_PXECONF_BOOT_WHOLE_DISK, pxeconf)

    def test_switch_uefi_grub_pxe_config_partition_image(self):
        boot_mode = 'uefi'
        fname = self._create_config(boot_mode=boot_mode, boot_loader='grub')
        utils.switch_pxe_config(fname,
                                '12345678-1234-1234-1234-1234567890abcdef',
                                boot_mode,
                                False)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_UEFI_PXECONF_BOOT_PARTITION_GRUB, pxeconf)

    def test_switch_uefi_grub_config_whole_disk_image(self):
        boot_mode = 'uefi'
        fname = self._create_config(boot_mode=boot_mode, boot_loader='grub')
        utils.switch_pxe_config(fname,
                                '0x12345678',
                                boot_mode,
                                True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_UEFI_PXECONF_BOOT_WHOLE_DISK_GRUB, pxeconf)

    def test_switch_uefi_ipxe_config_partition_image(self):
        boot_mode = 'uefi'
        fname = self._create_config(boot_mode=boot_mode, ipxe=True)
        utils.switch_pxe_config(fname,
                                '12345678-1234-1234-1234-1234567890abcdef',
                                boot_mode,
                                False,
                                ipxe_enabled=True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_IPXECONF_BOOT_PARTITION, pxeconf)

    def test_switch_uefi_ipxe_config_whole_disk_image(self):
        boot_mode = 'uefi'
        fname = self._create_config(boot_mode=boot_mode, ipxe=True)
        utils.switch_pxe_config(fname,
                                '0x12345678',
                                boot_mode,
                                True,
                                ipxe_enabled=True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_IPXECONF_BOOT_WHOLE_DISK, pxeconf)

    def test_switch_ipxe_iscsi_boot(self):
        boot_mode = 'iscsi'
        fname = self._create_config(boot_mode=boot_mode, ipxe=True)
        utils.switch_pxe_config(fname,
                                '0x12345678',
                                boot_mode,
                                False, False, True,
                                ipxe_enabled=True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_IPXECONF_BOOT_ISCSI_NO_CONFIG, pxeconf)


class GetPxeBootConfigTestCase(db_base.DbTestCase):

    def setUp(self):
        super(GetPxeBootConfigTestCase, self).setUp()
        self.node = obj_utils.get_test_node(self.context,
                                            driver='fake-hardware')
        self.config(pxe_bootfile_name='bios-bootfile', group='pxe')
        self.config(uefi_pxe_bootfile_name='uefi-bootfile', group='pxe')
        self.config(pxe_config_template='bios-template', group='pxe')
        self.config(uefi_pxe_config_template='uefi-template', group='pxe')
        self.bootfile_by_arch = {'aarch64': 'aarch64-bootfile',
                                 'ppc64': 'ppc64-bootfile'}
        self.template_by_arch = {'aarch64': 'aarch64-template',
                                 'ppc64': 'ppc64-template'}

    def test_get_pxe_boot_file_bios_without_by_arch(self):
        properties = {'cpu_arch': 'x86', 'capabilities': 'boot_mode:bios'}
        self.node.properties = properties
        self.config(pxe_bootfile_name_by_arch={}, group='pxe')
        result = utils.get_pxe_boot_file(self.node)
        self.assertEqual('bios-bootfile', result)

    def test_get_pxe_config_template_bios_without_by_arch(self):
        properties = {'cpu_arch': 'x86', 'capabilities': 'boot_mode:bios'}
        self.node.properties = properties
        self.config(pxe_config_template_by_arch={}, group='pxe')
        result = utils.get_pxe_config_template(self.node)
        self.assertEqual('bios-template', result)

    def test_get_pxe_boot_file_uefi_without_by_arch(self):
        properties = {'cpu_arch': 'x86_64', 'capabilities': 'boot_mode:uefi'}
        self.node.properties = properties
        self.config(pxe_bootfile_name_by_arch={}, group='pxe')
        result = utils.get_pxe_boot_file(self.node)
        self.assertEqual('uefi-bootfile', result)

    def test_get_pxe_config_template_uefi_without_by_arch(self):
        properties = {'cpu_arch': 'x86_64', 'capabilities': 'boot_mode:uefi'}
        self.node.properties = properties
        self.config(pxe_config_template_by_arch={}, group='pxe')
        result = utils.get_pxe_config_template(self.node)
        self.assertEqual('uefi-template', result)

    def test_get_pxe_boot_file_cpu_not_in_by_arch(self):
        properties = {'cpu_arch': 'x86', 'capabilities': 'boot_mode:bios'}
        self.node.properties = properties
        self.config(pxe_bootfile_name_by_arch=self.bootfile_by_arch,
                    group='pxe')
        result = utils.get_pxe_boot_file(self.node)
        self.assertEqual('bios-bootfile', result)

    def test_get_pxe_config_template_cpu_not_in_by_arch(self):
        properties = {'cpu_arch': 'x86', 'capabilities': 'boot_mode:bios'}
        self.node.properties = properties
        self.config(pxe_config_template_by_arch=self.template_by_arch,
                    group='pxe')
        result = utils.get_pxe_config_template(self.node)
        self.assertEqual('bios-template', result)

    def test_get_pxe_boot_file_cpu_in_by_arch(self):
        properties = {'cpu_arch': 'aarch64', 'capabilities': 'boot_mode:uefi'}
        self.node.properties = properties
        self.config(pxe_bootfile_name_by_arch=self.bootfile_by_arch,
                    group='pxe')
        result = utils.get_pxe_boot_file(self.node)
        self.assertEqual('aarch64-bootfile', result)

    def test_get_pxe_config_template_cpu_in_by_arch(self):
        properties = {'cpu_arch': 'aarch64', 'capabilities': 'boot_mode:uefi'}
        self.node.properties = properties
        self.config(pxe_config_template_by_arch=self.template_by_arch,
                    group='pxe')
        result = utils.get_pxe_config_template(self.node)
        self.assertEqual('aarch64-template', result)

    def test_get_pxe_boot_file_emtpy_property(self):
        self.node.properties = {}
        self.config(pxe_bootfile_name_by_arch=self.bootfile_by_arch,
                    group='pxe')
        result = utils.get_pxe_boot_file(self.node)
        self.assertEqual('bios-bootfile', result)

    def test_get_ipxe_boot_file(self):
        self.config(ipxe_bootfile_name='meow', group='pxe')
        result = utils.get_ipxe_boot_file(self.node)
        self.assertEqual('meow', result)

    def test_get_ipxe_boot_file_uefi(self):
        self.config(uefi_ipxe_bootfile_name='ipxe-uefi-bootfile', group='pxe')
        properties = {'capabilities': 'boot_mode:uefi'}
        self.node.properties = properties
        result = utils.get_ipxe_boot_file(self.node)
        self.assertEqual('ipxe-uefi-bootfile', result)

    def test_get_ipxe_boot_file_other_arch(self):
        arch_names = {'aarch64': 'ipxe-aa64.efi',
                      'x86_64': 'ipxe.kpxe'}
        self.config(ipxe_bootfile_name_by_arch=arch_names, group='pxe')
        properties = {'cpu_arch': 'aarch64', 'capabilities': 'boot_mode:uefi'}
        self.node.properties = properties
        result = utils.get_ipxe_boot_file(self.node)
        self.assertEqual('ipxe-aa64.efi', result)

    def test_get_ipxe_boot_file_fallback(self):
        self.config(ipxe_bootfile_name=None, group='pxe')
        self.config(uefi_ipxe_bootfile_name=None, group='pxe')
        self.config(pxe_bootfile_name='lolcat', group='pxe')
        result = utils.get_ipxe_boot_file(self.node)
        self.assertEqual('lolcat', result)

    def test_get_pxe_config_template_emtpy_property(self):
        self.node.properties = {}
        self.config(pxe_config_template_by_arch=self.template_by_arch,
                    group='pxe')
        result = utils.get_pxe_config_template(self.node)
        self.assertEqual('bios-template', result)

    def test_get_pxe_config_template_per_node(self):
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            driver_info={"pxe_template": "fake-template"},
        )
        result = utils.get_pxe_config_template(node)
        self.assertEqual('fake-template', result)

    def test_get_ipxe_config_template(self):
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware')
        self.assertIn('ipxe_config.template',
                      utils.get_ipxe_config_template(node))

    def test_get_ipxe_config_template_none(self):
        self.config(ipxe_config_template=None, group='pxe')
        self.config(pxe_config_template='magical_bootloader',
                    group='pxe')
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware')
        self.assertEqual('magical_bootloader',
                         utils.get_ipxe_config_template(node))

    def test_get_ipxe_config_template_override_pxe_fallback(self):
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            driver_info={'pxe_template': 'magical'})
        self.assertEqual('magical',
                         utils.get_ipxe_config_template(node))


@mock.patch('time.sleep', lambda sec: None)
class OtherFunctionTestCase(db_base.DbTestCase):

    def setUp(self):
        super(OtherFunctionTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               boot_interface='pxe')

    @mock.patch.object(utils, 'LOG', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(manager_utils, 'deploying_error_handler', autospec=True)
    def _test_set_failed_state(self, mock_error, mock_power, mock_log,
                               event_value=None, power_value=None,
                               log_calls=None, poweroff=True,
                               collect_logs=True):
        err_msg = 'some failure'
        mock_error.side_effect = event_value
        mock_power.side_effect = power_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            if collect_logs:
                utils.set_failed_state(task, err_msg)
            else:
                utils.set_failed_state(task, err_msg,
                                       collect_logs=collect_logs)
            mock_error.assert_called_once_with(task, err_msg, err_msg,
                                               clean_up=False)
            if poweroff:
                mock_power.assert_called_once_with(task, states.POWER_OFF)
            else:
                self.assertFalse(mock_power.called)
            self.assertEqual(err_msg, task.node.last_error)
            if (log_calls and poweroff):
                mock_log.exception.assert_has_calls(log_calls)
            else:
                self.assertFalse(mock_log.called)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    def test_set_failed_state(self, mock_collect):
        exc_state = exception.InvalidState('invalid state')
        exc_param = exception.InvalidParameterValue('invalid parameter')
        mock_call = mock.call(mock.ANY)
        self._test_set_failed_state()
        calls = [mock_call]
        self._test_set_failed_state(event_value=iter([exc_state] * len(calls)),
                                    log_calls=calls)
        calls = [mock_call]
        self._test_set_failed_state(power_value=iter([exc_param] * len(calls)),
                                    log_calls=calls)
        calls = [mock_call, mock_call]
        self._test_set_failed_state(event_value=iter([exc_state] * len(calls)),
                                    power_value=iter([exc_param] * len(calls)),
                                    log_calls=calls)
        self.assertEqual(4, mock_collect.call_count)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    def test_set_failed_state_no_poweroff(self, mock_collect):
        cfg.CONF.set_override('power_off_after_deploy_failure', False,
                              'deploy')
        exc_state = exception.InvalidState('invalid state')
        exc_param = exception.InvalidParameterValue('invalid parameter')
        mock_call = mock.call(mock.ANY)
        self._test_set_failed_state(poweroff=False)
        calls = [mock_call]
        self._test_set_failed_state(event_value=iter([exc_state] * len(calls)),
                                    log_calls=calls, poweroff=False)
        calls = [mock_call]
        self._test_set_failed_state(power_value=iter([exc_param] * len(calls)),
                                    log_calls=calls, poweroff=False)
        calls = [mock_call, mock_call]
        self._test_set_failed_state(event_value=iter([exc_state] * len(calls)),
                                    power_value=iter([exc_param] * len(calls)),
                                    log_calls=calls, poweroff=False)
        self.assertEqual(4, mock_collect.call_count)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    def test_set_failed_state_collect_deploy_logs(self, mock_collect):
        for opt in ('always', 'on_failure'):
            cfg.CONF.set_override('deploy_logs_collect', opt, 'agent')
            self._test_set_failed_state()
            mock_collect.assert_called_once_with(mock.ANY)
            mock_collect.reset_mock()

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    def test_set_failed_state_collect_deploy_logs_never(self, mock_collect):
        cfg.CONF.set_override('deploy_logs_collect', 'never', 'agent')
        self._test_set_failed_state()
        self.assertFalse(mock_collect.called)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    def test_set_failed_state_collect_deploy_logs_overide(self, mock_collect):
        cfg.CONF.set_override('deploy_logs_collect', 'always', 'agent')
        self._test_set_failed_state(collect_logs=False)
        self.assertFalse(mock_collect.called)

    def test_get_boot_option(self):
        self.node.instance_info = {'capabilities': '{"boot_option": "local"}'}
        result = utils.get_boot_option(self.node)
        self.assertEqual("local", result)

    def test_get_boot_option_default_value(self):
        self.node.instance_info = {}
        result = utils.get_boot_option(self.node)
        self.assertEqual("local", result)

    def test_get_boot_option_overridden_default_value(self):
        cfg.CONF.set_override('default_boot_option', 'local', 'deploy')
        self.node.instance_info = {}
        result = utils.get_boot_option(self.node)
        self.assertEqual("local", result)

    def test_get_boot_option_instance_info_priority(self):
        cfg.CONF.set_override('default_boot_option', 'local', 'deploy')
        self.node.instance_info = {'capabilities':
                                   '{"boot_option": "netboot"}'}
        result = utils.get_boot_option(self.node)
        self.assertEqual("netboot", result)

    @mock.patch.object(utils, 'is_software_raid', autospec=True)
    def test_get_boot_option_software_raid(self, mock_is_software_raid):
        mock_is_software_raid.return_value = True
        cfg.CONF.set_override('default_boot_option', 'netboot', 'deploy')
        result = utils.get_boot_option(self.node)
        self.assertEqual("local", result)

    @mock.patch.object(utils, 'is_anaconda_deploy', autospec=True)
    def test_get_boot_option_anaconda_deploy(self, mock_is_anaconda_deploy):
        mock_is_anaconda_deploy.return_value = True
        result = utils.get_boot_option(self.node)
        self.assertEqual("kickstart", result)

    def test_is_anaconda_deploy(self):
        self.node.deploy_interface = 'anaconda'
        result = utils.is_anaconda_deploy(self.node)
        self.assertTrue(result)

    def test_is_anaconda_deploy_false(self):
        result = utils.is_anaconda_deploy(self.node)
        self.assertFalse(result)

    def test_is_software_raid(self):
        self.node.target_raid_config = {
            "logical_disks": [
                {
                    "size_gb": 100,
                    "raid_level": "1",
                    "controller": "software",
                }
            ]
        }
        result = utils.is_software_raid(self.node)
        self.assertTrue(result)

    def test_is_software_raid_false(self):
        self.node.target_raid_config = {}
        result = utils.is_software_raid(self.node)
        self.assertFalse(result)

    @mock.patch.object(image_cache, 'clean_up_caches', autospec=True)
    def test_fetch_images(self, mock_clean_up_caches):

        mock_cache = mock.MagicMock(
            spec_set=['fetch_image', 'master_dir'], master_dir='master_dir')
        utils.fetch_images(None, mock_cache, [('uuid', 'path')])
        mock_clean_up_caches.assert_called_once_with(None, 'master_dir',
                                                     [('uuid', 'path')])
        mock_cache.fetch_image.assert_called_once_with('uuid', 'path',
                                                       ctx=None,
                                                       force_raw=True)

    @mock.patch.object(image_cache, 'clean_up_caches', autospec=True)
    def test_fetch_images_fail(self, mock_clean_up_caches):

        exc = exception.InsufficientDiskSpace(path='a',
                                              required=2,
                                              actual=1)

        mock_cache = mock.MagicMock(
            spec_set=['master_dir'], master_dir='master_dir')
        mock_clean_up_caches.side_effect = [exc]
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.fetch_images,
                          None,
                          mock_cache,
                          [('uuid', 'path')])
        mock_clean_up_caches.assert_called_once_with(None, 'master_dir',
                                                     [('uuid', 'path')])

    @mock.patch('ironic.common.keystone.get_auth', autospec=True)
    @mock.patch.object(utils, '_get_ironic_session', autospec=True)
    @mock.patch('ironic.common.keystone.get_adapter', autospec=True)
    def test_get_ironic_api_url_from_keystone(self, mock_ka, mock_ks,
                                              mock_auth):
        mock_sess = mock.Mock()
        mock_ks.return_value = mock_sess
        fake_api_url = 'http://foo/'
        mock_ka.return_value.get_endpoint.return_value = fake_api_url
        # NOTE(pas-ha) endpoint_override is None by default
        url = utils.get_ironic_api_url()
        # also checking for stripped trailing slash
        self.assertEqual(fake_api_url[:-1], url)
        mock_ka.assert_called_with('service_catalog', session=mock_sess,
                                   auth=mock_auth.return_value)
        mock_ka.return_value.get_endpoint.assert_called_once_with()

    @mock.patch('ironic.common.keystone.get_auth', autospec=True)
    @mock.patch.object(utils, '_get_ironic_session', autospec=True)
    @mock.patch('ironic.common.keystone.get_adapter', autospec=True)
    def test_get_ironic_api_url_fail(self, mock_ka, mock_ks, mock_auth):
        mock_sess = mock.Mock()
        mock_ks.return_value = mock_sess
        mock_ka.return_value.get_endpoint.side_effect = (
            exception.KeystoneFailure())
        self.assertRaises(exception.InvalidParameterValue,
                          utils.get_ironic_api_url)

    @mock.patch('ironic.common.keystone.get_auth', autospec=True)
    @mock.patch.object(utils, '_get_ironic_session', autospec=True)
    @mock.patch('ironic.common.keystone.get_adapter', autospec=True)
    def test_get_ironic_api_url_none(self, mock_ka, mock_ks, mock_auth):
        mock_sess = mock.Mock()
        mock_ks.return_value = mock_sess
        mock_ka.return_value.get_endpoint.return_value = None
        self.assertRaises(exception.InvalidParameterValue,
                          utils.get_ironic_api_url)


class GetSingleNicTestCase(db_base.DbTestCase):

    def setUp(self):
        super(GetSingleNicTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context)

    def test_get_single_nic_with_vif_port_id(self):
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='aa:bb:cc:dd:ee:ff',
            uuid=uuidutils.generate_uuid(),
            internal_info={'tenant_vif_port_id': 'test-vif-A'})
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            address = utils.get_single_nic_with_vif_port_id(task)
            self.assertEqual('aa:bb:cc:dd:ee:ff', address)

    def test_get_single_nic_with_cleaning_vif_port_id(self):
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='aa:bb:cc:dd:ee:ff',
            uuid=uuidutils.generate_uuid(),
            internal_info={'cleaning_vif_port_id': 'test-vif-A'})
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            address = utils.get_single_nic_with_vif_port_id(task)
            self.assertEqual('aa:bb:cc:dd:ee:ff', address)

    def test_get_single_nic_with_provisioning_vif_port_id(self):
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='aa:bb:cc:dd:ee:ff',
            uuid=uuidutils.generate_uuid(),
            internal_info={'provisioning_vif_port_id': 'test-vif-A'})
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            address = utils.get_single_nic_with_vif_port_id(task)
            self.assertEqual('aa:bb:cc:dd:ee:ff', address)


class ParseInstanceInfoCapabilitiesTestCase(tests_base.TestCase):

    def setUp(self):
        super(ParseInstanceInfoCapabilitiesTestCase, self).setUp()
        self.node = obj_utils.get_test_node(self.context,
                                            driver='fake-hardware')

    def test_parse_instance_info_capabilities_string(self):
        self.node.instance_info = {'capabilities': '{"cat": "meow"}'}
        expected_result = {"cat": "meow"}
        result = utils.parse_instance_info_capabilities(self.node)
        self.assertEqual(expected_result, result)

    def test_parse_instance_info_capabilities(self):
        self.node.instance_info = {'capabilities': {"dog": "wuff"}}
        expected_result = {"dog": "wuff"}
        result = utils.parse_instance_info_capabilities(self.node)
        self.assertEqual(expected_result, result)

    def test_parse_instance_info_invalid_type(self):
        self.node.instance_info = {'capabilities': 'not-a-dict'}
        self.assertRaises(exception.InvalidParameterValue,
                          utils.parse_instance_info_capabilities, self.node)

    def test_is_secure_boot_requested_true(self):
        self.node.instance_info = {'capabilities': {"secure_boot": "tRue"}}
        self.assertTrue(utils.is_secure_boot_requested(self.node))

    def test_is_secure_boot_requested_false(self):
        self.node.instance_info = {'capabilities': {"secure_boot": "false"}}
        self.assertFalse(utils.is_secure_boot_requested(self.node))

    def test_is_secure_boot_requested_invalid(self):
        self.node.instance_info = {'capabilities': {"secure_boot": "invalid"}}
        self.assertFalse(utils.is_secure_boot_requested(self.node))

    def test_is_trusted_boot_requested_true(self):
        self.node.instance_info = {'capabilities': {"trusted_boot": "true"}}
        self.assertTrue(utils.is_trusted_boot_requested(self.node))

    def test_is_trusted_boot_requested_false(self):
        self.node.instance_info = {'capabilities': {"trusted_boot": "false"}}
        self.assertFalse(utils.is_trusted_boot_requested(self.node))

    def test_is_trusted_boot_requested_invalid(self):
        self.node.instance_info = {'capabilities': {"trusted_boot": "invalid"}}
        self.assertFalse(utils.is_trusted_boot_requested(self.node))

    def test_validate_boot_mode_capability(self):
        prop = {'capabilities': 'boot_mode:uefi,cap2:value2'}
        self.node.properties = prop

        result = utils.validate_capabilities(self.node)
        self.assertIsNone(result)

    def test_validate_boot_mode_capability_with_exc(self):
        prop = {'capabilities': 'boot_mode:UEFI,cap2:value2'}
        self.node.properties = prop

        self.assertRaises(exception.InvalidParameterValue,
                          utils.validate_capabilities, self.node)

    def test_validate_boot_mode_capability_instance_info(self):
        inst_info = {'capabilities': {"boot_mode": "uefi", "cap2": "value2"}}
        self.node.instance_info = inst_info

        result = utils.validate_capabilities(self.node)
        self.assertIsNone(result)

    def test_validate_boot_mode_capability_instance_info_with_exc(self):
        inst_info = {'capabilities': {"boot_mode": "UEFI", "cap2": "value2"}}
        self.node.instance_info = inst_info

        self.assertRaises(exception.InvalidParameterValue,
                          utils.validate_capabilities, self.node)

    def test_validate_trusted_boot_capability(self):
        properties = {'capabilities': 'trusted_boot:value'}
        self.node.properties = properties
        self.assertRaises(exception.InvalidParameterValue,
                          utils.validate_capabilities, self.node)

    def test_all_supported_capabilities(self):
        self.assertEqual(('local', 'netboot', 'ramdisk', 'kickstart'),
                         utils.SUPPORTED_CAPABILITIES['boot_option'])
        self.assertEqual(('bios', 'uefi'),
                         utils.SUPPORTED_CAPABILITIES['boot_mode'])
        self.assertEqual(('true', 'false'),
                         utils.SUPPORTED_CAPABILITIES['secure_boot'])
        self.assertEqual(('true', 'false'),
                         utils.SUPPORTED_CAPABILITIES['trusted_boot'])

    def test_get_disk_label(self):
        inst_info = {'capabilities': {'disk_label': 'gpt', 'foo': 'bar'}}
        self.node.instance_info = inst_info
        result = utils.get_disk_label(self.node)
        self.assertEqual('gpt', result)

    def test_get_disk_label_nothing_set(self):
        inst_info = {'capabilities': {'cat': 'meows'}}
        self.node.instance_info = inst_info
        result = utils.get_disk_label(self.node)
        self.assertIsNone(result)

    def test_get_disk_label_uefi_mode(self):
        inst_info = {'capabilities': {'cat': 'meows'}}
        properties = {'capabilities': 'boot_mode:uefi'}
        self.node.instance_info = inst_info
        self.node.properties = properties
        result = utils.get_disk_label(self.node)
        self.assertEqual('gpt', result)


class TrySetBootDeviceTestCase(db_base.DbTestCase):

    def setUp(self):
        super(TrySetBootDeviceTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver="fake-hardware")

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    def test_try_set_boot_device_okay(self, node_set_boot_device_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            utils.try_set_boot_device(task, boot_devices.DISK,
                                      persistent=True)
            node_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)

    @mock.patch.object(utils, 'LOG', autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    def test_try_set_boot_device_ipmifailure_uefi(
            self, node_set_boot_device_mock, log_mock):
        self.node.properties = {'capabilities': 'boot_mode:uefi'}
        self.node.save()
        node_set_boot_device_mock.side_effect = exception.IPMIFailure(cmd='a')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            utils.try_set_boot_device(task, boot_devices.DISK,
                                      persistent=True)
            node_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)
            log_mock.warning.assert_called_once_with(mock.ANY, self.node.uuid)

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    def test_try_set_boot_device_ipmifailure_bios(
            self, node_set_boot_device_mock):
        node_set_boot_device_mock.side_effect = exception.IPMIFailure(cmd='a')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IPMIFailure,
                              utils.try_set_boot_device,
                              task, boot_devices.DISK, persistent=True)
            node_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    def test_try_set_boot_device_some_other_exception(
            self, node_set_boot_device_mock):
        exc = exception.IloOperationError(operation="qwe", error="error")
        node_set_boot_device_mock.side_effect = exc
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IloOperationError,
                              utils.try_set_boot_device,
                              task, boot_devices.DISK, persistent=True)
            node_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)


class AgentMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(AgentMethodsTestCase, self).setUp()

        self.clean_steps = {
            'deploy': [
                {'interface': 'deploy',
                 'step': 'erase_devices',
                 'priority': 20},
                {'interface': 'deploy',
                 'step': 'update_firmware',
                 'priority': 30}
            ],
            'raid': [
                {'interface': 'raid',
                 'step': 'create_configuration',
                 'priority': 10}
            ]
        }
        n = {'boot_interface': 'pxe',
             'deploy_interface': 'direct',
             'driver_internal_info': {
                 'agent_cached_clean_steps': self.clean_steps}}
        self.node = obj_utils.create_test_node(self.context, **n)
        self.ports = [obj_utils.create_test_port(self.context,
                                                 node_id=self.node.id)]

    def test_agent_add_clean_params(self):
        cfg.CONF.set_override('shred_random_overwrite_iterations', 2, 'deploy')
        cfg.CONF.set_override('shred_final_overwrite_with_zeros', False,
                              'deploy')
        cfg.CONF.set_override('continue_if_disk_secure_erase_fails', True,
                              'deploy')
        cfg.CONF.set_override('enable_ata_secure_erase', False, 'deploy')
        cfg.CONF.set_override('disk_erasure_concurrency', 8, 'deploy')
        cfg.CONF.set_override('enable_nvme_secure_erase', False, 'deploy')
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            utils.agent_add_clean_params(task)
            self.assertEqual(2, task.node.driver_internal_info[
                'agent_erase_devices_iterations'])
            self.assertIs(False, task.node.driver_internal_info[
                'agent_erase_devices_zeroize'])
            self.assertIs(True, task.node.driver_internal_info[
                'agent_continue_if_secure_erase_failed'])
            self.assertIs(False, task.node.driver_internal_info[
                'agent_enable_ata_secure_erase'])
            self.assertEqual(8, task.node.driver_internal_info[
                'disk_erasure_concurrency'])
            self.assertIs(False, task.node.driver_internal_info[
                'agent_enable_nvme_secure_erase'])

    @mock.patch('ironic.conductor.utils.is_fast_track', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    @mock.patch.object(utils, 'build_agent_options', autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.'
                'add_cleaning_network', autospec=True)
    def _test_prepare_inband_cleaning(
            self, add_cleaning_network_mock,
            build_options_mock, power_mock, prepare_ramdisk_mock,
            is_fast_track_mock, manage_boot=True, fast_track=False):
        build_options_mock.return_value = {'a': 'b'}
        is_fast_track_mock.return_value = fast_track
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertEqual(
                states.CLEANWAIT,
                utils.prepare_inband_cleaning(task, manage_boot=manage_boot))
            add_cleaning_network_mock.assert_called_once_with(
                task.driver.network, task)
            if not fast_track:
                power_mock.assert_called_once_with(task, states.REBOOT)
            else:
                self.assertFalse(power_mock.called)
            self.assertEqual(1, task.node.driver_internal_info[
                             'agent_erase_devices_iterations'])
            self.assertIs(True, task.node.driver_internal_info[
                          'agent_erase_devices_zeroize'])
            if manage_boot:
                prepare_ramdisk_mock.assert_called_once_with(
                    mock.ANY, mock.ANY, {'a': 'b'})
                build_options_mock.assert_called_once_with(task.node)
            else:
                self.assertFalse(prepare_ramdisk_mock.called)
                self.assertFalse(build_options_mock.called)

    def test_prepare_inband_cleaning(self):
        self._test_prepare_inband_cleaning()

    def test_prepare_inband_cleaning_manage_boot_false(self):
        self._test_prepare_inband_cleaning(manage_boot=False)

    def test_prepare_inband_cleaning_fast_track(self):
        self._test_prepare_inband_cleaning(fast_track=True)

    @mock.patch('ironic.conductor.utils.power_on_node_if_needed',
                autospec=True)
    @mock.patch('ironic.conductor.utils.is_fast_track', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    @mock.patch.object(utils, 'build_agent_options', autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.'
                'add_cleaning_network', autospec=True)
    def test_prepare_inband_cleaning_broken_fast_track(
            self, add_cleaning_network_mock,
            build_options_mock, power_mock, prepare_ramdisk_mock,
            is_fast_track_mock, power_on_if_needed_mock):
        build_options_mock.return_value = {'a': 'b'}
        is_fast_track_mock.side_effect = [True, False]
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertEqual(
                states.CLEANWAIT,
                utils.prepare_inband_cleaning(task))
            add_cleaning_network_mock.assert_called_once_with(
                task.driver.network, task)
            power_mock.assert_called_once_with(task, states.REBOOT)
            self.assertEqual(1, task.node.driver_internal_info[
                             'agent_erase_devices_iterations'])
            self.assertIs(True, task.node.driver_internal_info[
                          'agent_erase_devices_zeroize'])
            prepare_ramdisk_mock.assert_called_once_with(
                mock.ANY, mock.ANY, {'a': 'b'})
            build_options_mock.assert_called_once_with(task.node)
            self.assertFalse(power_on_if_needed_mock.called)

    @mock.patch('ironic.conductor.utils.is_fast_track', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.'
                'remove_cleaning_network', autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    def _test_tear_down_inband_cleaning(
            self, power_mock, remove_cleaning_network_mock,
            clean_up_ramdisk_mock, is_fast_track_mock,
            manage_boot=True, fast_track=False, cleaning_error=False):
        is_fast_track_mock.return_value = fast_track
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            if cleaning_error:
                task.node.fault = faults.CLEAN_FAILURE
            utils.tear_down_inband_cleaning(task, manage_boot=manage_boot)
            if not (fast_track or cleaning_error):
                power_mock.assert_called_once_with(task, states.POWER_OFF)
            else:
                self.assertFalse(power_mock.called)
            remove_cleaning_network_mock.assert_called_once_with(
                task.driver.network, task)
            if manage_boot:
                clean_up_ramdisk_mock.assert_called_once_with(
                    task.driver.boot, task)
            else:
                self.assertFalse(clean_up_ramdisk_mock.called)

    def test_tear_down_inband_cleaning(self):
        self._test_tear_down_inband_cleaning(manage_boot=True)

    def test_tear_down_inband_cleaning_manage_boot_false(self):
        self._test_tear_down_inband_cleaning(manage_boot=False)

    def test_tear_down_inband_cleaning_fast_track(self):
        self._test_tear_down_inband_cleaning(fast_track=True)

    def test_tear_down_inband_cleaning_cleaning_error(self):
        self._test_tear_down_inband_cleaning(cleaning_error=True)

    def test_build_agent_options_conf(self):
        self.config(endpoint_override='https://api-url',
                    group='service_catalog')
        options = utils.build_agent_options(self.node)
        self.assertEqual('https://api-url', options['ipa-api-url'])

    @mock.patch.object(utils, '_get_ironic_session', autospec=True)
    def test_build_agent_options_keystone(self, session_mock):
        sess = mock.Mock()
        sess.get_endpoint.return_value = 'https://api-url'
        session_mock.return_value = sess
        options = utils.build_agent_options(self.node)
        self.assertEqual('https://api-url', options['ipa-api-url'])

    def test_direct_deploy_should_convert_raw_image_true(self):
        cfg.CONF.set_override('force_raw_images', True)
        cfg.CONF.set_override('stream_raw_images', True, group='agent')
        internal_info = self.node.driver_internal_info
        internal_info['is_whole_disk_image'] = True
        self.node.driver_internal_info = internal_info
        self.assertTrue(
            utils.direct_deploy_should_convert_raw_image(self.node))

    def test_direct_deploy_should_convert_raw_image_no_force_raw(self):
        cfg.CONF.set_override('force_raw_images', False)
        cfg.CONF.set_override('stream_raw_images', True, group='agent')
        internal_info = self.node.driver_internal_info
        internal_info['is_whole_disk_image'] = True
        self.node.driver_internal_info = internal_info
        self.assertFalse(
            utils.direct_deploy_should_convert_raw_image(self.node))

    def test_direct_deploy_should_convert_raw_image_no_stream(self):
        cfg.CONF.set_override('force_raw_images', True)
        cfg.CONF.set_override('stream_raw_images', False, group='agent')
        internal_info = self.node.driver_internal_info
        internal_info['is_whole_disk_image'] = True
        self.node.driver_internal_info = internal_info
        self.assertFalse(
            utils.direct_deploy_should_convert_raw_image(self.node))

    def test_direct_deploy_should_convert_raw_image_partition(self):
        cfg.CONF.set_override('force_raw_images', True)
        cfg.CONF.set_override('stream_raw_images', True, group='agent')
        internal_info = self.node.driver_internal_info
        internal_info['is_whole_disk_image'] = False
        self.node.driver_internal_info = internal_info
        self.assertTrue(
            utils.direct_deploy_should_convert_raw_image(self.node))


class ValidateImagePropertiesTestCase(db_base.DbTestCase):

    @mock.patch.object(image_service, 'get_image_service', autospec=True)
    def test_validate_image_properties_glance_image(self, image_service_mock):
        node = obj_utils.create_test_node(
            self.context, boot_interface='pxe',
            instance_info=INST_INFO_DICT,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        inst_info = utils.get_image_instance_info(node)
        image_service_mock.return_value.show.return_value = {
            'properties': {'kernel_id': '1111', 'ramdisk_id': '2222'},
        }

        utils.validate_image_properties(self.context, inst_info,
                                        ['kernel_id', 'ramdisk_id'])
        image_service_mock.assert_called_once_with(
            node.instance_info['image_source'], context=self.context
        )

    @mock.patch.object(image_service, 'get_image_service', autospec=True)
    def test_validate_image_properties_glance_image_missing_prop(
            self, image_service_mock):
        node = obj_utils.create_test_node(
            self.context, boot_interface='pxe',
            instance_info=INST_INFO_DICT,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        inst_info = utils.get_image_instance_info(node)
        image_service_mock.return_value.show.return_value = {
            'properties': {'kernel_id': '1111'},
        }

        self.assertRaises(exception.MissingParameterValue,
                          utils.validate_image_properties,
                          self.context, inst_info, ['kernel_id', 'ramdisk_id'])
        image_service_mock.assert_called_once_with(
            node.instance_info['image_source'], context=self.context
        )

    @mock.patch.object(image_service, 'get_image_service', autospec=True)
    def test_validate_image_properties_glance_image_not_authorized(
            self, image_service_mock):
        inst_info = {'image_source': 'uuid'}
        show_mock = image_service_mock.return_value.show
        show_mock.side_effect = exception.ImageNotAuthorized(image_id='uuid')
        self.assertRaises(exception.InvalidParameterValue,
                          utils.validate_image_properties, self.context,
                          inst_info, [])

    @mock.patch.object(image_service, 'get_image_service', autospec=True)
    def test_validate_image_properties_glance_image_not_found(
            self, image_service_mock):
        inst_info = {'image_source': 'uuid'}
        show_mock = image_service_mock.return_value.show
        show_mock.side_effect = exception.ImageNotFound(image_id='uuid')
        self.assertRaises(exception.InvalidParameterValue,
                          utils.validate_image_properties, self.context,
                          inst_info, [])

    def test_validate_image_properties_invalid_image_href(self):
        inst_info = {'image_source': 'emule://uuid'}
        self.assertRaises(exception.InvalidParameterValue,
                          utils.validate_image_properties, self.context,
                          inst_info, [])

    @mock.patch.object(image_service.HttpImageService, 'show', autospec=True)
    def test_validate_image_properties_nonglance_image(
            self, image_service_show_mock):
        instance_info = {
            'image_source': 'http://ubuntu',
            'kernel': 'kernel_uuid',
            'ramdisk': 'file://initrd',
            'root_gb': 100,
        }
        image_service_show_mock.return_value = {'size': 1, 'properties': {}}
        node = obj_utils.create_test_node(
            self.context, boot_interface='pxe',
            instance_info=instance_info,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        inst_info = utils.get_image_instance_info(node)
        utils.validate_image_properties(self.context, inst_info,
                                        ['kernel', 'ramdisk'])
        image_service_show_mock.assert_called_once_with(
            mock.ANY, instance_info['image_source'])

    @mock.patch.object(image_service.HttpImageService, 'show', autospec=True)
    def test_validate_image_properties_nonglance_image_validation_fail(
            self, img_service_show_mock):
        instance_info = {
            'image_source': 'http://ubuntu',
            'kernel': 'kernel_uuid',
            'ramdisk': 'file://initrd',
            'root_gb': 100,
        }
        img_service_show_mock.side_effect = exception.ImageRefValidationFailed(
            image_href='http://ubuntu', reason='HTTPError')
        node = obj_utils.create_test_node(
            self.context, boot_interface='pxe',
            instance_info=instance_info,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        inst_info = utils.get_image_instance_info(node)
        expected_error = ('Validation of image href http://ubuntu '
                          'failed, reason: HTTPError')
        error = self.assertRaises(exception.InvalidParameterValue,
                                  utils.validate_image_properties,
                                  self.context,
                                  inst_info, ['kernel', 'ramdisk'])
        self.assertEqual(expected_error, str(error))

    def test_validate_image_properties_boot_iso_conflict(self):
        instance_info = {
            'image_source': 'http://ubuntu',
            'boot_iso': 'http://ubuntu.iso',
        }
        expected_error = ("An 'image_source' and 'boot_iso' "
                          "parameter may not be specified at "
                          "the same time.")
        error = self.assertRaises(exception.InvalidParameterValue,
                                  utils.validate_image_properties,
                                  self.context,
                                  instance_info, [])
        self.assertEqual(expected_error, str(error))


class ValidateParametersTestCase(db_base.DbTestCase):

    def _test__get_img_instance_info(
            self, instance_info=INST_INFO_DICT,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT):
        # make sure we get back the expected things
        node = obj_utils.create_test_node(
            self.context,
            boot_interface='pxe',
            instance_info=instance_info,
            driver_info=driver_info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )

        info = utils.get_image_instance_info(node)
        self.assertIsNotNone(info['image_source'])
        return info

    def test__get_img_instance_info_good(self):
        self._test__get_img_instance_info()

    def test__get_img_instance_info_good_non_glance_image(self):
        instance_info = INST_INFO_DICT.copy()
        instance_info['image_source'] = 'http://image'
        instance_info['kernel'] = 'http://kernel'
        instance_info['ramdisk'] = 'http://ramdisk'

        info = self._test__get_img_instance_info(instance_info=instance_info)

        self.assertIsNotNone(info['ramdisk'])
        self.assertIsNotNone(info['kernel'])

    def test__get_img_instance_info_non_glance_image_missing_kernel(self):
        instance_info = INST_INFO_DICT.copy()
        instance_info['image_source'] = 'http://image'
        instance_info['ramdisk'] = 'http://ramdisk'

        self.assertRaises(
            exception.MissingParameterValue,
            self._test__get_img_instance_info,
            instance_info=instance_info)

    def test__get_img_instance_info_non_glance_image_missing_ramdisk(self):
        instance_info = INST_INFO_DICT.copy()
        instance_info['image_source'] = 'http://image'
        instance_info['kernel'] = 'http://kernel'

        self.assertRaises(
            exception.MissingParameterValue,
            self._test__get_img_instance_info,
            instance_info=instance_info)

    def test__get_img_instance_info_missing_image_source(self):
        instance_info = INST_INFO_DICT.copy()
        del instance_info['image_source']

        self.assertRaises(
            exception.MissingParameterValue,
            self._test__get_img_instance_info,
            instance_info=instance_info)

    def test__get_img_instance_info_whole_disk_image(self):
        driver_internal_info = DRV_INTERNAL_INFO_DICT.copy()
        driver_internal_info['is_whole_disk_image'] = True

        self._test__get_img_instance_info(
            driver_internal_info=driver_internal_info)


class InstanceInfoTestCase(db_base.DbTestCase):

    def test_parse_instance_info_good(self):
        # make sure we get back the expected things
        node = obj_utils.create_test_node(
            self.context, boot_interface='pxe',
            instance_info=INST_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT
        )
        info = utils.parse_instance_info(node)
        self.assertIsNotNone(info['image_source'])
        self.assertIsNotNone(info['root_gb'])
        self.assertEqual(0, info['ephemeral_gb'])
        self.assertIsNone(info['configdrive'])

    def test_parse_instance_info_missing_instance_source(self):
        # make sure error is raised when info is missing
        info = dict(INST_INFO_DICT)
        del info['image_source']
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.MissingParameterValue,
                          utils.parse_instance_info,
                          node)

    def test_parse_instance_info_missing_root_gb(self):
        # make sure error is raised when info is missing
        info = dict(INST_INFO_DICT)
        del info['root_gb']

        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.MissingParameterValue,
                          utils.parse_instance_info,
                          node)

    def test_parse_instance_info_invalid_root_gb(self):
        info = dict(INST_INFO_DICT)
        info['root_gb'] = 'foobar'
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          utils.parse_instance_info,
                          node)

    def test_parse_instance_info_valid_ephemeral_gb(self):
        ephemeral_gb = 10
        ephemeral_mb = 1024 * ephemeral_gb
        ephemeral_fmt = 'test-fmt'
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = ephemeral_gb
        info['ephemeral_format'] = ephemeral_fmt
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        data = utils.parse_instance_info(node)
        self.assertEqual(ephemeral_mb, data['ephemeral_mb'])
        self.assertEqual(ephemeral_fmt, data['ephemeral_format'])

    def test_parse_instance_info_unicode_swap_mb(self):
        swap_mb = u'10'
        swap_mb_int = 10
        info = dict(INST_INFO_DICT)
        info['swap_mb'] = swap_mb
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        data = utils.parse_instance_info(node)
        self.assertEqual(swap_mb_int, data['swap_mb'])

    def test_parse_instance_info_invalid_ephemeral_gb(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 'foobar'
        info['ephemeral_format'] = 'exttest'

        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          utils.parse_instance_info,
                          node)

    def test_parse_instance_info_valid_ephemeral_missing_format(self):
        ephemeral_gb = 10
        ephemeral_fmt = 'test-fmt'
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = ephemeral_gb
        info['ephemeral_format'] = None
        self.config(default_ephemeral_format=ephemeral_fmt, group='pxe')
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        instance_info = utils.parse_instance_info(node)
        self.assertEqual(ephemeral_fmt, instance_info['ephemeral_format'])

    def test_parse_instance_info_valid_preserve_ephemeral_true(self):
        info = dict(INST_INFO_DICT)
        for opt in ['true', 'TRUE', 'True', 't',
                    'on', 'yes', 'y', '1']:
            info['preserve_ephemeral'] = opt

            node = obj_utils.create_test_node(
                self.context, uuid=uuidutils.generate_uuid(),
                instance_info=info,
                driver_internal_info=DRV_INTERNAL_INFO_DICT,
            )
            data = utils.parse_instance_info(node)
            self.assertTrue(data['preserve_ephemeral'])

    def test_parse_instance_info_valid_preserve_ephemeral_false(self):
        info = dict(INST_INFO_DICT)
        for opt in ['false', 'FALSE', 'False', 'f',
                    'off', 'no', 'n', '0']:
            info['preserve_ephemeral'] = opt
            node = obj_utils.create_test_node(
                self.context, uuid=uuidutils.generate_uuid(),
                instance_info=info,
                driver_internal_info=DRV_INTERNAL_INFO_DICT,
            )
            data = utils.parse_instance_info(node)
            self.assertFalse(data['preserve_ephemeral'])

    def test_parse_instance_info_invalid_preserve_ephemeral(self):
        info = dict(INST_INFO_DICT)
        info['preserve_ephemeral'] = 'foobar'
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          utils.parse_instance_info,
                          node)

    def test_parse_instance_info_invalid_ephemeral_disk(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 10
        info['swap_mb'] = 0
        info['root_gb'] = 20
        info['preserve_ephemeral'] = True
        drv_internal_dict = {'instance': {'ephemeral_gb': 9,
                                          'swap_mb': 0,
                                          'root_gb': 20}}
        drv_internal_dict.update(DRV_INTERNAL_INFO_DICT)
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=drv_internal_dict,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          utils.parse_instance_info,
                          node)

    def test__check_disk_layout_unchanged_fails(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 10
        info['swap_mb'] = 0
        info['root_gb'] = 20
        info['preserve_ephemeral'] = True
        drv_internal_dict = {'instance': {'ephemeral_gb': 20,
                                          'swap_mb': 0,
                                          'root_gb': 20}}
        drv_internal_dict.update(DRV_INTERNAL_INFO_DICT)
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=drv_internal_dict,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          utils._check_disk_layout_unchanged,
                          node, info)

    def test__check_disk_layout_unchanged(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 10
        info['swap_mb'] = 0
        info['root_gb'] = 20
        info['preserve_ephemeral'] = True
        drv_internal_dict = {'instance': {'ephemeral_gb': 10,
                                          'swap_mb': 0,
                                          'root_gb': 20}}
        drv_internal_dict.update(DRV_INTERNAL_INFO_DICT)
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=drv_internal_dict,
        )
        self.assertIsNone(utils._check_disk_layout_unchanged(node,
                                                             info))

    def test_parse_instance_info_configdrive(self):
        info = dict(INST_INFO_DICT)
        info['configdrive'] = 'http://1.2.3.4/cd'
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        instance_info = utils.parse_instance_info(node)
        self.assertEqual('http://1.2.3.4/cd', instance_info['configdrive'])

    def test_parse_instance_info_nonglance_image(self):
        info = INST_INFO_DICT.copy()
        info['image_source'] = 'file:///image.qcow2'
        info['kernel'] = 'file:///image.vmlinuz'
        info['ramdisk'] = 'file:///image.initrd'
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        utils.parse_instance_info(node)

    def test_parse_instance_info_nonglance_image_no_kernel(self):
        info = INST_INFO_DICT.copy()
        info['image_source'] = 'file:///image.qcow2'
        info['ramdisk'] = 'file:///image.initrd'
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.MissingParameterValue,
                          utils.parse_instance_info, node)

    def test_parse_instance_info_whole_disk_image(self):
        driver_internal_info = dict(DRV_INTERNAL_INFO_DICT)
        driver_internal_info['is_whole_disk_image'] = True
        node = obj_utils.create_test_node(
            self.context, instance_info=INST_INFO_DICT,
            driver_internal_info=driver_internal_info,
        )
        instance_info = utils.parse_instance_info(node)
        self.assertIsNotNone(instance_info['image_source'])
        self.assertNotIn('root_mb', instance_info)
        self.assertNotIn('ephemeral_mb', instance_info)
        self.assertNotIn('swap_mb', instance_info)
        self.assertIsNone(instance_info['configdrive'])

    def test_parse_instance_info_whole_disk_image_missing_root(self):
        driver_internal_info = dict(DRV_INTERNAL_INFO_DICT)
        driver_internal_info['is_whole_disk_image'] = True
        info = dict(INST_INFO_DICT)
        del info['root_gb']
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=driver_internal_info
        )

        instance_info = utils.parse_instance_info(node)
        self.assertIsNotNone(instance_info['image_source'])
        self.assertNotIn('root_mb', instance_info)
        self.assertNotIn('ephemeral_mb', instance_info)
        self.assertNotIn('swap_mb', instance_info)


class TestBuildInstanceInfoForDeploy(db_base.DbTestCase):
    def setUp(self):
        super(TestBuildInstanceInfoForDeploy, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               boot_interface='pxe',
                                               deploy_interface='direct')
        cfg.CONF.set_override('image_download_source', 'swift', group='agent')

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    @mock.patch.object(image_service, 'GlanceImageService', autospec=True)
    def test_build_instance_info_for_deploy_glance_image(self, glance_mock,
                                                         validate_mock):
        i_info = self.node.instance_info
        i_info['image_source'] = '733d1c44-a2ea-414b-aca7-69decf20d810'
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = True
        self.node.driver_internal_info = driver_internal_info
        self.node.instance_info = i_info
        self.node.save()

        image_info = {'checksum': 'aa', 'disk_format': 'qcow2',
                      'os_hash_algo': 'sha512', 'os_hash_value': 'fake-sha512',
                      'container_format': 'bare', 'properties': {}}
        glance_mock.return_value.show = mock.MagicMock(spec_set=[],
                                                       return_value=image_info)
        glance_mock.return_value.swift_temp_url.return_value = (
            'http://temp-url')
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            utils.build_instance_info_for_deploy(task)

            glance_mock.assert_called_once_with(context=task.context)
            glance_mock.return_value.show.assert_called_once_with(
                self.node.instance_info['image_source'])
            glance_mock.return_value.swift_temp_url.assert_called_once_with(
                image_info)
            validate_mock.assert_called_once_with(mock.ANY, 'http://temp-url',
                                                  secret=True)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    @mock.patch.object(utils, 'parse_instance_info', autospec=True)
    @mock.patch.object(image_service, 'GlanceImageService', autospec=True)
    def test_build_instance_info_for_deploy_glance_partition_image(
            self, glance_mock, parse_instance_info_mock, validate_mock):
        i_info = {}
        i_info['image_source'] = '733d1c44-a2ea-414b-aca7-69decf20d810'
        i_info['kernel'] = '13ce5a56-1de3-4916-b8b2-be778645d003'
        i_info['ramdisk'] = 'a5a370a8-1b39-433f-be63-2c7d708e4b4e'
        i_info['root_gb'] = 5
        i_info['swap_mb'] = 4
        i_info['ephemeral_gb'] = 0
        i_info['ephemeral_format'] = None
        i_info['configdrive'] = 'configdrive'
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = False
        self.node.driver_internal_info = driver_internal_info
        self.node.instance_info = i_info
        self.node.save()

        image_info = {'checksum': 'aa', 'disk_format': 'qcow2',
                      'os_hash_algo': 'sha512', 'os_hash_value': 'fake-sha512',
                      'container_format': 'bare',
                      'properties': {'kernel_id': 'kernel',
                                     'ramdisk_id': 'ramdisk'}}
        glance_mock.return_value.show = mock.MagicMock(spec_set=[],
                                                       return_value=image_info)
        glance_obj_mock = glance_mock.return_value
        glance_obj_mock.swift_temp_url.return_value = 'http://temp-url'
        parse_instance_info_mock.return_value = {'swap_mb': 4}
        image_source = '733d1c44-a2ea-414b-aca7-69decf20d810'
        expected_i_info = {'root_gb': 5,
                           'swap_mb': 4,
                           'ephemeral_gb': 0,
                           'ephemeral_format': None,
                           'configdrive': 'configdrive',
                           'image_source': image_source,
                           'image_url': 'http://temp-url',
                           'kernel': 'kernel',
                           'ramdisk': 'ramdisk',
                           'image_type': 'partition',
                           'image_tags': [],
                           'image_properties': {'kernel_id': 'kernel',
                                                'ramdisk_id': 'ramdisk'},
                           'image_checksum': 'aa',
                           'image_os_hash_algo': 'sha512',
                           'image_os_hash_value': 'fake-sha512',
                           'image_container_format': 'bare',
                           'image_disk_format': 'qcow2'}
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            info = utils.build_instance_info_for_deploy(task)

            glance_mock.assert_called_once_with(context=task.context)
            glance_mock.return_value.show.assert_called_once_with(
                self.node.instance_info['image_source'])
            glance_mock.return_value.swift_temp_url.assert_called_once_with(
                image_info)
            validate_mock.assert_called_once_with(
                mock.ANY, 'http://temp-url', secret=True)
            image_type = task.node.instance_info['image_type']
            self.assertEqual('partition', image_type)
            self.assertEqual('kernel', info['kernel'])
            self.assertEqual('ramdisk', info['ramdisk'])
            self.assertEqual(expected_i_info, info)
            parse_instance_info_mock.assert_called_once_with(task.node)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    def test_build_instance_info_for_deploy_nonglance_image(
            self, validate_href_mock):
        i_info = self.node.instance_info
        driver_internal_info = self.node.driver_internal_info
        i_info['image_source'] = 'http://image-ref'
        i_info['image_checksum'] = 'aa'
        i_info['root_gb'] = 10
        i_info['image_checksum'] = 'aa'
        driver_internal_info['is_whole_disk_image'] = True
        self.node.instance_info = i_info
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            info = utils.build_instance_info_for_deploy(task)

            self.assertEqual(self.node.instance_info['image_source'],
                             info['image_url'])
            validate_href_mock.assert_called_once_with(
                mock.ANY, 'http://image-ref', False)

    @mock.patch.object(utils, 'parse_instance_info', autospec=True)
    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    def test_build_instance_info_for_deploy_nonglance_partition_image(
            self, validate_href_mock, parse_instance_info_mock):
        i_info = {}
        driver_internal_info = self.node.driver_internal_info
        i_info['image_source'] = 'http://image-ref'
        i_info['kernel'] = 'http://kernel-ref'
        i_info['ramdisk'] = 'http://ramdisk-ref'
        i_info['image_checksum'] = 'aa'
        i_info['root_gb'] = 10
        i_info['configdrive'] = 'configdrive'
        driver_internal_info['is_whole_disk_image'] = False
        self.node.instance_info = i_info
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        validate_href_mock.side_effect = ['http://image-ref',
                                          'http://kernel-ref',
                                          'http://ramdisk-ref']
        parse_instance_info_mock.return_value = {'swap_mb': 5}
        expected_i_info = {'image_source': 'http://image-ref',
                           'image_url': 'http://image-ref',
                           'image_type': 'partition',
                           'kernel': 'http://kernel-ref',
                           'ramdisk': 'http://ramdisk-ref',
                           'image_checksum': 'aa',
                           'root_gb': 10,
                           'swap_mb': 5,
                           'configdrive': 'configdrive'}
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            info = utils.build_instance_info_for_deploy(task)

            self.assertEqual(self.node.instance_info['image_source'],
                             info['image_url'])
            validate_href_mock.assert_called_once_with(
                mock.ANY, 'http://image-ref', False)
            self.assertEqual('partition', info['image_type'])
            self.assertEqual(expected_i_info, info)
            parse_instance_info_mock.assert_called_once_with(task.node)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    def test_build_instance_info_for_deploy_image_not_found(
            self, validate_href_mock):
        validate_href_mock.side_effect = exception.ImageRefValidationFailed(
            image_href='http://img.qcow2', reason='fail')
        i_info = self.node.instance_info
        i_info['image_source'] = 'http://img.qcow2'
        i_info['image_checksum'] = 'aa'
        self.node.instance_info = i_info
        self.node.save()

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            self.assertRaises(exception.ImageRefValidationFailed,
                              utils.build_instance_info_for_deploy, task)


class TestBuildInstanceInfoForHttpProvisioning(db_base.DbTestCase):
    def setUp(self):
        super(TestBuildInstanceInfoForHttpProvisioning, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               boot_interface='pxe',
                                               deploy_interface='direct')
        i_info = self.node.instance_info
        i_info['image_source'] = '733d1c44-a2ea-414b-aca7-69decf20d810'
        i_info['root_gb'] = 100
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = True
        self.node.driver_internal_info = driver_internal_info
        self.node.instance_info = i_info
        self.node.save()

        self.checksum_mock = self.useFixture(fixtures.MockPatchObject(
            fileutils, 'compute_file_checksum')).mock
        self.checksum_mock.return_value = 'fake-checksum'
        self.cache_image_mock = self.useFixture(fixtures.MockPatchObject(
            utils, 'cache_instance_image', autospec=True)).mock
        self.fake_path = '/var/lib/ironic/images/{}/disk'.format(
            self.node.uuid)
        self.cache_image_mock.return_value = (
            '733d1c44-a2ea-414b-aca7-69decf20d810',
            self.fake_path)
        self.ensure_tree_mock = self.useFixture(fixtures.MockPatchObject(
            utils.fileutils, 'ensure_tree', autospec=True)).mock
        self.create_link_mock = self.useFixture(fixtures.MockPatchObject(
            common_utils, 'create_link_without_raise', autospec=True)).mock

        cfg.CONF.set_override('http_url', 'http://172.172.24.10:8080',
                              group='deploy')
        cfg.CONF.set_override('image_download_source', 'http', group='agent')

        self.expected_url = '/'.join([cfg.CONF.deploy.http_url,
                                     cfg.CONF.deploy.http_image_subdir,
                                     self.node.uuid])
        self.image_info = {'checksum': 'aa', 'disk_format': 'qcow2',
                           'os_hash_algo': 'sha512',
                           'os_hash_value': 'fake-sha512',
                           'container_format': 'bare', 'properties': {}}

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    @mock.patch.object(image_service, 'GlanceImageService', autospec=True)
    def _test_build_instance_info(self, glance_mock, validate_mock,
                                  image_info={}, expect_raw=False):
        glance_mock.return_value.show = mock.MagicMock(spec_set=[],
                                                       return_value=image_info)
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            instance_info = utils.build_instance_info_for_deploy(task)

            glance_mock.assert_called_once_with(context=task.context)
            glance_mock.return_value.show.assert_called_once_with(
                self.node.instance_info['image_source'])
            self.cache_image_mock.assert_called_once_with(task.context,
                                                          task.node,
                                                          force_raw=expect_raw)
            symlink_dir = utils._get_http_image_symlink_dir_path()
            symlink_file = utils._get_http_image_symlink_file_path(
                self.node.uuid)
            image_path = utils._get_image_file_path(self.node.uuid)
            self.ensure_tree_mock.assert_called_once_with(symlink_dir)
            self.create_link_mock.assert_called_once_with(image_path,
                                                          symlink_file)
            validate_mock.assert_called_once_with(mock.ANY, self.expected_url,
                                                  secret=False)
            return image_path, instance_info

    def test_build_instance_info_no_force_raw(self):
        cfg.CONF.set_override('force_raw_images', False)
        _, instance_info = self._test_build_instance_info(
            image_info=self.image_info, expect_raw=False)

        self.assertEqual(instance_info['image_checksum'], 'aa')
        self.assertEqual(instance_info['image_disk_format'], 'qcow2')
        self.assertEqual(instance_info['image_os_hash_algo'], 'sha512')
        self.assertEqual(instance_info['image_os_hash_value'],
                         'fake-sha512')
        self.checksum_mock.assert_not_called()

    def test_build_instance_info_force_raw(self):
        cfg.CONF.set_override('force_raw_images', True)
        image_path, instance_info = self._test_build_instance_info(
            image_info=self.image_info, expect_raw=True)

        self.assertIsNone(instance_info['image_checksum'])
        self.assertEqual(instance_info['image_disk_format'], 'raw')
        calls = [mock.call(image_path, algorithm='sha512')]
        self.checksum_mock.assert_has_calls(calls)

    def test_build_instance_info_force_raw_drops_md5(self):
        cfg.CONF.set_override('force_raw_images', True)
        self.image_info['os_hash_algo'] = 'md5'
        image_path, instance_info = self._test_build_instance_info(
            image_info=self.image_info, expect_raw=True)

        self.assertIsNone(instance_info['image_checksum'])
        self.assertEqual(instance_info['image_disk_format'], 'raw')
        calls = [mock.call(image_path, algorithm='sha256')]
        self.checksum_mock.assert_has_calls(calls)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    def test_build_instance_info_file_image(self, validate_href_mock):
        i_info = self.node.instance_info
        driver_internal_info = self.node.driver_internal_info
        i_info['image_source'] = 'file://image-ref'
        i_info['image_checksum'] = 'aa'
        i_info['root_gb'] = 10
        i_info['image_checksum'] = 'aa'
        driver_internal_info['is_whole_disk_image'] = True
        self.node.instance_info = i_info
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        expected_url = (
            'http://172.172.24.10:8080/agent_images/%s' % self.node.uuid)

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            info = utils.build_instance_info_for_deploy(task)

            self.assertEqual(expected_url, info['image_url'])
            self.assertEqual('sha256', info['image_os_hash_algo'])
            self.assertEqual('fake-checksum', info['image_os_hash_value'])
            self.cache_image_mock.assert_called_once_with(
                task.context, task.node, force_raw=True)
            self.checksum_mock.assert_called_once_with(
                self.fake_path, algorithm='sha256')
            validate_href_mock.assert_called_once_with(
                mock.ANY, expected_url, False)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    def test_build_instance_info_local_image(self, validate_href_mock):
        cfg.CONF.set_override('image_download_source', 'local', group='agent')
        i_info = self.node.instance_info
        driver_internal_info = self.node.driver_internal_info
        i_info['image_source'] = 'http://image-ref'
        i_info['image_checksum'] = 'aa'
        i_info['root_gb'] = 10
        i_info['image_checksum'] = 'aa'
        driver_internal_info['is_whole_disk_image'] = True
        self.node.instance_info = i_info
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        expected_url = (
            'http://172.172.24.10:8080/agent_images/%s' % self.node.uuid)

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            info = utils.build_instance_info_for_deploy(task)

            self.assertEqual(expected_url, info['image_url'])
            self.assertEqual('sha256', info['image_os_hash_algo'])
            self.assertEqual('fake-checksum', info['image_os_hash_value'])
            self.cache_image_mock.assert_called_once_with(
                task.context, task.node, force_raw=True)
            self.checksum_mock.assert_called_once_with(
                self.fake_path, algorithm='sha256')
            validate_href_mock.assert_called_once_with(
                mock.ANY, expected_url, False)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    def test_build_instance_info_local_image_via_iinfo(self,
                                                       validate_href_mock):
        cfg.CONF.set_override('image_download_source', 'http', group='agent')
        i_info = self.node.instance_info
        driver_internal_info = self.node.driver_internal_info
        i_info['image_source'] = 'http://image-ref'
        i_info['image_checksum'] = 'aa'
        i_info['root_gb'] = 10
        i_info['image_checksum'] = 'aa'
        i_info['image_download_source'] = 'local'
        driver_internal_info['is_whole_disk_image'] = True
        self.node.instance_info = i_info
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        expected_url = (
            'http://172.172.24.10:8080/agent_images/%s' % self.node.uuid)

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            info = utils.build_instance_info_for_deploy(task)

            self.assertEqual(expected_url, info['image_url'])
            self.assertEqual('sha256', info['image_os_hash_algo'])
            self.assertEqual('fake-checksum', info['image_os_hash_value'])
            self.cache_image_mock.assert_called_once_with(
                task.context, task.node, force_raw=True)
            self.checksum_mock.assert_called_once_with(
                self.fake_path, algorithm='sha256')
            validate_href_mock.assert_called_once_with(
                mock.ANY, expected_url, False)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    def test_build_instance_info_local_image_via_dinfo(self,
                                                       validate_href_mock):
        cfg.CONF.set_override('image_download_source', 'http', group='agent')
        i_info = self.node.instance_info
        d_info = self.node.driver_info
        driver_internal_info = self.node.driver_internal_info
        i_info['image_source'] = 'http://image-ref'
        i_info['image_checksum'] = 'aa'
        i_info['root_gb'] = 10
        i_info['image_checksum'] = 'aa'
        d_info['image_download_source'] = 'local'
        driver_internal_info['is_whole_disk_image'] = True
        self.node.instance_info = i_info
        self.node.driver_info = d_info
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        expected_url = (
            'http://172.172.24.10:8080/agent_images/%s' % self.node.uuid)

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            info = utils.build_instance_info_for_deploy(task)

            self.assertEqual(expected_url, info['image_url'])
            self.assertEqual('sha256', info['image_os_hash_algo'])
            self.assertEqual('fake-checksum', info['image_os_hash_value'])
            self.cache_image_mock.assert_called_once_with(
                task.context, task.node, force_raw=True)
            self.checksum_mock.assert_called_once_with(
                self.fake_path, algorithm='sha256')
            validate_href_mock.assert_called_once_with(
                mock.ANY, expected_url, False)


class TestStorageInterfaceUtils(db_base.DbTestCase):
    def setUp(self):
        super(TestStorageInterfaceUtils, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware')
        self.config(enabled_storage_interfaces=['noop', 'fake', 'cinder'])

    def test_check_interface_capability(self):
        class fake_driver(object):
            capabilities = ['foo', 'bar']

        self.assertTrue(utils.check_interface_capability(fake_driver, 'foo'))
        self.assertFalse(utils.check_interface_capability(fake_driver, 'baz'))

    def test_get_remote_boot_volume(self):
        obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=1, volume_id='4321')
        obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234', uuid=uuidutils.generate_uuid())
        self.node.storage_interface = 'cinder'
        self.node.save()

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            volume = utils.get_remote_boot_volume(task)
            self.assertEqual('1234', volume['volume_id'])

    def test_get_remote_boot_volume_none(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertIsNone(utils.get_remote_boot_volume(task))
        obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=1, volume_id='4321')
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertIsNone(utils.get_remote_boot_volume(task))

    @mock.patch.object(fake.FakeBoot, 'capabilities',
                       ['iscsi_volume_boot'], create=True)
    @mock.patch.object(fake.FakeDeploy, 'capabilities',
                       ['iscsi_volume_deploy'], create=True)
    @mock.patch.object(cinder.CinderStorage, 'should_write_image',
                       autospec=True)
    def test_populate_storage_driver_internal_info_iscsi(self,
                                                         mock_should_write):
        mock_should_write.return_value = True
        vol_uuid = uuidutils.generate_uuid()
        obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234', uuid=vol_uuid)
        # NOTE(TheJulia): Since the default for the storage_interface
        # is a noop interface, we need to define another driver that
        # can be loaded by driver_manager in order to create the task
        # to test this method.
        self.node.storage_interface = "cinder"
        self.node.save()

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            driver_utils.add_node_capability(task,
                                             'iscsi_boot',
                                             'True')
            utils.populate_storage_driver_internal_info(task)
            self.assertEqual(
                vol_uuid,
                task.node.driver_internal_info.get('boot_from_volume', None))
            self.assertEqual(
                vol_uuid,
                task.node.driver_internal_info.get('boot_from_volume_deploy',
                                                   None))

    @mock.patch.object(fake.FakeBoot, 'capabilities',
                       ['fibre_channel_volume_boot'], create=True)
    @mock.patch.object(fake.FakeDeploy, 'capabilities',
                       ['fibre_channel_volume_deploy'], create=True)
    @mock.patch.object(cinder.CinderStorage, 'should_write_image',
                       autospec=True)
    def test_populate_storage_driver_internal_info_fc(self,
                                                      mock_should_write):
        mock_should_write.return_value = True
        self.node.storage_interface = "cinder"
        self.node.save()

        vol_uuid = uuidutils.generate_uuid()
        obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='fibre_channel',
            boot_index=0, volume_id='1234', uuid=vol_uuid)
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            driver_utils.add_node_capability(task,
                                             'fibre_channel_boot',
                                             'True')
            utils.populate_storage_driver_internal_info(task)
            self.assertEqual(
                vol_uuid,
                task.node.driver_internal_info.get('boot_from_volume', None))
            self.assertEqual(
                vol_uuid,
                task.node.driver_internal_info.get('boot_from_volume_deploy',
                                                   None))

    @mock.patch.object(fake.FakeBoot, 'capabilities',
                       ['fibre_channel_volume_boot'], create=True)
    @mock.patch.object(fake.FakeDeploy, 'capabilities',
                       ['fibre_channel_volume_deploy'], create=True)
    def test_populate_storage_driver_internal_info_error(self):
        obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234')

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertRaises(exception.StorageError,
                              utils.populate_storage_driver_internal_info,
                              task)

    def test_tear_down_storage_configuration(self):
        vol_uuid = uuidutils.generate_uuid()
        obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234', uuid=vol_uuid)
        d_i_info = self.node.driver_internal_info
        d_i_info['boot_from_volume'] = vol_uuid
        d_i_info['boot_from_volume_deploy'] = vol_uuid
        self.node.driver_internal_info = d_i_info
        self.node.save()

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            node = task.node

            self.assertEqual(1, len(task.volume_targets))
            self.assertEqual(
                vol_uuid,
                node.driver_internal_info.get('boot_from_volume'))
            self.assertEqual(
                vol_uuid,
                node.driver_internal_info.get('boot_from_volume_deploy'))

            utils.tear_down_storage_configuration(task)

            node.refresh()
            self.assertIsNone(
                node.driver_internal_info.get('boot_from_volume'))
            self.assertIsNone(
                node.driver_internal_info.get('boot_from_volume_deploy'))
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertEqual(0, len(task.volume_targets))

    def test_is_iscsi_boot(self):
        vol_id = uuidutils.generate_uuid()
        obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234', uuid=vol_id)
        self.node.driver_internal_info = {'boot_from_volume': vol_id}
        self.node.save()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertTrue(utils.is_iscsi_boot(task))

    def test_is_iscsi_boot_exception(self):
        self.node.driver_internal_info = {
            'boot_from_volume': uuidutils.generate_uuid()}
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertFalse(utils.is_iscsi_boot(task))

    def test_is_iscsi_boot_false(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertFalse(utils.is_iscsi_boot(task))

    def test_is_iscsi_boot_false_fc_target(self):
        vol_id = uuidutils.generate_uuid()
        obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='fibre_channel',
            boot_index=0, volume_id='3214', uuid=vol_id)
        self.node.driver_internal_info.update({'boot_from_volume': vol_id})
        self.node.save()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertFalse(utils.is_iscsi_boot(task))


class InstanceImageCacheTestCase(db_base.DbTestCase):
    @mock.patch.object(fileutils, 'ensure_tree', autospec=True)
    def test_with_master_path(self, mock_ensure_tree):
        self.config(instance_master_path='/fake/path', group='pxe')
        self.config(image_cache_size=500, group='pxe')
        self.config(image_cache_ttl=30, group='pxe')

        cache = utils.InstanceImageCache()

        mock_ensure_tree.assert_called_once_with('/fake/path')
        self.assertEqual(500 * 1024 * 1024, cache._cache_size)
        self.assertEqual(30 * 60, cache._cache_ttl)

    @mock.patch.object(fileutils, 'ensure_tree', autospec=True)
    def test_without_master_path(self, mock_ensure_tree):
        self.config(instance_master_path='', group='pxe')
        self.config(image_cache_size=500, group='pxe')
        self.config(image_cache_ttl=30, group='pxe')

        cache = utils.InstanceImageCache()

        mock_ensure_tree.assert_not_called()
        self.assertEqual(500 * 1024 * 1024, cache._cache_size)
        self.assertEqual(30 * 60, cache._cache_ttl)


class AsyncStepTestCase(db_base.DbTestCase):

    def setUp(self):
        super(AsyncStepTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver="fake-hardware")

    def _test_get_async_step_return_state(self):
        result = utils.get_async_step_return_state(self.node)
        if self.node.clean_step:
            self.assertEqual(states.CLEANWAIT, result)
        else:
            self.assertEqual(states.DEPLOYWAIT, result)

    def test_get_async_step_return_state_cleaning(self):
        self.node.clean_step = {'step': 'create_configuration',
                                'interface': 'raid'}
        self.node.save()
        self._test_get_async_step_return_state()

    def test_get_async_step_return_state_deploying(self):
        self.node.deploy_step = {'step': 'create_configuration',
                                 'interface': 'raid'}
        self.node.save()
        self._test_get_async_step_return_state()

    def test_set_async_step_flags_cleaning_set_all(self):
        self.node.clean_step = {'step': 'create_configuration',
                                'interface': 'raid'}
        self.node.driver_internal_info = {}
        expected = {'cleaning_reboot': True,
                    'cleaning_polling': True,
                    'skip_current_clean_step': True}
        self.node.save()
        utils.set_async_step_flags(self.node, reboot=True,
                                   skip_current_step=True,
                                   polling=True)
        self.assertEqual(expected, self.node.driver_internal_info)

    def test_set_async_step_flags_cleaning_set_one(self):
        self.node.clean_step = {'step': 'create_configuration',
                                'interface': 'raid'}
        self.node.driver_internal_info = {}
        self.node.save()
        utils.set_async_step_flags(self.node, reboot=True)
        self.assertEqual({'cleaning_reboot': True},
                         self.node.driver_internal_info)

    def test_set_async_step_flags_deploying_set_all(self):
        self.node.deploy_step = {'step': 'create_configuration',
                                 'interface': 'raid'}
        self.node.driver_internal_info = {
            'agent_secret_token': 'test',
            'agent_secret_token_pregenerated': True}
        expected = {'deployment_reboot': True,
                    'deployment_polling': True,
                    'skip_current_deploy_step': True,
                    'agent_secret_token': 'test',
                    'agent_secret_token_pregenerated': True}
        self.node.save()
        utils.set_async_step_flags(self.node, reboot=True,
                                   skip_current_step=True,
                                   polling=True)
        self.assertEqual(expected, self.node.driver_internal_info)

    def test_set_async_step_flags_deploying_set_one(self):
        self.node.deploy_step = {'step': 'create_configuration',
                                 'interface': 'raid'}
        self.node.driver_internal_info = {}
        self.node.save()
        utils.set_async_step_flags(self.node, reboot=True)
        self.assertEqual({'deployment_reboot': True},
                         self.node.driver_internal_info)

    def test_set_async_step_flags_clears_non_pregenerated_token(self):
        self.node.clean_step = {'step': 'create_configuration',
                                'interface': 'raid'}
        self.node.driver_internal_info = {'agent_secret_token': 'test'}
        expected = {'cleaning_reboot': True,
                    'cleaning_polling': True,
                    'skip_current_clean_step': True}
        self.node.save()
        utils.set_async_step_flags(self.node, reboot=True,
                                   skip_current_step=True,
                                   polling=True)
        self.assertEqual(expected, self.node.driver_internal_info)
