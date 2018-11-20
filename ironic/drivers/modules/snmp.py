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
    from pysnmp import error as snmp_error
    from pysnmp import hlapi as snmp

    snmp_auth_protocols = {
        'md5': snmp.usmHMACMD5AuthProtocol,
        'sha': snmp.usmHMACSHAAuthProtocol,
        'none': snmp.usmNoAuthProtocol,
    }

    # available since pysnmp 4.4.1
    try:
        snmp_auth_protocols.update(
            {
                'sha224': snmp.usmHMAC128SHA224AuthProtocol,
                'sha256': snmp.usmHMAC192SHA256AuthProtocol,
                'sha384': snmp.usmHMAC256SHA384AuthProtocol,
                'sha512': snmp.usmHMAC384SHA512AuthProtocol,

            }
        )

    except AttributeError:
        pass

    snmp_priv_protocols = {
        'des': snmp.usmDESPrivProtocol,
        '3des': snmp.usm3DESEDEPrivProtocol,
        'aes': snmp.usmAesCfb128Protocol,
        'aes192': snmp.usmAesCfb192Protocol,
        'aes256': snmp.usmAesCfb256Protocol,
        'none': snmp.usmNoPrivProtocol,
    }

    # available since pysnmp 4.4.3
    try:
        snmp_priv_protocols.update(
            {
                'aes192blmt': snmp.usmAesBlumenthalCfb192Protocol,
                'aes256blmt': snmp.usmAesBlumenthalCfb256Protocol,

            }
        )

    except AttributeError:
        pass

else:
    snmp = None
    snmp_error = None

    snmp_auth_protocols = {
        'none': None
    }

    snmp_priv_protocols = {
        'none': None
    }

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
          "(optional, default %(v1)s).")
        % {"v1": SNMP_V1, "v2c": SNMP_V2C, "v3": SNMP_V3},
    'snmp_port':
        _("SNMP port, default %(port)d.") % {"port": SNMP_PORT},
    'snmp_community':
        _("SNMP community name to use for read and/or write class SNMP "
          "commands unless `snmp_community_read` and/or "
          "`snmp_community_write` properties are present in which case the "
          "latter takes over. Applicable only to versions %(v1)s and %(v2c)s.")
        % {"v1": SNMP_V1, "v2c": SNMP_V2C},
    'snmp_community_read':
        _("SNMP community name to use for read class SNMP commands. "
          "Takes precedence over the `snmp_community` property. "
          "Applicable only to versions %(v1)s and %(v2c)s.")
        % {"v1": SNMP_V1, "v2c": SNMP_V2C},
    'snmp_community_write':
        _("SNMP community name to use for write class SNMP commands. "
          "Takes precedence over the `snmp_community` property. "
          "Applicable only to versions %(v1)s and %(v2c)s.")
        % {"v1": SNMP_V1, "v2c": SNMP_V2C},
    'snmp_user':
        _("SNMPv3 User-based Security Model (USM) username. "
          "Required for version %(v3)s.")
        % {"v3": SNMP_V3},
    'snmp_auth_protocol':
        _("SNMPv3 message authentication protocol ID. "
          "Known values are: %(auth)s. "
          "Default is 'none' unless 'snmp_auth_key' is provided. "
          "In the latter case 'md5' is the default.")
        % {'auth': sorted(snmp_auth_protocols)},
    'snmp_auth_key':
        _("SNMPv3 message authentication key. "
          "Must be 8+ characters long. "
          "Required when message authentication is used. "
          "This key is used by the 'snmp_auth_protocol' algorithm."),
    'snmp_priv_protocol':
        _("SNMPv3 message privacy (encryption) protocol ID. "
          "Known values are: %(priv)s. "
          "Using message privacy requires using message authentication. "
          "Default is 'none' unless 'snmp_priv_key' is provided. "
          "In the latter case 'des' is the default.")
        % {'priv': sorted(snmp_priv_protocols)},
    'snmp_priv_key':
        _("SNMPv3 message authentication key. "
          "Must be 8+ characters long. "
          "Required when message authentication is used. "
          "This key is used by the 'snmp_priv_protocol' algorithm."),
    'snmp_context_engine_id':
        _("SNMPv3 context engine ID. "
          "Default is the value of authoritative engine ID."),
    'snmp_context_name':
        _("SNMPv3 context name. "
          "Default is an empty string ('')."),
}

