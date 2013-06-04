# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
Ironic SSH power manager.

Provides basic power control of virtual machines via SSH.

For use in dev and test environments.

Currently supported environments are:
    Virtual Box (vbox)
    Virsh       (virsh)

"""

import os

from oslo.config import cfg

from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.drivers import base
from ironic.manager import task_manager
from ironic.openstack.common import jsonutils as json
from ironic.openstack.common import log as logging

CONF = cfg.CONF

LOG = logging.getLogger(__name__)

COMMAND_SETS = {
    'vbox': {
        'base_cmd': '/usr/bin/VBoxManage',
        'start_cmd': 'startvm {_NodeName_}',
        'stop_cmd': 'controlvm {_NodeName_} poweroff',
        'reboot_cmd': 'controlvm {_NodeName_} reset',
        'list_all': "list vms|awk -F'\"' '{print $2}'",
        'list_running': 'list runningvms',
        'get_node_macs': ("showvminfo --machinereadable {_NodeName_} | "
            "grep "
            '"macaddress" | awk -F '
            "'"
            '"'
            "' '{print $2}'")
    },
    "virsh": {
        'base_cmd': '/usr/bin/virsh',
        'start_cmd': 'start {_NodeName_}',
        'stop_cmd': 'destroy {_NodeName_}',
        'reboot_cmd': 'reset {_NodeName_}',
        'list_all': "list --all | tail -n +2 | awk -F\" \" '{print $2}'",
        'list_running':
            "list --all|grep running|awk -v qc='\"' -F\" \" '{print qc$2qc}'",
        'get_node_macs': ("dumpxml {_NodeName_} | grep "
            '"mac address" | awk -F'
            '"'
            "'"
            '" '
            "'{print $2}' | tr -d ':'")
    }
}


def _normalize_mac(mac):
    return mac.translate(None, '-:').lower()


def _exec_ssh_command(ssh_obj, command):
    """Execute a SSH command on the host."""

    LOG.debug(_('Running cmd (SSH): %s'), command)

    stdin_stream, stdout_stream, stderr_stream = ssh_obj.exec_command(command)
    channel = stdout_stream.channel

    # NOTE(justinsb): This seems suspicious...
    # ...other SSH clients have buffering issues with this approach
    stdout = stdout_stream.read()
    stderr = stderr_stream.read()
    stdin_stream.close()

    exit_status = channel.recv_exit_status()

    # exit_status == -1 if no exit code was returned
    if exit_status != -1:
        LOG.debug(_('Result was %s') % exit_status)
        if exit_status != 0:
            raise exception.ProcessExecutionError(exit_code=exit_status,
                                                  stdout=stdout,
                                                  stderr=stderr,
                                                  cmd=command)

    return (stdout, stderr)


def _parse_control_info(node):
    info = json.loads(node.get('control_info', ''))
    host = info.get('ssh_host', None)
    username = info.get('ssh_user', None)
    password = info.get('ssh_pass', None)
    port = info.get('ssh_port', 22)
    key_filename = info.get('ssh_key', None)
    virt_type = info.get('virt_type', None)

    res = {
           'host': host,
           'username': username,
           'port': port,
           'virt_type': virt_type,
           'uuid': node.get('uuid')
          }

    if not virt_type:
        raise exception.InvalidParameterValue(_(
            "SSHPowerDriver requires virt_type be set."))

    cmd_set = COMMAND_SETS.get(virt_type, None)
    if not cmd_set:
        raise exception.InvalidParameterValue(_(
            "SSHPowerDriver unknown virt_type (%s).") % cmd_set)
    res['cmd_set'] = cmd_set

    if not host or not username:
        raise exception.InvalidParameterValue(_(
            "SSHPowerDriver requires both ssh_host and ssh_user be set."))
    if password:
        res['password'] = password
    else:
        if not key_filename:
            raise exception.InvalidParameterValue(_(
                "SSHPowerDriver requires either ssh_pass or ssh_key be set."))
        if not os.path.isfile(key_filename):
            raise exception.FileNotFound(file_path=key_filename)
        res['key_filename'] = key_filename

    return res


def _get_power_status(ssh_obj, c_info):
    """Returns a node's current power state."""

    power_state = None
    cmd_to_exec = c_info['cmd_set']['list_running']
    running_list = _exec_ssh_command(ssh_obj, cmd_to_exec)
    # Command should return a list of running vms. If the current node is
    # not listed then we can assume it is not powered on.
    node_name = _get_hosts_name_for_node(ssh_obj, c_info)
    if node_name:
        for node in running_list:
            if node_name in node:
                power_state = states.POWER_ON
                break
        if not power_state:
            power_state = states.POWER_OFF
    else:
        power_state = states.ERROR

    return power_state


def _get_connection(node):
    return utils.ssh_connect(_parse_control_info(node))


def _get_hosts_name_for_node(ssh_obj, c_info):
    """Get the name the host uses to reference the node."""

    matched_name = None
    cmd_to_exec = c_info['cmd_set']['list_all']
    full_node_list = _exec_ssh_command(ssh_obj, cmd_to_exec)
    # for each node check Mac Addresses
    for node in full_node_list:
        cmd_to_exec = c_info['cmd_set']['get_node_macs']
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', node)
        hosts_node_mac_list = _exec_ssh_command(ssh_obj, cmd_to_exec)

        for host_mac in hosts_node_mac_list:
            for node_mac in c_info['macs']:
                if _normalize_mac(host_mac) in _normalize_mac(node_mac):
                    matched_name = node
                    break

            if matched_name:
                break
        if matched_name:
            break

    return matched_name


