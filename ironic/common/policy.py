# Copyright (c) 2011 OpenStack Foundation
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

"""Policy Engine For Ironic."""

import itertools
import sys

from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log
from oslo_log import versionutils
from oslo_policy import opts
from oslo_policy import policy

from ironic.common import exception

_ENFORCER = None
CONF = cfg.CONF
LOG = log.getLogger(__name__)


# TODO(gmann): Remove setting the default value of config policy_file
# once oslo_policy change the default value to 'policy.yaml'.
# https://github.com/openstack/oslo.policy/blob/a626ad12fe5a3abd49d70e3e5b95589d279ab578/oslo_policy/opts.py#L49
DEFAULT_POLICY_FILE = 'policy.yaml'
opts.set_defaults(cfg.CONF, DEFAULT_POLICY_FILE)

# Generic policy check string for system administrators. These are the people
# who need the highest level of authorization to operate the deployment.
# They're allowed to create, read, update, or delete any system-specific
# resource. They can also operate on project-specific resources where
# applicable (e.g., cleaning up baremetal hosts)
SYSTEM_ADMIN = 'role:admin and system_scope:all'

# Generic policy check string for system users who don't require all the
# authorization that system administrators typically have. This persona, or
# check string, typically isn't used by default, but it's existence it useful
# in the event a deployment wants to offload some administrative action from
# system administrator to system members
SYSTEM_MEMBER = 'role:member and system_scope:all'

# Generic policy check string for read-only access to system-level resources.
# This persona is useful for someone who needs access for auditing or even
# support. These uses are also able to view project-specific resources where
# applicable (e.g., listing all volumes in the deployment, regardless of the
# project they belong to).
SYSTEM_READER = 'role:reader and system_scope:all'

# This check string is reserved for actions that require the highest level of
# authorization on a project or resources within the project (e.g., setting the
# default volume type for a project)
PROJECT_ADMIN = ('role:admin and '
                 'project_id:%(node.owner)s')
# This check string is the primary use case for typical end-users, who are
# working with resources that belong to a project (e.g., creating volumes and
# backups).
PROJECT_MEMBER = ('role:member and '
                  '(project_id:%(node.owner)s or project_id:%(node.lessee)s)')

# This check string should only be used to protect read-only project-specific
# resources. It should not be used to protect APIs that make writable changes
# (e.g., updating a volume or deleting a backup).
PROJECT_READER = ('role:reader and '
                  '(project_id:%(node.owner)s or project_id:%(node.lessee)s)')

# The following are common composite check strings that are useful for
# protecting APIs designed to operate with multiple scopes (e.g., a system
# administrator should be able to delete any baremetal host in the deployment,
# a project member should only be able to delete hosts in their project).
SYSTEM_OR_PROJECT_MEMBER = (
    '(' + SYSTEM_MEMBER + ') or (' + PROJECT_MEMBER + ')'
)
SYSTEM_OR_PROJECT_READER = (
    '(' + SYSTEM_READER + ') or (' + PROJECT_READER + ')'
)

PROJECT_OWNER_ADMIN = ('role:admin and project_id:%(node.owner)s')
PROJECT_OWNER_MEMBER = ('role:member and project_id:%(node.owner)s')
PROJECT_OWNER_READER = ('role:reader and project_id:%(node.owner)s')
PROJECT_LESSEE_ADMIN = ('role:admin and project_id:%(node.lessee)s')

SYSTEM_OR_OWNER_MEMBER_AND_LESSEE_ADMIN = (
    '(' + SYSTEM_MEMBER + ') or (' + PROJECT_OWNER_MEMBER + ') or (' + PROJECT_LESSEE_ADMIN + ')'  # noqa
)

SYSTEM_MEMBER_OR_OWNER_ADMIN = (
    '(' + SYSTEM_MEMBER + ') or (' + PROJECT_OWNER_ADMIN + ')'
)

SYSTEM_MEMBER_OR_OWNER_MEMBER = (
    '(' + SYSTEM_MEMBER + ') or (' + PROJECT_OWNER_MEMBER + ')'
)

SYSTEM_OR_OWNER_READER = (
    '(' + SYSTEM_READER + ') or (' + PROJECT_OWNER_READER + ')'
)

API_READER = ('role:reader')

default_policies = [
    # Legacy setting, don't remove. Likely to be overridden by operators who
    # forget to update their policy.json configuration file.
    # This gets rolled into the new "is_admin" rule below.
    policy.RuleDefault('admin_api',
                       'role:admin or role:administrator',
                       description='Legacy rule for cloud admin access'),
    # is_public_api is set in the environment from AuthPublicRoutes
    # TODO(TheJulia): Once legacy policy rules are removed, is_public_api
    # can be removed from the code base.
    policy.RuleDefault('public_api',
                       'is_public_api:True',
                       description='Internal flag for public API routes'),
    # Generic default to hide passwords in node driver_info
    # NOTE(tenbrae): the 'show_password' policy setting hides secrets in
    #             driver_info. However, the name exists for legacy
    #             purposes and can not be changed. Changing it will cause
    #             upgrade problems for any operators who have customized
    #             the value of this field
    policy.RuleDefault('show_password',
                       '!',
                       description='Show or mask secrets within node driver information in API responses'),  # noqa
    # Generic default to hide instance secrets
    policy.RuleDefault('show_instance_secrets',
                       '!',
                       description='Show or mask secrets within instance information in API responses'),  # noqa
    # Roles likely to be overridden by operator
    # TODO(TheJulia): Lets nuke demo from high orbit.
    policy.RuleDefault('is_member',
                       '(project_domain_id:default or project_domain_id:None) and (project_name:demo or project_name:baremetal)',  # noqa
                       description='May be used to restrict access to specific projects'),  # noqa
    policy.RuleDefault('is_observer',
                       'rule:is_member and (role:observer or role:baremetal_observer)',  # noqa
                       description='Read-only API access'),
    policy.RuleDefault('is_admin',
                       'rule:admin_api or (rule:is_member and role:baremetal_admin)',  # noqa
                       description='Full read/write API access'),
    policy.RuleDefault('is_node_owner',
                       'project_id:%(node.owner)s',
                       description='Owner of node'),
    policy.RuleDefault('is_node_lessee',
                       'project_id:%(node.lessee)s',
                       description='Lessee of node'),
    policy.RuleDefault('is_allocation_owner',
                       'project_id:%(allocation.owner)s',
                       description='Owner of allocation'),
]