DEPRECATED_PROPERTIES = {
    # synonym for `snmp_user`
    'snmp_security':
        _("SNMPv3 User-based Security Model (USM) username. "
          "Required for version %(v3)s. "
          "This property is deprecated, please use `snmp_user` instead.")
        % {"v3": SNMP_V3},
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)
COMMON_PROPERTIES.update(DEPRECATED_PROPERTIES)


class SNMPClient(object):
    """SNMP client object.

    Performs low level SNMP get and set operations. Encapsulates all
    interaction with PySNMP to simplify dynamic importing and unit testing.
    """

    def __init__(self, address, port, version,
                 read_community=None, write_community=None,
                 user=None, auth_proto=None,
                 auth_key=None, priv_proto=None,
                 priv_key=None, context_engine_id=None, context_name=None):
        if not snmp:
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import python-pysnmp library")
            )

        self.address = address
        self.port = port
        self.version = version
        if self.version == SNMP_V3:
            self.user = user
            self.auth_proto = auth_proto
            self.auth_key = auth_key
            self.priv_proto = priv_proto
            self.priv_key = priv_key
        else:
            self.read_community = read_community
            self.write_community = write_community

        self.context_engine_id = context_engine_id
        self.context_name = context_name or ''

        self.snmp_engine = snmp.SnmpEngine()

    def _get_auth(self, write_mode=False):
        """Return the authorization data for an SNMP request.

        :param write_mode: `True` if write class SNMP command is
            executed. Default is `False`.
        :returns: Either
            :class:`pysnmp.hlapi.CommunityData`
            or :class:`pysnmp.hlapi.UsmUserData`
            object depending on SNMP version being used.
        """
        if self.version == SNMP_V3:
            return snmp.UsmUserData(
                self.user,
                authKey=self.auth_key,
                authProtocol=self.auth_proto,
                privKey=self.priv_key,
                privProtocol=self.priv_proto
            )

        else:
            mp_model = 1 if self.version == SNMP_V2C else 0
            return snmp.CommunityData(
                self.write_community if write_mode else self.read_community,
                mpModel=mp_model
            )

    def _get_transport(self):
        """Return the transport target for an SNMP request.

        :returns: A :class:
            `pysnmp.hlapi.UdpTransportTarget` object.
        :raises: :class:`pysnmp.error.PySnmpError` if the transport address
            is bad.
        """
        # The transport target accepts timeout and retries parameters, which
        # default to 1 (second) and 5 respectively. These are deemed sensible
        # enough to allow for an unreliable network or slow device.
        return snmp.UdpTransportTarget(
            (self.address, self.port),
            timeout=CONF.snmp.udp_transport_timeout,
            retries=CONF.snmp.udp_transport_retries)

    def _get_context(self):
        """Return the SNMP context for an SNMP request.

        :returns: A :class:
            `pysnmp.hlapi.ContextData` object.
        :raises: :class:`pysnmp.error.PySnmpError` if SNMP context data
            is bad.
        """
        return snmp.ContextData(
            contextEngineId=self.context_engine_id,
            contextName=self.context_name
        )

    def get(self, oid):
        """Use PySNMP to perform an SNMP GET operation on a single object.

        :param oid: The OID of the object to get.
        :raises: SNMPFailure if an SNMP request fails.
        :returns: The value of the requested object.
        """
        try:
            snmp_gen = snmp.getCmd(self.snmp_engine,
                                   self._get_auth(),
                                   self._get_transport(),
                                   self._get_context(),
                                   snmp.ObjectType(snmp.ObjectIdentity(oid)))

        except snmp_error.PySnmpError as e:
            raise exception.SNMPFailure(operation="GET", error=e)

        error_indication, error_status, error_index, var_binds = next(snmp_gen)

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
            snmp_gen = snmp.nextCmd(self.snmp_engine,
                                    self._get_auth(),
                                    self._get_transport(),
                                    self._get_context(),
                                    snmp.ObjectType(snmp.ObjectIdentity(oid)),
                                    lexicographicMode=False)

        except snmp_error.PySnmpError as e:
            raise exception.SNMPFailure(operation="GET_NEXT", error=e)

        vals = []
        for (error_indication, error_status, error_index,
                var_binds) in snmp_gen:

            if error_indication:
                # SNMP engine-level error.
                raise exception.SNMPFailure(operation="GET_NEXT",
                                            error=error_indication)

            if error_status:
                # SNMP PDU error.
                raise exception.SNMPFailure(operation="GET_NEXT",
                                            error=error_status.prettyPrint())

            # this is not a table, but a table row
            # e.g. 1-D array of tuples
            _name, value = var_binds[0]
            vals.append(value)

        return vals

    def set(self, oid, value):
        """Use PySNMP to perform an SNMP SET operation on a single object.

        :param oid: The OID of the object to set.
        :param value: The value of the object to set.
        :raises: SNMPFailure if an SNMP request fails.
        """
        try:
            snmp_gen = snmp.setCmd(self.snmp_engine,
                                   self._get_auth(write_mode=True),
                                   self._get_transport(),
                                   self._get_context(),
                                   snmp.ObjectType(
                                       snmp.ObjectIdentity(oid), value))

        except snmp_error.PySnmpError as e:
            raise exception.SNMPFailure(operation="SET", error=e)

        error_indication, error_status, error_index, var_binds = next(snmp_gen)

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
                      snmp_info.get("read_community"),
                      snmp_info.get("write_community"),
                      snmp_info.get("user"),
                      snmp_info.get("auth_proto"),
                      snmp_info.get("auth_key"),
                      snmp_info.get("priv_proto"),
                      snmp_info.get("priv_key"),
                      snmp_info.get("context_engine_id"),
                      snmp_info.get("context_name"))


