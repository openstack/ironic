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
    VMware      (vmware)
    Parallels   (parallels)
    XenServer   (xenserver)
"""

import os

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import strutils

import retrying

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _, _LE, _LW
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import console_utils
from ironic.drivers import utils as driver_utils

LOG = logging.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'ssh_address': _("IP address or hostname of the node to ssh into. "
                     "Required."),
    'ssh_username': _("username to authenticate as. Required."),
    'ssh_virt_type': _("virtualization software to use; one of vbox, virsh, "
                       "vmware, parallels, xenserver. Required.")
}
OTHER_PROPERTIES = {
    'ssh_key_contents': _("private key(s). One of this, ssh_key_filename, "
                          "or ssh_password must be specified."),
    'ssh_key_filename': _("(list of) filename(s) of optional private key(s) "
                          "for authentication. One of this, ssh_key_contents, "
                          "or ssh_password must be specified."),
    'ssh_password': _("password to use for authentication or for unlocking a "
                      "private key. One of this, ssh_key_contents, or "
                      "ssh_key_filename must be specified."),
    'ssh_port': _("port on the node to connect to; default is 22. Optional."),
    'vbox_use_headless': _("True or False (Default). Optional. "
                           "In the case of VirtualBox 3.2 and above, allows "
                           "the user to use a headless remote VirtualBox "
                           "machine.")
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OTHER_PROPERTIES)
CONSOLE_PROPERTIES = {
    'ssh_terminal_port': _("node's UDP port to connect to. Only required for "
                           "console access and only applicable for 'virsh'.")
}

# NOTE(dguerri) Generic boot device map. Virtualisation types that don't define
# a more specific one, will use this.
# This is left for compatibility with other modules and is still valid for
# virsh and vmware.
_BOOT_DEVICES_MAP = {
    boot_devices.DISK: 'hd',
    boot_devices.PXE: 'network',
    boot_devices.CDROM: 'cdrom',
}


def _get_boot_device_map(virt_type):
    if virt_type in ('virsh', 'vmware'):
        return _BOOT_DEVICES_MAP
    elif virt_type == 'vbox':
        return {
            boot_devices.DISK: 'disk',
            boot_devices.PXE: 'net',
            boot_devices.CDROM: 'dvd',
        }
    elif virt_type == 'xenserver':
        return {
            boot_devices.DISK: 'c',
            boot_devices.PXE: 'n',
            boot_devices.CDROM: 'd',
        }
    elif virt_type == 'parallels':
        return {
            boot_devices.DISK: 'hdd0',
            boot_devices.PXE: 'net0',
            boot_devices.CDROM: 'cdrom0',
        }
    else:
        raise exception.InvalidParameterValue(_(
            "SSHPowerDriver '%(virt_type)s' is not a valid virt_type.") %
            {'virt_type': virt_type})


def _get_command_sets(virt_type, use_headless=False):
    """Retrieves the virt_type-specific commands to control power

    :param virt_type: Hypervisor type (virsh, vmware, vbox, parallels,
        xenserver)
    :param use_headless: boolean value, defaults to False.
        use_headless is used by some Hypervisors (only VBox v3.2 and above)
        to determine if the hypervisor is being used on a headless box.
        This is only relevant to Desktop Hypervisors that have different
        CLI settings depending upon the availability of a graphical
        environment working on the hypervisor itself. Again, only VBox
        makes this distinction and allows "--type headless" to some of
        its sub-commands. This is needed for support of tripleo with
        VBox as the Hypervisor but some other Hypervisors could make
        use of it in the future (Parallels, VMWare Workstation, etc...)

    Required commands are as follows:

    base_cmd: Used by most sub-commands as the primary executable
    list_all: Lists all VMs (by virt_type identifier) that can be managed.
        One name per line, must not be quoted.
    list_running: Lists all running VMs (by virt_type identifier).
        One name per line, can be quoted.
    start_cmd / stop_cmd: Starts or stops the identified VM
    get_node_macs: Retrieves all MACs for an identified VM.
        One MAC per line, any standard format (see driver_utils.normalize_mac)
    get_boot_device / set_boot_device: Gets or sets the primary boot device
    """
    if virt_type == 'vbox':
        vbox_headless_str = ''
        if use_headless:
            vbox_headless_str = ' --type headless'
        return {
            'base_cmd': 'LC_ALL=C /usr/bin/VBoxManage',
            'start_cmd': 'startvm {_NodeName_}%s' % vbox_headless_str,
            'stop_cmd': 'controlvm {_NodeName_} poweroff',
            'reboot_cmd': 'controlvm {_NodeName_} reset',
            'list_all': "list vms|awk -F'\"' '{print $2}'",
            'list_running': 'list runningvms',
            'get_node_macs': (
                "showvminfo --machinereadable {_NodeName_} | "
                "awk -F '\"' '/macaddress/{print $2}'"),
            'set_boot_device': (
                '{_BaseCmd_} modifyvm {_NodeName_} '
                '--boot1 {_BootDevice_}'),
            'get_boot_device': (
                "{_BaseCmd_} showvminfo "
                "--machinereadable {_NodeName_} | "
                "awk -F '\"' '/boot1/{print $2}'"),
        }
    elif virt_type == 'vmware':
        return {
            'base_cmd': 'LC_ALL=C /bin/vim-cmd',
            'start_cmd': 'vmsvc/power.on {_NodeName_}',
            'stop_cmd': 'vmsvc/power.off {_NodeName_}',
            'reboot_cmd': 'vmsvc/power.reboot {_NodeName_}',
            'list_all': "vmsvc/getallvms | awk '$1 ~ /^[0-9]+$/ {print $1}'",
            # NOTE(arata): In spite of its name, list_running_cmd shows a
            #              single vmid, not a list. But it is OK.
            'list_running': (
                "vmsvc/power.getstate {_NodeName_} | "
                "grep 'Powered on' >/dev/null && "
                "echo '\"{_NodeName_}\"' || true"),
            # NOTE(arata): `true` is needed to handle a false vmid, which can
            #              be returned by list_cmd. In that case, get_node_macs
            #              returns an empty list rather than fails with
            #              non-zero status code.
            'get_node_macs': (
                "vmsvc/device.getdevices {_NodeName_} | "
                "grep macAddress | awk -F '\"' '{print $2}' || true"),
        }
    elif virt_type == "virsh":
        # NOTE(NobodyCam): changes to the virsh commands will impact CI
        #                  see https://review.openstack.org/83906
        #                  Change-Id: I160e4202952b7551b855dc7d91784d6a184cb0ed
        #                  for more detail.
        virsh_cmds = {
            'base_cmd': 'LC_ALL=C /usr/bin/virsh',
            'start_cmd': 'start {_NodeName_}',
            'stop_cmd': 'destroy {_NodeName_}',
            'reboot_cmd': 'reset {_NodeName_}',
            'list_all': 'list --all --name',
            'list_running': 'list --name',
            'get_node_macs': (
                "dumpxml {_NodeName_} | "
                "awk -F \"'\" '/mac address/{print $2}'| tr -d ':'"),
            'set_boot_device': (
                "EDITOR=\"sed -i '/<boot \(dev\|order\)=*\>/d;"
                "/<\/os>/i\<boot dev=\\\"{_BootDevice_}\\\"/>'\" "
                "{_BaseCmd_} edit {_NodeName_}"),
            'get_boot_device': (
                "{_BaseCmd_} dumpxml {_NodeName_} | "
                "awk '/boot dev=/ { gsub( \".*dev=\" Q, \"\" ); "
                "gsub( Q \".*\", \"\" ); print; }' "
                "Q=\"'\" RS=\"[<>]\" | "
                "head -1"),
        }

        if CONF.ssh.libvirt_uri:
            virsh_cmds['base_cmd'] += ' --connect %s' % CONF.ssh.libvirt_uri

        return virsh_cmds
    elif virt_type == 'parallels':
        return {
            'base_cmd': 'LC_ALL=C /usr/bin/prlctl',
            'start_cmd': 'start {_NodeName_}',
            'stop_cmd': 'stop {_NodeName_} --kill',
            'reboot_cmd': 'reset {_NodeName_}',
            'list_all': "list -a -o name |tail -n +2",
            'list_running': 'list -o name |tail -n +2',
            'get_node_macs': (
                "list -j -i \"{_NodeName_}\" | "
                "awk -F'\"' '/\"mac\":/ {print $4}' | "
                "sed 's/\\(..\\)\\(..\\)\\(..\\)\\(..\\)\\(..\\)\\(..\\)/"
                "\\1:\\2:\\3:\\4:\\5\\6/' | "
                "tr '[:upper:]' '[:lower:]'"),
            'set_boot_device': (
                "{_BaseCmd_} set {_NodeName_} "
                "--device-bootorder \"{_BootDevice_}\""),
            'get_boot_device': (
                "{_BaseCmd_} list -i {_NodeName_} | "
                "awk '/^Boot order:/ {print $3}'"),
        }
    elif virt_type == 'xenserver':
        return {
            'base_cmd': 'LC_ALL=C /opt/xensource/bin/xe',
            # Note(bobba): XenServer appears to have a condition where
            #              vm-start can return before the power-state
            #              has been updated to 'running'.  Ironic
            #              expects the power-state to be updated
            #              immediately, so may find that power-state
            #              is still 'halted' and attempt to start the
            #              VM a second time.  Sleep to avoid the race.
            'start_cmd': 'vm-start uuid={_NodeName_} && sleep 10s',
            'stop_cmd': 'vm-shutdown uuid={_NodeName_} force=true',
            'list_all': "vm-list --minimal | tr ',' '\n'",
            'list_running': (
                "vm-list power-state=running --minimal |"
                " tr ',' '\n'"),
            'get_node_macs': (
                "vif-list vm-uuid={_NodeName_}"
                " params=MAC --minimal | tr ',' '\n'"),
            'set_boot_device': (
                "{_BaseCmd_} vm-param-set uuid={_NodeName_}"
                " HVM-boot-params:order='{_BootDevice_}'"),
            'get_boot_device': (
                "{_BaseCmd_} vm-param-get uuid={_NodeName_}"
                " --param-name=HVM-boot-params param-key=order | cut -b 1"),
        }
    else:
        raise exception.InvalidParameterValue(_(
            "SSHPowerDriver '%(virt_type)s' is not a valid virt_type, ") %
            {'virt_type': virt_type})


def _get_boot_device(ssh_obj, driver_info):
    """Get the current boot device.

    :param ssh_obj: paramiko.SSHClient, an active ssh connection.
    :param driver_info: information for accessing the node.
    :raises: SSHCommandFailed on an error from ssh.
    :raises: NotImplementedError if the virt_type does not support
        getting the boot device.
    :raises: NodeNotFound if could not find a VM corresponding to any
        of the provided MACs.

    """
    cmd_to_exec = driver_info['cmd_set'].get('get_boot_device')
    if cmd_to_exec:
        boot_device_map = _get_boot_device_map(driver_info['virt_type'])
        node_name = _get_hosts_name_for_node(ssh_obj, driver_info)
        base_cmd = driver_info['cmd_set']['base_cmd']
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', node_name)
        cmd_to_exec = cmd_to_exec.replace('{_BaseCmd_}', base_cmd)
        stdout, stderr = _ssh_execute(ssh_obj, cmd_to_exec)
        return next((dev for dev, hdev in boot_device_map.items()
                     if hdev == stdout), None)
    else:
        raise NotImplementedError()


def _set_boot_device(ssh_obj, driver_info, device):
    """Set the boot device.

    :param ssh_obj: paramiko.SSHClient, an active ssh connection.
    :param driver_info: information for accessing the node.
    :param device: the boot device.
    :raises: SSHCommandFailed on an error from ssh.
    :raises: NotImplementedError if the virt_type does not support
        setting the boot device.
    :raises: NodeNotFound if could not find a VM corresponding to any
        of the provided MACs.

    """
    cmd_to_exec = driver_info['cmd_set'].get('set_boot_device')
    if cmd_to_exec:
        node_name = _get_hosts_name_for_node(ssh_obj, driver_info)
        base_cmd = driver_info['cmd_set']['base_cmd']
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', node_name)
        cmd_to_exec = cmd_to_exec.replace('{_BootDevice_}', device)
        cmd_to_exec = cmd_to_exec.replace('{_BaseCmd_}', base_cmd)
        _ssh_execute(ssh_obj, cmd_to_exec)
    else:
        raise NotImplementedError()


def _ssh_execute(ssh_obj, cmd_to_exec):
    """Executes a command via ssh.

    Executes a command via ssh and returns a list of the lines of the
    output from the command.

    :param ssh_obj: paramiko.SSHClient, an active ssh connection.
    :param cmd_to_exec: command to execute.
    :returns: list of the lines of output from the command.
    :raises: SSHCommandFailed on an error from ssh.

    """
    try:
        output_list = processutils.ssh_execute(ssh_obj,
                                               cmd_to_exec)[0].split('\n')
    except Exception as e:
        LOG.error(_LE("Cannot execute SSH cmd %(cmd)s. Reason: %(err)s."),
                  {'cmd': cmd_to_exec, 'err': e})
        raise exception.SSHCommandFailed(cmd=cmd_to_exec)

    return output_list


def _parse_driver_info(node):
    """Gets the information needed for accessing the node.

    :param node: the Node of interest.
    :returns: dictionary of information.
    :raises: InvalidParameterValue if any required parameters are incorrect.
    :raises: MissingParameterValue if any required parameters are missing.

    """
    info = node.driver_info or {}
    missing_info = [key for key in REQUIRED_PROPERTIES if not info.get(key)]
    if missing_info:
        raise exception.MissingParameterValue(_(
            "SSHPowerDriver requires the following parameters to be set in "
            "node's driver_info: %s.") % missing_info)

    address = info.get('ssh_address')
    username = info.get('ssh_username')
    password = info.get('ssh_password')
    port = info.get('ssh_port', 22)
    port = utils.validate_network_port(port, 'ssh_port')
    key_contents = info.get('ssh_key_contents')
    key_filename = info.get('ssh_key_filename')
    use_headless = strutils.bool_from_string(info.get('vbox_use_headless',
                                                      False))
    virt_type = info.get('ssh_virt_type')
    terminal_port = info.get('ssh_terminal_port')

    if terminal_port is not None:
        terminal_port = utils.validate_network_port(terminal_port,
                                                    'ssh_terminal_port')

    # NOTE(deva): we map 'address' from API to 'host' for common utils
    res = {
        'host': address,
        'username': username,
        'port': port,
        'use_headless': use_headless,
        'virt_type': virt_type,
        'uuid': node.uuid,
        'terminal_port': terminal_port
    }

    cmd_set = _get_command_sets(virt_type, use_headless)
    res['cmd_set'] = cmd_set

    # Only one credential may be set (avoids complexity around having
    # precedence etc).
    if len([v for v in (password, key_filename, key_contents) if v]) != 1:
        raise exception.InvalidParameterValue(_(
            "SSHPowerDriver requires one and only one of ssh_password, "
            "ssh_key_contents and ssh_key_filename to be set."))
    if password:
        res['password'] = password
    elif key_contents:
        res['key_contents'] = key_contents
    else:
        if not os.path.isfile(key_filename):
            raise exception.InvalidParameterValue(_(
                "SSH key file %s not found.") % key_filename)
        res['key_filename'] = key_filename

    return res


def _get_power_status(ssh_obj, driver_info):
    """Returns a node's current power state.

    :param ssh_obj: paramiko.SSHClient, an active ssh connection.
    :param driver_info: information for accessing the node.
    :returns: one of ironic.common.states POWER_OFF, POWER_ON.
    :raises: NodeNotFound if could not find a VM corresponding to any
        of the provided MACs.

    """
    power_state = None
    node_name = _get_hosts_name_for_node(ssh_obj, driver_info)
    # Get a list of vms running on the host. If the command supports
    # it, explicitly specify the desired node."
    cmd_to_exec = "%s %s" % (driver_info['cmd_set']['base_cmd'],
                             driver_info['cmd_set']['list_running'])
    cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', node_name)
    running_list = _ssh_execute(ssh_obj, cmd_to_exec)

    # Command should return a list of running vms. If the current node is
    # not listed then we can assume it is not powered on.
    quoted_node_name = '"%s"' % node_name
    for node in running_list:
        if not node:
            continue
        # 'node' here is a formatted output from the virt cli's. The
        # node name is either an exact match or quoted (optionally with
        # other information, e.g. vbox returns '"NodeName" {<uuid>}')
        if (quoted_node_name in node) or (node_name == node):
            power_state = states.POWER_ON
            break
    if not power_state:
        power_state = states.POWER_OFF

    return power_state


def _get_connection(node):
    """Returns an SSH client connected to a node.

    :param node: the Node.
    :returns: paramiko.SSHClient, an active ssh connection.

    """
    return utils.ssh_connect(_parse_driver_info(node))


def _get_hosts_name_for_node(ssh_obj, driver_info):
    """Get the name the host uses to reference the node.

    :param ssh_obj: paramiko.SSHClient, an active ssh connection.
    :param driver_info: information for accessing the node.
    :returns: the name of the node.
    :raises: NodeNotFound if could not find a VM corresponding to any of
        the provided MACs

    """

    @retrying.retry(
        retry_on_result=lambda v: v is None,
        retry_on_exception=lambda _: False,  # Do not retry on SSHCommandFailed
        stop_max_attempt_number=CONF.ssh.get_vm_name_attempts,
        wait_fixed=CONF.ssh.get_vm_name_retry_interval * 1000)
    def _with_retries():
        matched_name = None
        cmd_to_exec = "%s %s" % (driver_info['cmd_set']['base_cmd'],
                                 driver_info['cmd_set']['list_all'])
        full_node_list = _ssh_execute(ssh_obj, cmd_to_exec)
        LOG.debug("Retrieved Node List: %s" % repr(full_node_list))
        # for each node check Mac Addresses
        for node in full_node_list:
            if not node:
                continue
            LOG.debug("Checking Node: %s's Mac address." % node)
            cmd_to_exec = "%s %s" % (driver_info['cmd_set']['base_cmd'],
                                     driver_info['cmd_set']['get_node_macs'])
            cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', node)
            hosts_node_mac_list = _ssh_execute(ssh_obj, cmd_to_exec)

            for host_mac in hosts_node_mac_list:
                if not host_mac:
                    continue
                for node_mac in driver_info['macs']:
                    if (driver_utils.normalize_mac(host_mac)
                            in driver_utils.normalize_mac(node_mac)):
                        LOG.debug("Found Mac address: %s" % node_mac)
                        matched_name = node
                        break

                if matched_name:
                    break
            if matched_name:
                break

        return matched_name

    try:
        return _with_retries()
    except retrying.RetryError:
        raise exception.NodeNotFound(
            _("SSH driver was not able to find a VM with any of the "
              "specified MACs: %(macs)s for node %(node)s.") %
            {'macs': driver_info['macs'], 'node': driver_info['uuid']})


def _power_on(ssh_obj, driver_info):
    """Power ON this node.

    :param ssh_obj: paramiko.SSHClient, an active ssh connection.
    :param driver_info: information for accessing the node.
    :returns: one of ironic.common.states POWER_ON or ERROR.

    """
    current_pstate = _get_power_status(ssh_obj, driver_info)
    if current_pstate == states.POWER_ON:
        _power_off(ssh_obj, driver_info)

    node_name = _get_hosts_name_for_node(ssh_obj, driver_info)
    cmd_to_power_on = "%s %s" % (driver_info['cmd_set']['base_cmd'],
                                 driver_info['cmd_set']['start_cmd'])
    cmd_to_power_on = cmd_to_power_on.replace('{_NodeName_}', node_name)

    _ssh_execute(ssh_obj, cmd_to_power_on)

    current_pstate = _get_power_status(ssh_obj, driver_info)
    if current_pstate == states.POWER_ON:
        return current_pstate
    else:
        return states.ERROR


def _power_off(ssh_obj, driver_info):
    """Power OFF this node.

    :param ssh_obj: paramiko.SSHClient, an active ssh connection.
    :param driver_info: information for accessing the node.
    :returns: one of ironic.common.states POWER_OFF or ERROR.

    """
    current_pstate = _get_power_status(ssh_obj, driver_info)
    if current_pstate == states.POWER_OFF:
        return current_pstate

    node_name = _get_hosts_name_for_node(ssh_obj, driver_info)
    cmd_to_power_off = "%s %s" % (driver_info['cmd_set']['base_cmd'],
                                  driver_info['cmd_set']['stop_cmd'])
    cmd_to_power_off = cmd_to_power_off.replace('{_NodeName_}', node_name)

    _ssh_execute(ssh_obj, cmd_to_power_off)

    current_pstate = _get_power_status(ssh_obj, driver_info)
    if current_pstate == states.POWER_OFF:
        return current_pstate
    else:
        return states.ERROR


class SSHPower(base.PowerInterface):
    """SSH Power Interface.

    This PowerInterface class provides a mechanism for controlling the power
    state of virtual machines via SSH.

    NOTE: This driver supports VirtualBox and Virsh commands.
    NOTE: This driver does not currently support multi-node operations.
    """

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task):
        """Check that the node's 'driver_info' is valid.

        Check that the node's 'driver_info' contains the requisite fields
        and that an SSH connection to the node can be established.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if any connection parameters are
            incorrect or if ssh failed to connect to the node.
        :raises: MissingParameterValue if no ports are enrolled for the given
                 node.
        """
        if not driver_utils.get_node_mac_addresses(task):
            raise exception.MissingParameterValue(
                _("Node %s does not have any port associated with it."
                  ) % task.node.uuid)
        try:
            _get_connection(task.node)
        except exception.SSHConnectFailed as e:
            raise exception.InvalidParameterValue(_("SSH connection cannot"
                                                    " be established: %s") % e)

    def get_power_state(self, task):
        """Get the current power state of the task's node.

        Poll the host for the current power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: power state. One of :class:`ironic.common.states`.
        :raises: InvalidParameterValue if any connection parameters are
            incorrect.
        :raises: MissingParameterValue when a required parameter is missing
        :raises: NodeNotFound if could not find a VM corresponding to any
            of the provided MACs.
        :raises: SSHCommandFailed on an error from ssh.
        :raises: SSHConnectFailed if ssh failed to connect to the node.
        """
        driver_info = _parse_driver_info(task.node)
        driver_info['macs'] = driver_utils.get_node_mac_addresses(task)
        ssh_obj = _get_connection(task.node)
        return _get_power_status(ssh_obj, driver_info)

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, pstate):
        """Turn the power on or off.

        Set the power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :param pstate: Either POWER_ON or POWER_OFF from :class:
            `ironic.common.states`.
        :raises: InvalidParameterValue if any connection parameters are
            incorrect, or if the desired power state is invalid.
        :raises: MissingParameterValue when a required parameter is missing
        :raises: NodeNotFound if could not find a VM corresponding to any
            of the provided MACs.
        :raises: PowerStateFailure if it failed to set power state to pstate.
        :raises: SSHCommandFailed on an error from ssh.
        :raises: SSHConnectFailed if ssh failed to connect to the node.
        """
        driver_info = _parse_driver_info(task.node)
        driver_info['macs'] = driver_utils.get_node_mac_addresses(task)
        ssh_obj = _get_connection(task.node)

        if pstate == states.POWER_ON:
            state = _power_on(ssh_obj, driver_info)
        elif pstate == states.POWER_OFF:
            state = _power_off(ssh_obj, driver_info)
        else:
            raise exception.InvalidParameterValue(
                _("set_power_state called with invalid power state %s."
                  ) % pstate)

        if state != pstate:
            raise exception.PowerStateFailure(pstate=pstate)

    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Cycles the power to the task's node.

        Power cycles a node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if any connection parameters are
            incorrect.
        :raises: MissingParameterValue when a required parameter is missing
        :raises: NodeNotFound if could not find a VM corresponding to any
            of the provided MACs.
        :raises: PowerStateFailure if it failed to set power state to POWER_ON.
        :raises: SSHCommandFailed on an error from ssh.
        :raises: SSHConnectFailed if ssh failed to connect to the node.
        """
        driver_info = _parse_driver_info(task.node)
        driver_info['macs'] = driver_utils.get_node_mac_addresses(task)
        ssh_obj = _get_connection(task.node)

        # _power_on will turn the power off if it's already on.
        state = _power_on(ssh_obj, driver_info)

        if state != states.POWER_ON:
            raise exception.PowerStateFailure(pstate=states.POWER_ON)


