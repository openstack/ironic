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
]

# NOTE(deva): to follow policy-in-code spec, we define defaults for
#             the granular policies in code, rather than in policy.json.
#             All of these may be overridden by configuration, but we can
#             depend on their existence throughout the code.

node_policies = [
    policy.RuleDefault('baremetal:node:get',
                       'rule:is_admin or rule:is_observer',
                       description='Retrieve Node records'),
    policy.RuleDefault('baremetal:node:get_boot_device',
                       'rule:is_admin or rule:is_observer',
                       description='Retrieve Node boot device metadata'),
    policy.RuleDefault('baremetal:node:get_states',
                       'rule:is_admin or rule:is_observer',
                       description='View Node power and provision state'),
    policy.RuleDefault('baremetal:node:create',
                       'rule:is_admin',
                       description='Create Node records'),
    policy.RuleDefault('baremetal:node:delete',
                       'rule:is_admin',
                       description='Delete Node records'),
    policy.RuleDefault('baremetal:node:update',
                       'rule:is_admin',
                       description='Update Node records'),
    policy.RuleDefault('baremetal:node:validate',
                       'rule:is_admin',
                       description='Request active validation of Nodes'),
    policy.RuleDefault('baremetal:node:set_maintenance',
                       'rule:is_admin',
                       description='Set maintenance flag, taking a Node '
                                   'out of service'),
    policy.RuleDefault('baremetal:node:clear_maintenance',
                       'rule:is_admin',
                       description='Clear maintenance flag, placing the Node '
                                   'into service again'),
    policy.RuleDefault('baremetal:node:set_boot_device',
                       'rule:is_admin',
                       description='Change Node boot device'),
    policy.RuleDefault('baremetal:node:set_power_state',
                       'rule:is_admin',
                       description='Change Node power status'),
    policy.RuleDefault('baremetal:node:set_provision_state',
                       'rule:is_admin',
                       description='Change Node provision status'),
    policy.RuleDefault('baremetal:node:set_raid_state',
                       'rule:is_admin',
                       description='Change Node RAID status'),
    policy.RuleDefault('baremetal:node:get_console',
                       'rule:is_admin',
                       description='Get Node console connection information'),
    policy.RuleDefault('baremetal:node:set_console_state',
                       'rule:is_admin',
                       description='Change Node console status'),
    policy.RuleDefault('baremetal:node:vif:list',
                       'rule:is_admin',
                       description='List VIFs attached to node'),
    policy.RuleDefault('baremetal:node:vif:attach',
                       'rule:is_admin',
                       description='Attach a VIF to a node'),
    policy.RuleDefault('baremetal:node:vif:detach',
                       'rule:is_admin',
                       description='Detach a VIF from a node'),
    policy.RuleDefault('baremetal:node:inject_nmi',
                       'rule:is_admin',
                       description='Inject NMI for a node'),
]

port_policies = [
    policy.RuleDefault('baremetal:port:get',
                       'rule:is_admin or rule:is_observer',
                       description='Retrieve Port records'),
    policy.RuleDefault('baremetal:port:create',
                       'rule:is_admin',
                       description='Create Port records'),
    policy.RuleDefault('baremetal:port:delete',
                       'rule:is_admin',
                       description='Delete Port records'),
    policy.RuleDefault('baremetal:port:update',
                       'rule:is_admin',
                       description='Update Port records'),
]

portgroup_policies = [
    policy.RuleDefault('baremetal:portgroup:get',
                       'rule:is_admin or rule:is_observer',
                       description='Retrieve Portgroup records'),
    policy.RuleDefault('baremetal:portgroup:create',
                       'rule:is_admin',
                       description='Create Portgroup records'),
    policy.RuleDefault('baremetal:portgroup:delete',
                       'rule:is_admin',
                       description='Delete Portgroup records'),
    policy.RuleDefault('baremetal:portgroup:update',
                       'rule:is_admin',
                       description='Update Portgroup records'),
]

chassis_policies = [
    policy.RuleDefault('baremetal:chassis:get',
                       'rule:is_admin or rule:is_observer',
                       description='Retrieve Chassis records'),
    policy.RuleDefault('baremetal:chassis:create',
                       'rule:is_admin',
                       description='Create Chassis records'),
    policy.RuleDefault('baremetal:chassis:delete',
                       'rule:is_admin',
                       description='Delete Chassis records'),
    policy.RuleDefault('baremetal:chassis:update',
                       'rule:is_admin',
                       description='Update Chassis records'),
]

driver_policies = [
    policy.RuleDefault('baremetal:driver:get',
                       'rule:is_admin or rule:is_observer',
                       description='View list of available drivers'),
    policy.RuleDefault('baremetal:driver:get_properties',
                       'rule:is_admin or rule:is_observer',
                       description='View driver-specific properties'),
    policy.RuleDefault('baremetal:driver:get_raid_logical_disk_properties',
                       'rule:is_admin or rule:is_observer',
                       description='View driver-specific RAID metadata'),

]

extra_policies = [
    policy.RuleDefault('baremetal:node:vendor_passthru',
                       'rule:is_admin',
                       description='Access vendor-specific Node functions'),
    policy.RuleDefault('baremetal:driver:vendor_passthru',
                       'rule:is_admin',
                       description='Access vendor-specific Driver functions'),
    policy.RuleDefault('baremetal:node:ipa_heartbeat',
                       'rule:public_api',
                       description='Send heartbeats from IPA ramdisk'),
    policy.RuleDefault('baremetal:driver:ipa_lookup',
                       'rule:public_api',
                       description='Access IPA ramdisk functions'),
]

volume_policies = [
    policy.RuleDefault('baremetal:volume:get',
                       'rule:is_admin or rule:is_observer',
                       description='Retrieve Volume connector and target '
                                   'records'),
    policy.RuleDefault('baremetal:volume:create',
                       'rule:is_admin',
                       description='Create Volume connector and target '
                                   'records'),
    policy.RuleDefault('baremetal:volume:delete',
                       'rule:is_admin',
                       description='Delete Volume connetor and target '
                                   'records'),
    policy.RuleDefault('baremetal:volume:update',
                       'rule:is_admin',
                       description='Update Volume connector and target '
                                   'records'),
]


def list_policies():
    policies = (default_policies
                + node_policies
                + port_policies
                + portgroup_policies
                + chassis_policies
                + driver_policies
                + extra_policies
                + volume_policies)
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

    Beginning with the Newton cycle, this should be used in place of 'enforce'.
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


def enforce(rule, target, creds, do_raise=False, exc=None, *args, **kwargs):
    """A shortcut for policy.Enforcer.enforce()

    Checks authorization of a rule against the target and credentials.
    Always returns true if CONF.auth_strategy == noauth.

    """
    # NOTE(deva): this method is obsoleted by authorize(), but retained for
    # backwards compatibility in case it has been used downstream.
    # It may be removed in the Pike cycle.
    LOG.warning("Deprecation warning: calls to ironic.common.policy.enforce() "
                "should be replaced with authorize(). This method may be "
                "removed in a future release.")
    if CONF.auth_strategy == 'noauth':
        return True
    enforcer = get_enforcer()
    return enforcer.enforce(rule, target, creds, do_raise=do_raise,
                            exc=exc, *args, **kwargs)