_memoized = {}


def memoize(f):
    def memoized(self, node_info):
        hashable_node_info = frozenset((key, val)
                                       for key, val in node_info.items()
                                       if key is not 'outlet')
        if hashable_node_info not in _memoized:
            _memoized[hashable_node_info] = f(self)
        return _memoized[hashable_node_info]
    return memoized


def retry_on_outdated_cache(f):
    def wrapper(self):
        try:
            return f(self)

        except exception.SNMPFailure:
            hashable_node_info = (
                frozenset((key, val)
                          for key, val in self.snmp_info.items()
                          if key is not 'outlet')
            )
            del _memoized[hashable_node_info]
            self.driver = self._get_pdu_driver(self.snmp_info)
            return f(self)

    return wrapper


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
        value = snmp.Integer(self.value_power_on)
        self.client.set(self.oid, value)

    def _snmp_power_off(self):
        value = snmp.Integer(self.value_power_off)
        self.client.set(self.oid, value)


class SNMPDriverAten(SNMPDriverSimple):
    """SNMP driver class for Aten PDU devices.

    SNMP objects for Aten PDU:
    1.3.6.1.4.1.21317.1.3.2.2.2.2 Outlet Power
    Values: 1=Off, 2=On, 3=Pending, 4=Reset
    """
    system_id = (21317,)
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

    system_id = (318, 1, 1, 4)
    oid_device = (318, 1, 1, 4, 4, 2, 1, 3)
    value_power_on = 1
    value_power_off = 2


class SNMPDriverAPCMasterSwitchPlus(SNMPDriverSimple):
    """SNMP driver class for APC MasterSwitchPlus PDU devices.

    SNMP objects for APC SNMPDriverAPCMasterSwitchPlus PDU:
    1.3.6.1.4.1.318.1.1.6.5.1.1.5 sPDUOutletControlMSPOutletCommand
    Values: 1=On, 3=Off, [...more options follow]
    """

    system_id = (318, 1, 1, 6)
    oid_device = (318, 1, 1, 6, 5, 1, 1, 5)
    value_power_on = 1
    value_power_off = 3


class SNMPDriverAPCRackPDU(SNMPDriverSimple):
    """SNMP driver class for APC RackPDU devices.

    SNMP objects for APC SNMPDriverAPCRackPDU PDU:
    # 1.3.6.1.4.1.318.1.1.12.3.3.1.1.4 rPDUOutletControlOutletCommand
    Values: 1=On, 2=Off, 3=PowerCycle, [...more options follow]
    """

    system_id = (318, 1, 1, 12)
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

    system_id = (3808,)
    oid_device = (3808, 1, 1, 3, 3, 3, 1, 1, 4)
    value_power_on = 1
    value_power_off = 2


