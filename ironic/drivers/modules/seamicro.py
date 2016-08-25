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
Ironic SeaMicro interfaces.

Provides basic power control of servers in SeaMicro chassis via
python-seamicroclient.

Provides vendor passthru methods for SeaMicro specific functionality.
"""
import os
import re

from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import importutils
from six.moves.urllib import parse as urlparse

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _, _LE, _LW
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import console_utils

seamicroclient = importutils.try_import('seamicroclient')
if seamicroclient:
    from seamicroclient import client as seamicro_client
    from seamicroclient import exceptions as seamicro_client_exception

LOG = logging.getLogger(__name__)

_BOOT_DEVICES_MAP = {
    boot_devices.DISK: 'hd0',
    boot_devices.PXE: 'pxe',
}

REQUIRED_PROPERTIES = {
    'seamicro_api_endpoint': _("API endpoint. Required."),
    'seamicro_password': _("password. Required."),
    'seamicro_server_id': _("server ID. Required."),
    'seamicro_username': _("username. Required."),
}
OPTIONAL_PROPERTIES = {
    'seamicro_api_version': _("version of SeaMicro API client; default is 2. "
                              "Optional.")
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)
CONSOLE_PROPERTIES = {
    'seamicro_terminal_port': _("node's UDP port to connect to. "
                                "Only required for console access.")
}
PORT_BASE = 2000


def _get_client(*args, **kwargs):
    """Creates the python-seamicro_client

    :param kwargs: A dict of keyword arguments to be passed to the method,
                   which should contain: 'username', 'password',
                   'auth_url', 'api_version' parameters.
    :returns: SeaMicro API client.
    """

    cl_kwargs = {'username': kwargs['username'],
                 'password': kwargs['password'],
                 'auth_url': kwargs['api_endpoint']}
    try:
        return seamicro_client.Client(kwargs['api_version'], **cl_kwargs)
    except seamicro_client_exception.UnsupportedVersion as e:
        raise exception.InvalidParameterValue(_(
            "Invalid 'seamicro_api_version' parameter. Reason: %s.") % e)


def _parse_driver_info(node):
    """Parses and creates seamicro driver info

    :param node: An Ironic node object.
    :returns: SeaMicro driver info.
    :raises: MissingParameterValue if any required parameters are missing.
    :raises: InvalidParameterValue if required parameter are invalid.
    """

    info = node.driver_info or {}
    missing_info = [key for key in REQUIRED_PROPERTIES if not info.get(key)]
    if missing_info:
        raise exception.MissingParameterValue(_(
            "SeaMicro driver requires the following parameters to be set in"
            " node's driver_info: %s.") % missing_info)

    api_endpoint = info.get('seamicro_api_endpoint')
    username = info.get('seamicro_username')
    password = info.get('seamicro_password')
    server_id = info.get('seamicro_server_id')
    api_version = info.get('seamicro_api_version', "2")
    port = info.get('seamicro_terminal_port')

    if port is not None:
        port = utils.validate_network_port(port, 'seamicro_terminal_port')

    r = re.compile(r"(^[0-9]+)/([0-9]+$)")
    if not r.match(server_id):
        raise exception.InvalidParameterValue(_(
            "Invalid 'seamicro_server_id' parameter in node's "
            "driver_info. Expected format of 'seamicro_server_id' "
            "is <int>/<int>"))

    url = urlparse.urlparse(api_endpoint)
    if (not (url.scheme == "http") or not url.netloc):
        raise exception.InvalidParameterValue(_(
            "Invalid 'seamicro_api_endpoint' parameter in node's "
            "driver_info."))

    res = {'username': username,
           'password': password,
           'api_endpoint': api_endpoint,
           'server_id': server_id,
           'api_version': api_version,
           'uuid': node.uuid,
           'port': port}

    return res


def _get_server(driver_info):
    """Get server from server_id."""

    s_client = _get_client(**driver_info)
    return s_client.servers.get(driver_info['server_id'])


def _get_volume(driver_info, volume_id):
    """Get volume from volume_id."""

    s_client = _get_client(**driver_info)
    return s_client.volumes.get(volume_id)


def _get_power_status(node):
    """Get current power state of this node

    :param node: Ironic node one of :class:`ironic.db.models.Node`
    :raises: InvalidParameterValue if a seamicro parameter is invalid.
    :raises: MissingParameterValue if required seamicro parameters are
        missing.
    :raises: ServiceUnavailable on an error from SeaMicro Client.
    :returns: Power state of the given node
    """

    seamicro_info = _parse_driver_info(node)
    try:
        server = _get_server(seamicro_info)
        if not hasattr(server, 'active') or server.active is None:
            return states.ERROR
        if not server.active:
            return states.POWER_OFF
        elif server.active:
            return states.POWER_ON

    except seamicro_client_exception.NotFound:
        raise exception.NodeNotFound(node=node.uuid)
    except seamicro_client_exception.ClientException as ex:
        LOG.error(_LE("SeaMicro client exception %(msg)s for node %(uuid)s"),
                  {'msg': ex.message, 'uuid': node.uuid})
        raise exception.ServiceUnavailable(message=ex.message)


def _power_on(node, timeout=None):
    """Power ON this node

    :param node: An Ironic node object.
    :param timeout: Time in seconds to wait till power on is complete.
    :raises: InvalidParameterValue if a seamicro parameter is invalid.
    :raises: MissingParameterValue if required seamicro parameters are
        missing.
    :returns: Power state of the given node.
    """
    if timeout is None:
        timeout = CONF.seamicro.action_timeout
    state = [None]
    retries = [0]
    seamicro_info = _parse_driver_info(node)
    server = _get_server(seamicro_info)

    def _wait_for_power_on(state, retries):
        """Called at an interval until the node is powered on."""

        state[0] = _get_power_status(node)
        if state[0] == states.POWER_ON:
            raise loopingcall.LoopingCallDone()

        if retries[0] > CONF.seamicro.max_retry:
            state[0] = states.ERROR
            raise loopingcall.LoopingCallDone()
        try:
            retries[0] += 1
            server.power_on()
        except seamicro_client_exception.ClientException:
            LOG.warning(_LW("Power-on failed for node %s."),
                        node.uuid)

    timer = loopingcall.FixedIntervalLoopingCall(_wait_for_power_on,
                                                 state, retries)
    timer.start(interval=timeout).wait()
    return state[0]


def _power_off(node, timeout=None):
    """Power OFF this node

    :param node: Ironic node one of :class:`ironic.db.models.Node`
    :param timeout: Time in seconds to wait till power off is compelete
    :raises: InvalidParameterValue if a seamicro parameter is invalid.
    :raises: MissingParameterValue if required seamicro parameters are
        missing.
    :returns: Power state of the given node
    """
    if timeout is None:
        timeout = CONF.seamicro.action_timeout
    state = [None]
    retries = [0]
    seamicro_info = _parse_driver_info(node)
    server = _get_server(seamicro_info)

    def _wait_for_power_off(state, retries):
        """Called at an interval until the node is powered off."""

        state[0] = _get_power_status(node)
        if state[0] == states.POWER_OFF:
            raise loopingcall.LoopingCallDone()

        if retries[0] > CONF.seamicro.max_retry:
            state[0] = states.ERROR
            raise loopingcall.LoopingCallDone()
        try:
            retries[0] += 1
            server.power_off()
        except seamicro_client_exception.ClientException:
            LOG.warning(_LW("Power-off failed for node %s."),
                        node.uuid)

    timer = loopingcall.FixedIntervalLoopingCall(_wait_for_power_off,
                                                 state, retries)
    timer.start(interval=timeout).wait()
    return state[0]


def _reboot(node, timeout=None):
    """Reboot this node.

    :param node: Ironic node one of :class:`ironic.db.models.Node`
    :param timeout: Time in seconds to wait till reboot is compelete
    :raises: InvalidParameterValue if a seamicro parameter is invalid.
    :raises: MissingParameterValue if required seamicro parameters are
        missing.
    :returns: Power state of the given node
    """
    if timeout is None:
        timeout = CONF.seamicro.action_timeout
    state = [None]
    retries = [0]
    seamicro_info = _parse_driver_info(node)
    server = _get_server(seamicro_info)

    def _wait_for_reboot(state, retries):
        """Called at an interval until the node is rebooted successfully."""

        state[0] = _get_power_status(node)
        if state[0] == states.POWER_ON:
            raise loopingcall.LoopingCallDone()

        if retries[0] > CONF.seamicro.max_retry:
            state[0] = states.ERROR
            raise loopingcall.LoopingCallDone()

        try:
            retries[0] += 1
            server.reset()
        except seamicro_client_exception.ClientException:
            LOG.warning(_LW("Reboot failed for node %s."),
                        node.uuid)

    timer = loopingcall.FixedIntervalLoopingCall(_wait_for_reboot,
                                                 state, retries)
    server.reset()
    timer.start(interval=timeout).wait()
    return state[0]


def _validate_volume(driver_info, volume_id):
    """Validates if volume is in Storage pools designated for ironic."""

    volume = _get_volume(driver_info, volume_id)

    # Check if the ironic <scard>/ironic-<pool_id>/<volume_id> naming scheme
    # is present in volume id
    try:
        pool_id = volume.id.split('/')[1].lower()
    except IndexError:
        pool_id = ""

    if "ironic-" in pool_id:
        return True
    else:
        raise exception.InvalidParameterValue(_(
            "Invalid volume id specified"))


def _get_pools(driver_info, filters=None):
    """Get SeaMicro storage pools matching given filters."""

    s_client = _get_client(**driver_info)
    return s_client.pools.list(filters=filters)


def _create_volume(driver_info, volume_size):
    """Create volume in the SeaMicro storage pools designated for ironic."""

    ironic_pools = _get_pools(driver_info, filters={'id': 'ironic-'})
    if ironic_pools is None:
        raise exception.VendorPassthruException(_(
            "No storage pools found for ironic"))

    least_used_pool = sorted(ironic_pools,
                             key=lambda x: x.freeSize)[0]
    return _get_client(**driver_info).volumes.create(volume_size,
                                                     least_used_pool)


def get_telnet_port(driver_info):
    """Get SeaMicro telnet port to listen."""
    server_id = int(driver_info['server_id'].split("/")[0])
    return PORT_BASE + (10 * server_id)


class Power(base.PowerInterface):
    """SeaMicro Power Interface.

    This PowerInterface class provides a mechanism for controlling the power
    state of servers in a seamicro chassis.
    """

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task):
        """Check that node 'driver_info' is valid.

        Check that node 'driver_info' contains the required fields.

        :param task: a TaskManager instance containing the node to act on.
        :raises: MissingParameterValue if required seamicro parameters are
            missing.
        """
        _parse_driver_info(task.node)

    def get_power_state(self, task):
        """Get the current power state of the task's node.

        Poll the host for the current power state of the node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: ServiceUnavailable on an error from SeaMicro Client.
        :raises: InvalidParameterValue if a seamicro parameter is invalid.
        :raises: MissingParameterValue when a required parameter is missing
        :returns: power state. One of :class:`ironic.common.states`.

        """
        return _get_power_status(task.node)

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, pstate):
        """Turn the power on or off.

        Set the power state of a node.

        :param task: a TaskManager instance containing the node to act on.
        :param pstate: Either POWER_ON or POWER_OFF from :class:
            `ironic.common.states`.
        :raises: InvalidParameterValue if an invalid power state was specified
            or a seamicro parameter is invalid.
        :raises: MissingParameterValue when a required parameter is missing
        :raises: PowerStateFailure if the desired power state couldn't be set.
        """

        if pstate == states.POWER_ON:
            state = _power_on(task.node)
        elif pstate == states.POWER_OFF:
            state = _power_off(task.node)
        else:
            raise exception.InvalidParameterValue(_(
                "set_power_state called with invalid power state."))

        if state != pstate:
            raise exception.PowerStateFailure(pstate=pstate)

    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Cycles the power to the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if a seamicro parameter is invalid.
        :raises: MissingParameterValue if required seamicro parameters are
            missing.
        :raises: PowerStateFailure if the final state of the node is not
            POWER_ON.
        """
        state = _reboot(task.node)

        if state != states.POWER_ON:
            raise exception.PowerStateFailure(pstate=states.POWER_ON)


