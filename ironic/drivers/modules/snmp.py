# Copyright 2013,2014 Cray Inc
#
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

"""
Ironic SNMP power manager.

Provides basic power control using an SNMP-enabled smart power controller.
Uses a pluggable driver model to support devices with different SNMP object
models.

"""

import abc
import time

from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import importutils
import six

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers import base

pysnmp = importutils.try_import('pysnmp')
if pysnmp:
    from pysnmp.entity.rfc3413.oneliner import cmdgen
    from pysnmp import error as snmp_error
    from pysnmp.proto import rfc1902
else:
    cmdgen = None
    snmp_error = None
    rfc1902 = None

LOG = logging.getLogger(__name__)


SNMP_V1 = '1'
SNMP_V2C = '2c'
SNMP_V3 = '3'
SNMP_PORT = 161

REQUIRED_PROPERTIES = {
    'snmp_driver': _("PDU manufacturer driver.  Required."),
    'snmp_address': _("PDU IPv4 address or hostname.  Required."),
    'snmp_outlet': _("PDU power outlet index (1-based).  Required."),
}
OPTIONAL_PROPERTIES = {
    'snmp_version':
        _("SNMP protocol version: %(v1)s, %(v2c)s or %(v3)s  "
          "(optional, default %(v1)s)")
        % {"v1": SNMP_V1, "v2c": SNMP_V2C, "v3": SNMP_V3},
    'snmp_port':
        _("SNMP port, default %(port)d") % {"port": SNMP_PORT},
    'snmp_community':
        _("SNMP community.  Required for versions %(v1)s and %(v2c)s")
        % {"v1": SNMP_V1, "v2c": SNMP_V2C},
    'snmp_security':
        _("SNMPv3 User-based Security Model (USM) username. "
          "Required for version %(v3)s")
        % {"v3": SNMP_V3},
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)


class SNMPClient(object):
    """SNMP client object.

    Performs low level SNMP get and set operations. Encapsulates all
    interaction with PySNMP to simplify dynamic importing and unit testing.
    """

    def __init__(self, address, port, version, community=None, security=None):
        self.address = address
        self.port = port
        self.version = version
        if self.version == SNMP_V3:
            self.security = security
        else:
            self.community = community
        self.cmd_gen = cmdgen.CommandGenerator()

    def _get_auth(self):
        """Return the authorization data for an SNMP request.

        :returns: A
            :class:`pysnmp.entity.rfc3413.oneliner.cmdgen.CommunityData`
            object.
        """
        if self.version == SNMP_V3:
            # Handling auth/encryption credentials is not (yet) supported.
            # This version supports a security name analogous to community.
            return cmdgen.UsmUserData(self.security)
        else:
            mp_model = 1 if self.version == SNMP_V2C else 0
            return cmdgen.CommunityData(self.community, mpModel=mp_model)

    def _get_transport(self):
        """Return the transport target for an SNMP request.

        :returns: A :class:
            `pysnmp.entity.rfc3413.oneliner.cmdgen.UdpTransportTarget` object.
        :raises: snmp_error.PySnmpError if the transport address is bad.
        """
        # The transport target accepts timeout and retries parameters, which
        # default to 1 (second) and 5 respectively. These are deemed sensible
        # enough to allow for an unreliable network or slow device.
        return cmdgen.UdpTransportTarget(
            (self.address, self.port),
            timeout=CONF.snmp.udp_transport_timeout,
            retries=CONF.snmp.udp_transport_retries)

    def get(self, oid):
        """Use PySNMP to perform an SNMP GET operation on a single object.

        :param oid: The OID of the object to get.
        :raises: SNMPFailure if an SNMP request fails.
        :returns: The value of the requested object.
        """
        try:
            results = self.cmd_gen.getCmd(self._get_auth(),
                                          self._get_transport(),
                                          oid)
        except snmp_error.PySnmpError as e:
            raise exception.SNMPFailure(operation="GET", error=e)

        error_indication, error_status, error_index, var_binds = results

        if error_indication:
            # SNMP engine-level error.
            raise exception.SNMPFailure(operation="GET",
                                        error=error_indication)

        if error_status:
            # SNMP PDU error.
            raise exception.SNMPFailure(operation="GET",
                                        error=error_status.prettyPrint())

        # We only expect a single value back
        name, val = var_binds[0]
        return val

    def get_next(self, oid):
        """Use PySNMP to perform an SNMP GET NEXT operation on a table object.

        :param oid: The OID of the object to get.
        :raises: SNMPFailure if an SNMP request fails.
        :returns: A list of values of the requested table object.
        """
        try:
            results = self.cmd_gen.nextCmd(self._get_auth(),
                                           self._get_transport(),
                                           oid)
        except snmp_error.PySnmpError as e:
            raise exception.SNMPFailure(operation="GET_NEXT", error=e)

        error_indication, error_status, error_index, var_bind_table = results

        if error_indication:
            # SNMP engine-level error.
            raise exception.SNMPFailure(operation="GET_NEXT",
                                        error=error_indication)

        if error_status:
            # SNMP PDU error.
            raise exception.SNMPFailure(operation="GET_NEXT",
                                        error=error_status.prettyPrint())

        return [val for row in var_bind_table for name, val in row]

    def set(self, oid, value):
        """Use PySNMP to perform an SNMP SET operation on a single object.

        :param oid: The OID of the object to set.
        :param value: The value of the object to set.
        :raises: SNMPFailure if an SNMP request fails.
        """
        try:
            results = self.cmd_gen.setCmd(self._get_auth(),
                                          self._get_transport(),
                                          (oid, value))
        except snmp_error.PySnmpError as e:
            raise exception.SNMPFailure(operation="SET", error=e)

        error_indication, error_status, error_index, var_binds = results

        if error_indication:
            # SNMP engine-level error.
            raise exception.SNMPFailure(operation="SET",
                                        error=error_indication)

        if error_status:
            # SNMP PDU error.
            raise exception.SNMPFailure(operation="SET",
                                        error=error_status.prettyPrint())


