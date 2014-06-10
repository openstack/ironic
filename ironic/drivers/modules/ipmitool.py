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
Ironic IPMI power manager.
"""

import contextlib
import os
import stat
import tempfile

from oslo.config import cfg

from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules import console_utils
from ironic.openstack.common import excutils
from ironic.openstack.common import log as logging
from ironic.openstack.common import loopingcall

CONF = cfg.CONF

LOG = logging.getLogger(__name__)

VALID_BOOT_DEVICES = ['pxe', 'disk', 'safe', 'cdrom', 'bios']
VALID_PRIV_LEVELS = ['ADMINISTRATOR', 'CALLBACK', 'OPERATOR', 'USER']


def _console_pwfile_path(uuid):
    """Return the file path for storing the ipmi password for a console."""
    file_name = "%(uuid)s.pw" % {'uuid': uuid}
    return os.path.join(tempfile.gettempdir(), file_name)


@contextlib.contextmanager
def _make_password_file(password):
    """Makes a temporary file that contains the password.

    :param password: the password
    :returns: the absolute pathname of the temporary file
    :raises: Exception from creating or writing to the temporary file
    """
    try:
        fd, path = tempfile.mkstemp()
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            f.write(password)

        yield path
        utils.delete_if_exists(path)
    except Exception:
        with excutils.save_and_reraise_exception():
            utils.delete_if_exists(path)


def _parse_driver_info(node):
    """Gets the parameters required for ipmitool to access the node.

    :param node: the Node of interest.
    :returns: dictionary of parameters.
    :raises: InvalidParameterValue if any required parameters are missing.

    """
    info = node.driver_info or {}
    address = info.get('ipmi_address')
    username = info.get('ipmi_username')
    password = info.get('ipmi_password')
    port = info.get('ipmi_terminal_port')
    priv_level = info.get('ipmi_priv_level', 'ADMINISTRATOR')

    if port:
        try:
            port = int(port)
        except ValueError:
            raise exception.InvalidParameterValue(_(
                "IPMI terminal port is not an integer."))

    if not address:
        raise exception.InvalidParameterValue(_(
            "IPMI address not supplied to IPMI driver."))

    if priv_level not in VALID_PRIV_LEVELS:
        valid_priv_lvls = ', '.join(VALID_PRIV_LEVELS)
        raise exception.InvalidParameterValue(_(
            "Invalid privilege level value:%(priv_level)s, the valid value"
            " can be one of %(valid_levels)s") %
            {'priv_level': priv_level, 'valid_levels': valid_priv_lvls})

    return {
            'address': address,
            'username': username,
            'password': password,
            'port': port,
            'uuid': node.uuid,
            'priv_level': priv_level
           }


def _exec_ipmitool(driver_info, command):
    """Execute the ipmitool command.

    This uses the lanplus interface to communicate with the BMC device driver.

    :param driver_info: the ipmitool parameters for accessing a node.
    :param command: the ipmitool command to be executed.
    :returns: (stdout, stderr) from executing the command.
    :raises: some Exception from making the password file or from executing
        the command.

    """
    args = ['ipmitool',
            '-I',
            'lanplus',
            '-H',
            driver_info['address'],
            '-L', driver_info.get('priv_level')
            ]

    if driver_info['username']:
        args.append('-U')
        args.append(driver_info['username'])

    # 'ipmitool' command will prompt password if there is no '-f' option,
    # we set it to '\0' to write a password file to support empty password

    with _make_password_file(driver_info['password'] or '\0') as pw_file:
        args.append('-f')
        args.append(pw_file)
        args.extend(command.split(" "))
        out, err = utils.execute(*args, attempts=3)
        LOG.debug("ipmitool stdout: '%(out)s', stderr: '%(err)s', from node "
                  "%(node_id)s",
                  {'out': out, 'err': err, 'node_id': driver_info['uuid']})
        return out, err


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
    :raises: IPMIFailure on an error from ipmitool (from _power_status call).

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
        except Exception:
            # Log failures but keep trying
            LOG.warning(_("IPMI power %(state)s failed for node %(node)s."),
                         {'state': state_name, 'node': driver_info['uuid']})
        finally:
            mutable['iter'] += 1

        if mutable['power'] == target_state:
            raise loopingcall.LoopingCallDone()

        sleep_time = _sleep_time(mutable['iter'])
        if (sleep_time + mutable['total_time']) > CONF.ipmi.retry_timeout:
            # Stop if the next loop would exceed maximum retry_timeout
            LOG.error(_('IPMI power %(state)s timed out after '
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
    except Exception as e:
        LOG.warning(_("IPMI power status failed for node %(node_id)s with "
                      "error: %(error)s.")
                    % {'node_id': driver_info['uuid'], 'error': e})
        raise exception.IPMIFailure(cmd=cmd)

    if out_err[0] == "Chassis Power is on\n":
        return states.POWER_ON
    elif out_err[0] == "Chassis Power is off\n":
        return states.POWER_OFF
    else:
        return states.ERROR


class IPMIPower(base.PowerInterface):

    def validate(self, task, node):
        """Validate driver_info for ipmitool driver.

        Check that node['driver_info'] contains IPMI credentials and BMC is
        accessible with this credentials.

        :param task: a task from TaskManager.
        :param node: Single node object.
        :raises: InvalidParameterValue if required ipmi parameters are missing.

        """
        driver_info = _parse_driver_info(node)
        try:
            _exec_ipmitool(driver_info, "mc guid")
        except Exception as e:
            msg = _("BMC inaccessible for node %(node)s: "
                    "%(error)s") % {'node': node.uuid, 'error': e}
            raise exception.InvalidParameterValue(msg)

    def get_power_state(self, task):
        """Get the current power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: one of ironic.common.states POWER_OFF, POWER_ON or ERROR.
        :raises: InvalidParameterValue if required ipmi parameters are missing.
        :raises: IPMIFailure on an error from ipmitool (from _power_status
            call).

        """
        driver_info = _parse_driver_info(task.node)
        return _power_status(driver_info)

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, pstate):
        """Turn the power on or off.

        :param task: a TaskManager instance containing the node to act on.
        :param pstate: The desired power state, one of ironic.common.states
            POWER_ON, POWER_OFF.
        :raises: InvalidParameterValue if required ipmi parameters are missing
            or if an invalid power state was specified.
        :raises: PowerStateFailure if the power couldn't be set to pstate.

        """
        driver_info = _parse_driver_info(task.node)

        if pstate == states.POWER_ON:
            state = _power_on(driver_info)
        elif pstate == states.POWER_OFF:
            state = _power_off(driver_info)
        else:
            raise exception.InvalidParameterValue(_("set_power_state called "
                    "with invalid power state %s.") % pstate)

        if state != pstate:
            raise exception.PowerStateFailure(pstate=pstate)

    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Cycles the power to the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if required ipmi parameters are missing.
        :raises: PowerStateFailure if the final state of the node is not
            POWER_ON.

        """
        driver_info = _parse_driver_info(task.node)
        _power_off(driver_info)
        state = _power_on(driver_info)

        if state != states.POWER_ON:
            raise exception.PowerStateFailure(pstate=states.POWER_ON)


