# Copyright 2016 Mirantis Inc
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

import copy

from keystoneauth1 import loading as kaloading
from oslo_config import cfg
from oslo_log import log


LOG = log.getLogger(__name__)

DEFAULT_VALID_INTERFACES = ['internal', 'public']


def register_auth_opts(conf, group, service_type=None):
    """Register session- and auth-related options

    Registers only basic auth options shared by all auth plugins.
    The rest are registered at runtime depending on auth plugin used.
    """
    kaloading.register_session_conf_options(conf, group)
    kaloading.register_auth_conf_options(conf, group)
    kaloading.register_adapter_conf_options(conf, group)
    conf.set_default('valid_interfaces', DEFAULT_VALID_INTERFACES, group=group)
    # TODO(pas-ha) use os-service-type to try find the service_type by the
    # config group name assuming it is a project name (e.g. 'glance')
    if service_type:
        conf.set_default('service_type', service_type, group=group)


def add_auth_opts(options, service_type=None):
    """Add auth options to sample config

    As these are dynamically registered at runtime,
    this adds options for most used auth_plugins
    when generating sample config.
    """
    def add_options(opts, opts_to_add):
        for new_opt in opts_to_add:
            for opt in opts:
                if opt.name == new_opt.name:
                    break
            else:
                opts.append(new_opt)

    opts = copy.deepcopy(options)
    opts.insert(0, kaloading.get_auth_common_conf_options()[0])
    # NOTE(dims): There are a lot of auth plugins, we just generate
    # the config options for a few common ones
    plugins = ['password', 'v2password', 'v3password']
    for name in plugins:
        plugin = kaloading.get_plugin_loader(name)
        add_options(opts, kaloading.get_auth_plugin_conf_options(plugin))
    add_options(opts, kaloading.get_session_conf_options())
    if service_type:
        adapter_opts = kaloading.get_adapter_conf_options(
            include_deprecated=False)
        # adding defaults for valid interfaces
        cfg.set_defaults(adapter_opts, service_type=service_type,
                         valid_interfaces=DEFAULT_VALID_INTERFACES)
        add_options(opts, adapter_opts)
    opts.sort(key=lambda x: x.name)
    return opts
