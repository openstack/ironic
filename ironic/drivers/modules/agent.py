# Copyright 2014 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import time

from oslo.config import cfg
from oslo.utils import excutils

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common import i18n
from ironic.common.i18n import _
from ironic.common import image_service
from ironic.common import keystone
from ironic.common import paths
from ironic.common import pxe_utils
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import image_cache
from ironic import objects
from ironic.openstack.common import fileutils
from ironic.openstack.common import log


_LE = i18n._LE
_LW = i18n._LW

agent_opts = [
    cfg.StrOpt('agent_pxe_append_params',
               default='nofb nomodeset vga=normal',
               help='Additional append parameters for baremetal PXE boot.'),
    cfg.StrOpt('agent_pxe_config_template',
               default=paths.basedir_def(
                   'drivers/modules/agent_config.template'),
               help='Template file for PXE configuration.'),
    cfg.StrOpt('agent_pxe_bootfile_name',
               default='pxelinux.0',
               help='Neutron bootfile DHCP parameter.'),
    cfg.IntOpt('heartbeat_timeout',
               default=300,
               help='Maximum interval (in seconds) for agent heartbeats.'),
    ]

CONF = cfg.CONF
CONF.import_opt('my_ip', 'ironic.netconf')
CONF.register_opts(agent_opts, group='agent')

LOG = log.getLogger(__name__)


def _time():
    """Broken out for testing."""
    return time.time()


def _get_client():
    client = agent_client.AgentClient()
    return client


def _build_pxe_config_options(pxe_info):
    ironic_api = (CONF.conductor.api_url or
                  keystone.get_service_url()).rstrip('/')
    return {
        'deployment_aki_path': pxe_info['deploy_kernel'][1],
        'deployment_ari_path': pxe_info['deploy_ramdisk'][1],
        'pxe_append_params': CONF.agent.agent_pxe_append_params,
        'ipa_api_url': ironic_api,
    }


def _get_tftp_image_info(node):
    return pxe_utils.get_deploy_kr_info(node.uuid, node.driver_info)


def _set_failed_state(task, msg):
    """Set a node's error state and provision state to signal Nova.

    When deploy steps aren't called by explicitly the conductor, but are
    the result of callbacks, we need to set the node's state explicitly.
    This tells Nova to change the instance's status so the user can see
    their deploy/tear down had an issue and makes debugging/deleting Nova
    instances easier.
    """
    node = task.node
    node.provision_state = states.DEPLOYFAIL
    node.target_provision_state = states.NOSTATE
    node.save(task.context)
    try:
        manager_utils.node_power_action(task, states.POWER_OFF)
    except Exception:
        msg = (_('Node %s failed to power off while handling deploy '
                 'failure. This may be a serious condition. Node '
                 'should be removed from Ironic or put in maintenance '
                 'mode until the problem is resolved.') % node.uuid)
        LOG.error(msg)
    finally:
        # NOTE(deva): node_power_action() erases node.last_error
        #             so we need to set it again here.
        node.last_error = msg
        node.save(task.context)


@image_cache.cleanup(priority=25)
class AgentTFTPImageCache(image_cache.ImageCache):
    def __init__(self, image_service=None):
        super(AgentTFTPImageCache, self).__init__(
            CONF.pxe.tftp_master_path,
            # MiB -> B
            CONF.pxe.image_cache_size * 1024 * 1024,
            # min -> sec
            CONF.pxe.image_cache_ttl * 60,
            image_service=image_service)


# copied from pxe driver - should be refactored per LP1350594
def _fetch_images(ctx, cache, images_info):
    """Check for available disk space and fetch images using ImageCache.

    :param ctx: context
    :param cache: ImageCache instance to use for fetching
    :param images_info: list of tuples (image uuid, destination path)
    :raises: InstanceDeployFailure if unable to find enough disk space
    """

    try:
        image_cache.clean_up_caches(ctx, cache.master_dir, images_info)
    except exception.InsufficientDiskSpace as e:
        raise exception.InstanceDeployFailure(reason=e)

    # NOTE(dtantsur): This code can suffer from race condition,
    # if disk space is used between the check and actual download.
    # This is probably unavoidable, as we can't control other
    # (probably unrelated) processes
    for uuid, path in images_info:
        cache.fetch_image(uuid, path, ctx=ctx)


# copied from pxe driver - should be refactored per LP1350594
def _cache_tftp_images(ctx, node, pxe_info):
    """Fetch the necessary kernels and ramdisks for the instance."""
    fileutils.ensure_tree(
        os.path.join(CONF.pxe.tftp_root, node.uuid))
    LOG.debug("Fetching kernel and ramdisk for node %s",
              node.uuid)
    _fetch_images(ctx, AgentTFTPImageCache(), pxe_info.values())