# NOTE(tenbrae): to follow policy-in-code spec, we define defaults for
#             the granular policies in code, rather than in policy.json.
#             All of these may be overridden by configuration, but we can
#             depend on their existence throughout the code.

deprecated_node_create = policy.DeprecatedRule(
    name='baremetal:node:create',
    check_str='rule:is_admin'
)
deprecated_node_get = policy.DeprecatedRule(
    name='baremetal:node:get',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_node_list = policy.DeprecatedRule(
    name='baremetal:node:list',
    check_str='rule:baremetal:node:get'
)
deprecated_node_list_all = policy.DeprecatedRule(
    name='baremetal:node:list_all',
    check_str='rule:baremetal:node:get'
)
deprecated_node_update = policy.DeprecatedRule(
    name='baremetal:node:update',
    check_str='rule:is_admin'
)
deprecated_node_update_extra = policy.DeprecatedRule(
    name='baremetal:node:update_extra',
    check_str='rule:baremetal:node:update'
)
deprecated_node_update_instance_info = policy.DeprecatedRule(
    name='baremetal:node:update_instance_info',
    check_str='rule:baremetal:node:update'
)
deprecated_node_update_owner_provisioned = policy.DeprecatedRule(
    name='baremetal:node:update_owner_provisioned',
    check_str='rule:is_admin'
)
deprecated_node_delete = policy.DeprecatedRule(
    name='baremetal:node:delete',
    check_str='rule:is_admin'
)
deprecated_node_validate = policy.DeprecatedRule(
    name='baremetal:node:validate',
    check_str='rule:is_admin'
)
deprecated_node_set_maintenance = policy.DeprecatedRule(
    name='baremetal:node:set_maintenance',
    check_str='rule:is_admin'
)
deprecated_node_clear_maintenance = policy.DeprecatedRule(
    name='baremetal:node:clear_maintenance',
    check_str='rule:is_admin'
)
deprecated_node_get_boot_device = policy.DeprecatedRule(
    name='baremetal:node:get_boot_device',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_node_set_boot_device = policy.DeprecatedRule(
    name='baremetal:node:set_boot_device',
    check_str='rule:is_admin'
)
deprecated_node_get_indicator_state = policy.DeprecatedRule(
    name='baremetal:node:get_indicator_state',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_node_set_indicator_state = policy.DeprecatedRule(
    name='baremetal:node:set_indicator_state',
    check_str='rule:is_admin'
)
deprecated_node_inject_nmi = policy.DeprecatedRule(
    name='baremetal:node:inject_nmi',
    check_str='rule:is_admin'
)
deprecated_node_get_states = policy.DeprecatedRule(
    name='baremetal:node:get_states',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_node_set_power_state = policy.DeprecatedRule(
    name='baremetal:node:set_power_state',
    check_str='rule:is_admin'
)
deprecated_node_set_provision_state = policy.DeprecatedRule(
    name='baremetal:node:set_provision_state',
    check_str='rule:is_admin'
)
deprecated_node_set_raid_state = policy.DeprecatedRule(
    name='baremetal:node:set_raid_state',
    check_str='rule:is_admin'
)
deprecated_node_get_console = policy.DeprecatedRule(
    name='baremetal:node:get_console',
    check_str='rule:is_admin'
)
deprecated_node_set_console_state = policy.DeprecatedRule(
    name='baremetal:node:set_console_state',
    check_str='rule:is_admin'
)
deprecated_node_vif_list = policy.DeprecatedRule(
    name='baremetal:node:vif:list',
    check_str='rule:is_admin'
)
deprecated_node_vif_attach = policy.DeprecatedRule(
    name='baremetal:node:vif:attach',
    check_str='rule:is_admin'
)
deprecated_node_vif_detach = policy.DeprecatedRule(
    name='baremetal:node:vif:detach',
    check_str='rule:is_admin'
)
deprecated_node_traits_list = policy.DeprecatedRule(
    name='baremetal:node:traits:list',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_node_traits_set = policy.DeprecatedRule(
    name='baremetal:node:traits:set',
    check_str='rule:is_admin'
)
deprecated_node_traits_delete = policy.DeprecatedRule(
    name='baremetal:node:traits:delete',
    check_str='rule:is_admin'
)
deprecated_node_bios_get = policy.DeprecatedRule(
    name='baremetal:node:bios:get',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_bios_disable_cleaning = policy.DeprecatedRule(
    name='baremetal:node:disable_cleaning',
    check_str='rule:baremetal:node:update',
)
deprecated_node_reason = """
The baremetal node API is now aware of system scope and default roles.
Capability to fallback to legacy admin project policy configuration
will be removed in the Xena release of Ironic.
"""


node_policies = [
    policy.DocumentedRuleDefault(
        name='baremetal:node:create',
        check_str=SYSTEM_ADMIN,
        scope_types=['system'],
        description='Create Node records',
        operations=[{'path': '/nodes', 'method': 'POST'}],
        deprecated_rule=deprecated_node_create,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:list',
        check_str=API_READER,
        scope_types=['system', 'project'],
        description='Retrieve multiple Node records, filtered by '
                    'an explicit owner or the client project_id',
        operations=[{'path': '/nodes', 'method': 'GET'},
                    {'path': '/nodes/detail', 'method': 'GET'}],
        deprecated_rule=deprecated_node_list,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:list_all',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='Retrieve multiple Node records',
        operations=[{'path': '/nodes', 'method': 'GET'},
                    {'path': '/nodes/detail', 'method': 'GET'}],
        deprecated_rule=deprecated_node_list_all,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:get',
        check_str=SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Retrieve a single Node record',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'GET'}],
        deprecated_rule=deprecated_node_get,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:get:filter_threshold',
        check_str=SYSTEM_READER,
        scope_types=['system', 'project'],
        description='Filter to allow operators to govern the threshold '
                    'where information should be filtered. Non-authorized '
                    'users will be subjected to additional API policy '
                    'checks for API content response bodies.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'GET'}],
        # This rule fallsback to deprecated_node_get in order to provide a
        # mechanism so the additional policies only engage in an updated
        # operating context.
        deprecated_rule=deprecated_node_get,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY,
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:get:last_error',
        check_str=SYSTEM_OR_OWNER_READER,
        scope_types=['system', 'project'],
        description='Governs if the node last_error field is masked from API'
                    'clients with insufficent privileges.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'GET'}],
        deprecated_rule=deprecated_node_get,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:get:reservation',
        check_str=SYSTEM_OR_OWNER_READER,
        scope_types=['system', 'project'],
        description='Governs if the node reservation field is masked from API'
                    'clients with insufficent privileges.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'GET'}],
        deprecated_rule=deprecated_node_get,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:get:driver_internal_info',
        check_str=SYSTEM_OR_OWNER_READER,
        scope_types=['system', 'project'],
        description='Governs if the node driver_internal_info field is '
                    'masked from API clients with insufficent privileges.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'GET'}],
        deprecated_rule=deprecated_node_get,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:get:driver_info',
        check_str=SYSTEM_OR_OWNER_READER,
        scope_types=['system', 'project'],
        description='Governs if the driver_info field is masked from API'
                    'clients with insufficent privileges.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'GET'}],
        deprecated_rule=deprecated_node_get,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:update:driver_info',
        check_str=SYSTEM_MEMBER_OR_OWNER_MEMBER,
        scope_types=['system', 'project'],
        description='Governs if node driver_info field can be updated via '
                    'the API clients.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:update:properties',
        check_str=SYSTEM_MEMBER_OR_OWNER_MEMBER,
        scope_types=['system', 'project'],
        description='Governs if node properties field can be updated via '
                    'the API clients.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:update:chassis_uuid',
        check_str=SYSTEM_ADMIN,
        scope_types=['system', 'project'],
        description='Governs if node chassis_uuid field can be updated via '
                    'the API clients.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:update:instance_uuid',
        check_str=SYSTEM_MEMBER_OR_OWNER_MEMBER,
        scope_types=['system', 'project'],
        description='Governs if node instance_uuid field can be updated via '
                    'the API clients.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:update:lessee',
        check_str=SYSTEM_MEMBER_OR_OWNER_MEMBER,
        scope_types=['system', 'project'],
        description='Governs if node lessee field can be updated via '
                    'the API clients.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:update:owner',
        check_str=SYSTEM_MEMBER,
        scope_types=['system', 'project'],
        description='Governs if node owner field can be updated via '
                    'the API clients.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:update:driver_interfaces',
        check_str=SYSTEM_MEMBER_OR_OWNER_ADMIN,
        scope_types=['system', 'project'],
        description='Governs if node driver and driver interfaces field '
                    'can be updated via the API clients.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:update:network_data',
        check_str=SYSTEM_MEMBER_OR_OWNER_MEMBER,
        scope_types=['system', 'project'],
        description='Governs if node driver_info field can be updated via '
                    'the API clients.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:update:conductor_group',
        check_str=SYSTEM_MEMBER,
        scope_types=['system', 'project'],
        description='Governs if node conductor_group field can be updated '
                    'via the API clients.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:update:name',
        check_str=SYSTEM_MEMBER_OR_OWNER_MEMBER,
        scope_types=['system', 'project'],
        description='Governs if node name field can be updated via '
                    'the API clients.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:update:retired',
        check_str=SYSTEM_MEMBER_OR_OWNER_MEMBER,
        scope_types=['system', 'project'],
        description='Governs if node retired and retired reason '
                    'can be updated by API clients.',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),

    # If this role is denied we should likely roll into the other rules
    # Like, this rule could match "SYSTEM_MEMBER" by default and then drill
    # further into each field, which would maintain what we do today, and
    # enable further testing.
    policy.DocumentedRuleDefault(
        name='baremetal:node:update',
        check_str=SYSTEM_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Generalized update of node records',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:update_extra',
        check_str=SYSTEM_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Update Node extra field',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update_extra,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    # TODO(TheJulia): So multiple additional fields need policies. This needs
    # to be reviewed/audited/addressed.
    # * Get ability on last_error - policy added
    # * Get ability on reservation (conductor names) - policy added
    # * get ability on driver_internal_info (internal addressing) added
    # * ability to get driver_info - policy added
    # * ability to set driver_info - policy added
    # * ability to set properties. - added
    # * ability to set chassis_uuid - added
    # * ability to set instance_uuid - added
    # * ability to set a lessee - default only to admin or owner. added
    # * ability to set driver/*_interface - added
    # * ability to set network_data - added
    # * ability to set conductor_group -added
    # * ability to set name -added
    policy.DocumentedRuleDefault(
        name='baremetal:node:update_instance_info',
        check_str=SYSTEM_OR_OWNER_MEMBER_AND_LESSEE_ADMIN,
        scope_types=['system', 'project'],
        description='Update Node instance_info field',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update_instance_info,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:update_owner_provisioned',
        check_str=SYSTEM_MEMBER,
        scope_types=['system'],
        description='Update Node owner even when Node is provisioned',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_node_update_owner_provisioned,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:delete',
        check_str=SYSTEM_ADMIN,
        scope_types=['system', 'project'],
        description='Delete Node records',
        operations=[{'path': '/nodes/{node_ident}', 'method': 'DELETE'}],
        deprecated_rule=deprecated_node_delete,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),

    policy.DocumentedRuleDefault(
        name='baremetal:node:validate',
        check_str=SYSTEM_OR_OWNER_MEMBER_AND_LESSEE_ADMIN,
        scope_types=['system', 'project'],
        description='Request active validation of Nodes',
        operations=[
            {'path': '/nodes/{node_ident}/validate', 'method': 'GET'}
        ],
        deprecated_rule=deprecated_node_validate,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),

    policy.DocumentedRuleDefault(
        name='baremetal:node:set_maintenance',
        check_str=SYSTEM_OR_OWNER_MEMBER_AND_LESSEE_ADMIN,
        scope_types=['system', 'project'],
        description='Set maintenance flag, taking a Node out of service',
        operations=[
            {'path': '/nodes/{node_ident}/maintenance', 'method': 'PUT'}
        ],
        deprecated_rule=deprecated_node_set_maintenance,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:clear_maintenance',
        check_str=SYSTEM_OR_OWNER_MEMBER_AND_LESSEE_ADMIN,
        scope_types=['system', 'project'],
        description=(
            'Clear maintenance flag, placing the Node into service again'
        ),
        operations=[
            {'path': '/nodes/{node_ident}/maintenance', 'method': 'DELETE'}
        ],
        deprecated_rule=deprecated_node_clear_maintenance,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),

    # NOTE(TheJulia): This should liekly be deprecated and be replaced with
    # a cached object.
    policy.DocumentedRuleDefault(
        name='baremetal:node:get_boot_device',
        check_str=SYSTEM_MEMBER_OR_OWNER_ADMIN,
        scope_types=['system', 'project'],
        description='Retrieve Node boot device metadata',
        operations=[
            {'path': '/nodes/{node_ident}/management/boot_device',
             'method': 'GET'},
            {'path': '/nodes/{node_ident}/management/boot_device/supported',
             'method': 'GET'}
        ],
        deprecated_rule=deprecated_node_get_boot_device,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:set_boot_device',
        check_str=SYSTEM_MEMBER_OR_OWNER_ADMIN,
        scope_types=['system', 'project'],
        description='Change Node boot device',
        operations=[
            {'path': '/nodes/{node_ident}/management/boot_device',
             'method': 'PUT'}
        ],
        deprecated_rule=deprecated_node_set_maintenance,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),

    policy.DocumentedRuleDefault(
        name='baremetal:node:get_indicator_state',
        check_str=SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Retrieve Node indicators and their states',
        operations=[
            {'path': '/nodes/{node_ident}/management/indicators/'
                     '{component}/{indicator}',
             'method': 'GET'},
            {'path': '/nodes/{node_ident}/management/indicators',
             'method': 'GET'}
        ],
        deprecated_rule=deprecated_node_get_indicator_state,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:set_indicator_state',
        check_str=SYSTEM_MEMBER_OR_OWNER_MEMBER,
        scope_types=['system', 'project'],
        description='Change Node indicator state',
        operations=[
            {'path': '/nodes/{node_ident}/management/indicators/'
                     '{component}/{indicator}',
             'method': 'PUT'}
        ],
        deprecated_rule=deprecated_node_set_indicator_state,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),

    policy.DocumentedRuleDefault(
        name='baremetal:node:inject_nmi',
        check_str=SYSTEM_MEMBER_OR_OWNER_ADMIN,
        scope_types=['system', 'project'],
        description='Inject NMI for a node',
        operations=[
            {'path': '/nodes/{node_ident}/management/inject_nmi',
             'method': 'PUT'}
        ],
        deprecated_rule=deprecated_node_inject_nmi,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),

    policy.DocumentedRuleDefault(
        name='baremetal:node:get_states',
        check_str=SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='View Node power and provision state',
        operations=[{'path': '/nodes/{node_ident}/states', 'method': 'GET'}],
        deprecated_rule=deprecated_node_get_states,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:set_power_state',
        check_str=SYSTEM_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Change Node power status',
        operations=[
            {'path': '/nodes/{node_ident}/states/power', 'method': 'PUT'}
        ],
        deprecated_rule=deprecated_node_set_power_state,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:set_provision_state',
        check_str=SYSTEM_OR_OWNER_MEMBER_AND_LESSEE_ADMIN,
        scope_types=['system', 'project'],
        description='Change Node provision status',
        operations=[
            {'path': '/nodes/{node_ident}/states/provision', 'method': 'PUT'}
        ],
        deprecated_rule=deprecated_node_set_provision_state,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:set_raid_state',
        check_str=SYSTEM_MEMBER_OR_OWNER_MEMBER,
        scope_types=['system', 'project'],
        description='Change Node RAID status',
        operations=[
            {'path': '/nodes/{node_ident}/states/raid', 'method': 'PUT'}
        ],
        deprecated_rule=deprecated_node_set_raid_state,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:get_console',
        check_str=SYSTEM_MEMBER_OR_OWNER_MEMBER,
        scope_types=['system', 'project'],
        description='Get Node console connection information',
        operations=[
            {'path': '/nodes/{node_ident}/states/console', 'method': 'GET'}
        ],
        deprecated_rule=deprecated_node_get_console,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:set_console_state',
        check_str=SYSTEM_MEMBER_OR_OWNER_MEMBER,
        scope_types=['system', 'project'],
        description='Change Node console status',
        operations=[
            {'path': '/nodes/{node_ident}/states/console', 'method': 'PUT'}
        ],
        deprecated_rule=deprecated_node_set_console_state,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),

    policy.DocumentedRuleDefault(
        name='baremetal:node:vif:list',
        check_str=SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='List VIFs attached to node',
        operations=[{'path': '/nodes/{node_ident}/vifs', 'method': 'GET'}],
        deprecated_rule=deprecated_node_vif_list,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:vif:attach',
        check_str=SYSTEM_OR_OWNER_MEMBER_AND_LESSEE_ADMIN,
        scope_types=['system', 'project'],
        description='Attach a VIF to a node',
        operations=[{'path': '/nodes/{node_ident}/vifs', 'method': 'POST'}],
        deprecated_rule=deprecated_node_vif_attach,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:vif:detach',
        check_str=SYSTEM_OR_OWNER_MEMBER_AND_LESSEE_ADMIN,
        scope_types=['system', 'project'],
        description='Detach a VIF from a node',
        operations=[
            {'path': '/nodes/{node_ident}/vifs/{node_vif_ident}',
             'method': 'DELETE'}
        ],
        deprecated_rule=deprecated_node_vif_detach,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:traits:list',
        check_str=SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='List node traits',
        operations=[{'path': '/nodes/{node_ident}/traits', 'method': 'GET'}],
        deprecated_rule=deprecated_node_traits_list,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:traits:set',
        check_str=SYSTEM_MEMBER_OR_OWNER_ADMIN,
        scope_types=['system', 'project'],
        description='Add a trait to, or replace all traits of, a node',
        operations=[
            {'path': '/nodes/{node_ident}/traits', 'method': 'PUT'},
            {'path': '/nodes/{node_ident}/traits/{trait}', 'method': 'PUT'}
        ],
        deprecated_rule=deprecated_node_traits_set,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:traits:delete',
        check_str=SYSTEM_MEMBER_OR_OWNER_ADMIN,
        scope_types=['system', 'project'],
        description='Remove one or all traits from a node',
        operations=[
            {'path': '/nodes/{node_ident}/traits', 'method': 'DELETE'},
            {'path': '/nodes/{node_ident}/traits/{trait}',
                     'method': 'DELETE'}
        ],
        deprecated_rule=deprecated_node_traits_delete,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),

    policy.DocumentedRuleDefault(
        name='baremetal:node:bios:get',
        check_str=SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Retrieve Node BIOS information',
        operations=[
            {'path': '/nodes/{node_ident}/bios', 'method': 'GET'},
            {'path': '/nodes/{node_ident}/bios/{setting}', 'method': 'GET'}
        ],
        deprecated_rule=deprecated_node_bios_get,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:node:disable_cleaning',
        check_str=SYSTEM_MEMBER,
        scope_types=['system'],
        description='Disable Node disk cleaning',
        operations=[
            {'path': '/nodes/{node_ident}', 'method': 'PATCH'}
        ],
        deprecated_rule=deprecated_bios_disable_cleaning,
        deprecated_reason=deprecated_node_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
]

deprecated_port_get = policy.DeprecatedRule(
    name='baremetal:port:get',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_port_list = policy.DeprecatedRule(
    name='baremetal:port:list',
    check_str='rule:baremetal:port:get'
)
deprecated_port_list_all = policy.DeprecatedRule(
    name='baremetal:port:list_all',
    check_str='rule:baremetal:port:get'
)
deprecated_port_create = policy.DeprecatedRule(
    name='baremetal:port:create',
    check_str='rule:is_admin'
)
deprecated_port_delete = policy.DeprecatedRule(
    name='baremetal:port:delete',
    check_str='rule:is_admin'
)
deprecated_port_update = policy.DeprecatedRule(
    name='baremetal:port:update',
    check_str='rule:is_admin'
)
deprecated_port_reason = """
The baremetal port API is now aware of system scope and default roles.
"""

port_policies = [
    policy.DocumentedRuleDefault(
        name='baremetal:port:get',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='Retrieve Port records',
        operations=[
            {'path': '/ports/{port_id}', 'method': 'GET'},
            {'path': '/nodes/{node_ident}/ports', 'method': 'GET'},
            {'path': '/nodes/{node_ident}/ports/detail', 'method': 'GET'},
            {'path': '/portgroups/{portgroup_ident}/ports', 'method': 'GET'},
            {'path': '/portgroups/{portgroup_ident}/ports/detail',
             'method': 'GET'}
        ],
        deprecated_rule=deprecated_port_get,
        deprecated_reason=deprecated_port_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:port:list',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='Retrieve multiple Port records, filtered by owner',
        operations=[
            {'path': '/ports', 'method': 'GET'},
            {'path': '/ports/detail', 'method': 'GET'}
        ],
        deprecated_rule=deprecated_port_list,
        deprecated_reason=deprecated_port_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:port:list_all',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='Retrieve multiple Port records',
        operations=[
            {'path': '/ports', 'method': 'GET'},
            {'path': '/ports/detail', 'method': 'GET'}
        ],
        deprecated_rule=deprecated_port_list_all,
        deprecated_reason=deprecated_port_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:port:create',
        check_str=SYSTEM_ADMIN,
        scope_types=['system'],
        description='Create Port records',
        operations=[{'path': '/ports', 'method': 'POST'}],
        deprecated_rule=deprecated_port_create,
        deprecated_reason=deprecated_port_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:port:delete',
        check_str=SYSTEM_ADMIN,
        scope_types=['system'],
        description='Delete Port records',
        operations=[{'path': '/ports/{port_id}', 'method': 'DELETE'}],
        deprecated_rule=deprecated_port_delete,
        deprecated_reason=deprecated_port_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:port:update',
        check_str=SYSTEM_MEMBER,
        scope_types=['system'],
        description='Update Port records',
        operations=[{'path': '/ports/{port_id}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_port_update,
        deprecated_reason=deprecated_port_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
]

deprecated_portgroup_get = policy.DeprecatedRule(
    name='baremetal:portgroup:get',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_portgroup_create = policy.DeprecatedRule(
    name='baremetal:portgroup:create',
    check_str='rule:is_admin'
)
deprecated_portgroup_delete = policy.DeprecatedRule(
    name='baremetal:portgroup:delete',
    check_str='rule:is_admin'
)
deprecated_portgroup_update = policy.DeprecatedRule(
    name='baremetal:portgroup:update',
    check_str='rule:is_admin'
)
deprecated_portgroup_reason = """
The baremetal port groups API is now aware of system scope and default roles.
"""

portgroup_policies = [
    policy.DocumentedRuleDefault(
        name='baremetal:portgroup:get',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='Retrieve Portgroup records',
        operations=[
            {'path': '/portgroups', 'method': 'GET'},
            {'path': '/portgroups/detail', 'method': 'GET'},
            {'path': '/portgroups/{portgroup_ident}', 'method': 'GET'},
            {'path': '/nodes/{node_ident}/portgroups', 'method': 'GET'},
            {'path': '/nodes/{node_ident}/portgroups/detail', 'method': 'GET'},
        ],
        deprecated_rule=deprecated_portgroup_get,
        deprecated_reason=deprecated_portgroup_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:portgroup:create',
        check_str=SYSTEM_ADMIN,
        scope_types=['system'],
        description='Create Portgroup records',
        operations=[{'path': '/portgroups', 'method': 'POST'}],
        deprecated_rule=deprecated_portgroup_create,
        deprecated_reason=deprecated_portgroup_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:portgroup:delete',
        check_str=SYSTEM_ADMIN,
        scope_types=['system'],
        description='Delete Portgroup records',
        operations=[
            {'path': '/portgroups/{portgroup_ident}', 'method': 'DELETE'}
        ],
        deprecated_rule=deprecated_portgroup_delete,
        deprecated_reason=deprecated_portgroup_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:portgroup:update',
        check_str=SYSTEM_MEMBER,
        scope_types=['system'],
        description='Update Portgroup records',
        operations=[
            {'path': '/portgroups/{portgroup_ident}', 'method': 'PATCH'}
        ],
        deprecated_rule=deprecated_portgroup_update,
        deprecated_reason=deprecated_portgroup_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
]


deprecated_chassis_get = policy.DeprecatedRule(
    name='baremetal:chassis:get',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_chassis_create = policy.DeprecatedRule(
    name='baremetal:chassis:create',
    check_str='rule:is_admin'
)
deprecated_chassis_delete = policy.DeprecatedRule(
    name='baremetal:chassis:delete',
    check_str='rule:is_admin'
)
deprecated_chassis_update = policy.DeprecatedRule(
    name='baremetal:chassis:update',
    check_str='rule:is_admin'
)
deprecated_chassis_reason = """
The baremetal chassis API is now aware of system scope and default roles.
"""

chassis_policies = [
    policy.DocumentedRuleDefault(
        name='baremetal:chassis:get',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='Retrieve Chassis records',
        operations=[
            {'path': '/chassis', 'method': 'GET'},
            {'path': '/chassis/detail', 'method': 'GET'},
            {'path': '/chassis/{chassis_id}', 'method': 'GET'}
        ],
        deprecated_rule=deprecated_chassis_get,
        deprecated_reason=deprecated_chassis_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:chassis:create',
        check_str=SYSTEM_ADMIN,
        scope_types=['system'],
        description='Create Chassis records',
        operations=[{'path': '/chassis', 'method': 'POST'}],
        deprecated_rule=deprecated_chassis_create,
        deprecated_reason=deprecated_chassis_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:chassis:delete',
        check_str=SYSTEM_ADMIN,
        scope_types=['system'],
        description='Delete Chassis records',
        operations=[{'path': '/chassis/{chassis_id}', 'method': 'DELETE'}],
        deprecated_rule=deprecated_chassis_delete,
        deprecated_reason=deprecated_chassis_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:chassis:update',
        check_str=SYSTEM_MEMBER,
        scope_types=['system'],
        description='Update Chassis records',
        operations=[{'path': '/chassis/{chassis_id}', 'method': 'PATCH'}],
        deprecated_rule=deprecated_chassis_update,
        deprecated_reason=deprecated_chassis_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
]


deprecated_driver_get = policy.DeprecatedRule(
    name='baremetal:driver:get',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_driver_get_properties = policy.DeprecatedRule(
    name='baremetal:driver:get_properties',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_driver_get_raid_properties = policy.DeprecatedRule(
    name='baremetal:driver:get_raid_logical_disk_properties',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_driver_reason = """
The baremetal driver API is now aware of system scope and default roles.
"""

driver_policies = [
    policy.DocumentedRuleDefault(
        name='baremetal:driver:get',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='View list of available drivers',
        operations=[
            {'path': '/drivers', 'method': 'GET'},
            {'path': '/drivers/{driver_name}', 'method': 'GET'}
        ],
        deprecated_rule=deprecated_driver_get,
        deprecated_reason=deprecated_driver_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:driver:get_properties',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='View driver-specific properties',
        operations=[
            {'path': '/drivers/{driver_name}/properties', 'method': 'GET'}
        ],
        deprecated_rule=deprecated_driver_get_properties,
        deprecated_reason=deprecated_driver_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:driver:get_raid_logical_disk_properties',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='View driver-specific RAID metadata',
        operations=[
            {'path': '/drivers/{driver_name}/raid/logical_disk_properties',
             'method': 'GET'}
        ],
        deprecated_rule=deprecated_driver_get_raid_properties,
        deprecated_reason=deprecated_driver_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
]

deprecated_node_passthru = policy.DeprecatedRule(
    name='baremetal:node:vendor_passthru',
    check_str='rule:is_admin'
)
deprecated_driver_passthru = policy.DeprecatedRule(
    name='baremetal:driver:vendor_passthru',
    check_str='rule:is_admin'
)
deprecated_vendor_reason = """
The baremetal vendor passthru API is now aware of system scope and default
roles.
"""

vendor_passthru_policies = [
    policy.DocumentedRuleDefault(
        name='baremetal:node:vendor_passthru',
        check_str=SYSTEM_ADMIN,
        # NOTE(TheJulia): Project scope listed, but not a project scoped role
        # as some operators may find it useful to provide access to say owner
        # admins.
        scope_types=['system', 'project'],
        description='Access vendor-specific Node functions',
        operations=[
            {'path': 'nodes/{node_ident}/vendor_passthru/methods',
             'method': 'GET'},
            {'path': 'nodes/{node_ident}/vendor_passthru?method={method_name}',
             'method': 'GET'},
            {'path': 'nodes/{node_ident}/vendor_passthru?method={method_name}',
             'method': 'PUT'},
            {'path': 'nodes/{node_ident}/vendor_passthru?method={method_name}',
             'method': 'POST'},
            {'path': 'nodes/{node_ident}/vendor_passthru?method={method_name}',
             'method': 'PATCH'},
            {'path': 'nodes/{node_ident}/vendor_passthru?method={method_name}',
             'method': 'DELETE'},
        ],
        deprecated_rule=deprecated_node_passthru,
        deprecated_reason=deprecated_vendor_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:driver:vendor_passthru',
        check_str=SYSTEM_ADMIN,
        scope_types=['system'],
        description='Access vendor-specific Driver functions',
        operations=[
            {'path': 'drivers/{driver_name}/vendor_passthru/methods',
             'method': 'GET'},
            {'path': 'drivers/{driver_name}/vendor_passthru?'
                     'method={method_name}',
             'method': 'GET'},
            {'path': 'drivers/{driver_name}/vendor_passthru?'
                     'method={method_name}',
             'method': 'PUT'},
            {'path': 'drivers/{driver_name}/vendor_passthru?'
                     'method={method_name}',
             'method': 'POST'},
            {'path': 'drivers/{driver_name}/vendor_passthru?'
                     'method={method_name}',
             'method': 'PATCH'},
            {'path': 'drivers/{driver_name}/vendor_passthru?'
                     'method={method_name}',
             'method': 'DELETE'}
        ],
        deprecated_rule=deprecated_driver_passthru,
        deprecated_reason=deprecated_vendor_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
]


deprecated_ipa_heartbeat = policy.DeprecatedRule(
    name='baremetal:node:ipa_heartbeat',
    check_str='rule:public_api'
)
deprecated_ipa_lookup = policy.DeprecatedRule(
    name='baremetal:driver:ipa_lookup',
    check_str='rule:public_api'
)
deprecated_utility_reason = """
The baremetal utility API is now aware of system scope and default
roles.
"""

# NOTE(TheJulia): Empty check strings basically mean nothing to apply,
# and the request is permitted.
utility_policies = [
    policy.DocumentedRuleDefault(
        name='baremetal:node:ipa_heartbeat',
        check_str='',
        description='Receive heartbeats from IPA ramdisk',
        operations=[{'path': '/heartbeat/{node_ident}', 'method': 'POST'}],
        deprecated_rule=deprecated_ipa_heartbeat,
        deprecated_reason=deprecated_utility_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:driver:ipa_lookup',
        check_str='',
        description='Access IPA ramdisk functions',
        operations=[{'path': '/lookup', 'method': 'GET'}],
        deprecated_rule=deprecated_ipa_lookup,
        deprecated_reason=deprecated_utility_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
]


deprecated_volume_get = policy.DeprecatedRule(
    name='baremetal:volume:get',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_volume_create = policy.DeprecatedRule(
    name='baremetal:volume:create',
    check_str='rule:is_admin'
)
deprecated_volume_delete = policy.DeprecatedRule(
    name='baremetal:volume:delete',
    check_str='rule:is_admin'
)
deprecated_volume_update = policy.DeprecatedRule(
    name='baremetal:volume:update',
    check_str='rule:is_admin'
)
deprecated_volume_reason = """
The baremetal volume API is now aware of system scope and default
roles.
"""

volume_policies = [
    policy.DocumentedRuleDefault(
        name='baremetal:volume:get',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='Retrieve Volume connector and target records',
        operations=[
            {'path': '/volume', 'method': 'GET'},
            {'path': '/volume/connectors', 'method': 'GET'},
            {'path': '/volume/connectors/{volume_connector_id}',
             'method': 'GET'},
            {'path': '/volume/targets', 'method': 'GET'},
            {'path': '/volume/targets/{volume_target_id}', 'method': 'GET'},
            {'path': '/nodes/{node_ident}/volume', 'method': 'GET'},
            {'path': '/nodes/{node_ident}/volume/connectors', 'method': 'GET'},
            {'path': '/nodes/{node_ident}/volume/targets', 'method': 'GET'}
        ],
        deprecated_rule=deprecated_volume_get,
        deprecated_reason=deprecated_volume_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:volume:create',
        check_str=SYSTEM_MEMBER,
        scope_types=['system'],
        description='Create Volume connector and target records',
        operations=[
            {'path': '/volume/connectors', 'method': 'POST'},
            {'path': '/volume/targets', 'method': 'POST'}
        ],
        deprecated_rule=deprecated_volume_create,
        deprecated_reason=deprecated_volume_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:volume:delete',
        check_str=SYSTEM_MEMBER,
        scope_types=['system'],
        description='Delete Volume connector and target records',
        operations=[
            {'path': '/volume/connectors/{volume_connector_id}',
             'method': 'DELETE'},
            {'path': '/volume/targets/{volume_target_id}',
             'method': 'DELETE'}
        ],
        deprecated_rule=deprecated_volume_delete,
        deprecated_reason=deprecated_volume_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:volume:update',
        check_str=SYSTEM_MEMBER,
        scope_types=['system'],
        description='Update Volume connector and target records',
        operations=[
            {'path': '/volume/connectors/{volume_connector_id}',
             'method': 'PATCH'},
            {'path': '/volume/targets/{volume_target_id}',
             'method': 'PATCH'}
        ],
        deprecated_rule=deprecated_volume_update,
        deprecated_reason=deprecated_volume_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
]


deprecated_conductor_get = policy.DeprecatedRule(
    name='baremetal:conductor:get',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_conductor_reason = """
The baremetal conductor API is now aware of system scope and default
roles.
"""

conductor_policies = [
    policy.DocumentedRuleDefault(
        name='baremetal:conductor:get',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='Retrieve Conductor records',
        operations=[
            {'path': '/conductors', 'method': 'GET'},
            {'path': '/conductors/{hostname}', 'method': 'GET'}
        ],
        deprecated_rule=deprecated_conductor_get,
        deprecated_reason=deprecated_conductor_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
]


deprecated_allocation_get = policy.DeprecatedRule(
    name='baremetal:allocation:get',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_allocation_list = policy.DeprecatedRule(
    name='baremetal:allocation:list',
    check_str='rule:baremetal:allocation:get'
)
deprecated_allocation_list_all = policy.DeprecatedRule(
    name='baremetal:allocation:list_all',
    check_str='rule:baremetal:allocation:get'
)
deprecated_allocation_create = policy.DeprecatedRule(
    name='baremetal:allocation:create',
    check_str='rule:is_admin'
)
deprecated_allocation_create_restricted = policy.DeprecatedRule(
    name='baremetal:allocation:create_restricted',
    check_str='rule:baremetal:allocation:create'
)
deprecated_allocation_delete = policy.DeprecatedRule(
    name='baremetal:allocation:delete',
    check_str='rule:is_admin'
)
deprecated_allocation_update = policy.DeprecatedRule(
    name='baremetal:allocation:update',
    check_str='rule:is_admin'
)
deprecated_allocation_reason = """
The baremetal allocation API is now aware of system scope and default
roles.
"""

allocation_policies = [
    policy.DocumentedRuleDefault(
        name='baremetal:allocation:get',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='Retrieve Allocation records',
        operations=[
            {'path': '/allocations/{allocation_id}', 'method': 'GET'},
            {'path': '/nodes/{node_ident}/allocation', 'method': 'GET'}
        ],
        deprecated_rule=deprecated_allocation_get,
        deprecated_reason=deprecated_allocation_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:allocation:list',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='Retrieve multiple Allocation records, filtered by owner',
        operations=[{'path': '/allocations', 'method': 'GET'}],
        deprecated_rule=deprecated_allocation_list,
        deprecated_reason=deprecated_allocation_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:allocation:list_all',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='Retrieve multiple Allocation records',
        operations=[{'path': '/allocations', 'method': 'GET'}],
        deprecated_rule=deprecated_allocation_list_all,
        deprecated_reason=deprecated_allocation_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:allocation:create',
        check_str=SYSTEM_MEMBER,
        scope_types=['system'],
        description='Create Allocation records',
        operations=[{'path': '/allocations', 'method': 'POST'}],
        deprecated_rule=deprecated_allocation_create,
        deprecated_reason=deprecated_allocation_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:allocation:create_restricted',
        check_str=SYSTEM_MEMBER,
        scope_types=['system'],
        description=(
            'Create Allocation records that are restricted to an owner'
        ),
        operations=[{'path': '/allocations', 'method': 'POST'}],
        deprecated_rule=deprecated_allocation_create_restricted,
        deprecated_reason=deprecated_allocation_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:allocation:delete',
        check_str=SYSTEM_MEMBER,
        scope_types=['system'],
        description='Delete Allocation records',
        operations=[
            {'path': '/allocations/{allocation_id}', 'method': 'DELETE'},
            {'path': '/nodes/{node_ident}/allocation', 'method': 'DELETE'}],
        deprecated_rule=deprecated_allocation_delete,
        deprecated_reason=deprecated_allocation_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:allocation:update',
        check_str=SYSTEM_MEMBER,
        scope_types=['system'],
        description='Change name and extra fields of an allocation',
        operations=[
            {'path': '/allocations/{allocation_id}', 'method': 'PATCH'},
        ],
        deprecated_rule=deprecated_allocation_update,
        deprecated_reason=deprecated_allocation_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
]


deprecated_event_create = policy.DeprecatedRule(
    name='baremetal:events:post',
    check_str='rule:is_admin'
)
deprecated_event_reason = """
The baremetal event API is now aware of system scope and default
roles.
"""

event_policies = [
    policy.DocumentedRuleDefault(
        name='baremetal:events:post',
        check_str=SYSTEM_ADMIN,
        scope_types=['system'],
        description='Post events',
        operations=[{'path': '/events', 'method': 'POST'}],
        deprecated_rule=deprecated_event_create,
        deprecated_reason=deprecated_event_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    )
]


deprecated_deploy_template_get = policy.DeprecatedRule(
    name='baremetal:deploy_template:get',
    check_str='rule:is_admin or rule:is_observer'
)
deprecated_deploy_template_create = policy.DeprecatedRule(
    name='baremetal:deploy_template:create',
    check_str='rule:is_admin'
)
deprecated_deploy_template_delete = policy.DeprecatedRule(
    name='baremetal:deploy_template:delete',
    check_str='rule:is_admin'
)
deprecated_deploy_template_update = policy.DeprecatedRule(
    name='baremetal:deploy_template:update',
    check_str='rule:is_admin'
)
deprecated_template_reason = """
The baremetal deploy template API is now aware of system scope and
default roles.
"""

deploy_template_policies = [
    policy.DocumentedRuleDefault(
        name='baremetal:deploy_template:get',
        check_str=SYSTEM_READER,
        scope_types=['system'],
        description='Retrieve Deploy Template records',
        operations=[
            {'path': '/deploy_templates', 'method': 'GET'},
            {'path': '/deploy_templates/{deploy_template_ident}',
             'method': 'GET'}
        ],
        deprecated_rule=deprecated_deploy_template_get,
        deprecated_reason=deprecated_template_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:deploy_template:create',
        check_str=SYSTEM_ADMIN,
        scope_types=['system'],
        description='Create Deploy Template records',
        operations=[{'path': '/deploy_templates', 'method': 'POST'}],
        deprecated_rule=deprecated_deploy_template_create,
        deprecated_reason=deprecated_template_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:deploy_template:delete',
        check_str=SYSTEM_ADMIN,
        scope_types=['system'],
        description='Delete Deploy Template records',
        operations=[
            {'path': '/deploy_templates/{deploy_template_ident}',
             'method': 'DELETE'}
        ],
        deprecated_rule=deprecated_deploy_template_delete,
        deprecated_reason=deprecated_template_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
    policy.DocumentedRuleDefault(
        name='baremetal:deploy_template:update',
        check_str=SYSTEM_ADMIN,
        scope_types=['system'],
        description='Update Deploy Template records',
        operations=[
            {'path': '/deploy_templates/{deploy_template_ident}',
             'method': 'PATCH'}
        ],
        deprecated_rule=deprecated_deploy_template_update,
        deprecated_reason=deprecated_template_reason,
        deprecated_since=versionutils.deprecated.WALLABY
    ),
]


def list_policies():
    policies = itertools.chain(
        default_policies,
        node_policies,
        port_policies,
        portgroup_policies,
        chassis_policies,
        driver_policies,
        vendor_passthru_policies,
        utility_policies,
        volume_policies,
        conductor_policies,
        allocation_policies,
        event_policies,
        deploy_template_policies,
    )
    return policies


@lockutils.synchronized('policy_enforcer')
def init_enforcer(policy_file=None, rules=None,
                  default_rule=None, use_conf=True):
    """Synchronously initializes the policy enforcer

       :param policy_file: Custom policy file to use, if none is specified,
                           `CONF.oslo_policy.policy_file` will be used.
       :param rules: Default dictionary / Rules to use. It will be
                     considered just in the first instantiation.
       :param default_rule: Default rule to use,
                            CONF.oslo_policy.policy_default_rule will
                            be used if none is specified.
       :param use_conf: Whether to load rules from config file.

    """
    global _ENFORCER

    if _ENFORCER:
        return

    # NOTE(tenbrae): Register defaults for policy-in-code here so that they are
    # loaded exactly once - when this module-global is initialized.
    # Defining these in the relevant API modules won't work
    # because API classes lack singletons and don't use globals.
    _ENFORCER = policy.Enforcer(
        CONF, policy_file=policy_file,
        rules=rules,
        default_rule=default_rule,
        use_conf=use_conf)
    _ENFORCER.register_defaults(list_policies())


def get_enforcer():
    """Provides access to the single instance of Policy enforcer."""

    if not _ENFORCER:
        init_enforcer()

    return _ENFORCER


def get_oslo_policy_enforcer():
    # This method is for use by oslopolicy CLI scripts. Those scripts need the
    # 'output-file' and 'namespace' options, but having those in sys.argv means
    # loading the Ironic config options will fail as those are not expected to
    # be present. So we pass in an arg list with those stripped out.

    conf_args = []
    # Start at 1 because cfg.CONF expects the equivalent of sys.argv[1:]
    i = 1
    while i < len(sys.argv):
        if sys.argv[i].strip('-') in ['namespace', 'output-file']:
            i += 2
            continue
        conf_args.append(sys.argv[i])
        i += 1

    cfg.CONF(conf_args, project='ironic')

    return get_enforcer()


# NOTE(tenbrae): We can't call these methods from within decorators because the
# 'target' and 'creds' parameter must be fetched from the call time
# context-local pecan.request magic variable, but decorators are compiled
# at module-load time.


def authorize(rule, target, creds, *args, **kwargs):
    """A shortcut for policy.Enforcer.authorize()

    Checks authorization of a rule against the target and credentials, and
    raises an exception if the rule is not defined.
    Always returns true if CONF.auth_strategy is not keystone.
    """
    if CONF.auth_strategy != 'keystone':
        return True
    enforcer = get_enforcer()
    try:
        return enforcer.authorize(rule, target, creds, do_raise=True,
                                  *args, **kwargs)
    except policy.PolicyNotAuthorized:
        raise exception.HTTPForbidden(resource=rule)


def check(rule, target, creds, *args, **kwargs):
    """A shortcut for policy.Enforcer.enforce()

    Checks authorization of a rule against the target and credentials
    and returns True or False.
    """
    enforcer = get_enforcer()
    return enforcer.enforce(rule, target, creds, *args, **kwargs)


def check_policy(rule, target, creds, *args, **kwargs):
    """Configuration aware role policy check wrapper.

    Checks authorization of a rule against the target and credentials
    and returns True or False.
    Always returns true if CONF.auth_strategy is not keystone.
    """
    if CONF.auth_strategy != 'keystone':
        return True
    enforcer = get_enforcer()
    return enforcer.enforce(rule, target, creds, *args, **kwargs)