class VendorPassthru(base.VendorInterface):
    """SeaMicro vendor-specific methods."""

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task, method, **kwargs):
        _parse_driver_info(task.node)

    @base.passthru(['POST'])
    def set_node_vlan_id(self, task, **kwargs):
        """Sets an untagged vlan id for NIC 0 of node.

        @kwargs vlan_id: id of untagged vlan for NIC 0 of node
        """
        node = task.node
        vlan_id = kwargs.get('vlan_id')
        if not vlan_id:
            raise exception.MissingParameterValue(_("No vlan id provided"))

        seamicro_info = _parse_driver_info(node)
        try:
            server = _get_server(seamicro_info)

            # remove current vlan for server
            if len(server.nic['0']['untaggedVlan']) > 0:
                server.unset_untagged_vlan(server.nic['0']['untaggedVlan'])
            server = server.refresh(5)
            server.set_untagged_vlan(vlan_id)
        except seamicro_client_exception.ClientException as ex:
            LOG.error(_LE("SeaMicro client exception: %s"), ex.message)
            raise exception.VendorPassthruException(message=ex.message)

        properties = node.properties
        properties['seamicro_vlan_id'] = vlan_id
        node.properties = properties
        node.save()

    @base.passthru(['POST'])
    def attach_volume(self, task, **kwargs):
        """Attach a volume to a node.

        Attach volume from SeaMicro storage pools for ironic to node.
        If kwargs['volume_id'] not given, Create volume in SeaMicro
        storage pool and attach to node.

        @kwargs volume_id: id of pre-provisioned volume that is to be attached
                           as root volume of node
        @kwargs volume_size: size of new volume to be created and attached
                             as root volume of node
        """
        node = task.node
        seamicro_info = _parse_driver_info(node)
        volume_id = kwargs.get('volume_id')

        if volume_id is None:
            volume_size = kwargs.get('volume_size')
            if volume_size is None:
                raise exception.MissingParameterValue(
                    _("No volume size provided for creating volume"))
            volume_id = _create_volume(seamicro_info, volume_size)

        if _validate_volume(seamicro_info, volume_id):
            try:
                server = _get_server(seamicro_info)
                server.detach_volume()
                server = server.refresh(5)
                server.attach_volume(volume_id)
            except seamicro_client_exception.ClientException as ex:
                LOG.error(_LE("SeaMicro client exception: %s"), ex.message)
                raise exception.VendorPassthruException(message=ex.message)

            properties = node.properties
            properties['seamicro_volume_id'] = volume_id
            node.properties = properties
            node.save()


