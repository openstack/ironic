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

from oslo_config import cfg

from ironic.common.i18n import _


opts = [
    cfg.StrOpt('ansible_extra_args',
               help=_('Extra arguments to pass on every '
                      'invocation of Ansible.')),
    cfg.IntOpt('verbosity',
               min=0,
               max=4,
               help=_('Set ansible verbosity level requested when invoking '
                      '"ansible-playbook" command. '
                      '4 includes detailed SSH session logging. '
                      'Default is 4 when global debug is enabled '
                      'and 0 otherwise.')),
    cfg.StrOpt('ansible_playbook_script',
               default='ansible-playbook',
               help=_('Path to "ansible-playbook" script. '
                      'Default will search the $PATH configured for user '
                      'running ironic-conductor process. '
                      'Provide the full path when ansible-playbook is not in '
                      '$PATH or installed in not default location.')),
    cfg.StrOpt('playbooks_path',
               default=os.path.join('$pybasedir',
                                    'drivers/modules/ansible/playbooks'),
               help=_('Path to directory with playbooks, roles and '
                      'local inventory.')),
    cfg.StrOpt('config_file_path',
               default=os.path.join(
                   '$pybasedir',
                   'drivers/modules/ansible/playbooks/ansible.cfg'),
               help=_('Path to ansible configuration file. If set to empty, '
                      'system default will be used.')),
    cfg.IntOpt('post_deploy_get_power_state_retries',
               min=0,
               default=6,
               help=_('Number of times to retry getting power state to check '
                      'if bare metal node has been powered off after a soft '
                      'power off. Value of 0 means do not retry on failure.')),
    cfg.IntOpt('post_deploy_get_power_state_retry_interval',
               min=0,
               default=5,
               help=_('Amount of time (in seconds) to wait between polling '
                      'power state after trigger soft poweroff.')),
    cfg.IntOpt('extra_memory',
               default=10,
               help=_('Extra amount of memory in MiB expected to be consumed '
                      'by Ansible-related processes on the node. Affects '
                      'decision whether image will fit into RAM.')),
    cfg.BoolOpt('image_store_insecure',
                default=False,
                help=_('Skip verifying SSL connections to the image store '
                       'when downloading the image. '
                       'Setting it to "True" is only recommended for testing '
                       'environments that use self-signed certificates.')),
    cfg.StrOpt('image_store_cafile',
               help=_('Specific CA bundle to use for validating '
                      'SSL connections to the image store. '
                      'If not specified, CA available in the ramdisk '
                      'will be used. '
                      'Is not used by default playbooks included with '
                      'the driver. '
                      'Suitable for environments that use self-signed '
                      'certificates.')),
    cfg.StrOpt('image_store_certfile',
               help=_('Client cert to use for SSL connections '
                      'to image store. '
                      'Is not used by default playbooks included with '
                      'the driver.')),
    cfg.StrOpt('image_store_keyfile',
               help=_('Client key to use for SSL connections '
                      'to image store. '
                      'Is not used by default playbooks included with '
                      'the driver.')),
    cfg.StrOpt('default_username',
               default='ansible',
               help=_("Name of the user to use for Ansible when connecting "
                      "to the ramdisk over SSH. It may be overridden "
                      "by per-node 'ansible_username' option "
                      "in node's 'driver_info' field.")),
    cfg.StrOpt('default_key_file',
               help=_("Absolute path to the private SSH key file to use "
                      "by Ansible by default when connecting to the ramdisk "
                      "over SSH. Default is to use default SSH keys "
                      "configured for the user running the ironic-conductor "
                      "service. Private keys with password must be pre-loaded "
                      "into 'ssh-agent'. It may be overridden by per-node "
                      "'ansible_key_file' option in node's "
                      "'driver_info' field.")),
    cfg.StrOpt('default_deploy_playbook',
               default='deploy.yaml',
               help=_("Path (relative to $playbooks_path or absolute) "
                      "to the default playbook used for deployment. "
                      "It may be overridden by per-node "
                      "'ansible_deploy_playbook' option in node's "
                      "'driver_info' field.")),
    cfg.StrOpt('default_shutdown_playbook',
               default='shutdown.yaml',
               help=_("Path (relative to $playbooks_path or absolute) "
                      "to the default playbook used for graceful in-band "
                      "shutdown of the node. "
                      "It may be overridden by per-node "
                      "'ansible_shutdown_playbook' option in node's "
                      "'driver_info' field.")),
    cfg.StrOpt('default_clean_playbook',
               default='clean.yaml',
               help=_("Path (relative to $playbooks_path or absolute) "
                      "to the default playbook used for node cleaning. "
                      "It may be overridden by per-node "
                      "'ansible_clean_playbook' option in node's "
                      "'driver_info' field.")),
    cfg.StrOpt('default_clean_steps_config',
               default='clean_steps.yaml',
               help=_("Path (relative to $playbooks_path or absolute) "
                      "to the default auxiliary cleaning steps file used "
                      "during the node cleaning. "
                      "It may be overridden by per-node "
                      "'ansible_clean_steps_config' option in node's "
                      "'driver_info' field.")),
    cfg.StrOpt('default_python_interpreter',
               help=_("Absolute path to the python interpreter on the "
                      "managed machines. It may be overridden by per-node "
                      "'ansible_python_interpreter' option in node's "
                      "'driver_info' field. "
                      "By default, ansible uses /usr/bin/python")),
]


def register_opts(conf):
    conf.register_opts(opts, group='ansible')
