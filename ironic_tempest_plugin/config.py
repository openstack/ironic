# Copyright 2015 NEC Corporation
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

from tempest import config  # noqa


service_option = cfg.BoolOpt('ironic',
                             default=False,
                             help='Whether or not Ironic is expected to be '
                                  'available')


baremetal_group = cfg.OptGroup(name='baremetal',
                               title='Baremetal provisioning service options',
                               help='When enabling baremetal tests, Nova '
                                    'must be configured to use the Ironic '
                                    'driver. The following parameters for the '
                                    '[compute] section must be disabled: '
                                    'console_output, interface_attach, '
                                    'live_migration, pause, rescue, resize, '
                                    'shelve, snapshot, and suspend')

baremetal_features_group = cfg.OptGroup(
    name='baremetal_feature_enabled',
    title="Enabled Baremetal Service Features")

BaremetalGroup = [
    cfg.StrOpt('catalog_type',
               default='baremetal',
               help="Catalog type of the baremetal provisioning service"),
    cfg.StrOpt('driver',
               default='fake',
               help="Driver name which Ironic uses"),
    cfg.StrOpt('endpoint_type',
               default='publicURL',
               choices=['public', 'admin', 'internal',
                        'publicURL', 'adminURL', 'internalURL'],
               help="The endpoint type to use for the baremetal provisioning"
                    " service"),
    cfg.IntOpt('deploywait_timeout',
               default=15,
               help="Timeout for Ironic node to reach the "
                    "wait-callback state after powering on."),
    cfg.IntOpt('active_timeout',
               default=300,
               help="Timeout for Ironic node to completely provision"),
    cfg.IntOpt('association_timeout',
               default=30,
               help="Timeout for association of Nova instance and Ironic "
                    "node"),
    cfg.IntOpt('power_timeout',
               default=60,
               help="Timeout for Ironic power transitions."),
    cfg.IntOpt('unprovision_timeout',
               default=300,
               help="Timeout for unprovisioning an Ironic node. "
                    "Takes longer since Kilo as Ironic performs an extra "
                    "step in Node cleaning."),
    cfg.StrOpt('min_microversion',
               help="Lower version of the test target microversion range. "
                    "The format is 'X.Y', where 'X' and 'Y' are int values. "
                    "Tempest selects tests based on the range between "
                    "min_microversion and max_microversion. "
                    "If both values are None, Tempest avoids tests which "
                    "require a microversion."),
    cfg.StrOpt('max_microversion',
               default='latest',
               help="Upper version of the test target microversion range. "
                    "The format is 'X.Y', where 'X' and 'Y' are int values. "
                    "Tempest selects tests based on the range between "
                    "min_microversion and max_microversion. "
                    "If both values are None, Tempest avoids tests which "
                    "require a microversion."),
    cfg.BoolOpt('use_provision_network',
                default=False,
                help="Whether the Ironic/Neutron tenant isolation is enabled"),
    cfg.StrOpt('whole_disk_image_ref',
               help="UUID of the wholedisk image to use in the tests."),
    cfg.StrOpt('whole_disk_image_url',
               help="An http link to the wholedisk image to use in the "
                    "tests."),
    cfg.StrOpt('whole_disk_image_checksum',
               help="An MD5 checksum of the image."),
    cfg.StrOpt('partition_image_ref',
               help="UUID of the partitioned image to use in the tests."),
    cfg.ListOpt('enabled_drivers',
                default=['fake', 'pxe_ipmitool', 'agent_ipmitool'],
                help="List of Ironic enabled drivers."),
    cfg.ListOpt('enabled_hardware_types',
                default=['ipmi'],
                help="List of Ironic enabled hardware types."),
    cfg.IntOpt('adjusted_root_disk_size_gb',
               min=0,
               help="Ironic adjusted disk size to use in the standalone tests "
                    "as instance_info/root_gb value."),
]

BaremetalFeaturesGroup = [
    cfg.BoolOpt('ipxe_enabled',
                default=True,
                help="Defines if IPXE is enabled"),
]