class Management(base.ManagementInterface):

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task):
        """Check that 'driver_info' contains SeaMicro credentials.

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required credentials information.

        :param task: a task from TaskManager.
        :raises: MissingParameterValue when a required parameter is missing

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
                 specified or if a seamicro parameter is invalid.
        :raises: IronicException on an error from seamicro-client.
        :raises: MissingParameterValue when a required parameter is missing

        """
        if device not in self.get_supported_boot_devices(task):
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)

        seamicro_info = _parse_driver_info(task.node)
        try:
            server = _get_server(seamicro_info)
            boot_device = _BOOT_DEVICES_MAP[device]
            server.set_boot_order(boot_device)
        except seamicro_client_exception.ClientException as ex:
            LOG.error(_LE("Seamicro set boot device failed for node "
                          "%(node)s with the following error: %(error)s"),
                      {'node': task.node.uuid, 'error': ex})
            raise exception.IronicException(ex)

    def get_boot_device(self, task):
        """Get the current boot device for the task's node.

        Returns the current boot device of the node. Be aware that not
        all drivers support this.

        :param task: a task from TaskManager.
        :returns: a dictionary containing:

            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` or None if it is unknown.
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.

        """
        # TODO(lucasagomes): The python-seamicroclient library currently
        # doesn't expose a method to get the boot device, update it once
        # it's implemented.
        return {'boot_device': None, 'persistent': None}

    def get_sensors_data(self, task):
        """Get sensors data method.

        Not implemented by this driver.
        :param task: a TaskManager instance.

        """
        raise NotImplementedError()


