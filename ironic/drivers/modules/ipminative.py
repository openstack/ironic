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
import tempfile

from oslo.config import cfg
from oslo.utils import excutils
from oslo.utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LW
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules import console_utils
from ironic.openstack.common import log as logging

pyghmi = importutils.try_import('pyghmi')
if pyghmi:
    from pyghmi import exceptions as pyghmi_exception
    from pyghmi.ipmi import command as ipmi_command

opts = [
    cfg.IntOpt('retry_timeout',
               default=60,
               help='Maximum time in seconds to retry IPMI operations.'),
    cfg.IntOpt('min_command_interval',
               default=5,
               help='Minimum time, in seconds, between IPMI operations '
                    'sent to a server. There is a risk with some hardware '
                    'that setting this too low may cause the BMC to crash. '
                    'Recommended setting is 5 seconds.'),
    ]

CONF = cfg.CONF
CONF.register_opts(opts, group='ipmi')

LOG = logging.getLogger(__name__)

REQUIRED_PROPERTIES = {'ipmi_address': _("IP of the node's BMC. Required."),
                       'ipmi_password': _("IPMI password. Required."),
                       'ipmi_username': _("IPMI username. Required.")}
COMMON_PROPERTIES = REQUIRED_PROPERTIES
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

    # get additional info
    bmc_info['uuid'] = node.uuid

    # terminal port must be an integer
    port = info.get('ipmi_terminal_port')
    if port is not None:
        try:
            port = int(port)
        except ValueError:
            raise exception.InvalidParameterValue(_(
                "IPMI terminal port is not an integer."))
    bmc_info['port'] = port

    return bmc_info


def _console_pwfile_path(uuid):
    """Return the file path for storing the ipmi password."""
    file_name = "%(uuid)s.pw" % {'uuid': uuid}
    return os.path.join(tempfile.gettempdir(), file_name)


def _power_on(driver_info):
    """Turn the power on for this node.

    :param driver_info: the bmc access info for a node.
    :returns: power state POWER_ON, one of :class:`ironic.common.states`.
    :raises: IPMIFailure when the native ipmi call fails.
    :raises: PowerStateFailure when invalid power state is returned
             from ipmi.
    """

    msg = _LW("IPMI power on failed for node %(node_id)s with the "
              "following error: %(error)s")
    try:
        ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                           userid=driver_info['username'],
                           password=driver_info['password'])
        wait = CONF.ipmi.retry_timeout
        ret = ipmicmd.set_power('on', wait)
    except pyghmi_exception.IpmiException as e:
        LOG.warning(msg, {'node_id': driver_info['uuid'], 'error': str(e)})
        raise exception.IPMIFailure(cmd=str(e))

    state = ret.get('powerstate')
    if state == 'on':
        return states.POWER_ON
    else:
        LOG.warning(msg, {'node_id': driver_info['uuid'], 'error': ret})
        raise exception.PowerStateFailure(pstate=state)


def _power_off(driver_info):
    """Turn the power off for this node.

    :param driver_info: the bmc access info for a node.
    :returns: power state POWER_OFF, one of :class:`ironic.common.states`.
    :raises: IPMIFailure when the native ipmi call fails.
    :raises: PowerStateFailure when invalid power state is returned
             from ipmi.
    """

    msg = _LW("IPMI power off failed for node %(node_id)s with the "
              "following error: %(error)s")
    try:
        ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                           userid=driver_info['username'],
                           password=driver_info['password'])
        wait = CONF.ipmi.retry_timeout
        ret = ipmicmd.set_power('off', wait)
    except pyghmi_exception.IpmiException as e:
        LOG.warning(msg, {'node_id': driver_info['uuid'], 'error': str(e)})
        raise exception.IPMIFailure(cmd=str(e))

    state = ret.get('powerstate')
    if state == 'off':
        return states.POWER_OFF
    else:
        LOG.warning(msg % {'node_id': driver_info['uuid'], 'error': ret})
        raise exception.PowerStateFailure(pstate=state)


