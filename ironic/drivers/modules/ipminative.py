# coding=utf-8

# Copyright 2013 International Business Machines Corporation
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
Ironic Native IPMI power manager.
"""

import os

from ironic_lib import metrics_utils
from ironic_lib import utils as ironic_utils
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import strutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _, _LE, _LW
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import console_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers import utils as driver_utils

pyghmi = importutils.try_import('pyghmi')
if pyghmi:
    from pyghmi import exceptions as pyghmi_exception
    from pyghmi.ipmi import command as ipmi_command

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

REQUIRED_PROPERTIES = {'ipmi_address': _("IP of the node's BMC. Required."),
                       'ipmi_password': _("IPMI password. Required."),
                       'ipmi_username': _("IPMI username. Required.")}
OPTIONAL_PROPERTIES = {
    'ipmi_force_boot_device': _("Whether Ironic should specify the boot "
                                "device to the BMC each time the server "
                                "is turned on, eg. because the BMC is not "
                                "capable of remembering the selected boot "
                                "device across power cycles; default value "
                                "is False. Optional.")
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)
CONSOLE_PROPERTIES = {
    'ipmi_terminal_port': _("node's UDP port to connect to. Only required for "
                            "console access.")
}

_BOOT_DEVICES_MAP = {
    boot_devices.DISK: 'hd',
    boot_devices.PXE: 'network',
    boot_devices.CDROM: 'cdrom',
    boot_devices.BIOS: 'setup',
}


def _parse_driver_info(node):
    """Gets the bmc access info for the given node.

    :raises: MissingParameterValue when required ipmi credentials
            are missing.
    :raises: InvalidParameterValue when the IPMI terminal port is not an
            integer.
    """

    info = node.driver_info or {}
    missing_info = [key for key in REQUIRED_PROPERTIES if not info.get(key)]
    if missing_info:
        raise exception.MissingParameterValue(_(
            "Missing the following IPMI credentials in node's"
            " driver_info: %s.") % missing_info)

    bmc_info = {}
    bmc_info['address'] = info.get('ipmi_address')
    bmc_info['username'] = info.get('ipmi_username')
    bmc_info['password'] = info.get('ipmi_password')
    bmc_info['force_boot_device'] = info.get('ipmi_force_boot_device', False)

    # get additional info
    bmc_info['uuid'] = node.uuid

    # terminal port must be an integer
    port = info.get('ipmi_terminal_port')
    if port is not None:
        port = utils.validate_network_port(port, 'ipmi_terminal_port')
    bmc_info['port'] = port

    return bmc_info


def _console_pwfile_path(uuid):
    """Return the file path for storing the ipmi password."""
    file_name = "%(uuid)s.pw" % {'uuid': uuid}
    return os.path.join(CONF.tempdir, file_name)


def _power_on(driver_info):
    """Turn the power on for this node.

    :param driver_info: the bmc access info for a node.
    :returns: power state POWER_ON, one of :class:`ironic.common.states`.
    :raises: IPMIFailure when the native ipmi call fails.
    :raises: PowerStateFailure when invalid power state is returned
             from ipmi.
    """

    msg = _("IPMI power on failed for node %(node_id)s with the "
            "following error: %(error)s")
    try:
        ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                                       userid=driver_info['username'],
                                       password=driver_info['password'])
        wait = CONF.ipmi.retry_timeout
        ret = ipmicmd.set_power('on', wait)
    except pyghmi_exception.IpmiException as e:
        error = msg % {'node_id': driver_info['uuid'], 'error': e}
        LOG.error(error)
        raise exception.IPMIFailure(error)

    state = ret.get('powerstate')
    if state == 'on':
        return states.POWER_ON
    else:
        error = _("bad response: %s") % ret
        LOG.error(msg, {'node_id': driver_info['uuid'], 'error': error})
        raise exception.PowerStateFailure(pstate=states.POWER_ON)


def _power_off(driver_info):
    """Turn the power off for this node.

    :param driver_info: the bmc access info for a node.
    :returns: power state POWER_OFF, one of :class:`ironic.common.states`.
    :raises: IPMIFailure when the native ipmi call fails.
    :raises: PowerStateFailure when invalid power state is returned
             from ipmi.
    """

    msg = _("IPMI power off failed for node %(node_id)s with the "
            "following error: %(error)s")
    try:
        ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                                       userid=driver_info['username'],
                                       password=driver_info['password'])
        wait = CONF.ipmi.retry_timeout
        ret = ipmicmd.set_power('off', wait)
    except pyghmi_exception.IpmiException as e:
        error = msg % {'node_id': driver_info['uuid'], 'error': e}
        LOG.error(error)
        raise exception.IPMIFailure(error)

    state = ret.get('powerstate')
    if state == 'off':
        return states.POWER_OFF
    else:
        error = _("bad response: %s") % ret
        LOG.error(msg, {'node_id': driver_info['uuid'], 'error': error})
        raise exception.PowerStateFailure(pstate=states.POWER_OFF)


def _reboot(driver_info):
    """Reboot this node.

    If the power is off, turn it on. If the power is on, reset it.

    :param driver_info: the bmc access info for a node.
    :returns: power state POWER_ON, one of :class:`ironic.common.states`.
    :raises: IPMIFailure when the native ipmi call fails.
    :raises: PowerStateFailure when invalid power state is returned
             from ipmi.
    """

    msg = _("IPMI power reboot failed for node %(node_id)s with the "
            "following error: %(error)s")
    try:
        ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                                       userid=driver_info['username'],
                                       password=driver_info['password'])
        wait = CONF.ipmi.retry_timeout
        ret = ipmicmd.set_power('boot', wait)
    except pyghmi_exception.IpmiException as e:
        error = msg % {'node_id': driver_info['uuid'], 'error': e}
        LOG.error(error)
        raise exception.IPMIFailure(error)

    if 'error' in ret:
        error = _("bad response: %s") % ret
        LOG.error(msg, {'node_id': driver_info['uuid'], 'error': error})
        raise exception.PowerStateFailure(pstate=states.REBOOT)

    return states.POWER_ON


def _power_status(driver_info):
    """Get the power status for this node.

    :param driver_info: the bmc access info for a node.
    :returns: power state POWER_ON, POWER_OFF or ERROR defined in
             :class:`ironic.common.states`.
    :raises: IPMIFailure when the native ipmi call fails.
    """

    try:
        ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                                       userid=driver_info['username'],
                                       password=driver_info['password'])
        ret = ipmicmd.get_power()
    except pyghmi_exception.IpmiException as e:
        msg = (_("IPMI get power state failed for node %(node_id)s "
                 "with the following error: %(error)s") %
               {'node_id': driver_info['uuid'], 'error': e})
        LOG.error(msg)
        raise exception.IPMIFailure(msg)

    state = ret.get('powerstate')
    if state == 'on':
        return states.POWER_ON
    elif state == 'off':
        return states.POWER_OFF
    else:
        # NOTE(linggao): Do not throw an exception here because it might
        # return other valid values. It is up to the caller to decide
        # what to do.
        LOG.warning(_LW("IPMI get power state for node %(node_id)s returns the"
                        " following details: %(detail)s"),
                    {'node_id': driver_info['uuid'], 'detail': ret})
        return states.ERROR


def _get_sensors_data(driver_info):
    """Get sensors data.

    :param driver_info: node's driver info
    :raises: FailedToGetSensorData when getting the sensor data fails.
    :returns: returns a dict of sensor data group by sensor type.
    """
    try:
        ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                                       userid=driver_info['username'],
                                       password=driver_info['password'])
        ret = ipmicmd.get_sensor_data()
    except Exception as e:
        LOG.error(_LE("IPMI get sensor data failed for node %(node_id)s "
                  "with the following error: %(error)s"),
                  {'node_id': driver_info['uuid'], 'error': e})
        raise exception.FailedToGetSensorData(
            node=driver_info['uuid'], error=e)

    if not ret:
        return {}

    sensors_data = {}
    for reading in ret:
        # ignore the sensor data which has no sensor reading value
        if not reading.value:
            continue
        sensors_data.setdefault(
            reading.type,
            {})[reading.name] = {
                'Sensor Reading': '%s %s' % (reading.value, reading.units),
                'Sensor ID': reading.name,
                'States': str(reading.states),
                'Units': reading.units,
                'Health': str(reading.health)}

    return sensors_data


def _parse_raw_bytes(raw_bytes):
    """Parse raw bytes string.

    :param raw_bytes: a string of hexadecimal raw bytes, e.g. '0x00 0x01'.
    :returns: a tuple containing the arguments for pyghmi call as integers,
             (IPMI net function, IPMI command, list of command's data).
    :raises: InvalidParameterValue when an invalid value is specified.
    """
    try:
        bytes_list = [int(x, base=16) for x in raw_bytes.split()]
        return bytes_list[0], bytes_list[1], bytes_list[2:]
    except ValueError:
        raise exception.InvalidParameterValue(_(
            "Invalid raw bytes string: '%s'") % raw_bytes)
    except IndexError:
        raise exception.InvalidParameterValue(_(
            "Raw bytes string requires two bytes at least."))


def _send_raw(driver_info, raw_bytes):
    """Send raw bytes to the BMC."""
    netfn, command, data = _parse_raw_bytes(raw_bytes)
    LOG.debug("Sending raw bytes %(bytes)s to node %(node_id)s",
              {'bytes': raw_bytes, 'node_id': driver_info['uuid']})
    try:
        ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                                       userid=driver_info['username'],
                                       password=driver_info['password'])
        ipmicmd.xraw_command(netfn, command, data=data)
    except pyghmi_exception.IpmiException as e:
        msg = (_("IPMI send raw bytes '%(bytes)s' failed for node %(node_id)s"
                 " with the following error: %(error)s") %
               {'bytes': raw_bytes, 'node_id': driver_info['uuid'],
                'error': e})
        LOG.error(msg)
        raise exception.IPMIFailure(msg)


class NativeIPMIPower(base.PowerInterface):
    """The power driver using native python-ipmi library."""

    def get_properties(self):
        return COMMON_PROPERTIES

    @METRICS.timer('NativeIPMIPower.validate')
    def validate(self, task):
        """Check that node['driver_info'] contains IPMI credentials.

        :param task: a TaskManager instance containing the node to act on.
        :raises: MissingParameterValue when required ipmi credentials
                 are missing.
        """
        _parse_driver_info(task.node)

    @METRICS.timer('NativeIPMIPower.get_power_state')
    def get_power_state(self, task):
        """Get the current power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :returns:  power state POWER_ON, POWER_OFF or ERROR defined in
                 :class:`ironic.common.states`.
        :raises: MissingParameterValue when required ipmi credentials
                 are missing.
        :raises: IPMIFailure when the native ipmi call fails.
        """
        driver_info = _parse_driver_info(task.node)
        return _power_status(driver_info)

    @METRICS.timer('NativeIPMIPower.set_power_state')
    @task_manager.require_exclusive_lock
    def set_power_state(self, task, pstate):
        """Turn the power on or off.

        :param task: a TaskManager instance containing the node to act on.
        :param pstate: a power state that will be set on the task's node.
        :raises: IPMIFailure when the native ipmi call fails.
        :raises: MissingParameterValue when required ipmi credentials
                 are missing.
        :raises: InvalidParameterValue when an invalid power state
                 is specified
        :raises: PowerStateFailure when invalid power state is returned
                 from ipmi.
        """

        driver_info = _parse_driver_info(task.node)

        if pstate == states.POWER_ON:
            driver_utils.ensure_next_boot_device(task, driver_info)
            _power_on(driver_info)
        elif pstate == states.POWER_OFF:
            _power_off(driver_info)
        else:
            raise exception.InvalidParameterValue(
                _("set_power_state called with an invalid power state: %s."
                  ) % pstate)

    @METRICS.timer('NativeIPMIPower.reboot')
    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Cycles the power to the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: IPMIFailure when the native ipmi call fails.
        :raises: MissingParameterValue when required ipmi credentials
                 are missing.
        :raises: PowerStateFailure when invalid power state is returned
                 from ipmi.
        """

        driver_info = _parse_driver_info(task.node)
        driver_utils.ensure_next_boot_device(task, driver_info)
        _reboot(driver_info)


class NativeIPMIManagement(base.ManagementInterface):

    def get_properties(self):
        return COMMON_PROPERTIES

    @METRICS.timer('NativeIPMIManagement.validate')
    def validate(self, task):
        """Check that 'driver_info' contains IPMI credentials.

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required credentials information.

        :param task: a task from TaskManager.
        :raises: MissingParameterValue when required ipmi credentials
                 are missing.

        """
        _parse_driver_info(task.node)

    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a task from TaskManager.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.

        """
        return list(_BOOT_DEVICES_MAP.keys())

    @METRICS.timer('NativeIPMIManagement.set_boot_device')
    @task_manager.require_exclusive_lock
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for the task's node.

        Set the boot device to use on next reboot of the node.

        :param task: a task from TaskManager.
        :param device: the boot device, one of
                       :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue if an invalid boot device is specified
                 or required ipmi credentials are missing.
        :raises: MissingParameterValue when required ipmi credentials
                 are missing.
        :raises: IPMIFailure on an error from pyghmi.
        """
        if device not in self.get_supported_boot_devices(task):
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)

        if task.node.driver_info.get('ipmi_force_boot_device', False):
            driver_utils.force_persistent_boot(task,
                                               device,
                                               persistent)
            # Reset persistent to False, in case of BMC does not support
            # persistent or we do not have admin rights.
            persistent = False

        boot_mode = deploy_utils.get_boot_mode_for_deploy(task.node)
        driver_info = _parse_driver_info(task.node)
        try:
            ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                                           userid=driver_info['username'],
                                           password=driver_info['password'])
            bootdev = _BOOT_DEVICES_MAP[device]
            uefiboot = boot_mode == 'uefi'
            ipmicmd.set_bootdev(bootdev, persist=persistent, uefiboot=uefiboot)
        except pyghmi_exception.IpmiException as e:
            LOG.error(_LE("IPMI set boot device failed for node %(node_id)s "
                          "with the following error: %(error)s"),
                      {'node_id': driver_info['uuid'], 'error': e})
            raise exception.IPMIFailure(cmd=e)

    @METRICS.timer('NativeIPMIManagement.get_boot_device')
    def get_boot_device(self, task):
        """Get the current boot device for the task's node.

        Returns the current boot device of the node.

        :param task: a task from TaskManager.
        :raises: MissingParameterValue if required IPMI parameters
            are missing.
        :raises: IPMIFailure on an error from pyghmi.
        :returns: a dictionary containing:

            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` or None if it is unknown.
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.

        """
        driver_info = task.node.driver_info
        driver_internal_info = task.node.driver_internal_info
        if (driver_info.get('ipmi_force_boot_device', False) and
                driver_internal_info.get('persistent_boot_device') and
                driver_internal_info.get('is_next_boot_persistent', True)):
            return {
                'boot_device': driver_internal_info['persistent_boot_device'],
                'persistent': True
            }

        driver_info = _parse_driver_info(task.node)
        response = {'boot_device': None}

        try:
            ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                                           userid=driver_info['username'],
                                           password=driver_info['password'])
            ret = ipmicmd.get_bootdev()
            # FIXME(lucasagomes): pyghmi doesn't seem to handle errors
            # consistently, for some errors it raises an exception
            # others it just returns a dictionary with the error.
            if 'error' in ret:
                raise pyghmi_exception.IpmiException(ret['error'])
        except pyghmi_exception.IpmiException as e:
            LOG.error(_LE("IPMI get boot device failed for node %(node_id)s "
                          "with the following error: %(error)s"),
                      {'node_id': driver_info['uuid'], 'error': e})
            raise exception.IPMIFailure(cmd=e)

        response['persistent'] = ret.get('persistent')
        bootdev = ret.get('bootdev')
        if bootdev:
            response['boot_device'] = next((dev for dev, hdev in
                                            _BOOT_DEVICES_MAP.items()
                                            if hdev == bootdev), None)
        return response

    @METRICS.timer('NativeIPMIManagement.get_sensors_data')
    def get_sensors_data(self, task):
        """Get sensors data.

        :param task: a TaskManager instance.
        :raises: FailedToGetSensorData when getting the sensor data fails.
        :raises: MissingParameterValue if required ipmi parameters are missing
        :returns: returns a dict of sensor data group by sensor type.

        """
        driver_info = _parse_driver_info(task.node)
        return _get_sensors_data(driver_info)