class ShellinaboxConsole(base.ConsoleInterface):
    """A ConsoleInterface that uses telnet and shellinabox."""

    def get_properties(self):
        d = COMMON_PROPERTIES.copy()
        d.update(CONSOLE_PROPERTIES)
        return d

    def validate(self, task):
        """Validate the Node console info.

        :param task: a task from TaskManager.
        :raises: MissingParameterValue if required seamicro parameters are
                 missing
        :raises: InvalidParameterValue if required parameter are invalid.
        """
        driver_info = _parse_driver_info(task.node)
        if not driver_info['port']:
            raise exception.MissingParameterValue(_(
                "Missing 'seamicro_terminal_port' parameter in node's "
                "driver_info"))

    def start_console(self, task):
        """Start a remote console for the node.

        :param task: a task from TaskManager
        :raises: MissingParameterValue if required seamicro parameters are
                 missing
        :raises: ConsoleError if the directory for the PID file cannot be
                 created
        :raises: ConsoleSubprocessFailed when invoking the subprocess failed
        :raises: InvalidParameterValue if required parameter are invalid.
        """

        driver_info = _parse_driver_info(task.node)
        telnet_port = get_telnet_port(driver_info)
        chassis_ip = urlparse.urlparse(driver_info['api_endpoint']).netloc

        seamicro_cmd = ("/:%(uid)s:%(gid)s:HOME:telnet %(chassis)s %(port)s"
                        % {'uid': os.getuid(),
                           'gid': os.getgid(),
                           'chassis': chassis_ip,
                           'port': telnet_port})

        console_utils.start_shellinabox_console(driver_info['uuid'],
                                                driver_info['port'],
                                                seamicro_cmd)

    def stop_console(self, task):
        """Stop the remote console session for the node.

        :param task: a task from TaskManager
        :raises: ConsoleError if unable to stop the console
        """

        console_utils.stop_shellinabox_console(task.node.uuid)

    def get_console(self, task):
        """Get the type and connection information about the console.

        :raises: MissingParameterValue if required seamicro parameters are
                 missing
        :raises: InvalidParameterValue if required parameter are invalid.
        """

        driver_info = _parse_driver_info(task.node)
        url = console_utils.get_shellinabox_console_url(driver_info['port'])
        return {'type': 'shellinabox', 'url': url}
