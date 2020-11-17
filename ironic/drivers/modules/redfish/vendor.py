# Copyright 2015 Hewlett-Packard Development Company, L.P.
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
Vendor Interface for Redfish drivers and its supporting methods.
"""

from ironic_lib import metrics_utils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers.modules.redfish import boot as redfish_boot
from ironic.drivers.modules.redfish import utils as redfish_utils

METRICS = metrics_utils.get_metrics_logger(__name__)


class RedfishVendorPassthru(base.VendorInterface):
    """Vendor-specific interfaces for Redfish drivers."""

    def get_properties(self):
        return {}

    @METRICS.timer('RedfishVendorPassthru.validate')
    def validate(self, task, method, **kwargs):
        """Validate vendor-specific actions.

        Checks if a valid vendor passthru method was passed and validates
        the parameters for the vendor passthru method.

        :param task: a TaskManager instance containing the node to act on.
        :param method: method to be validated.
        :param kwargs: kwargs containing the vendor passthru method's
            parameters.
        :raises: InvalidParameterValue, if any of the parameters have invalid
            value.
        """
        if method == 'eject_vmedia':
            self._validate_eject_vmedia(task, kwargs)
            return
        super(RedfishVendorPassthru, self).validate(task, method, **kwargs)

    def _validate_eject_vmedia(self, task, kwargs):
        """Verify that the boot_device input is valid."""

        # If a boot device is provided check that it's valid.
        # It is OK to eject if already ejected
        boot_device = kwargs.get('boot_device')

        if not boot_device:
            return

        system = redfish_utils.get_system(task.node)

        for manager in system.managers:
            for v_media in manager.virtual_media.get_members():
                if boot_device not in v_media.media_types:
                    raise exception.InvalidParameterValue(_(
                        "Boot device %s is not a valid value ") % boot_device)

    @METRICS.timer('RedfishVendorPassthru.eject_vmedia')
    @base.passthru(['POST'],
                   description=_("Eject a virtual media device. If no device "
                                 "is provided than all attached devices will "
                                 "be ejected. "
                                 "Optional arguments: "
                                 "'boot_device' - the boot device to eject, "
                                 "either 'cd', 'dvd', 'usb', or 'floppy'"))
    # @task_manager.require_exclusive_lock
    def eject_vmedia(self, task, **kwargs):
        """Eject a virtual media device.

        :param task: A TaskManager object.
        :param kwargs: The arguments sent with vendor passthru. The optional
            kwargs are::
            'boot_device': the boot device to eject
        """

        # If boot_device not provided all vmedia devices will be ejected
        boot_device = kwargs.get('boot_device')
        redfish_boot.eject_vmedia(task, boot_device)
