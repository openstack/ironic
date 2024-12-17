# coding=utf-8
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

"""Central place for handling Keystone authorization and service lookup."""

import copy
import functools

from keystoneauth1 import exceptions as ks_exception
from keystoneauth1 import loading as ks_loading
from keystoneauth1 import service_token
from keystoneauth1 import token_endpoint
import os_service_types
from oslo_config import cfg
from oslo_log import log as logging

from ironic.common import exception


LOG = logging.getLogger(__name__)

DEFAULT_VALID_INTERFACES = ['internal', 'public']

CONF = cfg.CONF


def ks_exceptions(f):
    """Wraps keystoneclient functions and centralizes exception handling."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ks_exception.EndpointNotFound:
            service_type = kwargs.get('service_type', 'baremetal')
            endpoint_type = kwargs.get('endpoint_type', 'internal')
            raise exception.CatalogNotFound(
                service_type=service_type, endpoint_type=endpoint_type)
        except (ks_exception.Unauthorized, ks_exception.AuthorizationFailure):
            raise exception.KeystoneUnauthorized()
        except (ks_exception.NoMatchingPlugin,
                ks_exception.MissingRequiredOptions) as e:
            raise exception.ConfigInvalid(str(e))
        except Exception as e:
            LOG.exception('Keystone request failed: %(msg)s',
                          {'msg': str(e)})
            raise exception.KeystoneFailure(str(e))
    return wrapper


@ks_exceptions
def get_session(group, **session_kwargs):
    """Loads session object from options in a configuration file section.

    The session_kwargs will be passed directly to keystoneauth1 Session
    and will override the values loaded from config.
    Consult keystoneauth1 docs for available options.

    :param group: name of the config section to load session options from

    """
    return ks_loading.load_session_from_conf_options(
        CONF, group, **session_kwargs)


@ks_exceptions
def get_auth(group, **auth_kwargs):
    """Loads auth plugin from options in a configuration file section.

    The auth_kwargs will be passed directly to keystoneauth1 auth plugin
    and will override the values loaded from config.
    Note that the accepted kwargs will depend on auth plugin type as defined
    by [group]auth_type option.
    Consult keystoneauth1 docs for available auth plugins and their options.

    :param group: name of the config section to load auth plugin options from

    """
    try:
        auth = ks_loading.load_auth_from_conf_options(CONF, group,
                                                      **auth_kwargs)
    except ks_exception.MissingRequiredOptions:
        LOG.error('Failed to load auth plugin from group %s', group)
        raise
    return auth


@ks_exceptions
def get_adapter(group, **adapter_kwargs):
    """Loads adapter from options in a configuration file section.

    The adapter_kwargs will be passed directly to keystoneauth1 Adapter
    and will override the values loaded from config.
    Consult keystoneauth1 docs for available adapter options.

    :param group: name of the config section to load adapter options from

    """
    return ks_loading.load_adapter_from_conf_options(CONF, group,
                                                     **adapter_kwargs)


def get_endpoint(group, **adapter_kwargs):
    """Get an endpoint from an adapter.

    The adapter_kwargs will be passed directly to keystoneauth1 Adapter
    and will override the values loaded from config.
    Consult keystoneauth1 docs for available adapter options.

    :param group: name of the config section to load adapter options from
    :raises: CatalogNotFound if the endpoint is not found
    """
    result = get_adapter(group, **adapter_kwargs).get_endpoint()
    if not result:
        service_type = adapter_kwargs.get(
            'service_type',
            getattr(getattr(CONF, group), 'service_type', group))
        endpoint_type = adapter_kwargs.get('endpoint_type', 'internal')
        raise exception.CatalogNotFound(
            service_type=service_type, endpoint_type=endpoint_type)
    return result


def get_service_auth(context, endpoint, service_auth,
                     only_service_auth=False):
    """Create auth plugin wrapping both user and service auth.

    When properly configured and using auth_token middleware,
    requests with valid service auth will not fail
    if the user token is expired.

    Ideally we would use the plugin provided by auth_token middleware
    however this plugin isn't serialized yet.

    :param context: The RequestContext instance from which the user
                    auth_token is extracted.
    :param endpoint: The requested endpoint to be utilized.
    :param service_auth: The service authentication credentals to be
                         used.
    :param only_service_auth: Boolean, default False. When set to True,
                              the resulting Service token pair is generated
                              as if it originates from the user itself.
                              Useful to cast admin level operations which are
                              launched by Ironic itself, as opposed to user
                              initiated requests.
    :returns: Returns a service token via the ServiceTokenAuthWrapper
              class.
    """
    user_auth = None
    if not only_service_auth:
        user_auth = token_endpoint.Token(endpoint, context.auth_token)
    else:
        user_auth = service_auth
    return service_token.ServiceTokenAuthWrapper(user_auth=user_auth,
                                                 service_auth=service_auth)


def register_auth_opts(conf, group, service_type=None):
    """Register session- and auth-related options

    Registers only basic auth options shared by all auth plugins.
    The rest are registered at runtime depending on auth plugin used.
    """
    ks_loading.register_session_conf_options(conf, group)
    ks_loading.register_auth_conf_options(conf, group)
    CONF.set_default('auth_type', default='password', group=group)
    ks_loading.register_adapter_conf_options(conf, group)
    conf.set_default('valid_interfaces', DEFAULT_VALID_INTERFACES, group=group)
    if service_type:
        conf.set_default('service_type', service_type, group=group)
    else:
        types = os_service_types.get_service_types()
        key = 'ironic-inspector' if group == 'inspector' else group
        service_types = types.service_types_by_project.get(key)
        if service_types:
            conf.set_default('service_type', service_types[0], group=group)


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
    opts.insert(0, ks_loading.get_auth_common_conf_options()[0])
    # NOTE(dims): There are a lot of auth plugins, we just generate
    # the config options for a few common ones
    plugins = ['password', 'v2password', 'v3password']
    for name in plugins:
        plugin = ks_loading.get_plugin_loader(name)
        add_options(opts, ks_loading.get_auth_plugin_conf_options(plugin))
    add_options(opts, ks_loading.get_session_conf_options())
    if service_type:
        adapter_opts = ks_loading.get_adapter_conf_options(
            include_deprecated=False)
        # adding defaults for valid interfaces
        cfg.set_defaults(adapter_opts, service_type=service_type,
                         valid_interfaces=DEFAULT_VALID_INTERFACES)
        add_options(opts, adapter_opts)
    opts.sort(key=lambda x: x.name)
    return opts
