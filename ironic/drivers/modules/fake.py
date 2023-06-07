# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
Fake driver interfaces used in testing.

This is also an example of some kinds of things which can be done within
drivers.  For instance, the MultipleVendorInterface class demonstrates how to
load more than one interface and wrap them in some logic to route incoming
vendor_passthru requests appropriately. This can be useful eg. when mixing
functionality between a power interface and a deploy interface, when both rely
on separate vendor_passthru methods.
"""

import random
import time

from oslo_log import log

from ironic.common import boot_devices
from ironic.common import components
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import indicator_states
from ironic.common import states
from ironic.conf import CONF
from ironic.drivers import base
from ironic import objects


LOG = log.getLogger(__name__)


def parse_sleep_range(sleep_range):
    if not sleep_range:
        return 0, 0

    sleep_split = sleep_range.split(',')
    if len(sleep_split) == 1:
        a = sleep_split[0]
        b = sleep_split[0]
    else:
        a = sleep_split[0]
        b = sleep_split[1]
    return int(a), int(b)


def sleep(sleep_range):
    earliest, latest = parse_sleep_range(sleep_range)
    if earliest == 0 and latest == 0:
        # no sleep
        return
    if earliest == latest:
        # constant sleep
        sleep = earliest
    else:
        # triangular random sleep, weighted towards the earliest
        sleep = random.triangular(earliest, latest, earliest)
    time.sleep(sleep)


class FakePower(base.PowerInterface):
    """Example implementation of a simple power interface."""

    def get_properties(self):
        return {}

    def validate(self, task):
        pass

    def get_power_state(self, task):
        sleep(CONF.fake.power_delay)
        return task.node.power_state

    def reboot(self, task, timeout=None):
        sleep(CONF.fake.power_delay)
        pass

    def set_power_state(self, task, power_state, timeout=None):
        sleep(CONF.fake.power_delay)
        if power_state not in [states.POWER_ON, states.POWER_OFF,
                               states.SOFT_REBOOT, states.SOFT_POWER_OFF]:
            raise exception.InvalidParameterValue(
                _("set_power_state called with an invalid power "
                  "state: %s.") % power_state)
        task.node.power_state = power_state

    def get_supported_power_states(self, task):
        return [states.POWER_ON, states.POWER_OFF, states.REBOOT,
                states.SOFT_REBOOT, states.SOFT_POWER_OFF]


class FakeBoot(base.BootInterface):
    """Example implementation of a simple boot interface."""

    # NOTE(TheJulia): default capabilities to make unit tests
    # happy with the fake boot interface.
    capabilities = ['ipxe_boot', 'pxe_boot']

    def get_properties(self):
        return {}

    def validate(self, task):
        pass

    def prepare_ramdisk(self, task, ramdisk_params, mode='deploy'):
        sleep(CONF.fake.boot_delay)
        pass

    def clean_up_ramdisk(self, task, mode='deploy'):
        sleep(CONF.fake.boot_delay)
        pass

    def prepare_instance(self, task):
        sleep(CONF.fake.boot_delay)
        pass

    def clean_up_instance(self, task):
        sleep(CONF.fake.boot_delay)
        pass


class FakeDeploy(base.DeployInterface):
    """Class for a fake deployment driver.

    Example implementation of a deploy interface that uses a
    separate power interface.
    """

    def get_properties(self):
        return {}

    def validate(self, task):
        pass

    @base.deploy_step(priority=100)
    def deploy(self, task):
        sleep(CONF.fake.deploy_delay)
        return None

    def tear_down(self, task):
        sleep(CONF.fake.deploy_delay)
        return states.DELETED

    def prepare(self, task):
        sleep(CONF.fake.deploy_delay)
        pass

    def clean_up(self, task):
        sleep(CONF.fake.deploy_delay)
        pass

    def take_over(self, task):
        sleep(CONF.fake.deploy_delay)
        pass


class FakeVendorA(base.VendorInterface):
    """Example implementation of a vendor passthru interface."""

    def get_properties(self):
        return {'A1': 'A1 description. Required.',
                'A2': 'A2 description. Optional.'}

    def validate(self, task, method, **kwargs):
        if method == 'first_method':
            bar = kwargs.get('bar')
            if not bar:
                raise exception.MissingParameterValue(_(
                    "Parameter 'bar' not passed to method 'first_method'."))

    # NOTE(TheJulia): As an example, it is advisable to assign
    # parameters from **kwargs, and then perform handling on
    # the needful necessary from there.
    @base.passthru(['POST'],
                   description=_("Test if the value of bar is baz"))
    def first_method(self, task, http_method, bar):
        sleep(CONF.fake.vendor_delay)
        return True if bar == 'baz' else False


class FakeVendorB(base.VendorInterface):
    """Example implementation of a secondary vendor passthru."""

    def get_properties(self):
        return {'B1': 'B1 description. Required.',
                'B2': 'B2 description. Required.'}

    def validate(self, task, method, **kwargs):
        if method in ('second_method', 'third_method_sync',
                      'fourth_method_shared_lock'):
            bar = kwargs.get('bar')
            if not bar:
                raise exception.MissingParameterValue(_(
                    "Parameter 'bar' not passed to method '%s'.") % method)

    @base.passthru(['POST'],
                   description=_("Test if the value of bar is kazoo"))
    def second_method(self, task, http_method, bar):
        sleep(CONF.fake.vendor_delay)
        return True if bar == 'kazoo' else False

    @base.passthru(['POST'], async_call=False,
                   description=_("Test if the value of bar is meow"))
    def third_method_sync(self, task, http_method, bar):
        sleep(CONF.fake.vendor_delay)
        return True if bar == 'meow' else False

    @base.passthru(['POST'], require_exclusive_lock=False,
                   description=_("Test if the value of bar is woof"))
    def fourth_method_shared_lock(self, task, http_method, bar):
        sleep(CONF.fake.vendor_delay)
        return True if bar == 'woof' else False

    @base.service_step(requires_ramdisk=False)
    @base.clean_step(priority=1)
    @base.passthru(['POST'],
                   description=_("Test pass-through to wait."))
    def log_passthrough(self, task, **kwargs):
        LOG.debug('Test method test_passhtrough_method called with '
                  'arguments %s.', kwargs)
        sleep(CONF.fake.vendor_delay)
        # NOTE(TheJulia): Step methods invoked via an API *cannot*
        # have return values

    @base.service_step()
    def trigger_servicewait(self, task, **kwargs):
        return states.SERVICEWAIT


class FakeConsole(base.ConsoleInterface):
    """Example implementation of a simple console interface."""

    def get_properties(self):
        return {}

    def validate(self, task):
        pass

    def start_console(self, task):
        pass

    def stop_console(self, task):
        pass

    def get_console(self, task):
        return {}


class FakeManagement(base.ManagementInterface):
    """Example implementation of a simple management interface."""

    def get_properties(self):
        return {}

    def validate(self, task):
        # TODO(dtantsur): remove when snmp hardware type no longer supports the
        # fake management.
        if task.node.driver == 'snmp':
            LOG.warning('Using "fake" management with "snmp" hardware type '
                        'is deprecated, use "noop" instead for node %s',
                        task.node.uuid)

    def get_supported_boot_devices(self, task):
        return [boot_devices.PXE]

    def set_boot_device(self, task, device, persistent=False):
        sleep(CONF.fake.management_delay)
        if device not in self.get_supported_boot_devices(task):
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)

    def get_boot_device(self, task):
        sleep(CONF.fake.management_delay)
        return {'boot_device': boot_devices.PXE, 'persistent': False}

    def get_sensors_data(self, task):
        sleep(CONF.fake.management_delay)
        return {}

    def get_supported_indicators(self, task, component=None):
        sleep(CONF.fake.management_delay)
        indicators = {
            components.CHASSIS: {
                'led-0': {
                    "readonly": True,
                    "states": [
                        indicator_states.OFF,
                        indicator_states.ON
                    ]
                }
            },
            components.SYSTEM: {
                'led': {
                    "readonly": False,
                    "states": [
                        indicator_states.BLINKING,
                        indicator_states.OFF,
                        indicator_states.ON
                    ]
                }
            }
        }

        return {c: indicators[c] for c in indicators
                if not component or component == c}

    def get_indicator_state(self, task, component, indicator):
        sleep(CONF.fake.management_delay)
        indicators = self.get_supported_indicators(task)
        if component not in indicators:
            raise exception.InvalidParameterValue(_(
                "Invalid component %s specified.") % component)

        if indicator not in indicators[component]:
            raise exception.InvalidParameterValue(_(
                "Invalid indicator %s specified.") % indicator)

        return indicator_states.ON


class FakeInspect(base.InspectInterface):

    """Example implementation of a simple inspect interface."""

    def get_properties(self):
        return {}

    def validate(self, task):
        pass

    def inspect_hardware(self, task):
        sleep(CONF.fake.inspect_delay)
        return states.MANAGEABLE


class FakeRAID(base.RAIDInterface):
    """Example implementation of simple RAIDInterface."""

    def get_properties(self):
        return {}

    def create_configuration(self, task, create_root_volume=True,
                             create_nonroot_volumes=True):
        sleep(CONF.fake.raid_delay)
        pass

    def delete_configuration(self, task):
        sleep(CONF.fake.raid_delay)
        pass


class FakeBIOS(base.BIOSInterface):
    """Fake implementation of simple BIOSInterface."""

    def get_properties(self):
        return {}

    def validate(self, task):
        pass

    @base.clean_step(priority=0, argsinfo={
        'settings': {'description': ('List of BIOS settings, each item needs '
                     'to contain a dictionary with name/value pairs'),
                     'required': True}})
    def apply_configuration(self, task, settings):
        sleep(CONF.fake.bios_delay)
        # Note: the implementation of apply_configuration in fake interface
        # is just for testing purpose, for real driver implementation, please
        # refer to develop doc at https://docs.openstack.org/ironic/latest/
        # contributor/bios_develop.html.
        node_id = task.node.id
        create_list, update_list, delete_list, nochange_list = (
            objects.BIOSSettingList.sync_node_setting(task.context, node_id,
                                                      settings))

        if len(create_list) > 0:
            objects.BIOSSettingList.create(task.context, node_id, create_list)
        if len(update_list) > 0:
            objects.BIOSSettingList.save(task.context, node_id, update_list)
        if len(delete_list) > 0:
            delete_names = [setting['name'] for setting in delete_list]
            objects.BIOSSettingList.delete(task.context, node_id,
                                           delete_names)

        # nochange_list is part of return of sync_node_setting and it might be
        # useful to the drivers to give a message if no change is required
        # during application of settings.
        if len(nochange_list) > 0:
            pass

    @base.clean_step(priority=0)
    def factory_reset(self, task):
        sleep(CONF.fake.bios_delay)
        # Note: the implementation of factory_reset in fake interface is
        # just for testing purpose, for real driver implementation, please
        # refer to develop doc at https://docs.openstack.org/ironic/latest/
        # contributor/bios_develop.html.
        node_id = task.node.id
        setting_objs = objects.BIOSSettingList.get_by_node_id(
            task.context, node_id)
        for setting in setting_objs:
            objects.BIOSSetting.delete(task.context, node_id, setting.name)

    @base.clean_step(priority=0)
    def cache_bios_settings(self, task):
        sleep(CONF.fake.bios_delay)
        # Note: the implementation of cache_bios_settings in fake interface
        # is just for testing purpose, for real driver implementation, please
        # refer to develop doc at https://docs.openstack.org/ironic/latest/
        # contributor/bios_develop.html.
        pass


class FakeStorage(base.StorageInterface):
    """Example implementation of simple storage Interface."""

    def validate(self, task):
        pass

    def get_properties(self):
        return {}

    def attach_volumes(self, task):
        sleep(CONF.fake.storage_delay)
        pass

    def detach_volumes(self, task):
        sleep(CONF.fake.storage_delay)
        pass

    def should_write_image(self, task):
        return True


class FakeRescue(base.RescueInterface):
    """Example implementation of a simple rescue interface."""

    def get_properties(self):
        return {}

    def validate(self, task):
        pass

    def rescue(self, task):
        sleep(CONF.fake.rescue_delay)
        return states.RESCUE

    def unrescue(self, task):
        sleep(CONF.fake.rescue_delay)
        return states.ACTIVE


class FakeFirmware(base.FirmwareInterface):
    """Example implementation of a simple firmware interface."""

    def get_properties(self):
        return {}

    def validate(self, task):
        pass

    @base.clean_step(priority=0, argsinfo={
        'settings': {'description': ('List of Firmware components, each item '
                     'needs to contain a dictionary with name/value pairs'),
                     'required': True}})
    def update(self, task, settings):
        LOG.debug('Calling update clean step with settings %s.',
                  settings)
        sleep(CONF.fake.firmware_delay)

    def cache_firmware_components(self, task):
        sleep(CONF.fake.firmware_delay)
        pass