class VendorPassthru(base.VendorInterface):

    @task_manager.require_exclusive_lock
    def _set_boot_device(self, task, device, persistent=False):
        """Set the boot device for a node.

        :param task: a TaskManager instance.
        :param device: Boot device. One of [pxe, disk, cdrom, safe, bios].
        :param persistent: Whether to set next-boot, or make the change
            permanent. Default: False.
        :raises: InvalidParameterValue if an invalid boot device is specified
            or if required ipmi parameters are missing.
        :raises: IPMIFailure on an error from ipmitool.

        """
        if device not in VALID_BOOT_DEVICES:
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)
        cmd = "chassis bootdev %s" % device
        if persistent:
            cmd = cmd + " options=persistent"
        driver_info = _parse_driver_info(task.node)
        try:
            out, err = _exec_ipmitool(driver_info, cmd)
            # TODO(deva): validate (out, err) and add unit test for failure
        except Exception:
            raise exception.IPMIFailure(cmd=cmd)

    def validate(self, task, **kwargs):
        method = kwargs['method']
        if method == 'set_boot_device':
            device = kwargs.get('device')
            if device not in VALID_BOOT_DEVICES:
                raise exception.InvalidParameterValue(_(
                    "Invalid boot device %s specified.") % device)
        else:
            raise exception.InvalidParameterValue(_(
                "Unsupported method (%s) passed to IPMItool driver.")
                % method)

        return True

    def vendor_passthru(self, task, **kwargs):
        method = kwargs['method']
        if method == 'set_boot_device':
            return self._set_boot_device(
                        task,
                        kwargs.get('device'),
                        kwargs.get('persistent', False))


class IPMIShellinaboxConsole(base.ConsoleInterface):
    """A ConsoleInterface that uses ipmitool and shellinabox."""

    def validate(self, task, node):
        """Validate the Node console info.

        :param node: a single Node to validate.
        :raises: InvalidParameterValue
        """
        driver_info = _parse_driver_info(node)
        if not driver_info['port']:
            raise exception.InvalidParameterValue(_(
                "IPMI terminal port not supplied to IPMI driver."))

    def start_console(self, task, node):
        """Start a remote console for the node."""
        driver_info = _parse_driver_info(node)

        path = _console_pwfile_path(driver_info['uuid'])
        pw_file = console_utils.make_persistent_password_file(
                path, driver_info['password'])

        ipmi_cmd = "/:%(uid)s:%(gid)s:HOME:ipmitool -H %(address)s" \
                   " -I lanplus -U %(user)s -f %(pwfile)s"  \
                   % {'uid': os.getuid(),
                      'gid': os.getgid(),
                      'address': driver_info['address'],
                      'user': driver_info['username'],
                      'pwfile': pw_file}
        if CONF.debug:
            ipmi_cmd += " -v"
        ipmi_cmd += " sol activate"
        console_utils.start_shellinabox_console(driver_info['uuid'],
                                                driver_info['port'],
                                                ipmi_cmd)

    def stop_console(self, task, node):
        """Stop the remote console session for the node."""
        driver_info = _parse_driver_info(node)
        console_utils.stop_shellinabox_console(driver_info['uuid'])
        utils.unlink_without_raise(_console_pwfile_path(driver_info['uuid']))

    def get_console(self, task, node):
        """Get the type and connection information about the console."""
        driver_info = _parse_driver_info(node)
        url = console_utils.get_shellinabox_console_url(driver_info['port'])
        return {'type': 'shellinabox', 'url': url}