def _reboot(driver_info):
    """Reboot this node.

    If the power is off, turn it on. If the power is on, reset it.

    :param driver_info: the bmc access info for a node.
    :returns: power state POWER_ON, one of :class:`ironic.common.states`.
    :raises: IPMIFailure when the native ipmi call fails.
    :raises: PowerStateFailure when invalid power state is returned
             from ipmi.
    """

    msg = _LW("IPMI power reboot failed for node %(node_id)s with the "
              "following error: %(error)s")
    try:
        ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                           userid=driver_info['username'],
                           password=driver_info['password'])
        wait = CONF.ipmi.retry_timeout
        ret = ipmicmd.set_power('boot', wait)
    except pyghmi_exception.IpmiException as e:
        LOG.warning(msg % {'node_id': driver_info['uuid'], 'error': str(e)})
        raise exception.IPMIFailure(cmd=str(e))

    state = ret.get('powerstate')
    if state == 'on':
        return states.POWER_ON
    else:
        LOG.warning(msg % {'node_id': driver_info['uuid'], 'error': ret})
        raise exception.PowerStateFailure(pstate=state)


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
        LOG.warning(_LW("IPMI get power state failed for node %(node_id)s "
                        "with the following error: %(error)s"),
                    {'node_id': driver_info['uuid'], 'error': str(e)})
        raise exception.IPMIFailure(cmd=str(e))

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
        sensors_data.setdefault(reading.type,
            {})[reading.name] = {
              'Sensor Reading': '%s %s' % (reading.value, reading.units),
              'Sensor ID': reading.name,
              'States': str(reading.states),
              'Units': reading.units,
              'Health': str(reading.health)}

    return sensors_data


class NativeIPMIPower(base.PowerInterface):
    """The power driver using native python-ipmi library."""

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task):
        """Check that node['driver_info'] contains IPMI credentials.

        :param task: a TaskManager instance containing the node to act on.
        :raises: MissingParameterValue when required ipmi credentials
                 are missing.
        """
        _parse_driver_info(task.node)

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
            _power_on(driver_info)
        elif pstate == states.POWER_OFF:
            _power_off(driver_info)
        else:
            raise exception.InvalidParameterValue(_(
                "set_power_state called with an invalid power state: %s."
                ) % pstate)

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
        _reboot(driver_info)


class NativeIPMIManagement(base.ManagementInterface):

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task):
        """Check that 'driver_info' contains IPMI credentials.

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required credentials information.

        :param task: a task from TaskManager.
        :raises: MissingParameterValue when required ipmi credentials
                 are missing.

        """
        _parse_driver_info(task.node)

    def get_supported_boot_devices(self):
        """Get a list of the supported boot devices.

        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.

        """
        return list(_BOOT_DEVICES_MAP.keys())

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
        if device not in self.get_supported_boot_devices():
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)
        driver_info = _parse_driver_info(task.node)
        try:
            ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                               userid=driver_info['username'],
                               password=driver_info['password'])
            bootdev = _BOOT_DEVICES_MAP[device]
            ipmicmd.set_bootdev(bootdev, persist=persistent)
        except pyghmi_exception.IpmiException as e:
            LOG.error(_LE("IPMI set boot device failed for node %(node_id)s "
                          "with the following error: %(error)s"),
                      {'node_id': driver_info['uuid'], 'error': e})
            raise exception.IPMIFailure(cmd=e)

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
                utils.unlink_without_raise(path)

    def stop_console(self, task):
        """Stop the remote console session for the node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: MissingParameterValue when required IPMI credentials or
            the IPMI terminal port are missing
        :raises: InvalidParameterValue when the IPMI terminal port is not
                an integer.
        :raises: ConsoleError if unable to stop the console process.
        """
        driver_info = _parse_driver_info(task.node)
        try:
            console_utils.stop_shellinabox_console(driver_info['uuid'])
        finally:
            password_file = _console_pwfile_path(driver_info['uuid'])
            utils.unlink_without_raise(password_file)

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
