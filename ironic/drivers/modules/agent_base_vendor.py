# -*- coding: utf-8 -*-
#
# Copyright 2014 Rackspace, Inc.
# Copyright 2015 Red Hat, Inc.
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


import time

from oslo_config import cfg
from oslo_log import log
from oslo_utils import excutils
import retrying

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.common.i18n import _LW
from ironic.common import states
from ironic.common import utils
from ironic.conductor import manager
from ironic.conductor import rpcapi
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import deploy_utils
from ironic import objects

agent_opts = [
    cfg.IntOpt('heartbeat_timeout',
               default=300,
               help=_('Maximum interval (in seconds) for agent heartbeats.')),
    cfg.IntOpt('post_deploy_get_power_state_retries',
               default=6,
               help=_('Number of times to retry getting power state to check '
                      'if bare metal node has been powered off after a soft '
                      'power off.')),
    cfg.IntOpt('post_deploy_get_power_state_retry_interval',
               default=5,
               help=_('Amount of time (in seconds) to wait between polling '
                      'power state after trigger soft poweroff.')),
]

CONF = cfg.CONF
CONF.register_opts(agent_opts, group='agent')

LOG = log.getLogger(__name__)


def _time():
    """Broken out for testing."""
    return time.time()


def _get_client():
    client = agent_client.AgentClient()
    return client