class SSHManagement(base.ManagementInterface):

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task):
        """Check that 'driver_info' contains SSH credentials.

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required credentials information.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue if any connection parameters are
            incorrect.
        :raises: MissingParameterValue if a required parameter is missing
        """
        _parse_driver_info(task.node)

    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a task from TaskManager.
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
                           Default: False. Ignored by this driver.
        :raises: InvalidParameterValue if an invalid boot device is
                 specified or if any connection parameters are incorrect.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: SSHConnectFailed if ssh failed to connect to the node.
        :raises: SSHCommandFailed on an error from ssh.
        :raises: NotImplementedError if the virt_type does not support
            setting the boot device.
        :raises: NodeNotFound if could not find a VM corresponding to any
            of the provided MACs.

        """
        node = task.node
        driver_info = _parse_driver_info(node)
        if device not in self.get_supported_boot_devices(task):
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)
        driver_info['macs'] = driver_utils.get_node_mac_addresses(task)
        ssh_obj = _get_connection(node)

        node_name = _get_hosts_name_for_node(ssh_obj, driver_info)
        virt_type = driver_info['virt_type']
        use_headless = driver_info['use_headless']

        if virt_type == 'vbox':
            if use_headless:
                current_pstate = _get_power_status(ssh_obj, driver_info)
                if current_pstate == states.POWER_ON:
                    LOG.debug("Forcing VBox VM %s to power off "
                              "in order to set the boot device.",
                              node_name)
                    _power_off(ssh_obj, driver_info)

        boot_device_map = _get_boot_device_map(driver_info['virt_type'])
        try:
            _set_boot_device(ssh_obj, driver_info, boot_device_map[device])
        except NotImplementedError:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to set boot device for node %(node)s, "
                              "virt_type %(vtype)s does not support this "
                              "operation"),
                          {'node': node.uuid,
                           'vtype': driver_info['virt_type']})

    def get_boot_device(self, task):
        """Get the current boot device for the task's node.

        Provides the current boot device of the node. Be aware that not
        all drivers support this.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue if any connection parameters are
            incorrect.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: SSHConnectFailed if ssh failed to connect to the node.
        :raises: SSHCommandFailed on an error from ssh.
        :raises: NodeNotFound if could not find a VM corresponding to any
            of the provided MACs.
        :returns: a dictionary containing:

            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` or None if it is unknown.
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.

        """
        node = task.node
        driver_info = _parse_driver_info(node)
        driver_info['macs'] = driver_utils.get_node_mac_addresses(task)
        ssh_obj = _get_connection(node)
        response = {'boot_device': None, 'persistent': None}
        try:
            response['boot_device'] = _get_boot_device(ssh_obj, driver_info)
        except NotImplementedError:
            LOG.warning(_LW("Failed to get boot device for node %(node)s, "
                            "virt_type %(vtype)s does not support this "
                            "operation"),
                        {'node': node.uuid, 'vtype': driver_info['virt_type']})
        return response

    def get_sensors_data(self, task):
        """Get sensors data.

        Not implemented by this driver.

        :param task: a TaskManager instance.

        """
        raise NotImplementedError()


class ShellinaboxConsole(base.ConsoleInterface):
    """A ConsoleInterface that uses ssh and shellinabox."""

    def get_properties(self):
        properties = COMMON_PROPERTIES.copy()
        properties.update(CONSOLE_PROPERTIES)
        return properties

    def validate(self, task):
        """Validate the Node console info.

        :param task: a task from TaskManager.
        :raises: MissingParameterValue if required ssh parameters are
                 missing
        :raises: InvalidParameterValue if required parameters are invalid.
        """
        driver_info = _parse_driver_info(task.node)

        if driver_info['virt_type'] != 'virsh':
            raise exception.InvalidParameterValue(_(
                "not supported for non-virsh types"))

        if not driver_info['terminal_port']:
            raise exception.MissingParameterValue(_(
                "Missing 'ssh_terminal_port' parameter in node's "
                "'driver_info'"))

    def start_console(self, task):
        """Start a remote console for the node.

        :param task: a task from TaskManager
        :raises: MissingParameterValue if required ssh parameters are
                 missing
        :raises: ConsoleError if the directory for the PID file cannot be
                 created
        :raises: ConsoleSubprocessFailed when invoking the subprocess failed
        :raises: InvalidParameterValue if required parameters are invalid.
        """

        driver_info = _parse_driver_info(task.node)
        driver_info['macs'] = driver_utils.get_node_mac_addresses(task)
        ssh_obj = _get_connection(task.node)
        node_name = _get_hosts_name_for_node(ssh_obj, driver_info)

        ssh_cmd = ("/:%(uid)s:%(gid)s:HOME:virsh console %(node)s"
                   % {'uid': os.getuid(),
                      'gid': os.getgid(),
                      'node': node_name})

        console_utils.start_shellinabox_console(driver_info['uuid'],
                                                driver_info['terminal_port'],
                                                ssh_cmd)

    def stop_console(self, task):
        """Stop the remote console session for the node.

        :param task: a task from TaskManager
        :raises: ConsoleError if unable to stop the console
        """

        console_utils.stop_shellinabox_console(task.node.uuid)

    def get_console(self, task):
        """Get the type and connection information about the console.

        :param task: a task from TaskManager
        :raises: MissingParameterValue if required ssh parameters are
                 missing
        :raises: InvalidParameterValue if required parameter are invalid.
        """

        driver_info = _parse_driver_info(task.node)
        url = console_utils.get_shellinabox_console_url(
            driver_info['terminal_port'])
        return {'type': 'shellinabox', 'url': url}