def _build_instance_info_for_deploy(task):
    """Build instance_info necessary for deploying to a node."""
    node = task.node
    instance_info = node.instance_info

    glance = image_service.Service(version=2, context=task.context)
    image_info = glance.show(instance_info['image_source'])
    swift_temp_url = glance.swift_temp_url(image_info)
    LOG.debug('Got image info: %(info)s for node %(node)s.',
              {'info': image_info, 'node': node.uuid})

    instance_info['image_url'] = swift_temp_url
    instance_info['image_checksum'] = image_info['checksum']
    return instance_info


class AgentDeploy(base.DeployInterface):
    """Interface for deploy-related actions."""

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return {}

    def validate(self, task):
        """Validate the driver-specific Node deployment info.

        This method validates whether the 'instance_info' property of the
        supplied node contains the required information for this driver to
        deploy images to the node.

        :param task: a TaskManager instance
        :raises: InvalidParameterValue
        """
        try:
            _get_tftp_image_info(task.node)
        except KeyError:
            raise exception.InvalidParameterValue(_(
                    'Node %s failed to validate deploy image info'),
                    task.node.uuid)

    @task_manager.require_exclusive_lock
    def deploy(self, task):
        """Perform a deployment to a node.

        Perform the necessary work to deploy an image onto the specified node.
        This method will be called after prepare(), which may have already
        performed any preparatory steps, such as pre-caching some data for the
        node.

        :param task: a TaskManager instance.
        :returns: status of the deploy. One of ironic.common.states.
        """
        dhcp_opts = pxe_utils.dhcp_options_for_instance(task)
        provider = dhcp_factory.DHCPFactory(token=task.context.auth_token)
        provider.update_dhcp(task, dhcp_opts)
        manager_utils.node_set_boot_device(task, 'pxe', persistent=True)
        manager_utils.node_power_action(task, states.REBOOT)

        return states.DEPLOYWAIT

    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        :param task: a TaskManager instance.
        :returns: status of the deploy. One of ironic.common.states.
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        return states.DELETED

    def prepare(self, task):
        """Prepare the deployment environment for this node.

        :param task: a TaskManager instance.
        """
        node = task.node
        pxe_info = _get_tftp_image_info(task.node)
        pxe_options = _build_pxe_config_options(pxe_info)
        pxe_utils.create_pxe_config(task,
                                    pxe_options,
                                    CONF.agent.agent_pxe_config_template)
        _cache_tftp_images(task.context, node, pxe_info)

        node.instance_info = _build_instance_info_for_deploy(task)
        node.save(task.context)

    def clean_up(self, task):
        """Clean up the deployment environment for this node.

        If preparation of the deployment environment ahead of time is possible,
        this method should be implemented by the driver. It should erase
        anything cached by the `prepare` method.

        If implemented, this method must be idempotent. It may be called
        multiple times for the same node on the same conductor, and it may be
        called by multiple conductors in parallel. Therefore, it must not
        require an exclusive lock.

        This method is called before `tear_down`.

        :param task: a TaskManager instance.
        """
        pxe_info = _get_tftp_image_info(task.node)
        for label in pxe_info:
            path = pxe_info[label][1]
            utils.unlink_without_raise(path)
        AgentTFTPImageCache().clean_up()

        pxe_utils.clean_up_pxe_config(task)

    def take_over(self, task):
        """Take over management of this node from a dead conductor.

        If conductors' hosts maintain a static relationship to nodes, this
        method should be implemented by the driver to allow conductors to
        perform the necessary work during the remapping of nodes to conductors
        when a conductor joins or leaves the cluster.

        For example, the PXE driver has an external dependency:
            Neutron must forward DHCP BOOT requests to a conductor which has
            prepared the tftpboot environment for the given node. When a
            conductor goes offline, another conductor must change this setting
            in Neutron as part of remapping that node's control to itself.
            This is performed within the `takeover` method.

        :param task: a TaskManager instance.
        """
        provider = dhcp_factory.DHCPFactory(token=task.context.auth_token)
        provider.update_dhcp(task, CONF.agent.agent_pxe_bootfile_name)


