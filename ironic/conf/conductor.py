# Copyright 2016 Intel Corporation
# Copyright 2013 Hewlett-Packard Development Company, L.P.
# Copyright 2013 International Business Machines Corporation
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

from oslo_config import cfg
from oslo_config import types

from ironic.common.i18n import _

opts = [
    cfg.IntOpt('workers_pool_size',
               default=100, min=3,
               help=_('The size of the workers greenthread pool. '
                      'Note that 2 threads will be reserved by the conductor '
                      'itself for handling heart beats and periodic tasks. '
                      'On top of that, `sync_power_state_workers` will take '
                      'up to 7 green threads with the default value of 8.')),
    cfg.IntOpt('heartbeat_interval',
               default=10,
               help=_('Seconds between conductor heart beats.')),
    cfg.IntOpt('heartbeat_timeout',
               default=60,
               # We're using timedelta which can overflow if somebody sets this
               # too high, so limit to a sane value of 10 years.
               max=315576000,
               mutable=True,
               help=_('Maximum time (in seconds) since the last check-in '
                      'of a conductor. A conductor is considered inactive '
                      'when this time has been exceeded.')),
    cfg.IntOpt('sync_power_state_interval',
               default=60,
               help=_('Interval between syncing the node power state to the '
                      'database, in seconds. Set to 0 to disable syncing.')),
    cfg.IntOpt('check_provision_state_interval',
               default=60,
               min=0,
               help=_('Interval between checks of provision timeouts, '
                      'in seconds. Set to 0 to disable checks.')),
    cfg.IntOpt('check_rescue_state_interval',
               default=60,
               min=1,
               help=_('Interval (seconds) between checks of rescue '
                      'timeouts.')),
    cfg.IntOpt('check_allocations_interval',
               default=60,
               min=0,
               help=_('Interval between checks of orphaned allocations, '
                      'in seconds. Set to 0 to disable checks.')),
    cfg.IntOpt('cache_clean_up_interval',
               default=3600, min=0,
               help=_('Interval between cleaning up image caches, in seconds. '
                      'Set to 0 to disable periodic clean-up.')),
    cfg.IntOpt('deploy_callback_timeout',
               default=1800,
               min=0,
               help=_('Timeout (seconds) to wait for a callback from '
                      'a deploy ramdisk. Set to 0 to disable timeout.')),
    cfg.BoolOpt('force_power_state_during_sync',
                default=True,
                mutable=True,
                help=_('During sync_power_state, should the hardware power '
                       'state be set to the state recorded in the database '
                       '(True) or should the database be updated based on '
                       'the hardware state (False).')),
    cfg.IntOpt('power_state_sync_max_retries',
               default=3,
               help=_('During sync_power_state failures, limit the '
                      'number of times Ironic should try syncing the '
                      'hardware node power state with the node power state '
                      'in DB')),
    cfg.IntOpt('sync_power_state_workers',
               default=8, min=1,
               help=_('The maximum number of worker threads that can be '
                      'started simultaneously to sync nodes power states from '
                      'the periodic task.')),
    cfg.IntOpt('periodic_max_workers',
               default=8,
               help=_('Maximum number of worker threads that can be started '
                      'simultaneously by a periodic task. Should be less '
                      'than RPC thread pool size.')),
    cfg.IntOpt('node_locked_retry_attempts',
               default=3,
               help=_('Number of attempts to grab a node lock.')),
    cfg.IntOpt('node_locked_retry_interval',
               default=1,
               help=_('Seconds to sleep between node lock attempts.')),
    cfg.IntOpt('sync_local_state_interval',
               default=180,
               help=_('When conductors join or leave the cluster, existing '
                      'conductors may need to update any persistent '
                      'local state as nodes are moved around the cluster. '
                      'This option controls how often, in seconds, each '
                      'conductor will check for nodes that it should '
                      '"take over". Set it to 0 (or a negative value) to '
                      'disable the check entirely.')),
    cfg.StrOpt('configdrive_swift_container',
               default='ironic_configdrive_container',
               help=_('Name of the Swift container to store config drive '
                      'data. Used when configdrive_use_object_store is '
                      'True.')),
    cfg.IntOpt('configdrive_swift_temp_url_duration',
               min=60,
               help=_('The timeout (in seconds) after which a configdrive '
                      'temporary URL becomes invalid. Defaults to '
                      'deploy_callback_timeout if it is set, otherwise to '
                      '1800 seconds. Used when '
                      'configdrive_use_object_store is True.')),
    cfg.IntOpt('inspect_wait_timeout',
               default=1800,
               min=0,
               help=_('Timeout (seconds) for waiting for node inspection. '
                      '0 - unlimited.')),
    cfg.BoolOpt('automated_clean',
                default=True,
                mutable=True,
                help=_('Enables or disables automated cleaning. Automated '
                       'cleaning is a configurable set of steps, '
                       'such as erasing disk drives, that are performed on '
                       'the node to ensure it is in a baseline state and '
                       'ready to be deployed to. This is '
                       'done after instance deletion as well as during '
                       'the transition from a "manageable" to "available" '
                       'state. When enabled, the particular steps '
                       'performed to clean a node depend on which driver '
                       'that node is managed by; see the individual '
                       'driver\'s documentation for details. '
                       'NOTE: The introduction of the cleaning operation '
                       'causes instance deletion to take significantly '
                       'longer. In an environment where all tenants are '
                       'trusted (eg, because there is only one tenant), '
                       'this option could be safely disabled.')),
    cfg.BoolOpt('allow_provisioning_in_maintenance',
                default=True,
                mutable=True,
                help=_('Whether to allow nodes to enter or undergo deploy or '
                       'cleaning when in maintenance mode. If this option is '
                       'set to False, and a node enters maintenance during '
                       'deploy or cleaning, the process will be aborted '
                       'after the next heartbeat. Automated cleaning or '
                       'making a node available will also fail. If True '
                       '(the default), the process will begin and will pause '
                       'after the node starts heartbeating. Moving it from '
                       'maintenance will make the process continue.')),
    cfg.IntOpt('clean_callback_timeout',
               default=1800,
               min=0,
               help=_('Timeout (seconds) to wait for a callback from the '
                      'ramdisk doing the cleaning. If the timeout is reached '
                      'the node will be put in the "clean failed" provision '
                      'state. Set to 0 to disable timeout.')),
    cfg.IntOpt('rescue_callback_timeout',
               default=1800,
               min=0,
               help=_('Timeout (seconds) to wait for a callback from the '
                      'rescue ramdisk. If the timeout is reached the node '
                      'will be put in the "rescue failed" provision state. '
                      'Set to 0 to disable timeout.')),
    cfg.IntOpt('soft_power_off_timeout',
               default=600,
               min=1,
               mutable=True,
               help=_('Timeout (in seconds) of soft reboot and soft power '
                      'off operation. This value always has to be positive.')),
    cfg.IntOpt('power_state_change_timeout',
               min=2, default=60,
               mutable=True,
               help=_('Number of seconds to wait for power operations to '
                      'complete, i.e., so that a baremetal node is in the '
                      'desired power state. If timed out, the power operation '
                      'is considered a failure.')),
    cfg.IntOpt('power_failure_recovery_interval',
               min=0, default=300,
               help=_('Interval (in seconds) between checking the power '
                      'state for nodes previously put into maintenance mode '
                      'due to power synchronization failure. A node is '
                      'automatically moved out of maintenance mode once its '
                      'power state is retrieved successfully. Set to 0 to '
                      'disable this check.')),
    cfg.StrOpt('conductor_group',
               default='',
               help=_('Name of the conductor group to join. Can be up to '
                      '255 characters and is case insensitive. This '
                      'conductor will only manage nodes with a matching '
                      '"conductor_group" field set on the node.')),
    cfg.BoolOpt('allow_deleting_available_nodes',
                default=True,
                mutable=True,
                help=_('Allow deleting nodes which are in state '
                       '\'available\'. Defaults to True.')),
    cfg.BoolOpt('enable_mdns', default=False,
                help=_('Whether to enable publishing the baremetal API '
                       'endpoint via multicast DNS.')),
    cfg.StrOpt('deploy_kernel',
               mutable=True,
               deprecated_for_removal=True,
               deprecated_reason=_('Replaced by deploy_kernel_by_arch which '
                                   'provides more configuration options.'),
               help=_('DEPRECATED: Glance ID, http:// or file:// URL of the '
                      'kernel of the default deploy image.')),
    cfg.StrOpt('deploy_ramdisk',
               mutable=True,
               deprecated_for_removal=True,
               deprecated_reason=_('Replaced by deploy_ramdisk_by_arch which '
                                   'provides more configuration options.'),
               help=_('DEPRECATED: Glance ID, http:// or file:// URL of the '
                      'initramfs of the default deploy image.')),
    cfg.DictOpt('deploy_kernel_by_arch',
                default={},
                mutable=True,
                help=_('A dictionary of key-value pairs of each architecture '
                       'with the Glance ID, http:// or file:// URL of the '
                       'kernel of the default deploy image.')),
    cfg.DictOpt('deploy_ramdisk_by_arch',
                default={},
                mutable=True,
                help=_('A dictionary of key-value pairs of each architecture '
                       'with the Glance ID, http:// or file:// URL of the '
                       'initramfs of the default deploy image.')),
    cfg.StrOpt('rescue_kernel',
               mutable=True,
               deprecated_for_removal=True,
               deprecated_reason=_('Replaced by rescue_kernel_by_arch which '
                                   'provides more configuration options.'),
               help=_('DEPRECATED: Glance ID, http:// or file:// URL of the '
                      'kernel of the default rescue image.')),
    cfg.StrOpt('rescue_ramdisk',
               mutable=True,
               deprecated_for_removal=True,
               deprecated_reason=_('Replaced by rescue_ramdisk_by_arch which '
                                   'provides more configuration options.'),
               help=_('DEPRECATED: Glance ID, http:// or file:// URL of the '
                      'initramfs of the default rescue image.')),
    cfg.DictOpt('rescue_kernel_by_arch',
                default={},
                mutable=True,
                help=_('A dictionary of key-value pairs of each architecture '
                       'with the Glance ID, http:// or file:// URL of the '
                       'kernel of the default rescue image.')),
    cfg.DictOpt('rescue_ramdisk_by_arch',
                default={},
                mutable=True,
                help=_('A dictionary of key-value pairs of each architecture '
                       'with the Glance ID, http:// or file:// URL of the '
                       'initramfs of the default rescue image.')),
    cfg.StrOpt('rescue_password_hash_algorithm',
               default='sha256',
               choices=['sha256', 'sha512'],
               mutable=True,
               help=_('Password hash algorithm to be used for the rescue '
                      'password.')),
    cfg.BoolOpt('require_rescue_password_hashed',
                # TODO(TheJulia): Change this to True in Victoria.
                default=False,
                mutable=True,
                help=_('Option to cause the conductor to not fallback to '
                       'an un-hashed version of the rescue password, '
                       'permitting rescue with older ironic-python-agent '
                       'ramdisks.')),
    cfg.StrOpt('bootloader',
               mutable=True,
               help=_('Glance ID, http:// or file:// URL of the EFI system '
                      'partition image containing EFI boot loader. This image '
                      'will be used by ironic when building UEFI-bootable ISO '
                      'out of kernel and ramdisk. Required for UEFI boot from '
                      'partition images.')),
    cfg.MultiOpt('clean_step_priority_override',
                 item_type=types.Dict(),
                 default={},
                 help=_('Priority to run automated clean steps for both '
                        'in-band and out of band clean steps, provided in '
                        'interface.step_name:priority format, e.g. '
                        'deploy.erase_devices_metadata:123. The option can '
                        'be specified multiple times to define priorities '
                        'for multiple steps. If set to 0, this specific step '
                        'will not run during cleaning. If unset for an '
                        'inband clean step, will use the priority set in the '
                        'ramdisk.')),
    cfg.BoolOpt('node_history',
                default=True,
                mutable=True,
                help=_('Boolean value, default True, if node event history '
                       'is to be recorded. Errors and other noteworthy '
                       'events in relation to a node are journaled to a '
                       'database table which incurs some additional load. '
                       'A periodic task does periodically remove entries '
                       'from the database. Please note, if this is disabled, '
                       'the conductor will continue to purge entries as '
                       'long as [conductor]node_history_cleanup_batch_count '
                       'is not 0.')),
    cfg.IntOpt('node_history_max_entries',
               default=300,
               min=0,
               mutable=True,
               help=_('Maximum number of history entries which will be stored '
                      'in the database per node. Default is 300. This setting '
                      'excludes the minimum number of days retained using the '
                      '[conductor]node_history_minimum_days setting.')),
    cfg.IntOpt('node_history_cleanup_interval',
               min=0,
               default=86400,
               mutable=False,
               help=_('Interval in seconds at which node history entries '
                      'can be cleaned up in the database. Setting to 0 '
                      'disables the periodic task. Defaults to once a day, '
                      'or 86400 seconds.')),
    cfg.IntOpt('node_history_cleanup_batch_count',
               min=0,
               default=1000,
               mutable=False,
               help=_('The target number of node history records to purge '
                      'from the database when performing clean-up. '
                      'Deletes are performed by node, and a node with excess '
                      'records for a node will still be deleted. '
                      'Defaults to 1000. Operators who find node history '
                      'building up may wish to '
                      'lower this threshold and decrease the time between '
                      'cleanup operations using the '
                      '``node_history_cleanup_interval`` setting.')),
    cfg.IntOpt('node_history_minimum_days',
               min=0,
               default=0,
               mutable=True,
               help=_('The minimum number of days to explicitly keep on '
                      'hand in the database history entries for nodes. '
                      'This is exclusive from the [conductor]'
                      'node_history_max_entries setting as users of '
                      'this setting are anticipated to need to retain '
                      'history by policy.')),
    cfg.MultiOpt('verify_step_priority_override',
                 item_type=types.Dict(),
                 default={},
                 mutable=True,
                 help=_('Priority to run automated verify steps '
                        'provided in interface.step_name:priority format,'
                        'e.g. management.clear_job_queue:123. The option can '
                        'be specified multiple times to define priorities '
                        'for multiple steps. If set to 0, this specific step '
                        'will not run during verification. ')),
    cfg.BoolOpt('automatic_lessee',
                default=False,
                mutable=True,
                help=_('If the conductor should record the Project ID '
                       'indicated by Keystone for a requested deployment. '
                       'Allows rights to be granted to directly access the '
                       'deployed node as a lessee within the RBAC security '
                       'model. The conductor does *not* record this value '
                       'otherwise, and this information is not backfilled '
                       'for prior instances which have been deployed.')),
    cfg.IntOpt('max_concurrent_deploy',
               default=250,
               min=1,
               mutable=True,
               help=_('The maximum number of concurrent nodes in deployment '
                      'which are permitted in this Ironic system. '
                      'If this limit is reached, new requests will be '
                      'rejected until the number of deployments in progress '
                      'is lower than this maximum. As this is a security '
                      'mechanism requests are not queued, and this setting '
                      'is a global setting applying to all requests this '
                      'conductor receives, regardless of access rights. '
                      'The concurrent deployment limit cannot be disabled.')),
    cfg.IntOpt('max_concurrent_clean',
               default=50,
               min=1,
               mutable=True,
               help=_('The maximum number of concurrent nodes in cleaning '
                      'which are permitted in this Ironic system. '
                      'If this limit is reached, new requests will be '
                      'rejected until the number of nodes in cleaning '
                      'is lower than this maximum. As this is a security '
                      'mechanism requests are not queued, and this setting '
                      'is a global setting applying to all requests this '
                      'conductor receives, regardless of access rights. '
                      'The concurrent clean limit cannot be disabled.')),
    cfg.BoolOpt('poweroff_in_cleanfail',
                default=False,
                help=_('If True power off nodes in the ``clean failed`` '
                       'state. Default False. Option may be unsafe '
                       'when using Cleaning to perform '
                       'hardware-transformative actions such as '
                       'firmware upgrade.')),
    cfg.BoolOpt('permit_child_node_step_async_result',
                default=False,
                mutable=True,
                help=_('This option allows child node steps to not error if '
                       'the resulting step execution returned a "wait" '
                       'state. Under normal conditions, child nodes are not '
                       'expected to request a wait state. This option exists '
                       'for operators to use if needed to perform specific '
                       'tasks where this is known acceptable. Use at your'
                       'own risk!')),
    cfg.IntOpt('max_conductor_wait_step_seconds',
               default=30,
               min=0,
               max=1800,
               mutable=True,
               help=_('The maximum number of seconds which a step can '
                      'be requested to explicitly sleep or wait. This '
                      'value should be changed sparingly as it holds a '
                      'conductor thread and if used across many nodes at '
                      'once can exhaust a conductor\'s resources. This'
                      'capability has a hard coded maximum wait of 1800 '
                      'seconds, or 30 minutes. If you need to wait longer '
                      'than the maximum value, we recommend exploring '
                      'hold steps.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='conductor')
