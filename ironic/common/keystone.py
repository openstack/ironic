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

from keystoneauth1 import exceptions as kaexception
from keystoneauth1 import loading as kaloading
from oslo_log import log as logging
import six
from six.moves.urllib import parse  # for legacy options loading only

from ironic.common import exception
from ironic.common.i18n import _, _LE
from ironic.conf import auth as ironic_auth
from ironic.conf import CONF


LOG = logging.getLogger(__name__)


# FIXME(pas-ha): for backward compat with legacy options loading only
def _is_apiv3(auth_url, auth_version):
    """Check if V3 version of API is being used or not.

    This method inspects auth_url and auth_version, and checks whether V3
    version of the API is being used or not.
    When no auth_version is specified and auth_url is not a versioned
    endpoint, v2.0 is assumed.
    :param auth_url: a http or https url to be inspected (like
        'http://127.0.0.1:9898/').
    :param auth_version: a string containing the version (like 'v2', 'v3.0')
                         or None
    :returns: True if V3 of the API is being used.
    """
    return auth_version == 'v3.0' or '/v3' in parse.urlparse(auth_url).path


def ks_exceptions(f):
    """Wraps keystoneclient functions and centralizes exception handling."""
    @six.wraps(f)
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
            raise exception.ConfigInvalid(six.text_type(e))
        except Exception as e:
            LOG.exception(_LE('Keystone request failed: %(msg)s'),
                          {'msg': six.text_type(e)})
            raise exception.KeystoneFailure(six.text_type(e))
    return wrapper


@ks_exceptions
def get_session(group):
    auth = ironic_auth.load_auth(CONF, group) or _get_legacy_auth()
    if not auth:
        msg = _("Failed to load auth from either [%(new)s] or [%(old)s] "
                "config sections.")
        raise exception.ConfigInvalid(message=msg, new=group,
                                      old=ironic_auth.LEGACY_SECTION)
    session = kaloading.load_session_from_conf_options(
        CONF, group, auth=auth)
    return session


# FIXME(pas-ha) remove legacy path after deprecation
def _get_legacy_auth():
    """Load auth from keystone_authtoken config section

    Used only to provide backward compatibility with old configs.
    """
    conf = getattr(CONF, ironic_auth.LEGACY_SECTION)
    # NOTE(pas-ha) first try to load auth from legacy section
    # using the new keystoneauth options that might be already set there
    auth = ironic_auth.load_auth(CONF, ironic_auth.LEGACY_SECTION)
    if auth:
        return auth
    # NOTE(pas-ha) now we surely have legacy config section for auth
    # and with legacy options set in it, deal with it.
    legacy_loader = kaloading.get_plugin_loader('password')
    auth_params = {
        'auth_url': conf.auth_uri,
        'username': conf.admin_user,
        'password': conf.admin_password,
        'tenant_name': conf.admin_tenant_name
    }
    api_v3 = _is_apiv3(conf.auth_uri, conf.auth_version)
    if api_v3:
        # NOTE(pas-ha): mimic defaults of keystoneclient
        auth_params.update({
            'project_domain_id': 'default',
            'user_domain_id': 'default',
        })
    return legacy_loader.load_from_options(**auth_params)


@ks_exceptions
def get_service_url(session, service_type='baremetal',
                    endpoint_type='internal'):
    """Wrapper for get service url from keystone service catalog.

    Given a service_type and an endpoint_type, this method queries
    keystone service catalog and provides the url for the desired
    endpoint.

    :param service_type: the keystone service for which url is required.
    :param endpoint_type: the type of endpoint for the service.
    :returns: an http/https url for the desired endpoint.
    """
    return session.get_endpoint(service_type=service_type,
                                interface=endpoint_type,
                                region=CONF.keystone.region_name)


@ks_exceptions
def get_admin_auth_token(session):
    """Get admin token.

    Currently used for inspector, glance and swift clients.
    Only swift client does not actually support using sessions directly,
    LP #1518938, others will be updated in ironic code.
    """
    return session.get_token()
