# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2012 Red Hat, Inc.
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

import os

from oslo_config import cfg
import osprofiler.opts as profiler_opts

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import rpc
from ironic import version


def parse_args(argv, default_config_files=None):
    # NOTE(amorin) allow wsgi app to start with custom config file/dir
    conf_file_from_env = os.environ.get('IRONIC_CONFIG_FILE')
    if conf_file_from_env and not default_config_files:
        default_config_files = [conf_file_from_env]
    conf_dir_from_env = os.environ.get('IRONIC_CONFIG_DIR')
    if conf_dir_from_env:
        default_config_dirs = [conf_dir_from_env]
    else:
        default_config_dirs = None

    rpc.set_defaults(control_exchange='ironic')
    cfg.CONF(argv[1:],
             project='ironic',
             version=version.version_info.release_string(),
             default_config_files=default_config_files,
             default_config_dirs=default_config_dirs)
    rpc.init(cfg.CONF)
    profiler_opts.set_defaults(cfg.CONF)
    validate_opts_using_custom_ironic_config_types()
    validate_image_server_auth_opts()


def validate_image_server_auth_opts():
    """Validate the image server authentication configuration.

    When an image server authentication strategy requiring credentials is
    configured, credentials must only be sent to an explicit set of trusted
    hosts unless the operator has opted in to sending them to any host. Refuse
    to start with credentials configured but no host policy, to avoid silently
    leaking them to untrusted, potentially user-supplied, hosts.

    :raises: exception.ConfigInvalid if credentials are configured without
        either ``image_server_auth_hosts`` or
        ``image_server_auth_permit_unknown_hosts``.
    """
    if cfg.CONF.deploy.image_server_auth_strategy == 'noauth':
        return
    if (cfg.CONF.deploy.image_server_password
            and not cfg.CONF.deploy.image_server_auth_hosts
            and not cfg.CONF.deploy.image_server_auth_permit_unknown_hosts):
        raise exception.ConfigInvalid(
            error_msg=_(
                "[deploy]image_server_password is configured without "
                "[deploy]image_server_auth_hosts. This would send image "
                "server credentials to every host from which images are "
                "requested, including user-supplied URLs. Configure "
                "[deploy]image_server_auth_hosts with the trusted hosts, or "
                "set [deploy]image_server_auth_permit_unknown_hosts to True "
                "to send credentials to any host."))


def validate_opts_using_custom_ironic_config_types():
    # Options using KernelParameterString
    kernel_param_opts = [
        ('inspector', 'extra_kernel_params'),
        ('pxe', 'kernel_append_params'),
        ('redfish', 'kernel_append_params'),
    ]
    # Options using ExplicitAbsolutePath
    explicit_abs_path_opts = [
        ('ansible', 'playbooks_path_allowlist'),
        ('conductor', 'file_url_allowed_paths'),
    ]
    custom_opts = kernel_param_opts + explicit_abs_path_opts

    for opt_tuple in custom_opts:
        group_name, opt_name = opt_tuple
        group = getattr(cfg.CONF, group_name)
        # NOTE(clif) Simply retrieving the option causes type
        # conversion/checking through the custom type's
        # types.ConfigType.__call__ override/implementation.
        # If conversion fails, a ValueError exception will be raised.
        getattr(group, opt_name)
