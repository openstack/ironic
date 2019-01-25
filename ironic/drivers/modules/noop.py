# Copyright 2016 Red Hat, Inc.
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
Dummy interface implementations for use as defaults with optional interfaces.

Note that unlike fake implementations, these do not pass validation and raise
exceptions for user-accessible actions.
"""

from ironic.common import exception
from ironic.drivers import base


def _fail(iface, task, *args, **kwargs):
    # TODO(dtanstur): support hardware types
    driver = task.node.driver
    raise exception.UnsupportedDriverExtension(
        driver=driver, extension=iface.interface_type)


class FailMixin(object):
    """Mixin to add to an interface to make it fail validation."""

    def get_properties(self):
        return {}

    validate = _fail


class NoConsole(FailMixin, base.ConsoleInterface):
    """Console interface implementation that raises errors on all requests."""
    stop_console = get_console = start_console = _fail


class NoRescue(FailMixin, base.RescueInterface):
    """Rescue interface implementation that raises errors on all requests."""
    rescue = unrescue = _fail


class NoVendor(FailMixin, base.VendorInterface):
    """Vendor interface implementation that raises errors on all requests."""

    def driver_validate(self, method, **kwargs):
        raise exception.UnsupportedDriverExtension(
            driver=type(self).__name__, extension=self.interface_type)


class NoInspect(FailMixin, base.InspectInterface):
    """Inspect interface implementation that raises errors on all requests."""
    inspect_hardware = _fail


class NoRAID(FailMixin, base.RAIDInterface):
    """RAID interface implementation that raises errors on all requests."""
    create_configuration = delete_configuration = _fail

    def validate_raid_config(self, task, raid_config):
        _fail(self, task)


class NoBIOS(FailMixin, base.BIOSInterface):
    """BIOS interface implementation that raises errors on all requests."""

    def apply_configuration(self, task, settings):
        _fail(self, task, settings)

    def factory_reset(self, task):
        _fail(self, task)

    def cache_bios_settings(self, task):
        pass