class SNMPDriverTeltronix(SNMPDriverSimple):
    """SNMP driver class for Teltronix PDU devices.

    SNMP objects for Teltronix PDU:
    1.3.6.1.4.1.23620.1.2.2.1.4   Outlet Power
    Values: 1=Off, 2=On
    """

    system_id = (23620,)
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

    system_id = (534,)
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
        value = snmp.Integer(self.value_power_on)
        self.client.set(oid, value)

    def _snmp_power_off(self):
        oid = self._snmp_oid(self.oid_poweroff)
        value = snmp.Integer(self.value_power_off)
        self.client.set(oid, value)


class SNMPDriverBaytechMRP27(SNMPDriverSimple):
    """SNMP driver class for Baytech MRP27 PDU devices.

    SNMP objects for Baytech MRP27 PDU:
    4779, 1, 3, 5, 3, 1, 3, {unit_id}  Outlet Power
    Values: 0=Off, 1=On, 2=Reboot
    """

    # TODO(srobert): Add support for dynamically allocated unit_id when needed
    unit_id = 1
    oid_device = (4779, 1, 3, 5, 3, 1, 3) + (unit_id,)
    value_power_off = 0
    value_power_on = 1


class SNMPDriverAuto(SNMPDriverBase):

    SYS_OBJ_OID = (1, 3, 6, 1, 2, 1, 1, 2)

    def __init__(self, *args, **kwargs):
        super(SNMPDriverAuto, self).__init__(*args, **kwargs)
        self.driver = self._get_pdu_driver(*args, **kwargs)

    def _get_pdu_driver(self, *args, **kwargs):
        drivers_map = {}

        for name, obj in DRIVER_CLASSES.items():
            if not getattr(obj, 'system_id', False):
                continue

            system_id = self.oid_enterprise + getattr(obj, 'system_id')

            if (system_id in drivers_map and
                    drivers_map[system_id] is not obj):
                raise exception.InvalidParameterValue(_(
                    "SNMPDriverAuto: duplicate driver system ID prefix "
                    "%(system_id)s") % {'system_id': system_id})

            drivers_map[system_id] = obj
            LOG.debug("SNMP driver mapping %(system_id)s -> %(name)s",
                      {'system_id': system_id, 'name': obj.__name__})

        system_id = self._fetch_driver(*args, **kwargs)

        LOG.debug("SNMP device reports sysObjectID %(system_id)s",
                  {'system_id': system_id})

        system_id_prefix = tuple(system_id)

        # pick driver by the longest matching sysObjectID prefix
        while len(system_id_prefix) > len(self.oid_enterprise):
            try:
                Driver = drivers_map[system_id_prefix]
                LOG.debug("Chosen SNMP driver %(name)s based on sysObjectID "
                          "prefix %(system_id_prefix)s", {Driver.__name__,
                                                          system_id_prefix})
                return Driver(*args, **kwargs)

            except KeyError:
                system_id_prefix = system_id_prefix[:-1]

        raise exception.InvalidParameterValue(_(
            "SNMPDriverAuto: no driver matching %(system_id)s") %
            {'system_id': system_id})

    @retry_on_outdated_cache
    def _snmp_power_state(self):
        current_power_state = self.driver._snmp_power_state()
        return current_power_state

    @retry_on_outdated_cache
    def _snmp_power_on(self):
        return self.driver._snmp_power_on()

    @retry_on_outdated_cache
    def _snmp_power_off(self):
        return self.driver._snmp_power_off()

    @memoize
    def _fetch_driver(self):
        return self.client.get(self.SYS_OBJ_OID)

# A dictionary of supported drivers keyed by snmp_driver attribute
DRIVER_CLASSES = {
    'apc': SNMPDriverAPCMasterSwitch,
    'apc_masterswitch': SNMPDriverAPCMasterSwitch,
    'apc_masterswitchplus': SNMPDriverAPCMasterSwitchPlus,
    'apc_rackpdu': SNMPDriverAPCRackPDU,
    'aten': SNMPDriverAten,
    'cyberpower': SNMPDriverCyberPower,
    'eatonpower': SNMPDriverEatonPower,
    'teltronix': SNMPDriverTeltronix,
    'baytech_mrp27': SNMPDriverBaytechMRP27,
    'auto': SNMPDriverAuto,
}


