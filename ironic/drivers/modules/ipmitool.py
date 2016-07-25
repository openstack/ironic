# coding=utf-8

# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 NTT DOCOMO, INC.
# Copyright 2014 International Business Machines Corporation
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
IPMI power manager driver.

Uses the 'ipmitool' command (http://ipmitool.sourceforge.net/) to remotely
manage hardware.  This includes setting the boot device, getting a
serial-over-LAN console, and controlling the power state of the machine.

NOTE THAT CERTAIN DISTROS MAY INSTALL openipmi BY DEFAULT, INSTEAD OF ipmitool,
WHICH PROVIDES DIFFERENT COMMAND-LINE OPTIONS AND *IS NOT SUPPORTED* BY THIS
DRIVER.
"""

import contextlib
import os
import re
import subprocess
import tempfile
import time

from ironic_lib import metrics_utils
from ironic_lib import utils as ironic_utils
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import strutils
import six

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _, _LE, _LI, _LW
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import console_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers import utils as driver_utils


LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

VALID_PRIV_LEVELS = ['ADMINISTRATOR', 'CALLBACK', 'OPERATOR', 'USER']

VALID_PROTO_VERSIONS = ('2.0', '1.5')

REQUIRED_PROPERTIES = {
    'ipmi_address': _("IP address or hostname of the node. Required.")
}
OPTIONAL_PROPERTIES = {
    'ipmi_password': _("password. Optional."),
    'ipmi_port': _("remote IPMI RMCP port. Optional."),
    'ipmi_priv_level': _("privilege level; default is ADMINISTRATOR. One of "
                         "%s. Optional.") % ', '.join(VALID_PRIV_LEVELS),
    'ipmi_username': _("username; default is NULL user. Optional."),
    'ipmi_bridging': _("bridging_type; default is \"no\". One of \"single\", "
                       "\"dual\", \"no\". Optional."),
    'ipmi_transit_channel': _("transit channel for bridged request. Required "
                              "only if ipmi_bridging is set to \"dual\"."),
    'ipmi_transit_address': _("transit address for bridged request. Required "
                              "only if ipmi_bridging is set to \"dual\"."),
    'ipmi_target_channel': _("destination channel for bridged request. "
                             "Required only if ipmi_bridging is set to "
                             "\"single\" or \"dual\"."),
    'ipmi_target_address': _("destination address for bridged request. "
                             "Required only if ipmi_bridging is set "
                             "to \"single\" or \"dual\"."),
    'ipmi_local_address': _("local IPMB address for bridged requests. "
                            "Used only if ipmi_bridging is set "
                            "to \"single\" or \"dual\". Optional."),
    'ipmi_protocol_version': _('the version of the IPMI protocol; default '
                               'is "2.0". One of "1.5", "2.0". Optional.'),
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
BRIDGING_OPTIONS = [('local_address', '-m'),
                    ('transit_channel', '-B'), ('transit_address', '-T'),
                    ('target_channel', '-b'), ('target_address', '-t')]

LAST_CMD_TIME = {}
TIMING_SUPPORT = None
SINGLE_BRIDGE_SUPPORT = None
DUAL_BRIDGE_SUPPORT = None
TMP_DIR_CHECKED = None

ipmitool_command_options = {
    'timing': ['ipmitool', '-N', '0', '-R', '0', '-h'],
    'single_bridge': ['ipmitool', '-m', '0', '-b', '0', '-t', '0', '-h'],
    'dual_bridge': ['ipmitool', '-m', '0', '-b', '0', '-t', '0',
                    '-B', '0', '-T', '0', '-h']}

# Note(TheJulia): This string is hardcoded in ipmitool's lanplus driver
# and is substituted in return for the error code received from the IPMI
# controller.  As of 1.8.15, no internationalization support appears to
# be in ipmitool which means the string should always be returned in this
# form regardless of locale.
IPMITOOL_RETRYABLE_FAILURES = ['insufficient resources for session']

# NOTE(lucasagomes): A mapping for the boot devices and their hexadecimal
# value. For more information about these values see the "Set System Boot
# Options Command" section of the link below (page 418)
# http://www.intel.com/content/www/us/en/servers/ipmi/ipmi-second-gen-interface-spec-v2-rev1-1.html  # noqa
BOOT_DEVICE_HEXA_MAP = {
    boot_devices.PXE: '0x04',
    boot_devices.DISK: '0x08',
    boot_devices.CDROM: '0x14',
    boot_devices.BIOS: '0x18',
    boot_devices.SAFE: '0x0c'
}


def _check_option_support(options):
    """Checks if the specific ipmitool options are supported on host.

    This method updates the module-level variables indicating whether
    an option is supported so that it is accessible by any driver
    interface class in this module. It is intended to be called from
    the __init__ method of such classes only.

    :param options: list of ipmitool options to be checked
    :raises: OSError
    """
    for opt in options:
        if _is_option_supported(opt) is None:
            try:
                cmd = ipmitool_command_options[opt]
                # NOTE(cinerama): use subprocess.check_call to
                # check options & suppress ipmitool output to
                # avoid alarming people
                with open(os.devnull, 'wb') as nullfile:
                    subprocess.check_call(cmd, stdout=nullfile,
                                          stderr=nullfile)
            except subprocess.CalledProcessError:
                LOG.info(_LI("Option %(opt)s is not supported by ipmitool"),
                         {'opt': opt})
                _is_option_supported(opt, False)
            else:
                LOG.info(_LI("Option %(opt)s is supported by ipmitool"),
                         {'opt': opt})
                _is_option_supported(opt, True)


def _is_option_supported(option, is_supported=None):
    """Indicates whether the particular ipmitool option is supported.

    :param option: specific ipmitool option
    :param is_supported: Optional Boolean. when specified, this value
                         is assigned to the module-level variable indicating
                         whether the option is supported. Used only if a value
                         is not already assigned.
    :returns: True, indicates the option is supported
    :returns: False, indicates the option is not supported
    :returns: None, indicates that it is not aware whether the option
              is supported
    """
    global SINGLE_BRIDGE_SUPPORT
    global DUAL_BRIDGE_SUPPORT
    global TIMING_SUPPORT

    if option == 'single_bridge':
        if (SINGLE_BRIDGE_SUPPORT is None) and (is_supported is not None):
            SINGLE_BRIDGE_SUPPORT = is_supported
        return SINGLE_BRIDGE_SUPPORT
    elif option == 'dual_bridge':
        if (DUAL_BRIDGE_SUPPORT is None) and (is_supported is not None):
            DUAL_BRIDGE_SUPPORT = is_supported
        return DUAL_BRIDGE_SUPPORT
    elif option == 'timing':
        if (TIMING_SUPPORT is None) and (is_supported is not None):
            TIMING_SUPPORT = is_supported
        return TIMING_SUPPORT


def _console_pwfile_path(uuid):
    """Return the file path for storing the ipmi password for a console."""
    file_name = "%(uuid)s.pw" % {'uuid': uuid}
    return os.path.join(CONF.tempdir, file_name)


@contextlib.contextmanager
def _make_password_file(password):
    """Makes a temporary file that contains the password.

    :param password: the password
    :returns: the absolute pathname of the temporary file
    :raises: PasswordFileFailedToCreate from creating or writing to the
             temporary file
    """
    f = None
    try:
        f = tempfile.NamedTemporaryFile(mode='w', dir=CONF.tempdir)
        f.write(str(password))
        f.flush()
    except (IOError, OSError) as exc:
        if f is not None:
            f.close()
        raise exception.PasswordFileFailedToCreate(error=exc)
    except Exception:
        with excutils.save_and_reraise_exception():
            if f is not None:
                f.close()

    try:
        # NOTE(jlvillal): This yield can not be in the try/except block above
        # because an exception by the caller of this function would then get
        # changed to a PasswordFileFailedToCreate exception which would mislead
        # about the problem and its cause.
        yield f.name
    finally:
        if f is not None:
            f.close()


def _parse_driver_info(node):
    """Gets the parameters required for ipmitool to access the node.

    :param node: the Node of interest.
    :returns: dictionary of parameters.
    :raises: InvalidParameterValue when an invalid value is specified
    :raises: MissingParameterValue when a required ipmi parameter is missing.

    """
    info = node.driver_info or {}
    bridging_types = ['single', 'dual']
    missing_info = [key for key in REQUIRED_PROPERTIES if not info.get(key)]
    if missing_info:
        raise exception.MissingParameterValue(_(
            "Missing the following IPMI credentials in node's"
            " driver_info: %s.") % missing_info)

    address = info.get('ipmi_address')
    username = info.get('ipmi_username')
    password = six.text_type(info.get('ipmi_password', ''))
    dest_port = info.get('ipmi_port')
    port = info.get('ipmi_terminal_port')
    priv_level = info.get('ipmi_priv_level', 'ADMINISTRATOR')
    bridging_type = info.get('ipmi_bridging', 'no')
    local_address = info.get('ipmi_local_address')
    transit_channel = info.get('ipmi_transit_channel')
    transit_address = info.get('ipmi_transit_address')
    target_channel = info.get('ipmi_target_channel')
    target_address = info.get('ipmi_target_address')
    protocol_version = str(info.get('ipmi_protocol_version', '2.0'))
    force_boot_device = info.get('ipmi_force_boot_device', False)

    if not username:
        LOG.warning(_LW('ipmi_username is not defined or empty for node %s: '
                        'NULL user will be utilized.') % node.uuid)
    if not password:
        LOG.warning(_LW('ipmi_password is not defined or empty for node %s: '
                        'NULL password will be utilized.') % node.uuid)

    if protocol_version not in VALID_PROTO_VERSIONS:
        valid_versions = ', '.join(VALID_PROTO_VERSIONS)
        raise exception.InvalidParameterValue(_(
            "Invalid IPMI protocol version value %(version)s, the valid "
            "value can be one of %(valid_versions)s") %
            {'version': protocol_version, 'valid_versions': valid_versions})

    if port is not None:
        port = utils.validate_network_port(port, 'ipmi_terminal_port')

    if dest_port is not None:
        dest_port = utils.validate_network_port(dest_port, 'ipmi_port')

    # check if ipmi_bridging has proper value
    if bridging_type == 'no':
        # if bridging is not selected, then set all bridging params to None
        (local_address, transit_channel, transit_address, target_channel,
         target_address) = (None,) * 5
    elif bridging_type in bridging_types:
        # check if the particular bridging option is supported on host
        if not _is_option_supported('%s_bridge' % bridging_type):
            raise exception.InvalidParameterValue(_(
                "Value for ipmi_bridging is provided as %s, but IPMI "
                "bridging is not supported by the IPMI utility installed "
                "on host. Ensure ipmitool version is > 1.8.11"
            ) % bridging_type)

        # ensure that all the required parameters are provided
        params_undefined = [param for param, value in [
            ("ipmi_target_channel", target_channel),
            ('ipmi_target_address', target_address)] if value is None]
        if bridging_type == 'dual':
            params_undefined2 = [param for param, value in [
                ("ipmi_transit_channel", transit_channel),
                ('ipmi_transit_address', transit_address)
            ] if value is None]
            params_undefined.extend(params_undefined2)
        else:
            # if single bridging was selected, set dual bridge params to None
            transit_channel = transit_address = None

        # If the required parameters were not provided,
        # raise an exception
        if params_undefined:
            raise exception.MissingParameterValue(_(
                "%(param)s not provided") % {'param': params_undefined})
    else:
        raise exception.InvalidParameterValue(_(
            "Invalid value for ipmi_bridging: %(bridging_type)s,"
            " the valid value can be one of: %(bridging_types)s"
        ) % {'bridging_type': bridging_type,
             'bridging_types': bridging_types + ['no']})

    if priv_level not in VALID_PRIV_LEVELS:
        valid_priv_lvls = ', '.join(VALID_PRIV_LEVELS)
        raise exception.InvalidParameterValue(_(
            "Invalid privilege level value:%(priv_level)s, the valid value"
            " can be one of %(valid_levels)s") %
            {'priv_level': priv_level, 'valid_levels': valid_priv_lvls})

    return {
        'address': address,
        'dest_port': dest_port,
        'username': username,
        'password': password,
        'port': port,
        'uuid': node.uuid,
        'priv_level': priv_level,
        'local_address': local_address,
        'transit_channel': transit_channel,
        'transit_address': transit_address,
        'target_channel': target_channel,
        'target_address': target_address,
        'protocol_version': protocol_version,
        'force_boot_device': force_boot_device,
    }


def _exec_ipmitool(driver_info, command, check_exit_code=None):
    """Execute the ipmitool command.

    :param driver_info: the ipmitool parameters for accessing a node.
    :param command: the ipmitool command to be executed.
    :param check_exit_code: Single bool, int, or list of allowed exit codes.
    :returns: (stdout, stderr) from executing the command.
    :raises: PasswordFileFailedToCreate from creating or writing to the
             temporary file.
    :raises: processutils.ProcessExecutionError from executing the command.

    """
    ipmi_version = ('lanplus'
                    if driver_info['protocol_version'] == '2.0'
                    else 'lan')
    args = ['ipmitool',
            '-I',
            ipmi_version,
            '-H',
            driver_info['address'],
            '-L', driver_info['priv_level']
            ]

    if driver_info['dest_port']:
        args.append('-p')
        args.append(driver_info['dest_port'])

    if driver_info['username']:
        args.append('-U')
        args.append(driver_info['username'])

    for name, option in BRIDGING_OPTIONS:
        if driver_info[name] is not None:
            args.append(option)
            args.append(driver_info[name])

    # specify retry timing more precisely, if supported
    num_tries = max(
        (CONF.ipmi.retry_timeout // CONF.ipmi.min_command_interval), 1)

    if _is_option_supported('timing'):
        args.append('-R')
        args.append(str(num_tries))

        args.append('-N')
        args.append(str(CONF.ipmi.min_command_interval))

    end_time = (time.time() + CONF.ipmi.retry_timeout)

    while True:
        num_tries = num_tries - 1
        # NOTE(deva): ensure that no communications are sent to a BMC more
        #             often than once every min_command_interval seconds.
        time_till_next_poll = CONF.ipmi.min_command_interval - (
            time.time() - LAST_CMD_TIME.get(driver_info['address'], 0))
        if time_till_next_poll > 0:
            time.sleep(time_till_next_poll)
        # Resetting the list that will be utilized so the password arguments
        # from any previous execution are preserved.
        cmd_args = args[:]
        extra_args = {}
        if check_exit_code is not None:
            extra_args['check_exit_code'] = check_exit_code
        # 'ipmitool' command will prompt password if there is no '-f'
        # option, we set it to '\0' to write a password file to support
        # empty password
        with _make_password_file(driver_info['password'] or '\0') as pw_file:
            cmd_args.append('-f')
            cmd_args.append(pw_file)
            cmd_args.extend(command.split(" "))
            try:
                out, err = utils.execute(*cmd_args, **extra_args)
                return out, err
            except processutils.ProcessExecutionError as e:
                with excutils.save_and_reraise_exception() as ctxt:
                    err_list = [x for x in IPMITOOL_RETRYABLE_FAILURES
                                if x in six.text_type(e)]
                    if ((time.time() > end_time) or
                        (num_tries == 0) or
                        not err_list):
                        LOG.error(_LE('IPMI Error while attempting "%(cmd)s"'
                                      'for node %(node)s. Error: %(error)s'), {
                                  'node': driver_info['uuid'],
                                  'cmd': e.cmd, 'error': e
                                  })
                    else:
                        ctxt.reraise = False
                        LOG.warning(_LW('IPMI Error encountered, retrying '
                                        '"%(cmd)s" for node %(node)s. '
                                        'Error: %(error)s'), {
                                    'node': driver_info['uuid'],
                                    'cmd': e.cmd, 'error': e
                                    })
            finally:
                LAST_CMD_TIME[driver_info['address']] = time.time()


def _sleep_time(iter):
    """Return the time-to-sleep for the n'th iteration of a retry loop.

    This implementation increases exponentially.

    :param iter: iteration number
    :returns: number of seconds to sleep

    """
    if iter <= 1:
        return 1
    return iter ** 2


def _set_and_wait(target_state, driver_info):
    """Helper function for DynamicLoopingCall.

    This method changes the power state and polls the BMCuntil the desired
    power state is reached, or CONF.ipmi.retry_timeout would be exceeded by the
    next iteration.

    This method assumes the caller knows the current power state and does not
    check it prior to changing the power state. Most BMCs should be fine, but
    if a driver is concerned, the state should be checked prior to calling this
    method.

    :param target_state: desired power state
    :param driver_info: the ipmitool parameters for accessing a node.
    :returns: one of ironic.common.states

    """
    if target_state == states.POWER_ON:
        state_name = "on"
    elif target_state == states.POWER_OFF:
        state_name = "off"

    def _wait(mutable):
        try:
            # Only issue power change command once
            if mutable['iter'] < 0:
                _exec_ipmitool(driver_info, "power %s" % state_name)
            else:
                mutable['power'] = _power_status(driver_info)
        except (exception.PasswordFileFailedToCreate,
                processutils.ProcessExecutionError,
                exception.IPMIFailure):
            # Log failures but keep trying
            LOG.warning(_LW("IPMI power %(state)s failed for node %(node)s."),
                        {'state': state_name, 'node': driver_info['uuid']})
        finally:
            mutable['iter'] += 1

        if mutable['power'] == target_state:
            raise loopingcall.LoopingCallDone()

        sleep_time = _sleep_time(mutable['iter'])
        if (sleep_time + mutable['total_time']) > CONF.ipmi.retry_timeout:
            # Stop if the next loop would exceed maximum retry_timeout
            LOG.error(_LE('IPMI power %(state)s timed out after '
                          '%(tries)s retries on node %(node_id)s.'),
                      {'state': state_name, 'tries': mutable['iter'],
                       'node_id': driver_info['uuid']})
            mutable['power'] = states.ERROR
            raise loopingcall.LoopingCallDone()
        else:
            mutable['total_time'] += sleep_time
            return sleep_time

    # Use mutable objects so the looped method can change them.
    # Start 'iter' from -1 so that the first two checks are one second apart.
    status = {'power': None, 'iter': -1, 'total_time': 0}

    timer = loopingcall.DynamicLoopingCall(_wait, status)
    timer.start().wait()
    return status['power']


def _power_on(driver_info):
    """Turn the power ON for this node.

    :param driver_info: the ipmitool parameters for accessing a node.
    :returns: one of ironic.common.states POWER_ON or ERROR.
    :raises: IPMIFailure on an error from ipmitool (from _power_status call).

    """
    return _set_and_wait(states.POWER_ON, driver_info)


def _power_off(driver_info):
    """Turn the power OFF for this node.

    :param driver_info: the ipmitool parameters for accessing a node.
    :returns: one of ironic.common.states POWER_OFF or ERROR.
    :raises: IPMIFailure on an error from ipmitool (from _power_status call).

    """
    return _set_and_wait(states.POWER_OFF, driver_info)


def _power_status(driver_info):
    """Get the power status for a node.

    :param driver_info: the ipmitool access parameters for a node.
    :returns: one of ironic.common.states POWER_OFF, POWER_ON or ERROR.
    :raises: IPMIFailure on an error from ipmitool.

    """
    cmd = "power status"
    try:
        out_err = _exec_ipmitool(driver_info, cmd)
    except (exception.PasswordFileFailedToCreate,
            processutils.ProcessExecutionError) as e:
        LOG.warning(_LW("IPMI power status failed for node %(node_id)s with "
                        "error: %(error)s."),
                    {'node_id': driver_info['uuid'], 'error': e})
        raise exception.IPMIFailure(cmd=cmd)

    if out_err[0] == "Chassis Power is on\n":
        return states.POWER_ON
    elif out_err[0] == "Chassis Power is off\n":
        return states.POWER_OFF
    else:
        return states.ERROR


def _process_sensor(sensor_data):
    sensor_data_fields = sensor_data.split('\n')
    sensor_data_dict = {}
    for field in sensor_data_fields:
        if not field:
            continue
        kv_value = field.split(':')
        if len(kv_value) != 2:
            continue
        sensor_data_dict[kv_value[0].strip()] = kv_value[1].strip()

    return sensor_data_dict


def _get_sensor_type(node, sensor_data_dict):
    # Have only three sensor type name IDs: 'Sensor Type (Analog)'
    # 'Sensor Type (Discrete)' and 'Sensor Type (Threshold)'

    for key in ('Sensor Type (Analog)', 'Sensor Type (Discrete)',
                'Sensor Type (Threshold)'):
        try:
            return sensor_data_dict[key].split(' ', 1)[0]
        except KeyError:
            continue

    raise exception.FailedToParseSensorData(
        node=node.uuid,
        error=(_("parse ipmi sensor data failed, unknown sensor type"
                 " data: %(sensors_data)s"),
               {'sensors_data': sensor_data_dict}))


def _parse_ipmi_sensors_data(node, sensors_data):
    """Parse the IPMI sensors data and format to the dict grouping by type.

    We run 'ipmitool' command with 'sdr -v' options, which can return sensor
    details in human-readable format, we need to format them to JSON string
    dict-based data for Ceilometer Collector which can be sent it as payload
    out via notification bus and consumed by Ceilometer Collector.

    :param sensors_data: the sensor data returned by ipmitool command.
    :returns: the sensor data with JSON format, grouped by sensor type.
    :raises: FailedToParseSensorData when error encountered during parsing.

    """
    sensors_data_dict = {}
    if not sensors_data:
        return sensors_data_dict

    sensors_data_array = sensors_data.split('\n\n')
    for sensor_data in sensors_data_array:
        sensor_data_dict = _process_sensor(sensor_data)
        if not sensor_data_dict:
            continue

        sensor_type = _get_sensor_type(node, sensor_data_dict)

        # ignore the sensors which has no current 'Sensor Reading' data
        if 'Sensor Reading' in sensor_data_dict:
            sensors_data_dict.setdefault(
                sensor_type,
                {})[sensor_data_dict['Sensor ID']] = sensor_data_dict

    # get nothing, no valid sensor data
    if not sensors_data_dict:
        raise exception.FailedToParseSensorData(
            node=node.uuid,
            error=(_("parse ipmi sensor data failed, get nothing with input"
                     " data: %(sensors_data)s")
                   % {'sensors_data': sensors_data}))
    return sensors_data_dict


@METRICS.timer('send_raw')
@task_manager.require_exclusive_lock
def send_raw(task, raw_bytes):
    """Send raw bytes to the BMC. Bytes should be a string of bytes.

    :param task: a TaskManager instance.
    :param raw_bytes: a string of raw bytes to send, e.g. '0x00 0x01'
    :returns: a tuple with stdout and stderr.
    :raises: IPMIFailure on an error from ipmitool.
    :raises: MissingParameterValue if a required parameter is missing.
    :raises: InvalidParameterValue when an invalid value is specified.

    """
    node_uuid = task.node.uuid
    LOG.debug('Sending node %(node)s raw bytes %(bytes)s',
              {'bytes': raw_bytes, 'node': node_uuid})
    driver_info = _parse_driver_info(task.node)
    cmd = 'raw %s' % raw_bytes

    try:
        out, err = _exec_ipmitool(driver_info, cmd)
        LOG.debug('send raw bytes returned stdout: %(stdout)s, stderr:'
                  ' %(stderr)s', {'stdout': out, 'stderr': err})
    except (exception.PasswordFileFailedToCreate,
            processutils.ProcessExecutionError) as e:
        LOG.exception(_LE('IPMI "raw bytes" failed for node %(node_id)s '
                      'with error: %(error)s.'),
                      {'node_id': node_uuid, 'error': e})
        raise exception.IPMIFailure(cmd=cmd)

    return out, err


@METRICS.timer('dump_sdr')
def dump_sdr(task, file_path):
    """Dump SDR data to a file.

    :param task: a TaskManager instance.
    :param file_path: the path to SDR dump file.
    :raises: IPMIFailure on an error from ipmitool.
    :raises: MissingParameterValue if a required parameter is missing.
    :raises: InvalidParameterValue when an invalid value is specified.

    """
    node_uuid = task.node.uuid
    LOG.debug('Dump SDR data for node %(node)s to file %(name)s',
              {'name': file_path, 'node': node_uuid})
    driver_info = _parse_driver_info(task.node)
    cmd = 'sdr dump %s' % file_path

    try:
        out, err = _exec_ipmitool(driver_info, cmd)
        LOG.debug('dump SDR returned stdout: %(stdout)s, stderr:'
                  ' %(stderr)s', {'stdout': out, 'stderr': err})
    except (exception.PasswordFileFailedToCreate,
            processutils.ProcessExecutionError) as e:
        LOG.exception(_LE('IPMI "sdr dump" failed for node %(node_id)s '
                      'with error: %(error)s.'),
                      {'node_id': node_uuid, 'error': e})
        raise exception.IPMIFailure(cmd=cmd)


def _check_temp_dir():
    """Check for Valid temp directory."""
    global TMP_DIR_CHECKED
    # because a temporary file is used to pass the password to ipmitool,
    # we should check the directory
    if TMP_DIR_CHECKED is None:
        try:
            utils.check_dir()
        except (exception.PathNotFound,
                exception.DirectoryNotWritable,
                exception.InsufficientDiskSpace) as e:
            with excutils.save_and_reraise_exception():
                TMP_DIR_CHECKED = False
                err_msg = (_("Ipmitool drivers need to be able to create "
                             "temporary files to pass password to ipmitool. "
                             "Encountered error: %s") % e)
                e.message = err_msg
                LOG.error(err_msg)
        else:
            TMP_DIR_CHECKED = True


def _constructor_checks(driver):
    """Common checks to be performed when instantiating an ipmitool class."""
    try:
        _check_option_support(['timing', 'single_bridge', 'dual_bridge'])
    except OSError:
        raise exception.DriverLoadError(
            driver=driver,
            reason=_("Unable to locate usable ipmitool command in "
                     "the system path when checking ipmitool version"))
    _check_temp_dir()


class IPMIPower(base.PowerInterface):

    def __init__(self):
        _constructor_checks(driver=self.__class__.__name__)

    def get_properties(self):
        return COMMON_PROPERTIES

    @METRICS.timer('IPMIPower.validate')
    def validate(self, task):
        """Validate driver_info for ipmitool driver.

        Check that node['driver_info'] contains IPMI credentials.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if required ipmi parameters are missing.
        :raises: MissingParameterValue if a required parameter is missing.

        """
        _parse_driver_info(task.node)
        # NOTE(deva): don't actually touch the BMC in validate because it is
        #             called too often, and BMCs are too fragile.
        #             This is a temporary measure to mitigate problems while
        #             1314954 and 1314961 are resolved.

    @METRICS.timer('IPMIPower.get_power_state')
    def get_power_state(self, task):
        """Get the current power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: one of ironic.common.states POWER_OFF, POWER_ON or ERROR.
        :raises: InvalidParameterValue if required ipmi parameters are missing.
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: IPMIFailure on an error from ipmitool (from _power_status
            call).

        """
        driver_info = _parse_driver_info(task.node)
        return _power_status(driver_info)

    @METRICS.timer('IPMIPower.set_power_state')
    @task_manager.require_exclusive_lock
    def set_power_state(self, task, pstate):
        """Turn the power on or off.

        :param task: a TaskManager instance containing the node to act on.
        :param pstate: The desired power state, one of ironic.common.states
            POWER_ON, POWER_OFF.
        :raises: InvalidParameterValue if an invalid power state was specified.
        :raises: MissingParameterValue if required ipmi parameters are missing
        :raises: PowerStateFailure if the power couldn't be set to pstate.

        """
        driver_info = _parse_driver_info(task.node)

        if pstate == states.POWER_ON:
            driver_utils.ensure_next_boot_device(task, driver_info)
            state = _power_on(driver_info)
        elif pstate == states.POWER_OFF:
            state = _power_off(driver_info)
        else:
            raise exception.InvalidParameterValue(
                _("set_power_state called "
                  "with invalid power state %s.") % pstate)

        if state != pstate:
            raise exception.PowerStateFailure(pstate=pstate)

    @METRICS.timer('IPMIPower.reboot')
    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Cycles the power to the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: MissingParameterValue if required ipmi parameters are missing.
        :raises: InvalidParameterValue if an invalid power state was specified.
        :raises: PowerStateFailure if the final state of the node is not
            POWER_ON.

        """
        driver_info = _parse_driver_info(task.node)
        _power_off(driver_info)
        driver_utils.ensure_next_boot_device(task, driver_info)
        state = _power_on(driver_info)

        if state != states.POWER_ON:
            raise exception.PowerStateFailure(pstate=states.POWER_ON)


class IPMIManagement(base.ManagementInterface):

    def get_properties(self):
        return COMMON_PROPERTIES

    def __init__(self):
        _constructor_checks(driver=self.__class__.__name__)

    @METRICS.timer('IPMIManagement.validate')
    def validate(self, task):
        """Check that 'driver_info' contains IPMI credentials.

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required credentials information.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue if required IPMI parameters
            are missing.
        :raises: MissingParameterValue if a required parameter is missing.

        """
        _parse_driver_info(task.node)

    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a task from TaskManager.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.

        """
        return list(BOOT_DEVICE_HEXA_MAP)

    @METRICS.timer('IPMIManagement.set_boot_device')
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
        :raises: MissingParameterValue if required ipmi parameters are missing.
        :raises: IPMIFailure on an error from ipmitool.

        """
        if device not in self.get_supported_boot_devices(task):
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)

        # note(JayF): IPMI spec indicates unless you send these raw bytes the
        # boot device setting times out after 60s. Since it's possible it
        # could be >60s before a node is rebooted, we should always send them.
        # This mimics pyghmi's current behavior, and the "option=timeout"
        # setting on newer ipmitool binaries.
        timeout_disable = "0x00 0x08 0x03 0x08"
        send_raw(task, timeout_disable)

        if task.node.driver_info.get('ipmi_force_boot_device', False):
            driver_utils.force_persistent_boot(task,
                                               device,
                                               persistent)
            # Reset persistent to False, in case of BMC does not support
            # persistent or we do not have admin rights.
            persistent = False

        # FIXME(lucasagomes): Older versions of the ipmitool utility
        # are not able to set the options "efiboot" and "persistent"
        # at the same time, combining other options seems to work fine,
        # except efiboot. Newer versions of ipmitool (1.8.17) does fix
        # this problem but (some) distros still packaging an older version.
        # To workaround this problem for now we can make use of sending
        # raw bytes to set the boot device for a node in persistent +
        # uefi mode, this will work with newer and older versions of the
        # ipmitool utility. Also see:
        # https://bugs.launchpad.net/ironic/+bug/1611306
        boot_mode = deploy_utils.get_boot_mode_for_deploy(task.node)
        if persistent and boot_mode == 'uefi':
            raw_cmd = ('0x00 0x08 0x05 0xe0 %s 0x00 0x00 0x00' %
                       BOOT_DEVICE_HEXA_MAP[device])
            send_raw(task, raw_cmd)
            return

        options = []
        if persistent:
            options.append('persistent')
        if boot_mode == 'uefi':
            options.append('efiboot')

        cmd = "chassis bootdev %s" % device
        if options:
            cmd = cmd + " options=%s" % ','.join(options)
        driver_info = _parse_driver_info(task.node)
        try:
            out, err = _exec_ipmitool(driver_info, cmd)
        except (exception.PasswordFileFailedToCreate,
                processutils.ProcessExecutionError) as e:
            LOG.warning(_LW('IPMI set boot device failed for node %(node)s '
                            'when executing "ipmitool %(cmd)s". '
                            'Error: %(error)s'),
                        {'node': driver_info['uuid'], 'cmd': cmd, 'error': e})
            raise exception.IPMIFailure(cmd=cmd)

    @METRICS.timer('IPMIManagement.get_boot_device')
    def get_boot_device(self, task):
        """Get the current boot device for the task's node.

        Returns the current boot device of the node.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue if required IPMI parameters
            are missing.
        :raises: IPMIFailure on an error from ipmitool.
        :raises: MissingParameterValue if a required parameter is missing.
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

        cmd = "chassis bootparam get 5"
        driver_info = _parse_driver_info(task.node)
        response = {'boot_device': None, 'persistent': None}

        try:
            out, err = _exec_ipmitool(driver_info, cmd)
        except (exception.PasswordFileFailedToCreate,
                processutils.ProcessExecutionError) as e:
            LOG.warning(_LW('IPMI get boot device failed for node %(node)s '
                            'when executing "ipmitool %(cmd)s". '
                            'Error: %(error)s'),
                        {'node': driver_info['uuid'], 'cmd': cmd, 'error': e})
            raise exception.IPMIFailure(cmd=cmd)

        re_obj = re.search('Boot Device Selector : (.+)?\n', out)
        if re_obj:
            boot_selector = re_obj.groups('')[0]
            if 'PXE' in boot_selector:
                response['boot_device'] = boot_devices.PXE
            elif 'Hard-Drive' in boot_selector:
                if 'Safe-Mode' in boot_selector:
                    response['boot_device'] = boot_devices.SAFE
                else:
                    response['boot_device'] = boot_devices.DISK
            elif 'BIOS' in boot_selector:
                response['boot_device'] = boot_devices.BIOS
            elif 'CD/DVD' in boot_selector:
                response['boot_device'] = boot_devices.CDROM

        response['persistent'] = 'Options apply to all future boots' in out
        return response

    @METRICS.timer('IPMIManagement.get_sensors_data')
    def get_sensors_data(self, task):
        """Get sensors data.

        :param task: a TaskManager instance.
        :raises: FailedToGetSensorData when getting the sensor data fails.
        :raises: FailedToParseSensorData when parsing sensor data fails.
        :raises: InvalidParameterValue if required ipmi parameters are missing
        :raises: MissingParameterValue if a required parameter is missing.
        :returns: returns a dict of sensor data group by sensor type.

        """
        driver_info = _parse_driver_info(task.node)
        # with '-v' option, we can get the entire sensor data including the
        # extended sensor informations
        cmd = "sdr -v"
        try:
            out, err = _exec_ipmitool(driver_info, cmd)
        except (exception.PasswordFileFailedToCreate,
                processutils.ProcessExecutionError) as e:
            raise exception.FailedToGetSensorData(node=task.node.uuid,
                                                  error=e)

        return _parse_ipmi_sensors_data(task.node, out)


class VendorPassthru(base.VendorInterface):

    def __init__(self):
        _constructor_checks(driver=self.__class__.__name__)

    @METRICS.timer('VendorPassthru.send_raw')
    @base.passthru(['POST'])
    @task_manager.require_exclusive_lock
    def send_raw(self, task, http_method, raw_bytes):
        """Send raw bytes to the BMC. Bytes should be a string of bytes.

        :param task: a TaskManager instance.
        :param http_method: the HTTP method used on the request.
        :param raw_bytes: a string of raw bytes to send, e.g. '0x00 0x01'
        :raises: IPMIFailure on an error from ipmitool.
        :raises: MissingParameterValue if a required parameter is missing.
        :raises:  InvalidParameterValue when an invalid value is specified.

        """
        send_raw(task, raw_bytes)

    @METRICS.timer('VendorPassthru.bmc_reset')
    @base.passthru(['POST'])
    @task_manager.require_exclusive_lock
    def bmc_reset(self, task, http_method, warm=True):
        """Reset BMC with IPMI command 'bmc reset (warm|cold)'.

        :param task: a TaskManager instance.
        :param http_method: the HTTP method used on the request.
        :param warm: boolean parameter to decide on warm or cold reset.
        :raises: IPMIFailure on an error from ipmitool.
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: InvalidParameterValue when an invalid value is specified

        """
        node_uuid = task.node.uuid

        warm = strutils.bool_from_string(warm)
        if warm:
            warm_param = 'warm'
        else:
            warm_param = 'cold'

        LOG.debug('Doing %(warm)s BMC reset on node %(node)s',
                  {'warm': warm_param, 'node': node_uuid})
        driver_info = _parse_driver_info(task.node)
        cmd = 'bmc reset %s' % warm_param

        try:
            out, err = _exec_ipmitool(driver_info, cmd)
            LOG.debug('bmc reset returned stdout: %(stdout)s, stderr:'
                      ' %(stderr)s', {'stdout': out, 'stderr': err})
        except (exception.PasswordFileFailedToCreate,
                processutils.ProcessExecutionError) as e:
            LOG.exception(_LE('IPMI "bmc reset" failed for node %(node_id)s '
                          'with error: %(error)s.'),
                          {'node_id': node_uuid, 'error': e})
            raise exception.IPMIFailure(cmd=cmd)

    def get_properties(self):
        return COMMON_PROPERTIES

    @METRICS.timer('VendorPassthru.validate')
    def validate(self, task, method, **kwargs):
        """Validate vendor-specific actions.

        If invalid, raises an exception; otherwise returns None.

        Valid methods:
          * send_raw
          * bmc_reset

        :param task: a task from TaskManager.
        :param method: method to be validated
        :param kwargs: info for action.
        :raises: InvalidParameterValue when an invalid parameter value is
                 specified.
        :raises: MissingParameterValue if a required parameter is missing.

        """
        if method == 'send_raw':
            if not kwargs.get('raw_bytes'):
                raise exception.MissingParameterValue(_(
                    'Parameter raw_bytes (string of bytes) was not '
                    'specified.'))

        _parse_driver_info(task.node)


class IPMIConsole(base.ConsoleInterface):
    """A base ConsoleInterface that uses ipmitool."""

    def __init__(self):
        _constructor_checks(driver=self.__class__.__name__)

    def get_properties(self):
        d = COMMON_PROPERTIES.copy()
        d.update(CONSOLE_PROPERTIES)
        return d

    @METRICS.timer('IPMIConsole.validate')
    def validate(self, task):
        """Validate the Node console info.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue
        :raises: MissingParameterValue when a required parameter is missing

        """
        driver_info = _parse_driver_info(task.node)
        if not driver_info['port']:
            raise exception.MissingParameterValue(_(
                "Missing 'ipmi_terminal_port' parameter in node's"
                " driver_info."))

        if driver_info['protocol_version'] != '2.0':
            raise exception.InvalidParameterValue(_(
                "Serial over lan only works with IPMI protocol version 2.0. "
                "Check the 'ipmi_protocol_version' parameter in "
                "node's driver_info"))

    def _start_console(self, driver_info, start_method):
        """Start a remote console for the node.

        :param driver_info: the parameters for accessing a node
        :param start_method: console_utils method to start console
        :raises: InvalidParameterValue if required ipmi parameters are missing
        :raises: PasswordFileFailedToCreate if unable to create a file
                 containing the password
        :raises: ConsoleError if the directory for the PID file cannot be
                 created
        :raises: ConsoleSubprocessFailed when invoking the subprocess failed
        """
        path = _console_pwfile_path(driver_info['uuid'])
        pw_file = console_utils.make_persistent_password_file(
            path, driver_info['password'] or '\0')

        ipmi_cmd = ("/:%(uid)s:%(gid)s:HOME:ipmitool -H %(address)s"
                    " -I lanplus -U %(user)s -f %(pwfile)s"
                    % {'uid': os.getuid(),
                       'gid': os.getgid(),
                       'address': driver_info['address'],
                       'user': driver_info['username'],
                       'pwfile': pw_file})

        for name, option in BRIDGING_OPTIONS:
            if driver_info[name] is not None:
                ipmi_cmd = " ".join([ipmi_cmd,
                                     option, driver_info[name]])

        if CONF.debug:
            ipmi_cmd += " -v"
        ipmi_cmd += " sol activate"
        try:
            start_method(driver_info['uuid'], driver_info['port'], ipmi_cmd)
        except (exception.ConsoleError, exception.ConsoleSubprocessFailed):
            with excutils.save_and_reraise_exception():
                ironic_utils.unlink_without_raise(path)


class IPMIShellinaboxConsole(IPMIConsole):
    """A ConsoleInterface that uses ipmitool and shellinabox."""

    @METRICS.timer('IPMIShellinaboxConsole.start_console')
    def start_console(self, task):
        """Start a remote console for the node.

        :param task: a task from TaskManager
        :raises: InvalidParameterValue if required ipmi parameters are missing
        :raises: PasswordFileFailedToCreate if unable to create a file
                 containing the password
        :raises: ConsoleError if the directory for the PID file cannot be
                 created
        :raises: ConsoleSubprocessFailed when invoking the subprocess failed
        """
        driver_info = _parse_driver_info(task.node)
        self._start_console(driver_info,
                            console_utils.start_shellinabox_console)

    @METRICS.timer('IPMIShellinaboxConsole.stop_console')
    def stop_console(self, task):
        """Stop the remote console session for the node.

        :param task: a task from TaskManager
        :raises: ConsoleError if unable to stop the console
        """
        try:
            console_utils.stop_shellinabox_console(task.node.uuid)
        finally:
            ironic_utils.unlink_without_raise(
                _console_pwfile_path(task.node.uuid))

    @METRICS.timer('IPMIShellinaboxConsole.get_console')
    def get_console(self, task):
        """Get the type and connection information about the console."""
        driver_info = _parse_driver_info(task.node)
        url = console_utils.get_shellinabox_console_url(driver_info['port'])
        return {'type': 'shellinabox', 'url': url}


class IPMISocatConsole(IPMIConsole):
    """A ConsoleInterface that uses ipmitool and socat."""

    @METRICS.timer('IPMISocatConsole.start_console')
    def start_console(self, task):
        """Start a remote console for the node.

        :param task: a task from TaskManager
        :raises: InvalidParameterValue if required ipmi parameters are missing
        :raises: PasswordFileFailedToCreate if unable to create a file
                 containing the password
        :raises: ConsoleError if the directory for the PID file cannot be
                 created
        :raises: ConsoleSubprocessFailed when invoking the subprocess failed
        """
        driver_info = _parse_driver_info(task.node)
        try:
            self._exec_stop_console(driver_info)
        except OSError:
            # We need to drop any existing sol sessions with sol deactivate.
            # OSError is raised when sol session is already deactivated,
            # so we can ignore it.
            pass
        self._start_console(driver_info, console_utils.start_socat_console)

    @METRICS.timer('IPMISocatConsole.stop_console')
    def stop_console(self, task):
        """Stop the remote console session for the node.

        :param task: a task from TaskManager
        :raises: ConsoleError if unable to stop the console
        """
        driver_info = _parse_driver_info(task.node)
        try:
            console_utils.stop_socat_console(task.node.uuid)
        finally:
            ironic_utils.unlink_without_raise(
                _console_pwfile_path(task.node.uuid))
        self._exec_stop_console(driver_info)

    def _exec_stop_console(self, driver_info):
        cmd = "sol deactivate"
        _exec_ipmitool(driver_info, cmd, check_exit_code=[0, 1])

    @METRICS.timer('IPMISocatConsole.get_console')
    def get_console(self, task):
        """Get the type and connection information about the console.

        :param task: a task from TaskManager
        """
        driver_info = _parse_driver_info(task.node)
        url = console_utils.get_socat_console_url(driver_info['port'])
        return {'type': 'socat', 'url': url}
