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

from ironic.common import exception
from ironic.conf import CONF


LOG = logging.getLogger(__name__)


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
            LOG.exception('Keystone request failed: %(msg)s',
                          {'msg': six.text_type(e)})
            raise exception.KeystoneFailure(six.text_type(e))
    return wrapper


@ks_exceptions
def get_session(group):
    try:
        auth = kaloading.load_auth_from_conf_options(CONF, group)
    except kaexception.MissingRequiredOptions:
        LOG.error('Failed to load auth plugin from group %s', group)
        raise
    session = kaloading.load_session_from_conf_options(
        CONF, group, auth=auth)
    return session


# TODO(pas-ha) we actually should barely need this at all:
# if we instantiate a identity.Token auth plugin from incoming
# request context we could build a session with it, and each client
# would know its service_type already, looking up the endpoint by itself
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
                                region_name=CONF.keystone.region_name)


# TODO(pas-ha) move all clients to sessions, then we do not need this
@ks_exceptions
def get_admin_auth_token(session):
    """Get admin token.

    Currently used for inspector, glance and swift clients.
    """
    return session.get_token()
