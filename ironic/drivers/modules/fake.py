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

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.drivers import base


class FakePower(base.PowerInterface):
    """Example implementation of a simple power interface."""

    def get_properties(self):
        return {}

    def validate(self, task):
        pass

    def get_power_state(self, task):
        return task.node.power_state

    def set_power_state(self, task, power_state, timeout=None):
        if power_state not in [states.POWER_ON, states.POWER_OFF]:
            raise exception.InvalidParameterValue(
                _("set_power_state called with an invalid power "
                  "state: %s.") % power_state)
        task.node.power_state = power_state

    def reboot(self, task, timeout=None):
        pass


class FakeSoftPower(FakePower):
    """Example implementation of a simple soft power operations."""

    def set_power_state(self, task, power_state, timeout=None):
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

    def get_properties(self):
        return {}

    def validate(self, task):
        pass

    def prepare_ramdisk(self, task, ramdisk_params):
        pass

    def clean_up_ramdisk(self, task):
        pass

    def prepare_instance(self, task):
        pass

    def clean_up_instance(self, task):
        pass


class FakeDeploy(base.DeployInterface):
    """Class for a fake deployment driver.

    Example imlementation of a deploy interface that uses a
    separate power interface.
    """

    def get_properties(self):
        return {}

    def validate(self, task):
        pass

    def deploy(self, task):
        return states.DEPLOYDONE

    def tear_down(self, task):
        return states.DELETED

    def prepare(self, task):
        pass

    def clean_up(self, task):
        pass

    def take_over(self, task):
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

    @base.passthru(['POST'],
                   description=_("Test if the value of bar is baz"))
    def first_method(self, task, http_method, bar):
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
        return True if bar == 'kazoo' else False

    @base.passthru(['POST'], async=False,
                   description=_("Test if the value of bar is meow"))
    def third_method_sync(self, task, http_method, bar):
        return True if bar == 'meow' else False

    @base.passthru(['POST'], require_exclusive_lock=False,
                   description=_("Test if the value of bar is woof"))
    def fourth_method_shared_lock(self, task, http_method, bar):
        return True if bar == 'woof' else False


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
        pass

    def get_supported_boot_devices(self, task):
        return [boot_devices.PXE]

    def set_boot_device(self, task, device, persistent=False):
        if device not in self.get_supported_boot_devices(task):
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)

    def get_boot_device(self, task):
        return {'boot_device': boot_devices.PXE, 'persistent': False}

    def get_sensors_data(self, task):
        return {}


class FakeInspect(base.InspectInterface):

    """Example implementation of a simple inspect interface."""

    def get_properties(self):
        return {}

    def validate(self, task):
        pass

    def inspect_hardware(self, task):
        return states.MANAGEABLE


class FakeRAID(base.RAIDInterface):
    """Example implementation of simple RAIDInterface."""

    def get_properties(self):
        return {}

    def create_configuration(self, task, create_root_volume=True,
                             create_nonroot_volumes=True):
        pass

    def delete_configuration(self, task):
        pass


class FakeStorage(base.StorageInterface):
    """Example implementation of simple storage Interface."""

    def validate(self, task):
        pass

    def get_properties(self):
        return {}

    def attach_volumes(self, task):
        pass

    def detach_volumes(self, task):
        pass

    def should_write_image(self, task):
        return True