class BaseAgentVendor(base.VendorInterface):

    def __init__(self):
        self.supported_payload_versions = ['2']
        self._client = _get_client()

    def continue_deploy(self, task, **kwargs):
        """Continues the deployment of baremetal node.

        This method continues the deployment of the baremetal node after
        the ramdisk have been booted.

        :param task: a TaskManager instance

        """
        pass

    def deploy_has_started(self, task):
        """Check if the deployment has started already.

        :returns: True if the deploy has started, False otherwise.
        """
        pass

    def deploy_is_done(self, task):
        """Check if the deployment is already completed.

        :returns: True if the deployment is completed. False otherwise

        """
        pass

    def reboot_to_instance(self, task, **kwargs):
        """Method invoked after the deployment is completed.

        :param task: a TaskManager instance

        """
        pass

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        # NOTE(jroll) all properties are set by the driver,
        #             not by the operator.
        return {}

    def validate(self, task, method, **kwargs):
        """Validate the driver-specific Node deployment info.

        No validation necessary.

        :param task: a TaskManager instance
        :param method: method to be validated
        """
        pass

    def driver_validate(self, method, **kwargs):
        """Validate the driver deployment info.

        :param method: method to be validated.
        """
        version = kwargs.get('version')

        if not version:
            raise exception.MissingParameterValue(_('Missing parameter '
                                                    'version'))
        if version not in self.supported_payload_versions:
            raise exception.InvalidParameterValue(_('Unknown lookup '
                                                    'payload version: %s')
                                                  % version)

    def _notify_conductor_resume_clean(self, task):
        LOG.debug('Sending RPC to conductor to resume cleaning for node %s',
                  task.node.uuid)
        uuid = task.node.uuid
        rpc = rpcapi.ConductorAPI()
        topic = rpc.get_topic_for(task.node)
        # Need to release the lock to let the conductor take it
        task.release_resources()
        rpc.continue_node_clean(task.context, uuid, topic=topic)

    def continue_cleaning(self, task, **kwargs):
        """Start the next cleaning step if the previous one is complete.

        In order to avoid errors and make agent upgrades painless, cleaning
        will check the version of all hardware managers during get_clean_steps
        at the beginning of cleaning and before executing each step in the
        agent. If the version has changed between steps, the agent is unable
        to tell if an ordering change will cause a cleaning issue. Therefore,
        we restart cleaning.
        """
        command = self._get_completed_cleaning_command(task)
        LOG.debug('Cleaning command status for node %(node)s on step %(step)s:'
                  ' %(command)s', {'node': task.node.uuid,
                                   'step': task.node.clean_step,
                                   'command': command})

        if not command:
            # Command is not done yet
            return

        if command.get('command_status') == 'FAILED':
            msg = (_('Agent returned error for clean step %(step)s on node '
                     '%(node)s : %(err)s.') %
                   {'node': task.node.uuid,
                    'err': command.get('command_error'),
                    'step': task.node.clean_step})
            LOG.error(msg)
            return manager.cleaning_error_handler(task, msg)
        elif command.get('command_status') == 'CLEAN_VERSION_MISMATCH':
            # Restart cleaning, agent must have rebooted to new version
            LOG.info(_LI('Node %s detected a clean version mismatch, '
                         'resetting clean steps and rebooting the node.'),
                     task.node.uuid)
            try:
                manager.set_node_cleaning_steps(task)
            except exception.NodeCleaningFailure:
                msg = (_('Could not restart cleaning on node %(node)s: '
                         '%(err)s.') %
                       {'node': task.node.uuid,
                        'err': command.get('command_error'),
                        'step': task.node.clean_step})
                LOG.exception(msg)
                return manager.cleaning_error_handler(task, msg)
            self._notify_conductor_resume_clean(task)

        elif command.get('command_status') == 'SUCCEEDED':
            LOG.info(_LI('Agent on node %s returned cleaning command success, '
                         'moving to next clean step'), task.node.uuid)
            self._notify_conductor_resume_clean(task)
        else:
            msg = (_('Agent returned unknown status for clean step %(step)s '
                     'on node %(node)s : %(err)s.') %
                   {'node': task.node.uuid,
                    'err': command.get('command_status'),
                    'step': task.node.clean_step})
            LOG.error(msg)
            return manager.cleaning_error_handler(task, msg)

    @base.passthru(['POST'])
    def heartbeat(self, task, **kwargs):
        """Method for agent to periodically check in.

        The agent should be sending its agent_url (so Ironic can talk back)
        as a kwarg. kwargs should have the following format::

         {
             'agent_url': 'http://AGENT_HOST:AGENT_PORT'
         }

        AGENT_PORT defaults to 9999.
        """
        node = task.node
        driver_internal_info = node.driver_internal_info
        LOG.debug(
            'Heartbeat from %(node)s, last heartbeat at %(heartbeat)s.',
            {'node': node.uuid,
             'heartbeat': driver_internal_info.get('agent_last_heartbeat')})
        driver_internal_info['agent_last_heartbeat'] = int(_time())
        try:
            driver_internal_info['agent_url'] = kwargs['agent_url']
        except KeyError:
            raise exception.MissingParameterValue(_('For heartbeat operation, '
                                                    '"agent_url" must be '
                                                    'specified.'))

        node.driver_internal_info = driver_internal_info
        node.save()

        # Async call backs don't set error state on their own
        # TODO(jimrollenhagen) improve error messages here
        msg = _('Failed checking if deploy is done.')
        try:
            if node.maintenance:
                # this shouldn't happen often, but skip the rest if it does.
                LOG.debug('Heartbeat from node %(node)s in maintenance mode; '
                          'not taking any action.', {'node': node.uuid})
                return
            elif (node.provision_state == states.DEPLOYWAIT and
                  not self.deploy_has_started(task)):
                msg = _('Node failed to get image for deploy.')
                self.continue_deploy(task, **kwargs)
            elif (node.provision_state == states.DEPLOYWAIT and
                  self.deploy_is_done(task)):
                msg = _('Node failed to move to active state.')
                self.reboot_to_instance(task, **kwargs)
            elif (node.provision_state == states.DEPLOYWAIT and
                  self.deploy_has_started(task)):
                node.touch_provisioning()
            # TODO(lucasagomes): CLEANING here for backwards compat
            # with previous code, otherwise nodes in CLEANING when this
            # is deployed would fail. Should be removed once the Mitaka
            # release starts.
            elif (node.provision_state in (states.CLEANWAIT, states.CLEANING)
                  and not node.clean_step):
                # Agent booted from prepare_cleaning
                LOG.debug('Node %s just booted to start cleaning.', node.uuid)
                manager.set_node_cleaning_steps(task)
                self._notify_conductor_resume_clean(task)
            # TODO(lucasagomes): CLEANING here for backwards compat
            # with previous code, otherwise nodes in CLEANING when this
            # is deployed would fail. Should be removed once the Mitaka
            # release starts.
            elif (node.provision_state in (states.CLEANWAIT, states.CLEANING)
                  and node.clean_step):
                self.continue_cleaning(task, **kwargs)

        except Exception as e:
            err_info = {'node': node.uuid, 'msg': msg, 'e': e}
            last_error = _('Asynchronous exception for node %(node)s: '
                           '%(msg)s exception: %(e)s') % err_info
            LOG.exception(last_error)
            deploy_utils.set_failed_state(task, last_error)

    @base.driver_passthru(['POST'], async=False)
    def lookup(self, context, **kwargs):
        """Find a matching node for the agent.

        Method to be called the first time a ramdisk agent checks in. This
        can be because this is a node just entering decom or a node that
        rebooted for some reason. We will use the mac addresses listed in the
        kwargs to find the matching node, then return the node object to the
        agent. The agent can that use that UUID to use the node vendor
        passthru method.

        Currently, we don't handle the instance where the agent doesn't have
        a matching node (i.e. a brand new, never been in Ironic node).

        kwargs should have the following format::

         {
             "version": "2"
             "inventory": {
                 "interfaces": [
                     {
                         "name": "eth0",
                         "mac_address": "00:11:22:33:44:55",
                         "switch_port_descr": "port24",
                         "switch_chassis_descr": "tor1"
                     }, ...
                 ], ...
             },
             "node_uuid": "ab229209-0139-4588-bbe5-64ccec81dd6e"
         }

        The interfaces list should include a list of the non-IPMI MAC addresses
        in the form aa:bb:cc:dd:ee:ff.

        node_uuid argument is optional. If it's provided (e.g. as a result of
        inspection run before lookup), this method will just return a node and
        options.

        This method will also return the timeout for heartbeats. The driver
        will expect the agent to heartbeat before that timeout, or it will be
        considered down. This will be in a root level key called
        'heartbeat_timeout'

        :raises: NotFound if no matching node is found.
        :raises: InvalidParameterValue with unknown payload version
        """
        LOG.debug('Agent lookup using data %s', kwargs)
        uuid = kwargs.get('node_uuid')
        if uuid:
            node = objects.Node.get_by_uuid(context, uuid)
        else:
            inventory = kwargs.get('inventory')
            interfaces = self._get_interfaces(inventory)
            mac_addresses = self._get_mac_addresses(interfaces)

            node = self._find_node_by_macs(context, mac_addresses)

        LOG.info(_LI('Initial lookup for node %s succeeded, agent is running '
                     'and waiting for commands'), node.uuid)

        return {
            'heartbeat_timeout': CONF.agent.heartbeat_timeout,
            'node': node.as_dict()
        }

    def _get_completed_cleaning_command(self, task):
        """Returns None or a completed cleaning command from the agent."""
        commands = self._client.get_commands_status(task.node)
        if not commands:
            return

        last_command = commands[-1]

        if last_command['command_name'] != 'execute_clean_step':
            # catches race condition where execute_clean_step is still
            # processing so the command hasn't started yet
            LOG.debug('Expected agent last command to be "execute_clean_step" '
                      'for node %(node)s, instead got "%(command)s". Waiting '
                      'for next heartbeat.',
                      {'node': task.node.uuid,
                       'command': last_command['command_name']})
            return

        last_result = last_command.get('command_result') or {}
        last_step = last_result.get('clean_step')
        if last_command['command_status'] == 'RUNNING':
            LOG.debug('Clean step still running for node %(node)s: %(step)s',
                      {'step': last_step, 'node': task.node.uuid})
            return
        elif (last_command['command_status'] == 'SUCCEEDED' and
              last_step != task.node.clean_step):
            # A previous clean_step was running, the new command has not yet
            # started.
            LOG.debug('Clean step not yet started for node %(node)s: %(step)s',
                      {'step': last_step, 'node': task.node.uuid})
            return
        else:
            return last_command

    def _get_interfaces(self, inventory):
        interfaces = []
        try:
            interfaces = inventory['interfaces']
        except (KeyError, TypeError):
            raise exception.InvalidParameterValue(_(
                'Malformed network interfaces lookup: %s') % inventory)

        return interfaces

    def _get_mac_addresses(self, interfaces):
        """Returns MACs for the network devices."""
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
        """Get nodes for a given list of MAC addresses.

        Given a list of MAC addresses, find the ports that match the MACs
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
                LOG.exception(_LE('Could not find matching node for the '
                                  'provided MACs %s.'), mac_addresses)

        return node

    def _find_ports_by_macs(self, context, mac_addresses):
        """Get ports for a given list of MAC addresses.

        Given a list of MAC addresses, find the ports that match the MACs
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
        """Get a node ID for a list of ports.

        Given a list of ports, either return the node_id they all share or
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

    def _log_and_raise_deployment_error(self, task, msg):
        """Helper method to log the error and raise exception."""
        LOG.error(msg)
        deploy_utils.set_failed_state(task, msg)
        raise exception.InstanceDeployFailure(msg)

    def reboot_and_finish_deploy(self, task):
        """Helper method to trigger reboot on the node and finish deploy.

        This method initiates a reboot on the node. On success, it
        marks the deploy as complete. On failure, it logs the error
        and marks deploy as failure.

        :param task: a TaskManager object containing the node
        :raises: InstanceDeployFailure, if node reboot failed.
        """
        wait = CONF.agent.post_deploy_get_power_state_retry_interval * 1000
        attempts = CONF.agent.post_deploy_get_power_state_retries + 1

        @retrying.retry(
            stop_max_attempt_number=attempts,
            retry_on_result=lambda state: state != states.POWER_OFF,
            wait_fixed=wait
        )
        def _wait_until_powered_off(task):
            return task.driver.power.get_power_state(task)

        node = task.node

        try:
            try:
                self._client.power_off(node)
                _wait_until_powered_off(task)
            except Exception as e:
                LOG.warning(
                    _LW('Failed to soft power off node %(node_uuid)s '
                        'in at least %(timeout)d seconds. Error: %(error)s'),
                    {'node_uuid': node.uuid,
                     'timeout': (wait * (attempts - 1)) / 1000,
                     'error': e})
                manager_utils.node_power_action(task, states.REBOOT)
            else:
                manager_utils.node_power_action(task, states.POWER_ON)
        except Exception as e:
            msg = (_('Error rebooting node %(node)s after deploy. '
                     'Error: %(error)s') %
                   {'node': node.uuid, 'error': e})
            self._log_and_raise_deployment_error(task, msg)

        task.process_event('done')
        LOG.info(_LI('Deployment to node %s done'), task.node.uuid)

    def configure_local_boot(self, task, root_uuid=None,
                             efi_system_part_uuid=None):
        """Helper method to configure local boot on the node.

        This method triggers bootloader installation on the node.
        On successful installation of bootloader, this method sets the
        node to boot from disk.

        :param task: a TaskManager object containing the node
        :param root_uuid: The UUID of the root partition. This is used
            for identifying the partition which contains the image deployed
            or None in case of whole disk images which we expect to already
            have a bootloader installed.
        :param efi_system_part_uuid: The UUID of the efi system partition.
            This is used only in uefi boot mode.
        :raises: InstanceDeployFailure if bootloader installation failed or
            on encountering error while setting the boot device on the node.
        """
        node = task.node
        LOG.debug('Configuring local boot for node %s', node.uuid)
        if not node.driver_internal_info.get(
                'is_whole_disk_image') and root_uuid:
            LOG.debug('Installing the bootloader for node %(node)s on ',
                      'partition %(part)s, EFI system partition %(efi)s',
                      {'node': node.uuid, 'part': root_uuid,
                       'efi': efi_system_part_uuid})
            result = self._client.install_bootloader(
                node, root_uuid=root_uuid,
                efi_system_part_uuid=efi_system_part_uuid)
            if result['command_status'] == 'FAILED':
                msg = (_("Failed to install a bootloader when "
                         "deploying node %(node)s. Error: %(error)s") %
                       {'node': node.uuid,
                        'error': result['command_error']})
                self._log_and_raise_deployment_error(task, msg)

        try:
            deploy_utils.try_set_boot_device(task, boot_devices.DISK)
        except Exception as e:
            msg = (_("Failed to change the boot device to %(boot_dev)s "
                     "when deploying node %(node)s. Error: %(error)s") %
                   {'boot_dev': boot_devices.DISK, 'node': node.uuid,
                    'error': e})
            self._log_and_raise_deployment_error(task, msg)

        LOG.info(_LI('Local boot successfully configured for node %s'),
                 node.uuid)