def _get_client(snmp_info):
    """Create and return an SNMP client object.

    :param snmp_info: SNMP driver info.
    :returns: A :class:`SNMPClient` object.
    """
    return SNMPClient(snmp_info["address"],
                      snmp_info["port"],
                      snmp_info["version"],
                      snmp_info.get("community"),
                      snmp_info.get("security"))


@six.add_metaclass(abc.ABCMeta)
class SNMPDriverBase(object):
    """SNMP power driver base class.

    The SNMPDriver class hierarchy implements manufacturer-specific MIB actions
    over SNMP to interface with different smart power controller products.
    """

    oid_enterprise = (1, 3, 6, 1, 4, 1)
    retry_interval = 1

    def __init__(self, snmp_info):
        self.snmp_info = snmp_info
        self.client = _get_client(snmp_info)

    @abc.abstractmethod
    def _snmp_power_state(self):
        """Perform the SNMP request required to get the current power state.

        :raises: SNMPFailure if an SNMP request fails.
        :returns: power state. One of :class:`ironic.common.states`.
        """

    @abc.abstractmethod
    def _snmp_power_on(self):
        """Perform the SNMP request required to set the power on.

        :raises: SNMPFailure if an SNMP request fails.
        """

    @abc.abstractmethod
    def _snmp_power_off(self):
        """Perform the SNMP request required to set the power off.

        :raises: SNMPFailure if an SNMP request fails.
        """

    def _snmp_wait_for_state(self, goal_state):
        """Wait for the power state of the PDU outlet to change.

        :param goal_state: The power state to wait for, one of
            :class:`ironic.common.states`.
        :raises: SNMPFailure if an SNMP request fails.
        :returns: power state. One of :class:`ironic.common.states`.
        """

        def _poll_for_state(mutable):
            """Called at an interval until the node's power is consistent.

            :param mutable: dict object containing "state" and "next_time"
            :raises: SNMPFailure if an SNMP request fails.
            """
            mutable["state"] = self._snmp_power_state()
            if mutable["state"] == goal_state:
                raise loopingcall.LoopingCallDone()

            mutable["next_time"] += self.retry_interval
            if mutable["next_time"] >= CONF.snmp.power_timeout:
                mutable["state"] = states.ERROR
                raise loopingcall.LoopingCallDone()

        # Pass state to the looped function call in a mutable form.
        state = {"state": None, "next_time": 0}
        timer = loopingcall.FixedIntervalLoopingCall(_poll_for_state,
                                                     state)
        timer.start(interval=self.retry_interval).wait()
        LOG.debug("power state '%s'", state["state"])
        return state["state"]

    def power_state(self):
        """Returns a node's current power state.

        :raises: SNMPFailure if an SNMP request fails.
        :returns: power state. One of :class:`ironic.common.states`.
        """
        return self._snmp_power_state()

    def power_on(self):
        """Set the power state to this node to ON.

        :raises: SNMPFailure if an SNMP request fails.
        :returns: power state. One of :class:`ironic.common.states`.
        """
        self._snmp_power_on()
        return self._snmp_wait_for_state(states.POWER_ON)

    def power_off(self):
        """Set the power state to this node to OFF.

        :raises: SNMPFailure if an SNMP request fails.
        :returns: power state. One of :class:`ironic.common.states`.
        """
        self._snmp_power_off()
        return self._snmp_wait_for_state(states.POWER_OFF)

    def power_reset(self):
        """Reset the power to this node.

        :raises: SNMPFailure if an SNMP request fails.
        :returns: power state. One of :class:`ironic.common.states`.
        """
        power_result = self.power_off()
        if power_result != states.POWER_OFF:
            return states.ERROR
        time.sleep(CONF.snmp.reboot_delay)
        power_result = self.power_on()
        if power_result != states.POWER_ON:
            return states.ERROR
        return power_result


