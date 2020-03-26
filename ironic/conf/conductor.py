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
    cfg.URIOpt('api_url',
               schemes=('http', 'https'),
               deprecated_for_removal=True,
               deprecated_reason=_("Use [service_catalog]endpoint_override "
                                   "option instead if required to use "
                                   "a specific ironic api address, "
                                   "for example in noauth mode."),
               help=_('URL of Ironic API service. If not set ironic can '
                      'get the current value from the keystone service '
                      'catalog. If set, the value must start with either '
                      'http:// or https://.')),
    cfg.IntOpt('heartbeat_timeout',
               default=60,
               # We're using timedelta which can overflow if somebody sets this
               # too high, so limit to a sane value of 10 years.
               max=315576000,
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
    cfg.IntOpt('deploy_callback_timeout',
               default=1800,
               help=_('Timeout (seconds) to wait for a callback from '
                      'a deploy ramdisk. Set to 0 to disable timeout.')),
    cfg.BoolOpt('force_power_state_during_sync',
                default=True,
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
    cfg.BoolOpt('send_sensor_data',
                default=False,
                help=_('Enable sending sensor data message via the '
                       'notification bus')),
    cfg.IntOpt('send_sensor_data_interval',
               default=600,
               min=1,
               help=_('Seconds between conductor sending sensor data message '
                      'to ceilometer via the notification bus.')),
    cfg.IntOpt('send_sensor_data_workers',
               default=4, min=1,
               help=_('The maximum number of workers that can be started '
                      'simultaneously for send data from sensors periodic '
                      'task.')),
    cfg.IntOpt('send_sensor_data_wait_timeout',
               default=300,
               help=_('The time in seconds to wait for send sensors data '
                      'periodic task to be finished before allowing periodic '
                      'call to happen again. Should be less than '
                      'send_sensor_data_interval value.')),
    cfg.ListOpt('send_sensor_data_types',
                default=['ALL'],
                help=_('List of comma separated meter types which need to be'
                       ' sent to Ceilometer. The default value, "ALL", is a '
                       'special value meaning send all the sensor data.')),
    cfg.BoolOpt('send_sensor_data_for_undeployed_nodes',
                default=False,
                help=_('The default for sensor data collection is to only '
                       'collect data for machines that are deployed, however '
                       'operators may desire to know if there are failures '
                       'in hardware that is not presently in use. '
                       'When set to true, the conductor will collect sensor '
                       'information from all nodes when sensor data '
                       'collection is enabled via the send_sensor_data '
                       'setting.')),
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
               help=_('Timeout (seconds) for waiting for node inspection. '
                      '0 - unlimited.')),
    cfg.BoolOpt('automated_clean',
                default=True,
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
               help=_('Timeout (in seconds) of soft reboot and soft power '
                      'off operation. This value always has to be positive.')),
    cfg.IntOpt('power_state_change_timeout',
               min=2, default=60,
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
               help=_('Glance ID, http:// or file:// URL of the kernel of '
                      'the default deploy image.')),
    cfg.StrOpt('deploy_ramdisk',
               mutable=True,
               help=_('Glance ID, http:// or file:// URL of the initramfs of '
                      'the default deploy image.')),
    cfg.StrOpt('rescue_kernel',
               mutable=True,
               help=_('Glance ID, http:// or file:// URL of the kernel of '
                      'the default rescue image.')),
    cfg.StrOpt('rescue_ramdisk',
               mutable=True,
               help=_('Glance ID, http:// or file:// URL of the initramfs of '
                      'the default rescue image.')),
    cfg.StrOpt('rescue_password_hash_algorithm',
               default='sha256',
               choices=['sha256', 'sha512'],
               help=_('Password hash algorithm to be used for the rescue '
                      'password.')),
    cfg.BoolOpt('require_rescue_password_hashed',
                # TODO(TheJulia): Change this to True in Victoria.
                default=False,
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
]


def register_opts(conf):
    conf.register_opts(opts, group='conductor')
