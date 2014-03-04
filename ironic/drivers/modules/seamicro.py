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
"""

from oslo.config import cfg
from seamicroclient import client as seamicro_client
from seamicroclient import exceptions as seamicro_client_exception


from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.openstack.common import log as logging
from ironic.openstack.common import loopingcall

opts = [
    cfg.IntOpt('max_retry',
               default=3,
               help='Maximum retries for SeaMicro operations'),
    cfg.IntOpt('action_timeout',
               default=10,
               help='Seconds to wait for power action to be completed')
]

CONF = cfg.CONF
opt_group = cfg.OptGroup(name='seamicro',
                         title='Options for the seamicro power driver')
CONF.register_group(opt_group)
CONF.register_opts(opts, opt_group)

LOG = logging.getLogger(__name__)


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
    return seamicro_client.Client(kwargs['api_version'], **cl_kwargs)


def _parse_driver_info(node):
    """Parses and creates seamicro driver info

    :param node: An Ironic node object.
    :returns: SeaMicro driver info.
    :raises: InvalidParameterValue if any required parameters are missing.
    """

    info = node.get('driver_info', {})
    api_endpoint = info.get('seamicro_api_endpoint')
    username = info.get('seamicro_username')
    password = info.get('seamicro_password')
    server_id = info.get('seamicro_server_id')
    api_version = info.get('seamicro_api_version', "2")

    if not api_endpoint:
        raise exception.InvalidParameterValue(_(
            "SeaMicro driver requires api_endpoint be set"))

    if not username or not password:
        raise exception.InvalidParameterValue(_(
            "SeaMicro driver requires both username and password be set"))

    if not server_id:
        raise exception.InvalidParameterValue(_(
            "SeaMicro driver requires server_id be set"))

    res = {'username': username,
           'password': password,
           'api_endpoint': api_endpoint,
           'server_id': server_id,
           'api_version': api_version,
           'uuid': node.get('uuid')}

    return res


def _get_server(driver_info):
    """Get server from server_id."""

    s_client = _get_client(**driver_info)
    return s_client.servers.get(driver_info['server_id'])


def _get_power_status(node):
    """Get current power state of this node

    :param node: Ironic node one of :class:`ironic.db.models.Node`
    :raises: InvalidParameterValue if required seamicro parameters are
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
        LOG.error(_("SeaMicro client exception %(msg)s for node %(uuid)s"),
                  {'msg': ex.message, 'uuid': node.uuid})
        raise exception.ServiceUnavailable(message=ex.message)


def _power_on(node, timeout=None):
    """Power ON this node

    :param node: An Ironic node object.
    :param timeout: Time in seconds to wait till power on is complete.
    :raises: InvalidParameterValue if required seamicro parameters are
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
            LOG.warning(_("Power-on failed for node %s."),
                        node.uuid)

    timer = loopingcall.FixedIntervalLoopingCall(_wait_for_power_on,
                                                 state, retries)
    timer.start(interval=timeout).wait()
    return state[0]


def _power_off(node, timeout=None):
    """Power OFF this node

    :param node: Ironic node one of :class:`ironic.db.models.Node`
    :param timeout: Time in seconds to wait till power off is compelete
    :raises: InvalidParameterValue if required seamicro parameters are
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
            LOG.warning(_("Power-off failed for node %s."),
                        node.uuid)

    timer = loopingcall.FixedIntervalLoopingCall(_wait_for_power_off,
                                                 state, retries)
    timer.start(interval=timeout).wait()
    return state[0]


def _reboot(node, timeout=None):
    """Reboot this node
    :param node: Ironic node one of :class:`ironic.db.models.Node`
    :param timeout: Time in seconds to wait till reboot is compelete
    :raises: InvalidParameterValue if required seamicro parameters are
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
            LOG.warning(_("Reboot failed for node %s."),
                        node.uuid)

    timer = loopingcall.FixedIntervalLoopingCall(_wait_for_reboot,
                                                 state, retries)
    server.reset()
    timer.start(interval=timeout).wait()
    return state[0]


class Power(base.PowerInterface):
    """SeaMicro Power Interface.

    This PowerInterface class provides a mechanism for controlling the power
    state of servers in a seamicro chassis.
    """

    def validate(self, node):
        """Check that node 'driver_info' is valid.

        Check that node 'driver_info' contains the required fields.

        :param node: Single node object.
        :raises: InvalidParameterValue if required seamicro parameters are
            missing.
        """
        _parse_driver_info(node)

    def get_power_state(self, task, node):
        """Get the current power state.

        Poll the host for the current power state of the node.

        :param task: A instance of `ironic.manager.task_manager.TaskManager`.
        :param node: A single node.
        :raises: InvalidParameterValue if required seamicro parameters are
            missing.
        :raises: ServiceUnavailable on an error from SeaMicro Client.
        :returns: power state. One of :class:`ironic.common.states`.
        """
        return _get_power_status(node)

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, node, pstate):
        """Turn the power on or off.

        Set the power state of a node.

        :param task: A instance of `ironic.manager.task_manager.TaskManager`.
        :param node: A single node.
        :param pstate: Either POWER_ON or POWER_OFF from :class:
            `ironic.common.states`.
        :raises: InvalidParameterValue if an invalid power state was specified.
        :raises: PowerStateFailure if the desired power state couldn't be set.
        """

        if pstate == states.POWER_ON:
            state = _power_on(node)
        elif pstate == states.POWER_OFF:
            state = _power_off(node)
        else:
            raise exception.InvalidParameterValue(_(
                "set_power_state called with invalid power state."))

        if state != pstate:
            raise exception.PowerStateFailure(pstate=pstate)

    @task_manager.require_exclusive_lock
    def reboot(self, task, node):
        """Cycles the power to a node.

        :param task: a TaskManager instance.
        :param node: An Ironic node object.
        :raises: InvalidParameterValue if required seamicro parameters are
            missing.
        :raises: PowerStateFailure if the final state of the node is not
            POWER_ON.
        """
        state = _reboot(node)

        if state != states.POWER_ON:
            raise exception.PowerStateFailure(pstate=states.POWER_ON)