class SNMPDriverSimple(SNMPDriverBase):
    """SNMP driver base class for simple PDU devices.

    Here, simple refers to devices which provide a single SNMP object for
    controlling the power state of an outlet.

    The default OID of the power state object is of the form
    <enterprise OID>.<device OID>.<outlet ID>. A different OID may be specified
    by overriding the _snmp_oid method in a subclass.
    """

    def __init__(self, *args, **kwargs):
        super(SNMPDriverSimple, self).__init__(*args, **kwargs)
        self.oid = self._snmp_oid()

    @abc.abstractproperty
    def oid_device(self):
        """Device dependent portion of the power state object OID."""

    @abc.abstractproperty
    def value_power_on(self):
        """Value representing power on state."""

    @abc.abstractproperty
    def value_power_off(self):
        """Value representing power off state."""

    def _snmp_oid(self):
        """Return the OID of the power state object.

        :returns: Power state object OID as a tuple of integers.
        """
        outlet = self.snmp_info['outlet']
        return self.oid_enterprise + self.oid_device + (outlet,)

    def _snmp_power_state(self):
        state = self.client.get(self.oid)

        # Translate the state to an Ironic power state.
        if state == self.value_power_on:
            power_state = states.POWER_ON
        elif state == self.value_power_off:
            power_state = states.POWER_OFF
        else:
            LOG.warning("SNMP PDU %(addr)s outlet %(outlet)s: "
                        "unrecognised power state %(state)s.",
                        {'addr': self.snmp_info['address'],
                         'outlet': self.snmp_info['outlet'],
                         'state': state})
            power_state = states.ERROR

        return power_state

    def _snmp_power_on(self):
        value = rfc1902.Integer(self.value_power_on)
        self.client.set(self.oid, value)

    def _snmp_power_off(self):
        value = rfc1902.Integer(self.value_power_off)
        self.client.set(self.oid, value)


class SNMPDriverAten(SNMPDriverSimple):
    """SNMP driver class for Aten PDU devices.

    SNMP objects for Aten PDU:
    1.3.6.1.4.1.21317.1.3.2.2.2.2 Outlet Power
    Values: 1=Off, 2=On, 3=Pending, 4=Reset
    """
    oid_device = (21317, 1, 3, 2, 2, 2, 2)
    value_power_on = 2
    value_power_off = 1

    def _snmp_oid(self):
        """Return the OID of the power state object.

        :returns: Power state object OID as a tuple of integers.
        """
        outlet = self.snmp_info['outlet']
        return self.oid_enterprise + self.oid_device + (outlet, 0,)