class NativeIPMIShellinaboxConsole(base.ConsoleInterface):
    """A ConsoleInterface that uses pyghmi and shellinabox."""

    def get_properties(self):
        d = COMMON_PROPERTIES.copy()
        d.update(CONSOLE_PROPERTIES)
        return d

    @METRICS.timer('NativeIPMIShellinaboxConsole.validate')
    def validate(self, task):
        """Validate the Node console info.

        :param task: a TaskManager instance containing the node to act on.
        :raises: MissingParameterValue when required IPMI credentials or
            the IPMI terminal port are missing
        :raises: InvalidParameterValue when the IPMI terminal port is not
                an integer.
        """
        driver_info = _parse_driver_info(task.node)
        if not driver_info['port']:
            raise exception.MissingParameterValue(_(
                "Missing 'ipmi_terminal_port' parameter in node's"
                " driver_info."))

    @METRICS.timer('NativeIPMIShellinaboxConsole.start_console')
    def start_console(self, task):
        """Start a remote console for the node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: MissingParameterValue when required ipmi credentials
                are missing.
        :raises: InvalidParameterValue when the IPMI terminal port is not an
                integer.
        :raises: ConsoleError if unable to start the console process.
        """
        driver_info = _parse_driver_info(task.node)

        path = _console_pwfile_path(driver_info['uuid'])
        pw_file = console_utils.make_persistent_password_file(
            path, driver_info['password'])

        console_cmd = ("/:%(uid)s:%(gid)s:HOME:pyghmicons %(bmc)s"
                       " %(user)s"
                       " %(passwd_file)s"
                       % {'uid': os.getuid(),
                          'gid': os.getgid(),
                          'bmc': driver_info['address'],
                          'user': driver_info['username'],
                          'passwd_file': pw_file})
        try:
            console_utils.start_shellinabox_console(driver_info['uuid'],
                                                    driver_info['port'],
                                                    console_cmd)
        except exception.ConsoleError:
            with excutils.save_and_reraise_exception():
                ironic_utils.unlink_without_raise(path)

    @METRICS.timer('NativeIPMIShellinaboxConsole.stop_console')
    def stop_console(self, task):
        """Stop the remote console session for the node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: ConsoleError if unable to stop the console process.
        """
        try:
            console_utils.stop_shellinabox_console(task.node.uuid)
        finally:
            password_file = _console_pwfile_path(task.node.uuid)
            ironic_utils.unlink_without_raise(password_file)

    @METRICS.timer('NativeIPMIShellinaboxConsole.get_console')
    def get_console(self, task):
        """Get the type and connection information about the console.

        :param task: a TaskManager instance containing the node to act on.
        :raises: MissingParameterValue when required IPMI credentials or
            the IPMI terminal port are missing
        :raises: InvalidParameterValue when the IPMI terminal port is not
                an integer.
        """
        driver_info = _parse_driver_info(task.node)
        url = console_utils.get_shellinabox_console_url(driver_info['port'])
        return {'type': 'shellinabox', 'url': url}