def _power_on(ssh_obj, c_info):
    """Power ON this node."""

    current_pstate = _get_power_status(ssh_obj, c_info)
    if current_pstate == states.POWER_ON:
        _power_off(ssh_obj, c_info)

    node_name = _get_hosts_name_for_node(ssh_obj, c_info)
    cmd_to_power_on = c_info['cmd_set']['start_cmd']
    cmd_to_power_on = cmd_to_power_on.replace('{_NodeName_}', node_name)

    _exec_ssh_command(ssh_obj, cmd_to_power_on)

    current_pstate = _get_power_status(ssh_obj, c_info)
    if current_pstate == states.POWER_ON:
        return current_pstate
    else:
        return states.ERROR


def _power_off(ssh_obj, c_info):
    """Power OFF this node."""

    current_pstate = _get_power_status(ssh_obj, c_info)
    if current_pstate == states.POWER_OFF:
        return current_pstate

    node_name = _get_hosts_name_for_node(ssh_obj, c_info)
    cmd_to_power_off = c_info['cmd_set']['stop_cmd']
    cmd_to_power_off = cmd_to_power_off.replace('{_NodeName_}', node_name)

    _exec_ssh_command(ssh_obj, cmd_to_power_off)

    current_pstate = _get_power_status(ssh_obj, c_info)
    if current_pstate == states.POWER_OFF:
        return current_pstate
    else:
        return states.ERROR


def _get_nodes_mac_addresses(task, node):
    """Get all mac addresses for a node."""
    interface_ports = task.dbapi.get_ports_by_node(node.get('id'))
    macs = [p.address for p in interface_ports]
    return macs


class SSHPowerDriver(base.ControlDriver):
    """SSH Power Driver.

    This ControlDriver class provides a mechanism for controlling the power
    state of virtual machines via SSH.

    NOTE: This driver supports VirtualBox and Virsh commands.
    NOTE: This driver does not currently support multi-node operations.

    """

    def __init__(self):
        pass

    def validate_driver_info(self, node):
        """Check that node['control_info'] contains the requisite fields.

        :param node: Single node object.

        :returns: True / False.

        """
        try:
            _parse_control_info(node)
        except exception.InvalidParameterValue:
            return False
        return True

    def get_power_state(self, task, node):
        """Get the current power state.

        Poll the host for the current power state of the node.

        :param task: A instance of `ironic.manager.task_manager.TaskManager`.
        :param node: A single node.

        :returns: power state. One of :class:`ironic.common.states`.

        """
        c_info = _parse_control_info(node)
        c_info['macs'] = _get_nodes_mac_addresses(task, node)
        ssh_obj = _get_connection(node)
        return _get_power_status(ssh_obj, c_info)

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, node, pstate):
        """Turn the power on or off.

        Set the power state of a node.

        :param task: A instance of `ironic.manager.task_manager.TaskManager`.
        :param node: A single node.
        :param pstate: Either POWER_ON or POWER_OFF from :class:
            `ironic.common.states`.

        :returns NOTHING:

        Can raise exception.IronicException or exception.PowerStateFailure.

        """
        c_info = _parse_control_info(node)
        c_info['macs'] = _get_nodes_mac_addresses(task, node)
        ssh_obj = _get_connection(node)

        if pstate == states.POWER_ON:
            state = _power_on(ssh_obj, c_info)
        elif pstate == states.POWER_OFF:
            state = _power_off(ssh_obj, c_info)
        else:
            raise exception.IronicException(_(
                "set_power_state called with invalid power state."))

        if state != pstate:
            raise exception.PowerStateFailure(pstate=pstate)

    @task_manager.require_exclusive_lock
    def reboot(self, task, node):
        """Cycles the power to a node.

        Power cycles a node.

        :param task: A instance of `ironic.manager.task_manager.TaskManager`.
        :param node: A single node.

        :returns NOTHING:

        Can raise exception.PowerStateFailure.

        """
        c_info = _parse_control_info(node)
        c_info['macs'] = _get_nodes_mac_addresses(task, node)
        ssh_obj = _get_connection(node)
        current_pstate = _get_power_status(ssh_obj, c_info)
        if current_pstate == states.POWER_ON:
            _power_off(ssh_obj, c_info)

        state = _power_on(ssh_obj, c_info)

        if state != states.POWER_ON:
            raise exception.PowerStateFailure(pstate=states.POWER_ON)

    def start_console(self, task, node):
        """Starts a console connection to a node.

        CURRENTLY NOT SUPPORTED.

        :param task: A instance of `ironic.manager.task_manager.TaskManager`.
        :param node: A single node.

        Will raise raise exception.IronicException.

        """
        raise exception.IronicException(_(
            "start_console is not supported by SSHPowerDriver."))

    def stop_console(self, task, node):
        """Stops a console connection to a node.

        CURRENTLY NOT SUPPORTED.

        :param task: A instance of `ironic.manager.task_manager.TaskManager`.
        :param node: A single node.

        Will raise raise exception.IronicException.

        """

        raise exception.IronicException(_(
            "stop_console is not supported by SSHPowerDriver."))
