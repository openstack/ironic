# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 NTT DOCOMO, INC.
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
Baremetal IPMI power manager.
"""

import os
import stat
import tempfile

from oslo.config import cfg

from ironic.common import exception
from ironic.common import paths
from ironic.common import states
from ironic.common import utils
from ironic.drivers import base
from ironic.manager import task_manager
from ironic.openstack.common import jsonutils as json
from ironic.openstack.common import log as logging
from ironic.openstack.common import loopingcall

opts = [
    cfg.StrOpt('terminal',
               default='shellinaboxd',
               help='path to baremetal terminal program'),
    cfg.StrOpt('terminal_cert_dir',
               default=None,
               help='path to baremetal terminal SSL cert(PEM)'),
    cfg.StrOpt('terminal_pid_dir',
               default=paths.state_path_def('baremetal/console'),
               help='path to directory stores pidfiles of baremetal_terminal'),
    cfg.IntOpt('ipmi_power_retry',
               default=5,
               help='Maximum seconds to retry IPMI operations'),
    ]

CONF = cfg.CONF
CONF.register_opts(opts)

LOG = logging.getLogger(__name__)

VALID_BOOT_DEVICES = ['pxe', 'disk', 'safe', 'cdrom', 'bios']


# TODO(deva): use a contextmanager for this, and port it to nova.
def _make_password_file(password):
    fd, path = tempfile.mkstemp()
    os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as f:
        f.write(password)
    return path


def _parse_control_info(node):
    info = json.loads(node.get('control_info', ''))
    address = info.get('ipmi_address', None)
    user = info.get('ipmi_username', None)
    password = info.get('ipmi_password', None)
    port = info.get('ipmi_terminal_port', None)

    if not address or not user or not password:
        raise exception.InvalidParameterValue(_(
            "IPMI credentials not supplied to IPMI driver."))

    return {
            'address': address,
            'user': user,
            'password': password,
            'port': port,
            'uuid': node.get('uuid')
           }


def _exec_ipmitool(c_info, command):
    args = ['ipmitool',
            '-I',
            'lanplus',
            '-H',
            c_info['address'],
            '-U',
            c_info['user'],
            '-f']
    try:
        pwfile = _make_password_file(c_info['password'])
        args.append(pwfile)
        args.extend(command.split(" "))
        out, err = utils.execute(*args, attempts=3)
        LOG.debug(_("ipmitool stdout: '%(out)s', stderr: '%(err)s'"),
                  locals())
        return out, err
    finally:
        utils.delete_if_exists(pwfile)


def _power_on(c_info):
    """Turn the power to this node ON."""

    # use mutable objects so the looped method can change them
    state = [None]
    retries = [0]

    def _wait_for_power_on(state, retries):
        """Called at an interval until the node's power is on."""

        state[0] = _power_status(c_info)
        if state[0] == states.POWER_ON:
            raise loopingcall.LoopingCallDone()

        if retries[0] > CONF.ipmi_power_retry:
            state[0] = states.ERROR
            raise loopingcall.LoopingCallDone()
        try:
            retries[0] += 1
            _exec_ipmitool(c_info, "power on")
        except Exception:
            # Log failures but keep trying
            LOG.warning(_("IPMI power on failed for node %s.")
                    % c_info['uuid'])

    timer = loopingcall.FixedIntervalLoopingCall(_wait_for_power_on,
                                                 state, retries)
    timer.start(interval=1).wait()
    return state[0]


def _power_off(c_info):
    """Turn the power to this node OFF."""

    # use mutable objects so the looped method can change them
    state = [None]
    retries = [0]

    def _wait_for_power_off(state, retries):
        """Called at an interval until the node's power is off."""

        state[0] = _power_status(c_info)
        if state[0] == states.POWER_OFF:
            raise loopingcall.LoopingCallDone()

        if retries[0] > CONF.ipmi_power_retry:
            state[0] = states.ERROR
            raise loopingcall.LoopingCallDone()
        try:
            retries[0] += 1
            _exec_ipmitool(c_info, "power off")
        except Exception:
            # Log failures but keep trying
            LOG.warning(_("IPMI power off failed for node %s.")
                    % c_info['uuid'])

    timer = loopingcall.FixedIntervalLoopingCall(_wait_for_power_off,
                                                 state=state, retries=retries)
    timer.start(interval=1).wait()
    return state[0]


def _power_status(c_info):
    out_err = _exec_ipmitool(c_info, "power status")
    if out_err[0] == "Chassis Power is on\n":
        return states.POWER_ON
    elif out_err[0] == "Chassis Power is off\n":
        return states.POWER_OFF
    else:
        return states.ERROR


class IPMIPowerDriver(base.ControlDriver):
    """Generic IPMI Power Driver

    This ControlDriver class provides mechanism for controlling the power state
    of physical hardware via IPMI calls. It also provides console access for
    some supported hardware.

    NOTE: This driver does not currently support multi-node operations.
    """

    def __init__(self):
        pass

    def validate_driver_info(self, node):
        """Check that node['control_info'] contains the requisite fields."""
        try:
            _parse_control_info(node)
        except exception.InvalidParameterValue:
            return False
        return True

    def get_power_state(self, task, node):
        """Get the current power state."""
        c_info = _parse_control_info(node)
        return _power_status(c_info)

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, node, pstate):
        """Turn the power on or off."""
        c_info = _parse_control_info(node)

        if pstate == states.POWER_ON:
            state = _power_on(c_info)
        elif pstate == states.POWER_OFF:
            state = _power_off(c_info)
        else:
            raise exception.IronicException(_(
                "set_power_state called with invalid power state."))

        if state != pstate:
            raise exception.PowerStateFailure(pstate=pstate)

    @task_manager.require_exclusive_lock
    def reboot(self, task, node):
        """Cycles the power to a node."""
        c_info = _parse_control_info(node)
        _power_off(c_info)
        state = _power_on(c_info)

        if state != states.POWER_ON:
            raise exception.PowerStateFailure(pstate=states.POWER_ON)

    @task_manager.require_exclusive_lock
    def set_boot_device(self, task, node, device, persistent=False):
        """Set the boot device for a node.

        :param task: TaskManager context.
        :param node: The Node.
        :param device: Boot device. One of [pxe, disk, cdrom, safe, bios].
        :param persistent: Whether to set next-boot, or make the change
            permanent. Default: False.
        :raises: InvalidParameterValue if an invalid boot device is specified.
        :raises: IPMIFailure on an error from ipmitool.

        """
        if device not in VALID_BOOT_DEVICES:
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)
        cmd = "chassis bootdev %s" % device
        if persistent:
            cmd = cmd + " options=persistent"
        c_info = _parse_control_info(node)
        try:
            out, err = _exec_ipmitool(c_info, cmd)
            # TODO(deva): validate (out, err) and add unit test for failure
        except Exception:
            raise exception.IPMIFailure(cmd=cmd)

    # TODO(deva): port start_console
    def start_console(self, task, node):
        raise exception.IronicException(_(
            "start_console is not supported by IPMIPowerDriver."))

    # TODO(deva): port stop_console
    def stop_console(self, task, node):
        raise exception.IronicException(_(
            "stop_console is not supported by IPMIPowerDriver."))
