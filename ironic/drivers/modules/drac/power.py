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
DRAC power interface
"""

import time

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import management as drac_management
from ironic.drivers.modules.redfish import power as redfish_power

drac_constants = importutils.try_import('dracclient.constants')
drac_exceptions = importutils.try_import('dracclient.exceptions')

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

if drac_constants:
    POWER_STATES = {
        drac_constants.POWER_ON: states.POWER_ON,
        drac_constants.POWER_OFF: states.POWER_OFF,
        drac_constants.REBOOT: states.REBOOT
    }

    REVERSE_POWER_STATES = dict((v, k) for (k, v) in POWER_STATES.items())

POWER_STATE_TRIES = 15
POWER_STATE_SLEEP = 2
POWER_STATE_CHANGE_FAIL = 'The command failed to set RequestedState'


def _get_power_state(node):
    """Returns the current power state of the node.

    :param node: an ironic node object.
    :returns: the power state, one of :mod:`ironic.common.states`.
    :raises: InvalidParameterValue if required DRAC credentials are missing.
    :raises: DracOperationError on an error from python-dracclient
    """

    client = drac_common.get_drac_client(node)

    try:
        drac_power_state = client.get_power_state()
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to get power state for node '
                  '%(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.DracOperationError(error=exc)

    return POWER_STATES[drac_power_state]


def _commit_boot_list_change(node):
    driver_internal_info = node.driver_internal_info

    boot_device = node.driver_internal_info.get('drac_boot_device')
    if boot_device is None:
        return

    drac_management.set_boot_device(node, boot_device['boot_device'],
                                    boot_device['persistent'])

    driver_internal_info['drac_boot_device'] = None
    node.driver_internal_info = driver_internal_info
    node.save()


def _set_power_state(node, power_state):
    """Turns the server power on/off or do a reboot.

    :param node: an ironic node object.
    :param power_state: a power state from :mod:`ironic.common.states`.
    :raises: InvalidParameterValue if required DRAC credentials are missing.
    :raises: DracOperationError on an error from python-dracclient
    """

    # NOTE(ifarkas): DRAC interface doesn't allow changing the boot device
    #                multiple times in a row without a reboot. This is
    #                because a change need to be committed via a
    #                configuration job, and further configuration jobs
    #                cannot be created until the previous one is processed
    #                at the next boot. As a workaround, it is saved to
    #                driver_internal_info during set_boot_device and committing
    #                it here.
    _commit_boot_list_change(node)

    client = drac_common.get_drac_client(node)
    tries = POWER_STATE_TRIES

    # Cases have been seen where the iDRAC returns a SYS021 error even when
    # the server is in the right power state and a valid power state change
    # is attempted. Retry in this case.
    while tries > 0:
        # The iDRAC will return a SYS021 error if the server is powered off
        # and a reboot is requested.  In this situation, convert the requested
        # reboot into a power on to avoid this error. To minimize the chance
        # of a race condition, it is critical to do this check immediately
        # before sending the power state change command.  This keeps the
        # window during which the server could change power states without us
        # knowing about it as small as possible.
        calc_power_state = power_state
        if power_state == states.REBOOT:
            current_power_state = _get_power_state(node)
            # If the server is not on, then power it on instead of rebooting
            if current_power_state != states.POWER_ON:
                calc_power_state = states.POWER_ON

        target_power_state = REVERSE_POWER_STATES[calc_power_state]

        try:
            client.set_power_state(target_power_state)
            break
        except drac_exceptions.BaseClientException as exc:
            if (power_state == states.REBOOT
                    and POWER_STATE_CHANGE_FAIL in str(exc)
                    and tries > 0):
                LOG.warning('DRAC driver failed to set power state for node '
                            '%(node_uuid)s to %(calc_power_state)s. '
                            'Reason: %(error)s. Retrying...',
                            {'node_uuid': node.uuid,
                             'calc_power_state': calc_power_state,
                             'error': exc})
                tries -= 1
                time.sleep(POWER_STATE_SLEEP)
            else:
                LOG.error('DRAC driver failed to set power state for node '
                          '%(node_uuid)s to %(calc_power_state)s. '
                          'Reason: %(error)s.',
                          {'node_uuid': node.uuid,
                           'calc_power_state': calc_power_state,
                           'error': exc})
                raise exception.DracOperationError(error=exc)

    if tries <= 0:
        error_msg = (_('DRAC driver timed out while trying to set the power '
                       'state for node %(node_uuid)s to '
                       '%(calc_power_state)s.') %
                     {'node_uuid': node.uuid,
                      'calc_power_state': calc_power_state})
        LOG.error(error_msg)
        raise exception.DracOperationError(error_msg)


class DracRedfishPower(redfish_power.RedfishPower):
    """iDRAC Redfish interface for power-related actions.

    Presently, this class entirely defers to its base class, a generic,
    vendor-independent Redfish interface. Future resolution of Dell EMC-
    specific incompatibilities and introduction of vendor value added
    should be implemented by this class.
    """
    pass


class DracWSManPower(base.PowerInterface):
    """Interface for power-related actions."""

    def get_properties(self):
        """Return the properties of the interface."""
        return drac_common.COMMON_PROPERTIES

    @METRICS.timer('DracPower.validate')
    def validate(self, task):
        """Validate the driver-specific Node power info.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        manage the power state of the node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if required driver_info attribute
                 is missing or invalid on the node.
        """
        return drac_common.parse_driver_info(task.node)

    @METRICS.timer('DracPower.get_power_state')
    def get_power_state(self, task):
        """Return the power state of the node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: the power state, one of :mod:`ironic.common.states`.
        :raises: InvalidParameterValue if required DRAC credentials are
                 missing.
        :raises: DracOperationError on an error from python-dracclient.
        """
        return _get_power_state(task.node)

    @METRICS.timer('DracPower.set_power_state')
    @task_manager.require_exclusive_lock
    def set_power_state(self, task, power_state, timeout=None):
        """Set the power state of the node.

        :param task: a TaskManager instance containing the node to act on.
        :param power_state: a power state from :mod:`ironic.common.states`.
        :param timeout: timeout (in seconds). Unsupported by this interface.
        :raises: InvalidParameterValue if required DRAC credentials are
                 missing.
        :raises: DracOperationError on an error from python-dracclient.
        """
        # TODO(rloo): Support timeouts!
        if timeout is not None:
            LOG.warning(
                "The 'idrac' Power Interface's 'set_power_state' method "
                "doesn't support the 'timeout' parameter. Ignoring "
                "timeout=%(timeout)s",
                {'timeout': timeout})

        _set_power_state(task.node, power_state)

    @METRICS.timer('DracPower.reboot')
    @task_manager.require_exclusive_lock
    def reboot(self, task, timeout=None):
        """Perform a reboot of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :param timeout: timeout (in seconds). Unsupported by this interface.
        :raises: InvalidParameterValue if required DRAC credentials are
                 missing.
        :raises: DracOperationError on an error from python-dracclient.
        """
        # TODO(rloo): Support timeouts!
        if timeout is not None:
            LOG.warning("The 'idrac' Power Interface's 'reboot' method "
                        "doesn't support the 'timeout' parameter. Ignoring "
                        "timeout=%(timeout)s",
                        {'timeout': timeout})

        _set_power_state(task.node, states.REBOOT)


class DracPower(DracWSManPower):
    """Class alias of class DracWSManPower.

    This class provides ongoing support of the deprecated 'idrac' power
    interface implementation entrypoint.

    All bug fixes and new features should be implemented in its base
    class, DracWSManPower. That makes them available to both the
    deprecated 'idrac' and new 'idrac-wsman' entrypoints. Such changes
    should not be made to this class.
    """

    def __init__(self):
        super(DracPower, self).__init__()
        LOG.warning("Power interface 'idrac' is deprecated and may be removed "
                    "in a future release. Use 'idrac-wsman' instead.")