class VendorPassthru(base.VendorInterface):

    def get_properties(self):
        return COMMON_PROPERTIES

    @METRICS.timer('VendorPassthru.validate')
    def validate(self, task, method, **kwargs):
        """Validate vendor-specific actions.

        :param task: a task from TaskManager.
        :param method: method to be validated
        :param kwargs: info for action.
        :raises: InvalidParameterValue when an invalid parameter value is
                 specified.
        :raises: MissingParameterValue if a required parameter is missing.

        """
        if method == 'send_raw':
            raw_bytes = kwargs.get('raw_bytes')
            if not raw_bytes:
                raise exception.MissingParameterValue(_(
                    'Parameter raw_bytes (string of bytes) was not '
                    'specified.'))
            _parse_raw_bytes(raw_bytes)

        _parse_driver_info(task.node)

    @METRICS.timer('VendorPassthru.send_raw')
    @base.passthru(['POST'])
    @task_manager.require_exclusive_lock
    def send_raw(self, task, http_method, raw_bytes):
        """Send raw bytes to the BMC. Bytes should be a string of bytes.

        :param task: a TaskManager instance.
        :param http_method: the HTTP method used on the request.
        :param raw_bytes: a string of raw bytes to send, e.g. '0x00 0x01'
        :raises: IPMIFailure on an error from native IPMI call.
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: InvalidParameterValue when an invalid value is specified.

        """
        driver_info = _parse_driver_info(task.node)
        _send_raw(driver_info, raw_bytes)

    @METRICS.timer('VendorPassthru.bmc_reset')
    @base.passthru(['POST'])
    @task_manager.require_exclusive_lock
    def bmc_reset(self, task, http_method, warm=True):
        """Reset BMC via IPMI command.

        :param task: a TaskManager instance.
        :param http_method: the HTTP method used on the request.
        :param warm: boolean parameter to decide on warm or cold reset.
        :raises: IPMIFailure on an error from native IPMI call.
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: InvalidParameterValue when an invalid value is specified

        """
        driver_info = _parse_driver_info(task.node)
        warm = strutils.bool_from_string(warm)
        # NOTE(yuriyz): pyghmi 0.8.0 does not have a method for BMC reset
        command = '0x03' if warm else '0x02'
        raw_command = '0x06 ' + command
        _send_raw(driver_info, raw_command)