class SNMPDriverAPCMasterSwitch(SNMPDriverSimple):
    """SNMP driver class for APC MasterSwitch PDU devices.

    SNMP objects for APC SNMPDriverAPCMasterSwitch PDU:
    1.3.6.1.4.1.318.1.1.4.4.2.1.3 sPDUOutletCtl
    Values: 1=On, 2=Off, 3=PowerCycle, [...more options follow]
    """

    oid_device = (318, 1, 1, 4, 4, 2, 1, 3)
    value_power_on = 1
    value_power_off = 2


class SNMPDriverAPCMasterSwitchPlus(SNMPDriverSimple):
    """SNMP driver class for APC MasterSwitchPlus PDU devices.

    SNMP objects for APC SNMPDriverAPCMasterSwitchPlus PDU:
    1.3.6.1.4.1.318.1.1.6.5.1.1.5 sPDUOutletControlMSPOutletCommand
    Values: 1=On, 3=Off, [...more options follow]
    """

    oid_device = (318, 1, 1, 6, 5, 1, 1, 5)
    value_power_on = 1
    value_power_off = 3


class SNMPDriverAPCRackPDU(SNMPDriverSimple):
    """SNMP driver class for APC RackPDU devices.

    SNMP objects for APC SNMPDriverAPCMasterSwitch PDU:
    # 1.3.6.1.4.1.318.1.1.12.3.3.1.1.4 rPDUOutletControlOutletCommand
    Values: 1=On, 2=Off, 3=PowerCycle, [...more options follow]
    """

    oid_device = (318, 1, 1, 12, 3, 3, 1, 1, 4)
    value_power_on = 1
    value_power_off = 2


class SNMPDriverCyberPower(SNMPDriverSimple):
    """SNMP driver class for CyberPower PDU devices.

    SNMP objects for CyberPower PDU:
    1.3.6.1.4.1.3808.1.1.3.3.3.1.1.4 ePDUOutletControlOutletCommand
    Values: 1=On, 2=Off, 3=PowerCycle, [...more options follow]
    """

    # NOTE(mgoddard): This device driver is currently untested, this driver has
    #                 been implemented based upon its published MIB
    #                 documentation.

    oid_device = (3808, 1, 1, 3, 3, 3, 1, 1, 4)
    value_power_on = 1
    value_power_off = 2


class SNMPDriverTeltronix(SNMPDriverSimple):
    """SNMP driver class for Teltronix PDU devices.

    SNMP objects for Teltronix PDU:
    1.3.6.1.4.1.23620.1.2.2.1.4   Outlet Power
    Values: 1=Off, 2=On
    """

    oid_device = (23620, 1, 2, 2, 1, 4)
    value_power_on = 2
    value_power_off = 1


