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

from keystoneauth1 import exceptions as kaexception
from keystoneauth1 import loading as kaloading
from oslo_config import cfg


LEGACY_SECTION = 'keystone_authtoken'
OLD_SESSION_OPTS = {
    'certfile': [cfg.DeprecatedOpt('certfile', LEGACY_SECTION)],
    'keyfile': [cfg.DeprecatedOpt('keyfile', LEGACY_SECTION)],
    'cafile': [cfg.DeprecatedOpt('cafile', LEGACY_SECTION)],
    'insecure': [cfg.DeprecatedOpt('insecure', LEGACY_SECTION)],
    'timeout': [cfg.DeprecatedOpt('timeout', LEGACY_SECTION)],
}

# FIXME(pas-ha) remove import of auth_token section after deprecation period
cfg.CONF.import_group(LEGACY_SECTION, 'keystonemiddleware.auth_token')


def load_auth(conf, group):
    try:
        auth = kaloading.load_auth_from_conf_options(conf, group)
    except kaexception.MissingRequiredOptions:
        auth = None
    return auth


def register_auth_opts(conf, group):
    """Register session- and auth-related options

    Registers only basic auth options shared by all auth plugins.
    The rest are registered at runtime depending on auth plugin used.
    """
    kaloading.register_session_conf_options(
        conf, group, deprecated_opts=OLD_SESSION_OPTS)
    kaloading.register_auth_conf_options(conf, group)


def add_auth_opts(options):
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
    opts.sort(key=lambda x: x.name)
    return opts
