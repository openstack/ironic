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

import functools

from keystoneauth1 import exceptions as kaexception
from keystoneauth1 import loading as kaloading
from keystoneauth1 import service_token
from keystoneauth1 import token_endpoint
from oslo_log import log as logging

from ironic.common import exception
from ironic.conf import CONF


LOG = logging.getLogger(__name__)


def ks_exceptions(f):
    """Wraps keystoneclient functions and centralizes exception handling."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except kaexception.EndpointNotFound:
            service_type = kwargs.get('service_type', 'baremetal')
            endpoint_type = kwargs.get('endpoint_type', 'internal')
            raise exception.CatalogNotFound(
                service_type=service_type, endpoint_type=endpoint_type)
        except (kaexception.Unauthorized, kaexception.AuthorizationFailure):
            raise exception.KeystoneUnauthorized()
        except (kaexception.NoMatchingPlugin,
                kaexception.MissingRequiredOptions) as e:
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
    return kaloading.load_session_from_conf_options(
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
        auth = kaloading.load_auth_from_conf_options(CONF, group,
                                                     **auth_kwargs)
    except kaexception.MissingRequiredOptions:
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
    return kaloading.load_adapter_from_conf_options(CONF, group,
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
    :param service_auth: The service authenticaiton credentals to be
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