class SNMPDriverEatonPower(SNMPDriverBase):
    """SNMP driver class for Eaton Power PDU.

    The Eaton power PDU does not follow the model of SNMPDriverSimple as it
    uses multiple SNMP objects.

    SNMP objects for Eaton Power PDU
    1.3.6.1.4.1.534.6.6.7.6.6.1.2.<outlet ID> outletControlStatus
    Read 0=off, 1=on, 2=pending off, 3=pending on
    1.3.6.1.4.1.534.6.6.7.6.6.1.3.<outlet ID> outletControlOffCmd
    Write 0 for immediate power off
    1.3.6.1.4.1.534.6.6.7.6.6.1.4.<outlet ID> outletControlOnCmd
    Write 0 for immediate power on
    """

    # NOTE(mgoddard): This device driver is currently untested, this driver has
    #                 been implemented based upon its published MIB
    #                 documentation.

    oid_device = (534, 6, 6, 7, 6, 6, 1)
    oid_status = (2,)
    oid_poweron = (3,)
    oid_poweroff = (4,)

    status_off = 0
    status_on = 1
    status_pending_off = 2
    status_pending_on = 3

    value_power_on = 0
    value_power_off = 0

    def __init__(self, *args, **kwargs):
        super(SNMPDriverEatonPower, self).__init__(*args, **kwargs)
        # Due to its use of different OIDs for different actions, we only form
        # an OID that holds the common substring of the OIDs for power
        # operations.
        self.oid_base = self.oid_enterprise + self.oid_device

    def _snmp_oid(self, oid):
        """Return the OID for one of the outlet control objects.

        :param oid: The action-dependent portion of the OID, as a tuple of
            integers.
        :returns: The full OID as a tuple of integers.
        """
        outlet = self.snmp_info['outlet']
        return self.oid_base + oid + (outlet,)

    def _snmp_power_state(self):
        oid = self._snmp_oid(self.oid_status)
        state = self.client.get(oid)

        # Translate the state to an Ironic power state.
        if state in (self.status_on, self.status_pending_off):
            power_state = states.POWER_ON
        elif state in (self.status_off, self.status_pending_on):
            power_state = states.POWER_OFF
        else:
            LOG.warning("Eaton Power SNMP PDU %(addr)s outlet %(outlet)s: "
                        "unrecognised power state %(state)s.",
                        {'addr': self.snmp_info['address'],
                         'outlet': self.snmp_info['outlet'],
                         'state': state})
            power_state = states.ERROR

        return power_state

    def _snmp_power_on(self):
        oid = self._snmp_oid(self.oid_poweron)
        value = rfc1902.Integer(self.value_power_on)
        self.client.set(oid, value)

    def _snmp_power_off(self):
        oid = self._snmp_oid(self.oid_poweroff)
        value = rfc1902.Integer(self.value_power_off)
        self.client.set(oid, value)


# A dictionary of supported drivers keyed by snmp_driver attribute
DRIVER_CLASSES = {
    'apc': SNMPDriverAPCMasterSwitch,
    'apc_masterswitch': SNMPDriverAPCMasterSwitch,
    'apc_masterswitchplus': SNMPDriverAPCMasterSwitchPlus,
    'apc_rackpdu': SNMPDriverAPCRackPDU,
    'aten': SNMPDriverAten,
    'cyberpower': SNMPDriverCyberPower,
    'eatonpower': SNMPDriverEatonPower,
    'teltronix': SNMPDriverTeltronix
}


def _parse_driver_info(node):
    """Parse a node's driver_info values.

    Return a dictionary of validated driver information, usable for
    SNMPDriver object creation.

    :param node: An Ironic node object.
    :returns: SNMP driver info.
    :raises: MissingParameterValue if any required parameters are missing.
    :raises: InvalidParameterValue if any parameters are invalid.
    """
    info = node.driver_info or {}
    missing_info = [key for key in REQUIRED_PROPERTIES if not info.get(key)]
    if missing_info:
        raise exception.MissingParameterValue(_(
            "SNMP driver requires the following parameters to be set in "
            "node's driver_info: %s.") % missing_info)

    snmp_info = {}

    # Validate PDU driver type
    snmp_info['driver'] = info['snmp_driver']
    if snmp_info['driver'] not in DRIVER_CLASSES:
        raise exception.InvalidParameterValue(_(
            "SNMPPowerDriver: unknown driver: '%s'") % snmp_info['driver'])

    # In absence of a version, default to SNMPv1
    snmp_info['version'] = info.get('snmp_version', SNMP_V1)
    if snmp_info['version'] not in (SNMP_V1, SNMP_V2C, SNMP_V3):
        raise exception.InvalidParameterValue(_(
            "SNMPPowerDriver: unknown SNMP version: '%s'") %
            snmp_info['version'])

    # In absence of a configured UDP port, default to the standard port
    port_str = info.get('snmp_port', SNMP_PORT)
    snmp_info['port'] = utils.validate_network_port(port_str, 'snmp_port')

    if snmp_info['port'] < 1 or snmp_info['port'] > 65535:
        raise exception.InvalidParameterValue(_(
            "SNMPPowerDriver: SNMP UDP port out of range: %d")
            % snmp_info['port'])

    # Extract version-dependent required parameters
    if snmp_info['version'] in (SNMP_V1, SNMP_V2C):
        if 'snmp_community' not in info:
            raise exception.MissingParameterValue(_(
                "SNMP driver requires snmp_community to be set for version "
                "%s.") % snmp_info['version'])
        snmp_info['community'] = info.get('snmp_community')
    elif snmp_info['version'] == SNMP_V3:
        if 'snmp_security' not in info:
            raise exception.MissingParameterValue(_(
                "SNMP driver requires snmp_security to be set for version %s.")
                % (SNMP_V3))
        snmp_info['security'] = info.get('snmp_security')

    # Target PDU IP address and power outlet identification
    snmp_info['address'] = info['snmp_address']
    outlet = info['snmp_outlet']
    try:
        snmp_info['outlet'] = int(outlet)
    except ValueError:
        raise exception.InvalidParameterValue(_(
            "SNMPPowerDriver: PDU power outlet index is not an integer: %s")
            % outlet)

    return snmp_info


