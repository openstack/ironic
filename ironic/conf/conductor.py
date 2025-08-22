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

from ironic.common import automated_clean_methods
from ironic.common import boot_modes
from ironic.common.i18n import _
from ironic.common import lessee_sources
from ironic.conf import types as ir_types


opts = [
    cfg.IntOpt('workers_pool_size',
               default=300, min=3,
               help=_('The size of the workers thread pool. '
                      'Note that 2 threads will be reserved by the conductor '
                      'itself for handling heart beats and periodic tasks. '
                      'On top of that, `sync_power_state_workers` will take '
                      'up to 7 threads with the default value of 8.')),
    cfg.IntOpt('reserved_workers_pool_percentage',
               default=5, min=0, max=50,
               help=_('The percentage of the whole workers pool that will be '
                      'kept for API requests and other important tasks. '
                      'This part of the pool will not be used for periodic '
                      'tasks or agent heartbeats. Set to 0 to disable.')),
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
                       'driver\'s documentation for details.')),
    cfg.StrOpt('automated_cleaning_step_source',
               default='autogenerated',
               mutable=True,
               choices=[
                   (automated_clean_methods.AUTOGENERATED, _(
                       'Collects steps from hardware interfaces and orders '
                       'by priority. This provides the original Ironic '
                       'cleaning behavior originally implemented in Kilo.')),
                   (automated_clean_methods.RUNBOOK, _(
                       'Runs cleaning via a runbook specified in '
                       'configuration or node driver_info. If a runbook '
                       'is not specified while automated_clean is enabled, '
                       'cleaning will fail.')),
                   (automated_clean_methods.HYBRID, _(
                       'Runs cleaning via a runbook if one is specified in '
                       'configuration or node driver_info. If a runbook '
                       'is not specified while automated_clean is enabled, '
                       'Ironic will fallback to \'autogenerated\' '
                       'cleaning steps.'))
               ],
               help=_('Determines how automated_cleaning is performed; the '
                      'default, \'autogenerated\' collects steps from '
                      'hardware interfaces, then ordering by priority; '
                      '\'runbook\' requires a runbook to be specified in '
                      'config or driver_info, which is then used to clean the'
                      'node; \'hybrid\' uses a runbook if available, '
                      'and falls-back to autogenerated cleaning steps if not.'
                      )),
    cfg.StrOpt('automated_cleaning_runbook',
               default=None,
               mutable=True,
               help=_('If set and [conductor]/automated_clean_step_source '
                      'is set to \'hybrid\' or \'runbook\', the runbook '
                      'UUID or name provided here will be used during '
                      'automated_cleaning for nodes which do not have a '
                      'resource_class-specific runbook or runbook set in '
                      'driver_info.')),
    cfg.DictOpt('automated_cleaning_runbook_by_resource_class',
                default={},
                mutable=True,
                help=_('A dictionary of key-value pairs of node '
                       'resource_class and runbook UUID or name which will be '
                       'used to clean the node if '
                       '[conductor]automated_clean_step_source is set to '
                       '\'hybrid\' or \'runbook\' and a more specific runbook '
                       'has not been configured in driver_info.')),
    cfg.BoolOpt('automated_cleaning_runbook_from_node',
                default=False,
                mutable=True,
                help=_('When enabled, allows an administrator to configure '
                       'a runbook in '
                       'node[\'driver_info\'][\'cleaning_runbook\'] to '
                       'use for that node when '
                       '[conductor]automated_clean_step_source is set to '
                       '\'hybrid\' or \'runbook\'. '
                       'NOTE: This will permit any user with access to edit '
                       'node[\'driver_info\'] to circumvent cleaning.')),
    cfg.BoolOpt('automated_cleaning_runbook_validate_traits',
                default=True,
                mutable=True,
                help=_('When enabled, this option requires validation of a '
                       'runbook before it\'s used for automated cleaning. '
                       'Nodes configured with a runbook that is not validated '
                       'for use via trait matching will fail to clean.')),
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
    cfg.IntOpt('service_callback_timeout',
               default=1800,
               min=0,
               help=_('Timeout (seconds) to wait for a callback from the '
                      'ramdisk doing the servicing. If the timeout is reached '
                      'the node will be put in the "service failed" provision '
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
               help=_('Glance ID, http:// or file:// URL of the '
                      'kernel of the default deploy image.')),
    cfg.StrOpt('deploy_ramdisk',
               mutable=True,
               help=_('Glance ID, http:// or file:// URL of the '
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
               help=_('Glance ID, http:// or file:// URL of the '
                      'kernel of the default rescue image.')),
    cfg.StrOpt('rescue_ramdisk',
               mutable=True,
               help=_('Glance ID, http:// or file:// URL of the '
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
                default=True,
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
                      'partition images. Can be overridden per-architecture '
                      'using the bootloader_by_arch option.')),
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
    cfg.IntOpt('conductor_cleanup_interval',
               min=0,
               default=86400,
               mutable=False,
               help=_('Interval in seconds at which stale conductor entries '
                      'can be cleaned up from the database. Setting to 0 '
                      'disables the periodic task. Defaults to 86400 (1 day).'
                      )),
    cfg.IntOpt('conductor_cleanup_timeout',
               min=60,
               default=1209600,
               mutable=True,
               help=_('Timeout in seconds after which offline conductors '
                      'are considered stale and can be cleaned up from the '
                      'database. It defaults to two weeks (1209600 seconds) '
                      'and is always required to be at least 3x larger than '
                      '[conductor]heartbeat_timeout since if otherwise, '
                      'active conductors might be mistakenly removed from '
                      'the database.')),
    cfg.IntOpt('conductor_cleanup_batch_size',
               min=1,
               default=50,
               mutable=True,
               help=_('The maximum number of stale conductor records to clean '
                      'up from the database in a single cleanup operation. '
                      'Defaults to 50.')),
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
                default=True,
                mutable=True,
                help=_('Deprecated. If Ironic should set the node.lessee '
                       'field at deployment. Use '
                       '[\'conductor\']/automatic_lessee_source instead.'),
                deprecated_for_removal=True),
    cfg.StrOpt('automatic_lessee_source',
               help=_('Source for Project ID the Ironic should '
                      'record at deployment time in node.lessee field. If set '
                      'to none, Ironic will not set a lessee field. '
                      'If set to instance (default), uses Project ID '
                      'indicated in instance metadata set by Nova or '
                      'another external deployment service. '
                      'If set to keystone, Ironic uses Project ID indicated '
                      'by Keystone context. '),
               choices=[
                   (lessee_sources.INSTANCE, _(  # 'instance'
                    'Populates node.lessee field using metadata from '
                    'node.instance_info[\'project_id\'] at deployment '
                    'time. Useful for Nova-fronted deployments.')),
                   (lessee_sources.REQUEST, _(  # 'request'
                    'Populates node.lessee field using metadata '
                    'from request context. Only useful for direct '
                    'deployment requests to Ironic; not those proxied '
                    'via an external service like Nova.')),
                   (lessee_sources.NONE, _(  # 'none'
                    'Ironic will not populate the node.lessee field.'))
               ],
               default='instance',
               mutable=True),
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
    cfg.BoolOpt('poweroff_in_servicefail',
                default=False,
                help=_('If True power off nodes in the ``service failed`` '
                       'state. Default False. Option may be unsafe '
                       'when using service to perform '
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
    cfg.ListOpt('disallowed_deployment_boot_modes',
                item_type=types.String(
                    choices=[
                        (boot_modes.UEFI, _('UEFI boot mode')),
                        (boot_modes.LEGACY_BIOS, _('Legacy BIOS boot mode'))],
                ),
                default=[],
                mutable=True,
                help=_("Specifies a list of boot modes that are not allowed "
                       "during deployment. Eg: ['bios']")),
    cfg.BoolOpt('disable_deep_image_inspection',
                default=False,
                # Normally such an option would be mutable, but this is,
                # a security guard and operators should not expect to change
                # this option under normal circumstances.
                mutable=False,
                help=_('Security Option to permit an operator to disable '
                       'file content inspections. Under normal conditions, '
                       'the conductor will inspect requested image contents '
                       'which are transferred through the conductor. '
                       'Disabling this option is not advisable and opens '
                       'the risk of unsafe images being processed which may '
                       'allow an attacker to leverage unsafe features in '
                       'various disk image formats to perform a variety of '
                       'unsafe and potentially compromising actions. '
                       'This option is *not* mutable, and '
                       'requires a service restart to change.')),
    cfg.BoolOpt('conductor_always_validates_images',
                default=False,
                # Normally mutable, however from a security context we do want
                # all logging to be generated from this option to be changed,
                # and as such is set to False to force a conductor restart.
                mutable=False,
                help=_('Security Option to enable the conductor to *always* '
                       'inspect the image content of any requested deploy, '
                       'even if the deployment would have normally bypassed '
                       'the conductor\'s cache. When this is set to False, '
                       'the Ironic-Python-Agent is responsible '
                       'for any necessary image checks. Setting this to '
                       'True will result in a higher utilization of '
                       'resources (disk space, network traffic) '
                       'as the conductor will evaluate *all* images. '
                       'This option is *not* mutable, and requires a '
                       'service restart to change. This option requires '
                       '[conductor]disable_deep_image_inspection to be set '
                       'to False.')),
    cfg.ListOpt('permitted_image_formats',
                default=['raw', 'gpt', 'qcow2', 'iso'],
                mutable=True,
                help=_('The supported list of image formats which are '
                       'permitted for deployment with Ironic. If an image '
                       'format outside of this list is detected, the image '
                       'validation logic will fail the deployment process.')),
    cfg.BoolOpt('disable_file_checksum',
                default=False,
                mutable=False,
                help=_('Deprecated Security option: In the default case, '
                       'image files have their checksums verified before '
                       'undergoing additional conductor side actions such '
                       'as image conversion. '
                       'Enabling this option opens the risk of files being '
                       'replaced at the source without the user\'s '
                       'knowledge.'),
                deprecated_for_removal=True),
    cfg.BoolOpt('disable_support_for_checksum_files',
                default=False,
                mutable=False,
                help=_('Security option: By default Ironic will attempt to '
                       'retrieve a remote checksum file via HTTP(S) URL in '
                       'order to validate an image download. This is '
                       'functionality aligning with ironic-python-agent '
                       'support for standalone users. Disabling this '
                       'functionality by setting this option to True will '
                       'create a more secure environment, however it may '
                       'break users in an unexpected fashion.')),
    cfg.BoolOpt('disable_zstandard_decompression',
                default=False,
                mutable=False,
                help=_('Option to enable disabling transparent decompression '
                       'of files which are compressed with Zstandard '
                       'compression. This option is provided should operators '
                       'wish to disable this functionality, otherwise it is '
                       'automatically applied by the conductor should a '
                       'compressed artifact be detected.')),
    cfg.ListOpt('file_url_allowed_paths',
                default=['/var/lib/ironic', '/shared/html', '/templates',
                         '/opt/cache/files', '/vagrant'],
                item_type=ir_types.ExplicitAbsolutePath(),
                help=_(
                    'List of paths that are allowed to be used as file:// '
                    'URLs. Files in /boot, /dev, /etc, /proc, /sys and other'
                    'system paths are always disallowed for security reasons. '
                    'Any files in this path readable by ironic may be used as '
                    'an image source when deploying. Setting this value to '
                    '"" (empty) disables file:// URL support. Paths listed '
                    'here are validated as absolute paths and will be rejected'
                    'if they contain path traversal mechanisms, such as "..".'
                )),
    cfg.IntOpt('graceful_shutdown_timeout',
               deprecated_group='DEFAULT',
               deprecated_reason=_(
                   'This replaces oslo.service '
                   '[DEFAULT]/graceful_shutdown_timeout option.'),
               default=60,
               help='Specify a timeout after which a gracefully shutdown '
                    'conductor will exit. Zero value means endless wait.'),
    cfg.DictOpt('bootloader_by_arch',
                default={},
                help=_(
                    'Bootloader ESP image parameter per node architecture. '
                    'For example: x86_64:bootx64.efi,aarch64:grubaa64.efi. '
                    'A node\'s cpu_arch property is used as the key to get '
                    'the appropriate bootloader ESP image. If the node\'s '
                    'cpu_arch is not in the dictionary, '
                    'the [conductor]bootloader value will be used instead.'
                )),
    cfg.BoolOpt('disable_configdrive_check',
                default=False,
                mutable=True,
                help=_('Option to disable operations which check and '
                       'potentially fix up configuration drive contents, '
                       'such as invalid network metadata values. When these '
                       'issues are detected, and Ironic is able to correct '
                       'the data, Ironic will do so transparently. Setting '
                       'this option to True will disable this '
                       'functionality.')),
    cfg.BoolOpt('disable_metadata_mtu_check',
                default=False,
                mutable=True,
                help=_('Option to disable consideration of supplied '
                       'network_data.json link MTU values as basis to '
                       'regenerate the supplied metadata.')),
    cfg.BoolOpt('error_on_ramdisk_config_inconsistency',
                default=False,
                mutable=True,
                help=_('Option to determine if Ironic should fail to boot '
                       'ramdisk in situations where configuration is '
                       'ambiguous.e.g. if node[driver_info] contains an '
                       'override for deploy_ramdisk but not deploy_kernel '
                       'when ambiguous. When set to True, Ironic will raise '
                       'and fail the provisioning action that required a '
                       'ramdisk and kernel. When set to False, Ironic will '
                       'fallback to the next valid, consistent configured '
                       'ramdisk and kernel for the node.')),
    cfg.BoolOpt(
        "record_step_flows_in_history",
        default=True,
        help=(
            "When True, the conductor writes a Node History entry at the "
            "start and end of every cleaning/servicing/deploy-steps flow. "
            "Disable this in very high-churn environments to reduce DB load."
        )),
    cfg.BoolOpt(
        'log_step_flows_to_syslog',
        default=False,
        help=(
            "Log steps at the start/end of cleaning/servicing/deployment "
            "to the conductor service log (WARNING for aborted/failure, "
            "INFO otherwise.")),
]


def register_opts(conf):
    conf.register_opts(opts, group='conductor')
