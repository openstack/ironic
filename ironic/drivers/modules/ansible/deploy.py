#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
Ansible deploy interface
"""

import json
import os
import shlex
from urllib import parse as urlparse

from ironic_lib import metrics_utils
from ironic_lib import utils as irlib_utils
from oslo_concurrency import processutils
from oslo_log import log
from oslo_utils import strutils
from oslo_utils import units
import retrying
import yaml

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import images
from ironic.common import states
from ironic.common import utils
from ironic.conductor import steps as conductor_steps
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import agent_base
from ironic.drivers.modules import deploy_utils


LOG = log.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

OPTIONAL_PROPERTIES = {
    'ansible_username': _('Deploy ramdisk username for Ansible. '
                          'This user must have passwordless sudo '
                          'permissions. Optional.'),
    'ansible_key_file': _('Full path to private SSH key file. '
                          'If not specified, default keys for user running '
                          'ironic-conductor process will be used. '
                          'Note that for keys with password, those '
                          'must be pre-loaded into ssh-agent. '
                          'Optional.'),
    'ansible_playbooks_path': _('Path to folder holding playbooks to use '
                                'for this node. Optional. '
                                'Default is set in ironic config.'),
    'ansible_deploy_playbook': _('Name of the Ansible playbook file inside '
                                 'the "ansible_playbooks_path" folder which '
                                 'is used for node deployment. Optional.'),
    'ansible_shutdown_playbook': _('Name of the Ansible playbook file inside '
                                   'the "ansible_playbooks_path" folder which '
                                   'is used for node shutdown. Optional.'),
    'ansible_clean_playbook': _('Name of the Ansible playbook file inside '
                                'the "ansible_playbooks_path" folder which '
                                'is used for node cleaning. Optional.'),
    'ansible_clean_steps_config': _('Name of the file inside the '
                                    '"ansible_playbooks_path" folder with '
                                    'cleaning steps configuration. Optional.'),
    'ansible_python_interpreter': _('Absolute path to the python interpreter '
                                    'on the managed machines. Optional.'),
}

COMMON_PROPERTIES = OPTIONAL_PROPERTIES


class PlaybookNotFound(exception.IronicException):
    _msg_fmt = _('Failed to set ansible playbook for action %(action)s')


def _get_playbooks_path(node):
    return node.driver_info.get('ansible_playbooks_path',
                                CONF.ansible.playbooks_path)


def _parse_ansible_driver_info(node, action='deploy'):
    user = node.driver_info.get('ansible_username',
                                CONF.ansible.default_username)
    key = node.driver_info.get('ansible_key_file',
                               CONF.ansible.default_key_file)
    playbook = node.driver_info.get('ansible_%s_playbook' % action,
                                    getattr(CONF.ansible,
                                            'default_%s_playbook' % action,
                                            None))
    if not playbook:
        raise PlaybookNotFound(action=action)
    return os.path.basename(playbook), user, key


def _get_python_interpreter(node):
    return node.driver_info.get('ansible_python_interpreter',
                                CONF.ansible.default_python_interpreter)


def _get_configdrive_path(basename):
    return os.path.join(CONF.tempdir, basename + '.cndrive')


def _get_node_ip(task):
    callback_url = task.node.driver_internal_info.get('agent_url', '')
    return urlparse.urlparse(callback_url).netloc.split(':')[0]


def _prepare_extra_vars(host_list, variables=None):
    nodes_var = []
    for node_uuid, ip, user, extra in host_list:
        nodes_var.append(dict(name=node_uuid, ip=ip, user=user, extra=extra))
    extra_vars = dict(nodes=nodes_var)
    if variables:
        extra_vars.update(variables)
    return extra_vars


def _run_playbook(node, name, extra_vars, key, tags=None, notags=None):
    """Execute ansible-playbook."""
    root = _get_playbooks_path(node)
    playbook = os.path.join(root, name)
    inventory = os.path.join(root, 'inventory')
    ironic_vars = {'ironic': extra_vars}
    python_interpreter = _get_python_interpreter(node)
    if python_interpreter:
        ironic_vars['ansible_python_interpreter'] = python_interpreter
    args = [CONF.ansible.ansible_playbook_script, playbook,
            '-i', inventory,
            '-e', json.dumps(ironic_vars),
            ]

    if CONF.ansible.config_file_path:
        env = ['env', 'ANSIBLE_CONFIG=%s' % CONF.ansible.config_file_path]
        args = env + args

    if tags:
        args.append('--tags=%s' % ','.join(tags))

    if notags:
        args.append('--skip-tags=%s' % ','.join(notags))

    if key:
        args.append('--private-key=%s' % key)

    verbosity = CONF.ansible.verbosity
    if verbosity is None and CONF.debug:
        verbosity = 4
    if verbosity:
        args.append('-' + 'v' * verbosity)

    if CONF.ansible.ansible_extra_args:
        args.extend(shlex.split(CONF.ansible.ansible_extra_args))

    try:
        out, err = utils.execute(*args)
        return out, err
    except processutils.ProcessExecutionError as e:
        raise exception.InstanceDeployFailure(reason=e)


def _calculate_memory_req(task):
    image_source = task.node.instance_info['image_source']
    image_size = images.download_size(task.context, image_source)
    return image_size // units.Mi + CONF.ansible.extra_memory


def _parse_partitioning_info(node):

    info = node.instance_info
    i_info = {'label': deploy_utils.get_disk_label(node) or 'msdos'}
    is_gpt = i_info['label'] == 'gpt'
    unit = 'MiB'
    partitions = {}

    def add_partition(name, start, end):
        partitions[name] = {'number': len(partitions) + 1,
                            'part_start': '%i%s' % (start, unit),
                            'part_end': '%i%s' % (end, unit)}
        if is_gpt:
            partitions[name]['name'] = name

    end = 1
    if is_gpt:
        # prepend 1MiB bios_grub partition for GPT so that grub(2) installs
        start, end = end, end + 1
        add_partition('bios', start, end)
        partitions['bios']['flags'] = ['bios_grub']

    ephemeral_mb = info['ephemeral_mb']
    if ephemeral_mb:
        start, end = end, end + ephemeral_mb
        add_partition('ephemeral', start, end)
        i_info['ephemeral_format'] = info['ephemeral_format']
        i_info['preserve_ephemeral'] = (
            'yes' if info['preserve_ephemeral'] else 'no')

    swap_mb = info['swap_mb']
    if swap_mb:
        start, end = end, end + swap_mb
        add_partition('swap', start, end)

    configdrive = info.get('configdrive')
    if configdrive:
        # pre-create 64MiB partition for configdrive
        start, end = end, end + 64
        add_partition('configdrive', start, end)

    # NOTE(pas-ha) make the root partition last so that
    # e.g. cloud-init can grow it on first start
    start, end = end, end + info['root_mb']
    add_partition('root', start, end)
    if not is_gpt:
        partitions['root']['flags'] = ['boot']
    i_info['partitions'] = partitions
    return {'partition_info': i_info}


def _parse_root_device_hints(node):
    """Convert string with hints to dict. """
    parsed_hints = deploy_utils.get_root_device_for_deploy(node)
    if not parsed_hints:
        return {}

    root_device_hints = {}
    advanced = {}
    for hint, value in parsed_hints.items():
        if isinstance(value, str):
            if value.startswith('== '):
                root_device_hints[hint] = int(value[3:])
            elif value.startswith('s== '):
                root_device_hints[hint] = urlparse.unquote(value[4:])
            else:
                advanced[hint] = value
        else:
            root_device_hints[hint] = value
    if advanced:
        raise exception.InvalidParameterValue(
            _('Ansible-deploy does not support advanced root device hints '
              'based on oslo.utils operators. '
              'Present advanced hints for node %(node)s are %(hints)s.') % {
                  'node': node.uuid, 'hints': advanced})
    return root_device_hints


def _add_ssl_image_options(image):
    image['validate_certs'] = ('no' if CONF.ansible.image_store_insecure
                               else 'yes')
    if CONF.ansible.image_store_cafile:
        image['cafile'] = CONF.ansible.image_store_cafile
    if CONF.ansible.image_store_certfile and CONF.ansible.image_store_keyfile:
        image['client_cert'] = CONF.ansible.image_store_certfile
        image['client_key'] = CONF.ansible.image_store_keyfile


def _prepare_variables(task):
    node = task.node
    i_info = node.instance_info
    image = {}
    for i_key, i_value in i_info.items():
        if i_key.startswith('image_'):
            image[i_key[6:]] = i_value

    checksum = image.get('checksum')
    if checksum:
        # NOTE(pas-ha) checksum can be in <algo>:<checksum> format
        # as supported by various Ansible modules, mostly good for
        # standalone Ironic case when instance_info is populated manually.
        # With no <algo> we take that instance_info is populated from Glance,
        # where API reports checksum as MD5 always.
        if ':' not in checksum:
            image['checksum'] = 'md5:%s' % checksum
    _add_ssl_image_options(image)
    variables = {'image': image}
    configdrive = i_info.get('configdrive')
    if configdrive:
        if urlparse.urlparse(configdrive).scheme in ('http', 'https'):
            cfgdrv_type = 'url'
            cfgdrv_location = configdrive
        else:
            cfgdrv_location = _get_configdrive_path(node.uuid)
            with open(cfgdrv_location, 'w') as f:
                f.write(configdrive)
            cfgdrv_type = 'file'
        variables['configdrive'] = {'type': cfgdrv_type,
                                    'location': cfgdrv_location}

    root_device_hints = _parse_root_device_hints(node)
    if root_device_hints:
        variables['root_device_hints'] = root_device_hints

    return variables


def _validate_clean_steps(steps, node_uuid):
    missing = []
    for step in steps:
        name = step.get('name')
        if not name:
            missing.append({'name': 'undefined', 'field': 'name'})
            continue
        if 'interface' not in step:
            missing.append({'name': name, 'field': 'interface'})
        args = step.get('args', {})
        for arg_name, arg in args.items():
            if arg.get('required', False) and 'value' not in arg:
                missing.append({'name': name,
                                'field': '%s.value' % arg_name})
    if missing:
        err_string = ', '.join(
            'name %(name)s, field %(field)s' % i for i in missing)
        msg = _("Malformed clean_steps file: %s") % err_string
        LOG.error(msg)
        raise exception.NodeCleaningFailure(node=node_uuid,
                                            reason=msg)
    if len(set(s['name'] for s in steps)) != len(steps):
        msg = _("Cleaning steps do not have unique names.")
        LOG.error(msg)
        raise exception.NodeCleaningFailure(node=node_uuid,
                                            reason=msg)


def _get_clean_steps(node, interface=None, override_priorities=None):
    """Get cleaning steps."""
    clean_steps_file = node.driver_info.get(
        'ansible_clean_steps_config', CONF.ansible.default_clean_steps_config)
    path = os.path.join(node.driver_info.get('ansible_playbooks_path',
                                             CONF.ansible.playbooks_path),
                        os.path.basename(clean_steps_file))
    try:
        with open(path) as f:
            internal_steps = yaml.safe_load(f)
    except Exception as e:
        msg = _('Failed to load clean steps from file '
                '%(file)s: %(exc)s') % {'file': path, 'exc': e}
        raise exception.NodeCleaningFailure(node=node.uuid, reason=msg)

    _validate_clean_steps(internal_steps, node.uuid)

    steps = []
    override = override_priorities or {}
    for params in internal_steps:
        name = params['name']
        clean_if = params['interface']
        if interface is not None and interface != clean_if:
            continue
        new_priority = override.get(name)
        priority = (new_priority if new_priority is not None else
                    params.get('priority', 0))
        args = {}
        argsinfo = params.get('args', {})
        for arg, arg_info in argsinfo.items():
            args[arg] = arg_info.pop('value', None)
        step = {
            'interface': clean_if,
            'step': name,
            'priority': priority,
            'abortable': False,
            'argsinfo': argsinfo,
            'args': args
        }
        steps.append(step)

    return steps


class AnsibleDeploy(agent_base.HeartbeatMixin,
                    agent_base.AgentOobStepsMixin,
                    base.DeployInterface):
    """Interface for deploy-related actions."""

    has_decomposed_deploy_steps = True

    collect_deploy_logs = False

    def get_properties(self):
        """Return the properties of the interface."""
        props = COMMON_PROPERTIES.copy()
        # NOTE(pas-ha) this is to get the deploy_forces_oob_reboot property
        props.update(agent_base.VENDOR_PROPERTIES)
        return props

    @METRICS.timer('AnsibleDeploy.validate')
    def validate(self, task):
        """Validate the driver-specific Node deployment info."""
        task.driver.boot.validate(task)

        node = task.node
        iwdi = node.driver_internal_info.get('is_whole_disk_image')
        if not iwdi and deploy_utils.get_boot_option(node) == "netboot":
            raise exception.InvalidParameterValue(_(
                "Node %(node)s is configured to use the ansible deploy "
                "interface, which does not support netboot.") %
                {'node': node.uuid})

        params = {}
        image_source = node.instance_info.get('image_source')
        params['instance_info.image_source'] = image_source
        error_msg = _('Node %s failed to validate deploy image info. Some '
                      'parameters were missing') % node.uuid
        deploy_utils.check_for_missing_params(params, error_msg)
        # validate root device hints, proper exceptions are raised from there
        _parse_root_device_hints(node)
        # TODO(pas-ha) validate that all playbooks and ssh key (if set)
        # are pointing to actual files

    def _ansible_deploy(self, task, node_address):
        """Internal function for deployment to a node."""
        node = task.node
        LOG.debug('IP of node %(node)s is %(ip)s',
                  {'node': node.uuid, 'ip': node_address})
        variables = _prepare_variables(task)
        if not node.driver_internal_info.get('is_whole_disk_image'):
            variables.update(_parse_partitioning_info(node))
        if node.target_raid_config:
            variables.update({'raid_config': node.target_raid_config})
        playbook, user, key = _parse_ansible_driver_info(node)
        node_list = [(node.uuid, node_address, user, node.extra)]
        extra_vars = _prepare_extra_vars(node_list, variables=variables)

        LOG.debug('Starting deploy on node %s', node.uuid)
        # any caller should manage exceptions raised from here
        _run_playbook(node, playbook, extra_vars, key)

    @METRICS.timer('AnsibleDeploy.deploy')
    @base.deploy_step(priority=100)
    @task_manager.require_exclusive_lock
    def deploy(self, task):
        """Perform a deployment to a node."""
        self._required_image_info(task)
        manager_utils.node_power_action(task, states.REBOOT)
        return states.DEPLOYWAIT

    def process_next_step(self, task, step_type):
        """Start the next clean/deploy step if the previous one is complete.

        :param task: a TaskManager instance
        :param step_type: "clean" or "deploy"
        """
        # Run the next step as soon as agent heartbeats in deploy.deploy
        if step_type == 'deploy' and self.in_core_deploy_step(task):
            manager_utils.notify_conductor_resume_deploy(task)

    @staticmethod
    def _required_image_info(task):
        """Gather and save needed image info while the context is good.

        Gather image info that will be needed later, during the
        write_image execution, where the context won't be the same
        anymore, since coming from the server's heartbeat.
        """
        node = task.node
        i_info = node.instance_info
        i_info['image_mem_req'] = _calculate_memory_req(task)
        node.instance_info = i_info
        node.save()

    @METRICS.timer('AnsibleDeploy.tear_down')
    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node."""
        manager_utils.node_power_action(task, states.POWER_OFF)
        power_state_to_restore = manager_utils.power_on_node_if_needed(task)
        task.driver.network.unconfigure_tenant_networks(task)
        manager_utils.restore_power_state_if_needed(
            task, power_state_to_restore)
        return states.DELETED

    @METRICS.timer('AnsibleDeploy.prepare')
    def prepare(self, task):
        """Prepare the deployment environment for this node."""
        node = task.node
        # TODO(pas-ha) investigate takeover scenario
        if node.provision_state == states.DEPLOYING:
            # adding network-driver dependent provisioning ports
            manager_utils.node_power_action(task, states.POWER_OFF)
            power_state_to_restore = (
                manager_utils.power_on_node_if_needed(task))
            task.driver.network.add_provisioning_network(task)
            manager_utils.restore_power_state_if_needed(
                task, power_state_to_restore)
        if node.provision_state not in [states.ACTIVE, states.ADOPTING]:
            node.instance_info = deploy_utils.build_instance_info_for_deploy(
                task)
            node.save()
            boot_opt = deploy_utils.build_agent_options(node)
            task.driver.boot.prepare_ramdisk(task, boot_opt)

    @METRICS.timer('AnsibleDeploy.clean_up')
    def clean_up(self, task):
        """Clean up the deployment environment for this node."""
        task.driver.boot.clean_up_ramdisk(task)
        provider = dhcp_factory.DHCPFactory()
        provider.clean_dhcp(task)
        irlib_utils.unlink_without_raise(
            _get_configdrive_path(task.node.uuid))

    def take_over(self, task):
        LOG.error("Ansible deploy does not support take over. "
                  "You must redeploy the node %s explicitly.",
                  task.node.uuid)

    def get_clean_steps(self, task):
        """Get the list of clean steps from the file.

        :param task: a TaskManager object containing the node
        :returns: A list of clean step dictionaries
        """
        new_priorities = {
            'erase_devices': CONF.deploy.erase_devices_priority,
            'erase_devices_metadata':
                CONF.deploy.erase_devices_metadata_priority
        }
        return _get_clean_steps(task.node, interface='deploy',
                                override_priorities=new_priorities)

    @METRICS.timer('AnsibleDeploy.execute_clean_step')
    def execute_clean_step(self, task, step):
        """Execute a clean step.

        :param task: a TaskManager object containing the node
        :param step: a clean step dictionary to execute
        :returns: None
        """
        node = task.node
        playbook, user, key = _parse_ansible_driver_info(
            task.node, action='clean')
        stepname = step['step']

        node_address = _get_node_ip(task)

        node_list = [(node.uuid, node_address, user, node.extra)]

        if node.target_raid_config:
            variables = {'raid_config': node.target_raid_config}
            extra_vars = _prepare_extra_vars(node_list, variables=variables)
        else:
            extra_vars = _prepare_extra_vars(node_list)

        LOG.debug('Starting cleaning step %(step)s on node %(node)s',
                  {'node': node.uuid, 'step': stepname})
        step_tags = step['args'].get('tags', [])
        LOG.debug("Detected tags from cleaning step: %(tags)s",
                  {'tags': step_tags})
        _run_playbook(node, playbook, extra_vars, key, tags=step_tags)
        LOG.info('Ansible completed cleaning step %(step)s '
                 'on node %(node)s.',
                 {'node': node.uuid, 'step': stepname})

    @METRICS.timer('AnsibleDeploy.prepare_cleaning')
    def prepare_cleaning(self, task):
        """Boot into the ramdisk to prepare for cleaning.

        :param task: a TaskManager object containing the node
        :raises NodeCleaningFailure: if the previous cleaning ports cannot
                be removed or if new cleaning ports cannot be created
        :returns: None or states.CLEANWAIT for async prepare.
        """
        node = task.node
        conductor_steps.set_node_cleaning_steps(task)
        if not node.driver_internal_info['clean_steps']:
            # no clean steps configured, nothing to do.
            return
        power_state_to_restore = manager_utils.power_on_node_if_needed(task)
        task.driver.network.add_cleaning_network(task)
        manager_utils.restore_power_state_if_needed(
            task, power_state_to_restore)
        boot_opt = deploy_utils.build_agent_options(node)
        task.driver.boot.prepare_ramdisk(task, boot_opt)
        manager_utils.node_power_action(task, states.REBOOT)
        return states.CLEANWAIT

    @METRICS.timer('AnsibleDeploy.tear_down_cleaning')
    def tear_down_cleaning(self, task):
        """Clean up the PXE and DHCP files after cleaning.

        :param task: a TaskManager object containing the node
        :raises NodeCleaningFailure: if the cleaning ports cannot be
                removed
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        task.driver.boot.clean_up_ramdisk(task)
        power_state_to_restore = manager_utils.power_on_node_if_needed(task)
        task.driver.network.remove_cleaning_network(task)
        manager_utils.restore_power_state_if_needed(
            task, power_state_to_restore)

    @METRICS.timer('AnsibleDeploy.write_image')
    @base.deploy_step(priority=80)
    def write_image(self, task):
        # NOTE(pas-ha) the lock should be already upgraded in heartbeat,
        # just setting its purpose for better logging
        task.upgrade_lock(purpose='deploy')
        # NOTE(pas-ha) this method is called from heartbeat processing only,
        # so we are sure we need this particular method, not the general one
        node_address = _get_node_ip(task)
        self._ansible_deploy(task, node_address)
        LOG.info('Ansible complete deploy on node %s', task.node.uuid)
        manager_utils.node_set_boot_device(task, 'disk', persistent=True)

    @METRICS.timer('AnsibleDeploy.tear_down_agent')
    @base.deploy_step(priority=40)
    @task_manager.require_exclusive_lock
    def tear_down_agent(self, task):
        """A deploy step to tear down the agent.

        Shuts down the machine and removes it from the provisioning
        network.

        :param task: a TaskManager object containing the node
        """
        wait = CONF.ansible.post_deploy_get_power_state_retry_interval * 1000
        attempts = CONF.ansible.post_deploy_get_power_state_retries + 1

        @retrying.retry(
            stop_max_attempt_number=attempts,
            retry_on_result=lambda state: state != states.POWER_OFF,
            wait_fixed=wait
        )
        def _wait_until_powered_off(task):
            return task.driver.power.get_power_state(task)

        node = task.node
        oob_power_off = strutils.bool_from_string(
            node.driver_info.get('deploy_forces_oob_reboot', False))
        try:
            if not oob_power_off:
                try:
                    node_address = _get_node_ip(task)
                    playbook, user, key = _parse_ansible_driver_info(
                        node, action='shutdown')
                    node_list = [(node.uuid, node_address, user, node.extra)]
                    extra_vars = _prepare_extra_vars(node_list)
                    _run_playbook(node, playbook, extra_vars, key)
                    _wait_until_powered_off(task)
                except Exception as e:
                    LOG.warning('Failed to soft power off node %(node_uuid)s '
                                'in at least %(timeout)d seconds. '
                                'Error: %(error)s',
                                {'node_uuid': node.uuid,
                                 'timeout': (wait * (attempts - 1)) / 1000,
                                 'error': e})
                    # NOTE(pas-ha) flush is a part of deploy playbook
                    # so if it finished successfully we can safely
                    # power off the node out-of-band
                    manager_utils.node_power_action(task, states.POWER_OFF)
            else:
                manager_utils.node_power_action(task, states.POWER_OFF)
        except Exception as e:
            msg = (_('Error rebooting node %(node)s after deploy. '
                     'Error: %(error)s') %
                   {'node': node.uuid, 'error': e})
            agent_base.log_and_raise_deployment_error(task, msg)
