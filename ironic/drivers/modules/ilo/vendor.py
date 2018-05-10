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
Vendor Interface for iLO drivers and its supporting methods.
"""

from ironic_lib import metrics_utils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import common as ilo_common

METRICS = metrics_utils.get_metrics_logger(__name__)


class VendorPassthru(base.VendorInterface):
    """Vendor-specific interfaces for iLO deploy drivers."""

    def get_properties(self):
        return {}

    @METRICS.timer('IloVendorPassthru.validate')
    def validate(self, task, method, **kwargs):
        """Validate vendor-specific actions.

        Checks if a valid vendor passthru method was passed and validates
        the parameters for the vendor passthru method.

        :param task: a TaskManager instance containing the node to act on.
        :param method: method to be validated.
        :param kwargs: kwargs containing the vendor passthru method's
            parameters.
        :raises: MissingParameterValue, if some required parameters were not
            passed.
        :raises: InvalidParameterValue, if any of the parameters have invalid
            value.
        """
        if method == 'boot_into_iso':
            self._validate_boot_into_iso(task, kwargs)
            return
        super(VendorPassthru, self).validate(task, method, **kwargs)

    def _validate_boot_into_iso(self, task, kwargs):
        """Validates if attach_iso can be called and if inputs are proper."""
        if not (task.node.provision_state == states.MANAGEABLE
                or task.node.maintenance is True):
            msg = (_("The requested action 'boot_into_iso' can be performed "
                     "only when node %(node_uuid)s is in %(state)s state or "
                     "in 'maintenance' mode") %
                   {'node_uuid': task.node.uuid,
                    'state': states.MANAGEABLE})
            raise exception.InvalidStateRequested(msg)
        d_info = {'boot_iso_href': kwargs.get('boot_iso_href')}
        error_msg = _("Error validating input for boot_into_iso vendor "
                      "passthru. Some parameters were not provided: ")
        deploy_utils.check_for_missing_params(d_info, error_msg)
        deploy_utils.validate_image_properties(
            task.context, {'image_source': kwargs.get('boot_iso_href')}, [])

    @METRICS.timer('IloVendorPassthru.boot_into_iso')
    @base.passthru(['POST'],
                   description=_("Attaches an ISO image and reboots the node. "
                                 "Required argument: 'boot_iso_href' - href "
                                 "of the image to be booted. This can be a "
                                 "Glance UUID or an HTTP(S) URL."))
    @task_manager.require_exclusive_lock
    def boot_into_iso(self, task, **kwargs):
        """Attaches an ISO image in glance and reboots bare metal.

        This method accepts an ISO image href (a Glance UUID or an HTTP(S) URL)
        attaches it as virtual media and then reboots the node.  This is
        useful for debugging purposes.  This can be invoked only when the node
        is in manage state.

        :param task: A TaskManager object.
        :param kwargs: The arguments sent with vendor passthru. The expected
            kwargs are::

                'boot_iso_href': href of the image to be booted. This can be
                    a Glance UUID or an HTTP(S) URL.
        """
        ilo_common.setup_vmedia(task, kwargs['boot_iso_href'],
                                ramdisk_options=None)
        manager_utils.node_power_action(task, states.REBOOT)