def _parse_driver_info_snmpv3_user(node, info):
    snmp_info = {}

    if 'snmp_user' not in info and 'snmp_security' not in info:
        raise exception.MissingParameterValue(_(
            "SNMP driver requires `driver_info/snmp_user` to be set in "
            "node %(node)s configuration for SNMP version %(ver)s.") %
            {'node': node.uuid, 'ver': SNMP_V3})

    snmp_info['user'] = info.get('snmp_user', info.get('snmp_security'))

    if 'snmp_security' in info:
        LOG.warning("The `driver_info/snmp_security` parameter is deprecated "
                    "in favor of `driver_info/snmp_user` parameter. Please "
                    "remove the `driver_info/snmp_security` parameter from "
                    "node %(node)s configuration.", {'node': node.uuid})

        if 'snmp_user' in info:
            LOG.warning("The `driver_info/snmp_security` parameter is ignored "
                        "in favor of `driver_info/snmp_user` parameter in "
                        "node %(node)s configuration.", {'node': node.uuid})

    return snmp_info


def _parse_driver_info_snmpv3_crypto(node, info):
    snmp_info = {}

    if 'snmp_auth_protocol' in info:
        auth_p = info['snmp_auth_protocol']
        try:
            snmp_info['auth_protocol'] = snmp_auth_protocols[auth_p]

        except KeyError:
            raise exception.InvalidParameterValue(_(
                "SNMPPowerDriver: unknown SNMPv3 authentication protocol "
                "`driver_info/snmp_auth_protocol` %(proto)s in node %(node)s "
                "configuration, known protocols are: %(protos)s") %
                {'node': node.uuid, 'proto': auth_p,
                 'protos': ', '.join(snmp_auth_protocols)}
            )
    if 'snmp_priv_protocol' in info:
        priv_p = info['snmp_priv_protocol']
        try:
            snmp_info['priv_protocol'] = snmp_priv_protocols[priv_p]

        except KeyError:
            raise exception.InvalidParameterValue(_(
                "SNMPPowerDriver: unknown SNMPv3 privacy protocol "
                "`driver_info/snmp_priv_protocol` %(proto)s in node "
                "%(node)s configuration, known protocols are: %(protos)s") %
                {'node': node.uuid, 'proto': priv_p,
                 'protos': ', '.join(snmp_priv_protocols)}
            )
    if 'snmp_auth_key' in info:
        auth_k = info['snmp_auth_key']
        if len(auth_k) < 8:
            raise exception.InvalidParameterValue(_(
                "SNMPPowerDriver: short SNMPv3 authentication key "
                "`driver_info/snmp_auth_key` in node %(node)s configuration "
                "(8+ chars required)") % {'node': node.uuid})

        snmp_info['auth_key'] = auth_k

        if 'auth_protocol' not in snmp_info:
            snmp_info['auth_protocol'] = snmp_auth_protocols['md5']

    if 'snmp_priv_key' in info:
        priv_k = info['snmp_priv_key']
        if len(priv_k) < 8:
            raise exception.InvalidParameterValue(_(
                "SNMPPowerDriver: short SNMPv3 privacy key "
                "`driver_info/snmp_priv_key` node %(node)s configuration "
                "(8+ chars required)") % {'node': node.uuid})

        snmp_info['priv_key'] = priv_k

        if 'priv_protocol' not in snmp_info:
            snmp_info['priv_protocol'] = snmp_priv_protocols['des']

    if ('priv_protocol' in snmp_info and
            'auth_protocol' not in snmp_info):
        raise exception.MissingParameterValue(_(
            "SNMPPowerDriver: SNMPv3 privacy requires authentication. "
            "Please add `driver_info/auth_protocol` property to node "
            "%(node)s configuration.") % {'node': node.uuid})

    if ('auth_protocol' in snmp_info and
            'auth_key' not in snmp_info):
        raise exception.MissingParameterValue(_(
            "SNMPPowerDriver: missing SNMPv3 authentication key while "
            "`driver_info/snmp_auth_protocol` is present. Please "
            "add `driver_info/snmp_auth_key` to node %(node)s "
            "configuration.") % {'node': node.uuid})

    if ('priv_protocol' in snmp_info and
            'priv_key' not in snmp_info):
        raise exception.MissingParameterValue(_(
            "SNMPPowerDriver: missing SNMPv3 privacy key while "
            "`driver_info/snmp_priv_protocol` is present. Please "
            "add `driver_info/snmp_priv_key` to node %(node)s "
            "configuration.") % {'node': node.uuid})

    return snmp_info


