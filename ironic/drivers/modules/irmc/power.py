# Copyright 2015 FUJITSU LIMITED
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
iRMC Power Driver using the Base Server Profile
"""
from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules.irmc import boot as irmc_boot
from ironic.drivers.modules.irmc import common as irmc_common
from ironic.drivers.modules.redfish import power as redfish_power
from ironic.drivers.modules import snmp

scci = importutils.try_import('scciclient.irmc.scci')

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

"""
SC2.mib: sc2srvCurrentBootStatus returns status of the current boot
"""
BOOT_STATUS_OID = "1.3.6.1.4.1.231.2.10.2.2.10.4.1.1.4.1"
BOOT_STATUS_VALUE = {
    'error': 0,
    'unknown': 1,
    'off': 2,
    'no-boot-cpu': 3,
    'self-test': 4,
    'setup': 5,
    'os-boot': 6,
    'diagnostic-boot': 7,
    'os-running': 8,
    'diagnostic-running': 9,
    'os-shutdown': 10,
    'diagnostic-shutdown': 11,
    'reset': 12
}
BOOT_STATUS = {v: k for k, v in BOOT_STATUS_VALUE.items()}

if scci:
    STATES_MAP = {states.POWER_OFF: scci.POWER_OFF,
                  states.POWER_ON: scci.POWER_ON,
                  states.REBOOT: scci.POWER_RESET,
                  states.SOFT_REBOOT: scci.POWER_SOFT_CYCLE,
                  states.SOFT_POWER_OFF: scci.POWER_SOFT_OFF}


def _is_expected_power_state(target_state, boot_status_value):
    """Predicate if target power state and boot status values match.

    :param target_state: Target power state.
    :param boot_status_value: SNMP BOOT_STATUS_VALUE.
    :returns: True if expected power state, otherwise Flase.
    """
    if (target_state == states.SOFT_POWER_OFF
        and boot_status_value in (BOOT_STATUS_VALUE['unknown'],
                                  BOOT_STATUS_VALUE['off'])):
        return True
    elif (target_state == states.SOFT_REBOOT
          and boot_status_value == BOOT_STATUS_VALUE['os-running']):
        return True

    return False


def _wait_power_state(task, target_state, timeout=None):
    """Wait for having changed to the target power state.

    :param task: A TaskManager instance containing the node to act on.
    :raises: IRMCOperationError if the target state acknowledge failed.
    :raises: SNMPFailure if SNMP request failed.
    """
    node = task.node
    d_info = irmc_common.parse_driver_info(node)
    snmp_client = snmp.SNMPClient(
        address=d_info['irmc_address'],
        port=d_info['irmc_snmp_port'],
        version=d_info['irmc_snmp_version'],
        read_community=d_info['irmc_snmp_community'],
        user=d_info.get('irmc_snmp_user'),
        auth_proto=d_info.get('irmc_snmp_auth_proto'),
        auth_key=d_info.get('irmc_snmp_auth_password'),
        priv_proto=d_info.get('irmc_snmp_priv_proto'),
        priv_key=d_info.get('irmc_snmp_priv_password'))

    interval = CONF.irmc.snmp_polling_interval
    retry_timeout_soft = timeout or CONF.conductor.soft_power_off_timeout
    max_retry = int(retry_timeout_soft / interval)

    def _wait(mutable):
        mutable['boot_status_value'] = snmp_client.get(BOOT_STATUS_OID)
        LOG.debug("iRMC SNMP agent of %(node_id)s returned "
                  "boot status value %(bootstatus)s on attempt %(times)s.",
                  {'node_id': node.uuid,
                   'bootstatus': BOOT_STATUS[mutable['boot_status_value']],
                   'times': mutable['times']})

        if _is_expected_power_state(target_state,
                                    mutable['boot_status_value']):
            mutable['state'] = target_state
            raise loopingcall.LoopingCallDone()

        mutable['times'] += 1
        if mutable['times'] > max_retry:
            mutable['state'] = states.ERROR
            raise loopingcall.LoopingCallDone()

    store = {'state': None, 'times': 0, 'boot_status_value': None}
    timer = loopingcall.FixedIntervalLoopingCall(_wait, store)
    timer.start(interval=interval).wait()

    if store['state'] == target_state:
        # iRMC acknowledged the target state
        node.last_error = None
        node.power_state = (states.POWER_OFF
                            if target_state == states.SOFT_POWER_OFF
                            else states.POWER_ON)
        node.target_power_state = states.NOSTATE
        node.save()
        LOG.info('iRMC successfully set node %(node_id)s '
                 'power state to %(bootstatus)s.',
                 {'node_id': node.uuid,
                  'bootstatus': BOOT_STATUS[store['boot_status_value']]})
    else:
        # iRMC failed to acknowledge the target state
        last_error = (_('iRMC returned unexpected boot status value %s') %
                      BOOT_STATUS[store['boot_status_value']])
        node.last_error = last_error
        node.power_state = states.ERROR
        node.target_power_state = states.NOSTATE
        node.save()
        LOG.error('iRMC failed to acknowledge the target state for node '
                  '%(node_id)s. Error: %(last_error)s',
                  {'node_id': node.uuid, 'last_error': last_error})
        error = _('unexpected boot status value')
        raise exception.IRMCOperationError(operation=target_state,
                                           error=error)


def _set_power_state(task, target_state, timeout=None):
    """Turn the server power on/off or do a reboot.

    :param task: a TaskManager instance containing the node to act on.
    :param target_state: target state of the node.
    :param timeout: timeout (in seconds) positive integer (> 0) for any
      power state. ``None`` indicates default timeout.
    :raises: InvalidParameterValue if an invalid power state was specified.
    :raises: MissingParameterValue if some mandatory information
      is missing on the node
    :raises: IRMCOperationError on an error from SCCI or SNMP
    """
    node = task.node
    irmc_client = irmc_common.get_irmc_client(node)

    if target_state in (states.POWER_ON, states.REBOOT, states.SOFT_REBOOT):
        irmc_boot.attach_boot_iso_if_needed(task)

    try:
        irmc_client(STATES_MAP[target_state])

    except KeyError:
        msg = _("_set_power_state called with invalid power state "
                "'%s'") % target_state
        raise exception.InvalidParameterValue(msg)

    except scci.SCCIClientError as irmc_exception:
        LOG.error("iRMC set_power_state failed to set state to %(tstate)s "
                  " for node %(node_id)s with error: %(error)s",
                  {'tstate': target_state, 'node_id': node.uuid,
                   'error': irmc_exception})
        operation = _('iRMC set_power_state')
        raise exception.IRMCOperationError(operation=operation,
                                           error=irmc_exception)

    try:
        if target_state in (states.SOFT_REBOOT, states.SOFT_POWER_OFF):
            # note (naohirot):
            # The following call covers both cases since SOFT_REBOOT matches
            # 'unknown' and SOFT_POWER_OFF matches 'off' or 'unknown'.
            _wait_power_state(task, states.SOFT_POWER_OFF, timeout=timeout)
        if target_state == states.SOFT_REBOOT:
            _wait_power_state(task, states.SOFT_REBOOT, timeout=timeout)

    except exception.SNMPFailure as snmp_exception:
        advice = ("The SNMP related parameters' value may be different with "
                  "the server, please check if you have set them correctly.")
        LOG.error("iRMC failed to acknowledge the target state "
                  "for node %(node_id)s. Error: %(error)s. %(advice)s",
                  {'node_id': node.uuid, 'error': snmp_exception,
                   'advice': advice})
        raise exception.IRMCOperationError(operation=target_state,
                                           error=snmp_exception)


class IRMCPower(redfish_power.RedfishPower, base.PowerInterface):
    """Interface for power-related actions."""

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return irmc_common.COMMON_PROPERTIES

    @METRICS.timer('IRMCPower.validate')
    def validate(self, task):
        """Validate the driver-specific Node power info.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        manage the power state of the node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if required driver_info attribute
                 is missing or invalid on the node.
        :raises: MissingParameterValue if a required parameter is missing.
        """
        # validate method of power interface is called at very first point
        # in verifying.
        # We take try-fallback approach against iRMC S6 2.00 and later
        # incompatibility in which iRMC firmware disables IPMI by default.
        # get_power_state method first try IPMI and if fails try Redfish
        # along with setting irmc_ipmi_succeed flag to indicate if IPMI works.
        if (task.node.driver_internal_info.get('irmc_ipmi_succeed')
            or (task.node.driver_internal_info.get('irmc_ipmi_succeed')
            is None)):
            irmc_common.parse_driver_info(task.node)
        else:
            irmc_common.parse_driver_info(task.node)
            super(IRMCPower, self).validate(task)

    @METRICS.timer('IRMCPower.get_power_state')
    def get_power_state(self, task):
        """Return the power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: a power state. One of :mod:`ironic.common.states`.
        :raises: InvalidParameterValue if required parameters are incorrect.
        :raises: MissingParameterValue if required parameters are missing.
        :raises: IRMCOperationError If IPMI or Redfish operation fails
        """
        # If IPMI operation failed, iRMC may not enable/support IPMI,
        # so fallback to Redfish.
        # get_power_state is called at verifying and is called periodically
        # so this method is good choice to determine IPMI enablement.
        try:
            irmc_common.update_ipmi_properties(task)
            ipmi_power = ipmitool.IPMIPower()
            pw_state = ipmi_power.get_power_state(task)
            if (task.node.driver_internal_info.get('irmc_ipmi_succeed')
                is not True):
                task.upgrade_lock(purpose='update irmc_ipmi_succeed flag',
                                  retry=True)
                task.node.set_driver_internal_info('irmc_ipmi_succeed', True)
                task.node.save()
                task.downgrade_lock()
            return pw_state
        except exception.IPMIFailure:
            if (task.node.driver_internal_info.get('irmc_ipmi_succeed')
                is not False):
                task.upgrade_lock(purpose='update irmc_ipmi_succeed flag',
                                  retry=True)
                task.node.set_driver_internal_info('irmc_ipmi_succeed', False)
                task.node.save()
                task.downgrade_lock()
            try:
                return super(IRMCPower, self).get_power_state(task)
            except (exception.RedfishConnectionError,
                    exception.RedfishError):
                raise exception.IRMCOperationError(
                    operation='IPMI try and Redfish fallback operation')

    @METRICS.timer('IRMCPower.set_power_state')
    @task_manager.require_exclusive_lock
    def set_power_state(self, task, power_state, timeout=None):
        """Set the power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :param power_state: Any power state from :mod:`ironic.common.states`.
        :param timeout: timeout (in seconds) positive integer (> 0) for any
          power state. ``None`` indicates default timeout.
        :raises: InvalidParameterValue if an invalid power state was specified.
        :raises: MissingParameterValue if some mandatory information
          is missing on the node
        :raises: IRMCOperationError if failed to set the power state.
        """
        _set_power_state(task, power_state, timeout=timeout)

    @METRICS.timer('IRMCPower.reboot')
    @task_manager.require_exclusive_lock
    def reboot(self, task, timeout=None):
        """Perform a hard reboot of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :param timeout: timeout (in seconds) positive integer (> 0) for any
          power state. ``None`` indicates default timeout.
        :raises: InvalidParameterValue if an invalid power state was specified.
        :raises: IRMCOperationError if failed to set the power state.
        """
        current_pstate = self.get_power_state(task)
        if current_pstate == states.POWER_ON:
            _set_power_state(task, states.REBOOT, timeout=timeout)
        elif current_pstate == states.POWER_OFF:
            _set_power_state(task, states.POWER_ON, timeout=timeout)

    @METRICS.timer('IRMCPower.get_supported_power_states')
    def get_supported_power_states(self, task):
        """Get a list of the supported power states.

        :param task: A TaskManager instance containing the node to act on.
            currently not used.
        :returns: A list with the supported power states defined
                  in :mod:`ironic.common.states`.
        """
        return [states.POWER_ON, states.POWER_OFF, states.REBOOT,
                states.SOFT_REBOOT, states.SOFT_POWER_OFF]
