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
from oslo_policy import policy

from ironic.common import exception

_ENFORCER = None
CONF = cfg.CONF
LOG = log.getLogger(__name__)

default_policies = [
    # Legacy setting, don't remove. Likely to be overridden by operators who
    # forget to update their policy.json configuration file.
    # This gets rolled into the new "is_admin" rule below.
    policy.RuleDefault('admin_api',
                       'role:admin or role:administrator',
                       description='Legacy rule for cloud admin access'),
    # is_public_api is set in the environment from AuthTokenMiddleware
    policy.RuleDefault('public_api',
                       'is_public_api:True',
                       description='Internal flag for public API routes'),
    # Generic default to hide passwords in node driver_info
    # NOTE(deva): the 'show_password' policy setting hides secrets in
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
]

# NOTE(deva): to follow policy-in-code spec, we define defaults for
#             the granular policies in code, rather than in policy.json.
#             All of these may be overridden by configuration, but we can
#             depend on their existence throughout the code.

node_policies = [
    policy.DocumentedRuleDefault(
        'baremetal:node:create',
        'rule:is_admin',
        'Create Node records',
        [{'path': '/nodes', 'method': 'POST'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:get',
        'rule:is_admin or rule:is_observer',
        'Retrieve a single Node record',
        [{'path': '/nodes/{node_ident}', 'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:list',
        'rule:baremetal:node:get',
        'Retrieve multiple Node records, filtered by owner',
        [{'path': '/nodes', 'method': 'GET'},
         {'path': '/nodes/detail', 'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:list_all',
        'rule:baremetal:node:get',
        'Retrieve multiple Node records',
        [{'path': '/nodes', 'method': 'GET'},
         {'path': '/nodes/detail', 'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:update',
        'rule:is_admin',
        'Update Node records',
        [{'path': '/nodes/{node_ident}', 'method': 'PATCH'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:delete',
        'rule:is_admin',
        'Delete Node records',
        [{'path': '/nodes/{node_ident}', 'method': 'DELETE'}]),

    policy.DocumentedRuleDefault(
        'baremetal:node:validate',
        'rule:is_admin',
        'Request active validation of Nodes',
        [{'path': '/nodes/{node_ident}/validate', 'method': 'GET'}]),

    policy.DocumentedRuleDefault(
        'baremetal:node:set_maintenance',
        'rule:is_admin',
        'Set maintenance flag, taking a Node out of service',
        [{'path': '/nodes/{node_ident}/maintenance', 'method': 'PUT'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:clear_maintenance',
        'rule:is_admin',
        'Clear maintenance flag, placing the Node into service again',
        [{'path': '/nodes/{node_ident}/maintenance', 'method': 'DELETE'}]),

    policy.DocumentedRuleDefault(
        'baremetal:node:get_boot_device',
        'rule:is_admin or rule:is_observer',
        'Retrieve Node boot device metadata',
        [{'path': '/nodes/{node_ident}/management/boot_device',
          'method': 'GET'},
         {'path': '/nodes/{node_ident}/management/boot_device/supported',
          'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:set_boot_device',
        'rule:is_admin',
        'Change Node boot device',
        [{'path': '/nodes/{node_ident}/management/boot_device',
          'method': 'PUT'}]),

    policy.DocumentedRuleDefault(
        'baremetal:node:inject_nmi',
        'rule:is_admin',
        'Inject NMI for a node',
        [{'path': '/nodes/{node_ident}/management/inject_nmi',
          'method': 'PUT'}]),

    policy.DocumentedRuleDefault(
        'baremetal:node:get_states',
        'rule:is_admin or rule:is_observer',
        'View Node power and provision state',
        [{'path': '/nodes/{node_ident}/states', 'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:set_power_state',
        'rule:is_admin',
        'Change Node power status',
        [{'path': '/nodes/{node_ident}/states/power', 'method': 'PUT'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:set_provision_state',
        'rule:is_admin',
        'Change Node provision status',
        [{'path': '/nodes/{node_ident}/states/provision', 'method': 'PUT'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:set_raid_state',
        'rule:is_admin',
        'Change Node RAID status',
        [{'path': '/nodes/{node_ident}/states/raid', 'method': 'PUT'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:get_console',
        'rule:is_admin',
        'Get Node console connection information',
        [{'path': '/nodes/{node_ident}/states/console', 'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:set_console_state',
        'rule:is_admin',
        'Change Node console status',
        [{'path': '/nodes/{node_ident}/states/console', 'method': 'PUT'}]),

    policy.DocumentedRuleDefault(
        'baremetal:node:vif:list',
        'rule:is_admin',
        'List VIFs attached to node',
        [{'path': '/nodes/{node_ident}/vifs', 'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:vif:attach',
        'rule:is_admin',
        'Attach a VIF to a node',
        [{'path': '/nodes/{node_ident}/vifs', 'method': 'POST'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:vif:detach',
        'rule:is_admin',
        'Detach a VIF from a node',
        [{'path': '/nodes/{node_ident}/vifs/{node_vif_ident}',
          'method': 'DELETE'}]),

    policy.DocumentedRuleDefault(
        'baremetal:node:traits:list',
        'rule:is_admin or rule:is_observer',
        'List node traits',
        [{'path': '/nodes/{node_ident}/traits', 'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:traits:set',
        'rule:is_admin',
        'Add a trait to, or replace all traits of, a node',
        [{'path': '/nodes/{node_ident}/traits', 'method': 'PUT'},
         {'path': '/nodes/{node_ident}/traits/{trait}', 'method': 'PUT'}]),
    policy.DocumentedRuleDefault(
        'baremetal:node:traits:delete',
        'rule:is_admin',
        'Remove one or all traits from a node',
        [{'path': '/nodes/{node_ident}/traits', 'method': 'DELETE'},
         {'path': '/nodes/{node_ident}/traits/{trait}',
          'method': 'DELETE'}]),

    policy.DocumentedRuleDefault(
        'baremetal:node:bios:get',
        'rule:is_admin or rule:is_observer',
        'Retrieve Node BIOS information',
        [{'path': '/nodes/{node_ident}/bios', 'method': 'GET'},
         {'path': '/nodes/{node_ident}/bios/{setting}', 'method': 'GET'}])
]

port_policies = [
    policy.DocumentedRuleDefault(
        'baremetal:port:get',
        'rule:is_admin or rule:is_observer',
        'Retrieve Port records',
        [{'path': '/ports', 'method': 'GET'},
         {'path': '/ports/detail', 'method': 'GET'},
         {'path': '/ports/{port_id}', 'method': 'GET'},
         {'path': '/nodes/{node_ident}/ports', 'method': 'GET'},
         {'path': '/nodes/{node_ident}/ports/detail', 'method': 'GET'},
         {'path': '/portgroups/{portgroup_ident}/ports', 'method': 'GET'},
         {'path': '/portgroups/{portgroup_ident}/ports/detail',
          'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:port:create',
        'rule:is_admin',
        'Create Port records',
        [{'path': '/ports', 'method': 'POST'}]),
    policy.DocumentedRuleDefault(
        'baremetal:port:delete',
        'rule:is_admin',
        'Delete Port records',
        [{'path': '/ports/{port_id}', 'method': 'DELETE'}]),
    policy.DocumentedRuleDefault(
        'baremetal:port:update',
        'rule:is_admin',
        'Update Port records',
        [{'path': '/ports/{port_id}', 'method': 'PATCH'}]),
]

portgroup_policies = [
    policy.DocumentedRuleDefault(
        'baremetal:portgroup:get',
        'rule:is_admin or rule:is_observer',
        'Retrieve Portgroup records',
        [{'path': '/portgroups', 'method': 'GET'},
         {'path': '/portgroups/detail', 'method': 'GET'},
         {'path': '/portgroups/{portgroup_ident}', 'method': 'GET'},
         {'path': '/nodes/{node_ident}/portgroups', 'method': 'GET'},
         {'path': '/nodes/{node_ident}/portgroups/detail', 'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:portgroup:create',
        'rule:is_admin',
        'Create Portgroup records',
        [{'path': '/portgroups', 'method': 'POST'}]),
    policy.DocumentedRuleDefault(
        'baremetal:portgroup:delete',
        'rule:is_admin',
        'Delete Portgroup records',
        [{'path': '/portgroups/{portgroup_ident}', 'method': 'DELETE'}]),
    policy.DocumentedRuleDefault(
        'baremetal:portgroup:update',
        'rule:is_admin',
        'Update Portgroup records',
        [{'path': '/portgroups/{portgroup_ident}', 'method': 'PATCH'}]),
]

chassis_policies = [
    policy.DocumentedRuleDefault(
        'baremetal:chassis:get',
        'rule:is_admin or rule:is_observer',
        'Retrieve Chassis records',
        [{'path': '/chassis', 'method': 'GET'},
         {'path': '/chassis/detail', 'method': 'GET'},
         {'path': '/chassis/{chassis_id}', 'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:chassis:create',
        'rule:is_admin',
        'Create Chassis records',
        [{'path': '/chassis', 'method': 'POST'}]),
    policy.DocumentedRuleDefault(
        'baremetal:chassis:delete',
        'rule:is_admin',
        'Delete Chassis records',
        [{'path': '/chassis/{chassis_id}', 'method': 'DELETE'}]),
    policy.DocumentedRuleDefault(
        'baremetal:chassis:update',
        'rule:is_admin',
        'Update Chassis records',
        [{'path': '/chassis/{chassis_id}', 'method': 'PATCH'}]),
]

driver_policies = [
    policy.DocumentedRuleDefault(
        'baremetal:driver:get',
        'rule:is_admin or rule:is_observer',
        'View list of available drivers',
        [{'path': '/drivers', 'method': 'GET'},
         {'path': '/drivers/{driver_name}', 'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:driver:get_properties',
        'rule:is_admin or rule:is_observer',
        'View driver-specific properties',
        [{'path': '/drivers/{driver_name}/properties', 'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:driver:get_raid_logical_disk_properties',
        'rule:is_admin or rule:is_observer',
        'View driver-specific RAID metadata',
        [{'path': '/drivers/{driver_name}/raid/logical_disk_properties',
          'method': 'GET'}]),
]

vendor_passthru_policies = [
    policy.DocumentedRuleDefault(
        'baremetal:node:vendor_passthru',
        'rule:is_admin',
        'Access vendor-specific Node functions',
        [{'path': 'nodes/{node_ident}/vendor_passthru/methods',
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
          'method': 'DELETE'}]),
    policy.DocumentedRuleDefault(
        'baremetal:driver:vendor_passthru',
        'rule:is_admin',
        'Access vendor-specific Driver functions',
        [{'path': 'drivers/{driver_name}/vendor_passthru/methods',
          'method': 'GET'},
         {'path': 'drivers/{driver_name}/vendor_passthru?method={method_name}',
          'method': 'GET'},
         {'path': 'drivers/{driver_name}/vendor_passthru?method={method_name}',
          'method': 'PUT'},
         {'path': 'drivers/{driver_name}/vendor_passthru?method={method_name}',
          'method': 'POST'},
         {'path': 'drivers/{driver_name}/vendor_passthru?method={method_name}',
          'method': 'PATCH'},
         {'path': 'drivers/{driver_name}/vendor_passthru?method={method_name}',
          'method': 'DELETE'}]),
]

utility_policies = [
    policy.DocumentedRuleDefault(
        'baremetal:node:ipa_heartbeat',
        'rule:public_api',
        'Send heartbeats from IPA ramdisk',
        [{'path': '/heartbeat/{node_ident}', 'method': 'POST'}]),
    policy.DocumentedRuleDefault(
        'baremetal:driver:ipa_lookup',
        'rule:public_api',
        'Access IPA ramdisk functions',
        [{'path': '/lookup', 'method': 'GET'}]),
]

volume_policies = [
    policy.DocumentedRuleDefault(
        'baremetal:volume:get',
        'rule:is_admin or rule:is_observer',
        'Retrieve Volume connector and target records',
        [{'path': '/volume', 'method': 'GET'},
         {'path': '/volume/connectors', 'method': 'GET'},
         {'path': '/volume/connectors/{volume_connector_id}', 'method': 'GET'},
         {'path': '/volume/targets', 'method': 'GET'},
         {'path': '/volume/targets/{volume_target_id}', 'method': 'GET'},
         {'path': '/nodes/{node_ident}/volume', 'method': 'GET'},
         {'path': '/nodes/{node_ident}/volume/connectors', 'method': 'GET'},
         {'path': '/nodes/{node_ident}/volume/targets', 'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:volume:create',
        'rule:is_admin',
        'Create Volume connector and target records',
        [{'path': '/volume/connectors', 'method': 'POST'},
         {'path': '/volume/targets', 'method': 'POST'}]),
    policy.DocumentedRuleDefault(
        'baremetal:volume:delete',
        'rule:is_admin',
        'Delete Volume connector and target records',
        [{'path': '/volume/connectors/{volume_connector_id}',
          'method': 'DELETE'},
         {'path': '/volume/targets/{volume_target_id}',
          'method': 'DELETE'}]),
    policy.DocumentedRuleDefault(
        'baremetal:volume:update',
        'rule:is_admin',
        'Update Volume connector and target records',
        [{'path': '/volume/connectors/{volume_connector_id}',
          'method': 'PATCH'},
         {'path': '/volume/targets/{volume_target_id}',
          'method': 'PATCH'}]),
]

conductor_policies = [
    policy.DocumentedRuleDefault(
        'baremetal:conductor:get',
        'rule:is_admin or rule:is_observer',
        'Retrieve Conductor records',
        [{'path': '/conductors', 'method': 'GET'},
         {'path': '/conductors/{hostname}', 'method': 'GET'}]),
]

allocation_policies = [
    policy.DocumentedRuleDefault(
        'baremetal:allocation:get',
        'rule:is_admin or rule:is_observer',
        'Retrieve Allocation records',
        [{'path': '/allocations', 'method': 'GET'},
         {'path': '/allocations/{allocation_id}', 'method': 'GET'},
         {'path': '/nodes/{node_ident}/allocation', 'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:allocation:create',
        'rule:is_admin',
        'Create Allocation records',
        [{'path': '/allocations', 'method': 'POST'}]),
    policy.DocumentedRuleDefault(
        'baremetal:allocation:delete',
        'rule:is_admin',
        'Delete Allocation records',
        [{'path': '/allocations/{allocation_id}', 'method': 'DELETE'},
         {'path': '/nodes/{node_ident}/allocation', 'method': 'DELETE'}]),
    policy.DocumentedRuleDefault(
        'baremetal:allocation:update',
        'rule:is_admin',
        'Change name and extra fields of an allocation',
        [{'path': '/allocations/{allocation_id}', 'method': 'PATCH'}]),
]

event_policies = [
    policy.DocumentedRuleDefault(
        'baremetal:events:post',
        'rule:is_admin',
        'Post events',
        [{'path': '/events', 'method': 'POST'}])
]


deploy_template_policies = [
    policy.DocumentedRuleDefault(
        'baremetal:deploy_template:get',
        'rule:is_admin or rule:is_observer',
        'Retrieve Deploy Template records',
        [{'path': '/deploy_templates', 'method': 'GET'},
         {'path': '/deploy_templates/{deploy_template_ident}',
          'method': 'GET'}]),
    policy.DocumentedRuleDefault(
        'baremetal:deploy_template:create',
        'rule:is_admin',
        'Create Deploy Template records',
        [{'path': '/deploy_templates', 'method': 'POST'}]),
    policy.DocumentedRuleDefault(
        'baremetal:deploy_template:delete',
        'rule:is_admin',
        'Delete Deploy Template records',
        [{'path': '/deploy_templates/{deploy_template_ident}',
          'method': 'DELETE'}]),
    policy.DocumentedRuleDefault(
        'baremetal:deploy_template:update',
        'rule:is_admin',
        'Update Deploy Template records',
        [{'path': '/deploy_templates/{deploy_template_ident}',
          'method': 'PATCH'}]),
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

    # NOTE(deva): Register defaults for policy-in-code here so that they are
    # loaded exactly once - when this module-global is initialized.
    # Defining these in the relevant API modules won't work
    # because API classes lack singletons and don't use globals.
    _ENFORCER = policy.Enforcer(CONF, policy_file=policy_file,
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


# NOTE(deva): We can't call these methods from within decorators because the
# 'target' and 'creds' parameter must be fetched from the call time
# context-local pecan.request magic variable, but decorators are compiled
# at module-load time.


def authorize(rule, target, creds, *args, **kwargs):
    """A shortcut for policy.Enforcer.authorize()

    Checks authorization of a rule against the target and credentials, and
    raises an exception if the rule is not defined.
    Always returns true if CONF.auth_strategy == noauth.
    """
    if CONF.auth_strategy == 'noauth':
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