def _parse_driver_info_snmpv3_context(node, info):
    snmp_info = {}

    if 'snmp_context_engine_id' in info:
        snmp_info['context_engine_id'] = info['snmp_context_engine_id']

    if 'snmp_context_name' in info:
        snmp_info['context_name'] = info['snmp_context_name']

    return snmp_info


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
        read_community = info.get('snmp_community_read')
        if read_community is None:
            read_community = info.get('snmp_community')

        write_community = info.get('snmp_community_write')
        if write_community is None:
            write_community = info.get('snmp_community')

        if not read_community or not write_community:
            raise exception.MissingParameterValue(_(
                "SNMP driver requires `snmp_community` or "
                "`snmp_community_read`/`snmp_community_write` properties "
                "to be set for version %s.") % snmp_info['version'])
        snmp_info['read_community'] = read_community
        snmp_info['write_community'] = write_community

    elif snmp_info['version'] == SNMP_V3:
        snmp_info.update(_parse_driver_info_snmpv3_user(node, info))
        snmp_info.update(_parse_driver_info_snmpv3_crypto(node, info))
        snmp_info.update(_parse_driver_info_snmpv3_context(node, info))

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

        :param task: An instance of `ironic.manager.task_manager.TaskManager`.
        :raises: MissingParameterValue if required SNMP parameters are missing.
        :raises: InvalidParameterValue if SNMP parameters are invalid.
        :raises: SNMPFailure if an SNMP request fails.
        :returns: power state. One of :class:`ironic.common.states`.
        """
        driver = _get_driver(task.node)
        power_state = driver.power_state()
        return power_state

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, pstate, timeout=None):
        """Turn the power on or off.

        Set the power state of a node.

        :param task: An instance of `ironic.manager.task_manager.TaskManager`.
        :param pstate: Either POWER_ON or POWER_OFF from :class:
            `ironic.common.states`.
        :param timeout: timeout (in seconds). Unsupported by this interface.
        :raises: MissingParameterValue if required SNMP parameters are missing.
        :raises: InvalidParameterValue if SNMP parameters are invalid or
            `pstate` is invalid.
        :raises: PowerStateFailure if the final power state of the node is not
            as requested after the timeout.
        :raises: SNMPFailure if an SNMP request fails.
        """
        # TODO(rloo): Support timeouts!
        if timeout is not None:
            LOG.warning(
                "The 'snmp' Power Interface's 'set_power_state' method "
                "doesn't support the 'timeout' parameter. Ignoring "
                "timeout=%(timeout)s",
                {'timeout': timeout})

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
    def reboot(self, task, timeout=None):
        """Cycles the power to a node.

        :param task: An instance of `ironic.manager.task_manager.TaskManager`.
        :param timeout: timeout (in seconds). Unsupported by this interface.
        :raises: MissingParameterValue if required SNMP parameters are missing.
        :raises: InvalidParameterValue if SNMP parameters are invalid.
        :raises: PowerStateFailure if the final power state of the node is not
            POWER_ON after the timeout.
        :raises: SNMPFailure if an SNMP request fails.
        """
        # TODO(rloo): Support timeouts!
        if timeout is not None:
            LOG.warning("The 'snmp' Power Interface's 'reboot' method "
                        "doesn't support the 'timeout' parameter. Ignoring "
                        "timeout=%(timeout)s",
                        {'timeout': timeout})

        driver = _get_driver(task.node)
        state = driver.power_reset()
        if state != states.POWER_ON:
            raise exception.PowerStateFailure(pstate=states.POWER_ON)
