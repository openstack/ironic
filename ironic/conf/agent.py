# Copyright 2016 Intel Corporation
# Copyright 2014 Rackspace, Inc.
# Copyright 2015 Red Hat, Inc.
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

from oslo_config import cfg

from ironic.common.i18n import _


opts = [
    cfg.BoolOpt('manage_agent_boot',
                default=True,
                help=_('Whether Ironic will manage booting of the agent '
                       'ramdisk. If set to False, you will need to configure '
                       'your mechanism to allow booting the agent '
                       'ramdisk.')),
    cfg.IntOpt('memory_consumed_by_agent',
               default=0,
               mutable=True,
               help=_('The memory size in MiB consumed by agent when it is '
                      'booted on a bare metal node. This is used for '
                      'checking if the image can be downloaded and deployed '
                      'on the bare metal node after booting agent ramdisk. '
                      'This may be set according to the memory consumed by '
                      'the agent ramdisk image.')),
    cfg.BoolOpt('stream_raw_images',
                default=True,
                mutable=True,
                help=_('Whether the agent ramdisk should stream raw images '
                       'directly onto the disk or not. By streaming raw '
                       'images directly onto the disk the agent ramdisk will '
                       'not spend time copying the image to a tmpfs partition '
                       '(therefore consuming less memory) prior to writing it '
                       'to the disk. Unless the disk where the image will be '
                       'copied to is really slow, this option should be set '
                       'to True. Defaults to True.')),
    cfg.IntOpt('post_deploy_get_power_state_retries',
               default=6,
               help=_('Number of times to retry getting power state to check '
                      'if bare metal node has been powered off after a soft '
                      'power off.')),
    cfg.IntOpt('post_deploy_get_power_state_retry_interval',
               default=5,
               help=_('Amount of time (in seconds) to wait between polling '
                      'power state after trigger soft poweroff.')),
    cfg.StrOpt('agent_api_version',
               default='v1',
               help=_('API version to use for communicating with the ramdisk '
                      'agent.')),
    cfg.StrOpt('deploy_logs_collect',
               choices=[('always', _('always collect the logs')),
                        ('on_failure', _('only collect logs if there is a '
                                         'failure')),
                        ('never', _('never collect logs'))],
               default='on_failure',
               mutable=True,
               help=_('Whether Ironic should collect the deployment logs on '
                      'deployment failure (on_failure), always or never.')),
    cfg.StrOpt('deploy_logs_storage_backend',
               choices=[('local', _('store the logs locally')),
                        ('swift', _('store the logs in Object Storage '
                                    'service'))],
               default='local',
               mutable=True,
               help=_('The name of the storage backend where the logs '
                      'will be stored.')),
    cfg.StrOpt('deploy_logs_local_path',
               default='/var/log/ironic/deploy',
               mutable=True,
               help=_('The path to the directory where the logs should be '
                      'stored, used when the deploy_logs_storage_backend '
                      'is configured to "local".')),
    cfg.StrOpt('deploy_logs_swift_container',
               default='ironic_deploy_logs_container',
               mutable=True,
               help=_('The name of the Swift container to store the logs, '
                      'used when the deploy_logs_storage_backend is '
                      'configured to "swift".')),
    cfg.IntOpt('deploy_logs_swift_days_to_expire',
               default=30,
               mutable=True,
               help=_('Number of days before a log object is marked as '
                      'expired in Swift. If None, the logs will be kept '
                      'forever or until manually deleted. Used when the '
                      'deploy_logs_storage_backend is configured to '
                      '"swift".')),
    cfg.StrOpt('image_download_source',
               choices=[('swift', _('IPA ramdisk retrieves instance image '
                                    'from the Object Storage service.')),
                        ('http', _('IPA ramdisk retrieves instance image '
                                   'from HTTP service served at conductor '
                                   'nodes.')),
                        ('local', _('Same as "http", but HTTP images '
                                    'are also cached locally, converted '
                                    'and served from the conductor'))],
               default='http',
               mutable=True,
               help=_('Specifies whether direct deploy interface should try '
                      'to use the image source directly or if ironic should '
                      'cache the image on the conductor and serve it from '
                      'ironic\'s own http server.')),
    cfg.IntOpt('command_timeout',
               default=60,
               mutable=True,
               help=_('Timeout (in seconds) for IPA commands.')),
    cfg.IntOpt('max_command_attempts',
               default=3,
               help=_('This is the maximum number of attempts that will be '
                      'done for IPA commands that fails due to network '
                      'problems.')),
    cfg.IntOpt('command_wait_attempts',
               default=100,
               help=_('Number of attempts to check for asynchronous commands '
                      'completion before timing out.')),
    cfg.IntOpt('command_wait_interval',
               default=6,
               help=_('Number of seconds to wait for between checks for '
                      'asynchronous commands completion.')),
    cfg.IntOpt('neutron_agent_poll_interval',
               default=2,
               mutable=True,
               help=_('The number of seconds Neutron agent will wait between '
                      'polling for device changes. This value should be '
                      'the same as CONF.AGENT.polling_interval in Neutron '
                      'configuration.')),
    cfg.IntOpt('neutron_agent_max_attempts',
               default=100,
               help=_('Max number of attempts to validate a Neutron agent '
                      'status before raising network error for a '
                      'dead agent.')),
    cfg.IntOpt('neutron_agent_status_retry_interval',
               default=10,
               help=_('Wait time in seconds between attempts for validating '
                      'Neutron agent status.')),
    cfg.BoolOpt('require_tls',
                default=False,
                mutable=True,
                help=_('If set to True, callback URLs without https:// will '
                       'be rejected by the conductor.')),
    cfg.StrOpt('certificates_path',
               default='/var/lib/ironic/certificates',
               help=_('Path to store auto-generated TLS certificates used to '
                      'validate connections to the ramdisk.')),
    cfg.StrOpt('verify_ca',
               default='True',
               help=_('Path to the TLS CA to validate connection to the '
                      'ramdisk. Set to True to use the system default CA '
                      'storage. Set to False to disable validation. Ignored '
                      'when automatic TLS setup is used.')),
    cfg.StrOpt('api_ca_file',
               help=_('Path to the TLS CA that is used to start the bare '
                      'metal API. In some boot methods this file can be '
                      'passed to the ramdisk.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='agent')