class AgentVendorInterface(base.VendorInterface):
    def __init__(self):
        self.vendor_routes = {
            'heartbeat': self._heartbeat
        }
        self.driver_routes = {
            'lookup': self._lookup,
        }
        self.supported_payload_versions = ['2']
        self._client = _get_client()

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        # NOTE(jroll) all properties are set by the driver,
        #             not by the operator.
        return {}

    def validate(self, task, **kwargs):
        """Validate the driver-specific Node deployment info.

        No validation necessary.

        :param task: a TaskManager instance
        """
        pass

    def driver_vendor_passthru(self, task, method, **kwargs):
        """A node that does not know its UUID should POST to this method.
        Given method, route the command to the appropriate private function.
        """
        if method not in self.driver_routes:
            raise exception.InvalidParameterValue(_('No handler for method %s')
                                                  % method)
        func = self.driver_routes[method]
        return func(task, **kwargs)

    def vendor_passthru(self, task, **kwargs):
        """A node that knows its UUID should heartbeat to this passthru.

        It will get its node object back, with what Ironic thinks its provision
        state is and the target provision state is.
        """
        method = kwargs['method']  # Existence checked in mixin
        if method not in self.vendor_routes:
            raise exception.InvalidParameterValue(_('No handler for method '
                                                    '%s') % method)
        func = self.vendor_routes[method]
        try:
            return func(task, **kwargs)
        except Exception:
            # catch-all in case something bubbles up here
            with excutils.save_and_reraise_exception():
                LOG.exception(_('vendor_passthru failed with method %s'),
                              method)

    def _heartbeat(self, task, **kwargs):
        """Method for agent to periodically check in.

        The agent should be sending its agent_url (so Ironic can talk back)
        as a kwarg.

        kwargs should have the following format:
        {
            'agent_url': 'http://AGENT_HOST:AGENT_PORT'
        }
                AGENT_PORT defaults to 9999.
        """
        node = task.node
        driver_info = node.driver_info
        LOG.debug(
            'Heartbeat from %(node)s, last heartbeat at %(heartbeat)s.',
            {'node': node.uuid,
             'heartbeat': driver_info.get('agent_last_heartbeat')})
        driver_info['agent_last_heartbeat'] = int(_time())
        driver_info['agent_url'] = kwargs['agent_url']
        node.driver_info = driver_info
        node.save(task.context)

        # Async call backs don't set error state on their own
        # TODO(jimrollenhagen) improve error messages here
        try:
            if node.provision_state == states.DEPLOYWAIT:
                msg = _('Node failed to get image for deploy.')
                self._continue_deploy(task, **kwargs)
            elif (node.provision_state == states.DEPLOYING
                    and self._deploy_is_done(node)):
                msg = _('Node failed to move to active state.')
                self._reboot_to_instance(task, **kwargs)
        except Exception:
            LOG.exception(_LE('Async exception for %(node)s: %(msg)s'),
                          {'node': node,
                           'msg': msg})
            _set_failed_state(task, msg)

    def _deploy_is_done(self, node):
        return self._client.deploy_is_done(node)

    @task_manager.require_exclusive_lock
    def _continue_deploy(self, task, **kwargs):
        node = task.node
        image_source = node.instance_info.get('image_source')
        LOG.debug('Continuing deploy for %s', node.uuid)

        image_info = {
            'id': image_source,
            'urls': [node.instance_info['image_url']],
            'checksum': node.instance_info['image_checksum'],
        }

        # Tell the client to download and write the image with the given args
        res = self._client.prepare_image(node, image_info)
        LOG.debug('prepare_image got response %(res)s for node %(node)s',
                  {'res': res, 'node': node.uuid})

        node.provision_state = states.DEPLOYING
        node.save(task.context)

    def _check_deploy_success(self, node):
        # should only ever be called after we've validated that
        # the prepare_image command is complete
        command = self._client.get_commands_status(node)[-1]
        if command['command_status'] == 'FAILED':
            return command['command_error']

    def _reboot_to_instance(self, task, **kwargs):
        node = task.node
        LOG.debug('Preparing to reboot to instance for node %s',
                  node.uuid)
        error = self._check_deploy_success(node)
        if error is not None:
            # TODO(jimrollenhagen) power off if using neutron dhcp to
            #                      align with pxe driver?
            msg = _('node %(node)s command status errored: %(error)s') % (
                   {'node': node.uuid, 'error': error})
            LOG.error(msg)
            _set_failed_state(task, msg)
            return

        LOG.debug('Rebooting node %s to disk', node.uuid)

        manager_utils.node_set_boot_device(task, 'disk', persistent=True)
        manager_utils.node_power_action(task, states.REBOOT)

        node.provision_state = states.ACTIVE
        node.target_provision_state = states.NOSTATE
        node.save(task.context)

    def _lookup(self, context, **kwargs):
        """Method to be called the first time a ramdisk agent checks in. This
        can be because this is a node just entering decom or a node that
        rebooted for some reason. We will use the mac addresses listed in the
        kwargs to find the matching node, then return the node object to the
        agent. The agent can that use that UUID to use the normal vendor
        passthru method.

        Currently, we don't handle the instance where the agent doesn't have
        a matching node (i.e. a brand new, never been in Ironic node).

        kwargs should have the following format:
        {
            "version": "2"
            "inventory": {
                "interfaces": [
                    {
                        "name": "eth0",
                        "mac_address": "00:11:22:33:44:55",
                        "switch_port_descr": "port24"
                        "switch_chassis_descr": "tor1"
                    },
                    ...
                ], ...
            }
        }

        The interfaces list should include a list of the non-IPMI MAC addresses
        in the form aa:bb:cc:dd:ee:ff.

        This method will also return the timeout for heartbeats. The driver
        will expect the agent to heartbeat before that timeout, or it will be
        considered down. This will be in a root level key called
        'heartbeat_timeout'

        :raises: NotFound if no matching node is found.
        :raises: InvalidParameterValue with unknown payload version
        """
        version = kwargs.get('version')

        if version not in self.supported_payload_versions:
            raise exception.InvalidParameterValue(_('Unknown lookup payload'
                                                    'version: %s') % version)
        interfaces = self._get_interfaces(version, kwargs)
        mac_addresses = self._get_mac_addresses(interfaces)

        node = self._find_node_by_macs(context, mac_addresses)

        LOG.debug('Initial lookup for node %s succeeded.', node.uuid)

        # Only support additional hardware in v2 and above. Grab all the
        # top level keys in inventory that aren't interfaces and add them.
        # Nest it in 'hardware' to avoid namespace issues
        hardware = {
            'hardware': {
                'network': interfaces
            }
        }

        for key, value in kwargs.items():
            if key != 'interfaces':
                hardware['hardware'][key] = value

        return {
            'heartbeat_timeout': CONF.agent.heartbeat_timeout,
            'node': node
        }

    def _get_interfaces(self, version, inventory):
        interfaces = []
        try:
            interfaces = inventory['inventory']['interfaces']
        except (KeyError, TypeError):
            raise exception.InvalidParameterValue(_(
                'Malformed network interfaces lookup: %s') % inventory)

        return interfaces

    def _get_mac_addresses(self, interfaces):
        """Returns MACs for the network devices
        """
        mac_addresses = []

        for interface in interfaces:
            try:
                mac_addresses.append(utils.validate_and_normalize_mac(
                    interface.get('mac_address')))
            except exception.InvalidMAC:
                LOG.warning(_LW('Malformed MAC: %s'), interface.get(
                    'mac_address'))
        return mac_addresses

    def _find_node_by_macs(self, context, mac_addresses):
        """Given a list of MAC addresses, find the ports that match the MACs
        and return the node they are all connected to.

        :raises: NodeNotFound if the ports point to multiple nodes or no
        nodes.
        """
        ports = self._find_ports_by_macs(context, mac_addresses)
        if not ports:
            raise exception.NodeNotFound(_(
                'No ports matching the given MAC addresses %sexist in the '
                'database.') % mac_addresses)
        node_id = self._get_node_id(ports)
        try:
            node = objects.Node.get_by_id(context, node_id)
        except exception.NodeNotFound:
            with excutils.save_and_reraise_exception():
                LOG.exception(_('Could not find matching node for the '
                                'provided MACs %s.'), mac_addresses)

        return node

    def _find_ports_by_macs(self, context, mac_addresses):
        """Given a list of MAC addresses, find the ports that match the MACs
        and return them as a list of Port objects, or an empty list if there
        are no matches
        """
        ports = []
        for mac in mac_addresses:
            # Will do a search by mac if the mac isn't malformed
            try:
                port_ob = objects.Port.get_by_address(context, mac)
                ports.append(port_ob)

            except exception.PortNotFound:
                LOG.warning(_LW('MAC address %s not found in database'), mac)

        return ports

    def _get_node_id(self, ports):
        """Given a list of ports, either return the node_id they all share or
        raise a NotFound if there are multiple node_ids, which indicates some
        ports are connected to one node and the remaining port(s) are connected
        to one or more other nodes.

        :raises: NodeNotFound if the MACs match multiple nodes. This
        could happen if you swapped a NIC from one server to another and
        don't notify Ironic about it or there is a MAC collision (since
        they're not guaranteed to be unique).
        """
        # See if all the ports point to the same node
        node_ids = set(port_ob.node_id for port_ob in ports)
        if len(node_ids) > 1:
            raise exception.NodeNotFound(_(
                'Ports matching mac addresses match multiple nodes. MACs: '
                '%(macs)s. Port ids: %(port_ids)s') %
                {'macs': [port_ob.address for port_ob in ports], 'port_ids':
                 [port_ob.uuid for port_ob in ports]}
            )

        # Only have one node_id left, return it.
        return node_ids.pop()