def _get_driver(node):
    """Return a new SNMP driver object of the correct type for `node`.

    :param node: Single node object.
    :raises: InvalidParameterValue if node power config is incomplete or
        invalid.
    :returns: SNMP driver object.
    """
    snmp_info = _parse_driver_info(node)
    cls = DRIVER_CLASSES[snmp_info['driver']]
    return cls(snmp_info)


class SNMPPower(base.PowerInterface):
    """SNMP Power Interface.

    This PowerInterface class provides a mechanism for controlling the power
    state of a physical device using an SNMP-enabled smart power controller.
    """

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return COMMON_PROPERTIES

    def validate(self, task):
        """Check that node.driver_info contains the requisite fields.

        :raises: MissingParameterValue if required SNMP parameters are missing.
        :raises: InvalidParameterValue if SNMP parameters are invalid.
        """
        _parse_driver_info(task.node)

    def get_power_state(self, task):
        """Get the current power state.

        Poll the SNMP device for the current power state of the node.

        :param task: A instance of `ironic.manager.task_manager.TaskManager`.
        :raises: MissingParameterValue if required SNMP parameters are missing.
        :raises: InvalidParameterValue if SNMP parameters are invalid.
        :raises: SNMPFailure if an SNMP request fails.
        :returns: power state. One of :class:`ironic.common.states`.
        """
        driver = _get_driver(task.node)
        power_state = driver.power_state()
        return power_state

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, pstate):
        """Turn the power on or off.

        Set the power state of a node.

        :param task: A instance of `ironic.manager.task_manager.TaskManager`.
        :param pstate: Either POWER_ON or POWER_OFF from :class:
            `ironic.common.states`.
        :raises: MissingParameterValue if required SNMP parameters are missing.
        :raises: InvalidParameterValue if SNMP parameters are invalid or
            `pstate` is invalid.
        :raises: PowerStateFailure if the final power state of the node is not
            as requested after the timeout.
        :raises: SNMPFailure if an SNMP request fails.
        """

        driver = _get_driver(task.node)
        if pstate == states.POWER_ON:
            state = driver.power_on()
        elif pstate == states.POWER_OFF:
            state = driver.power_off()
        else:
            raise exception.InvalidParameterValue(_("set_power_state called "
                                                    "with invalid power "
                                                    "state %s.") % str(pstate))
        if state != pstate:
            raise exception.PowerStateFailure(pstate=pstate)

    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Cycles the power to a node.

        :param task: A instance of `ironic.manager.task_manager.TaskManager`.
        :raises: MissingParameterValue if required SNMP parameters are missing.
        :raises: InvalidParameterValue if SNMP parameters are invalid.
        :raises: PowerStateFailure if the final power state of the node is not
            POWER_ON after the timeout.
        :raises: SNMPFailure if an SNMP request fails.
        """

        driver = _get_driver(task.node)
        state = driver.power_reset()
        if state != states.POWER_ON:
            raise exception.PowerStateFailure(pstate=states.POWER_ON)
