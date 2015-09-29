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

from keystoneclient import exceptions as ksexception
from oslo_concurrency import lockutils
from oslo_config import cfg
from six.moves.urllib import parse

from ironic.common import exception
from ironic.common.i18n import _

CONF = cfg.CONF

keystone_opts = [
    cfg.StrOpt('region_name',
               help=_('The region used for getting endpoints of OpenStack'
                      ' services.')),
]

CONF.register_opts(keystone_opts, group='keystone')
CONF.import_group('keystone_authtoken', 'keystonemiddleware.auth_token')

_KS_CLIENT = None


def _is_apiv3(auth_url, auth_version):
    """Checks if V3 version of API is being used or not.

    This method inspects auth_url and auth_version, and checks whether V3
    version of the API is being used or not.

    :param auth_url: a http or https url to be inspected (like
        'http://127.0.0.1:9898/').
    :param auth_version: a string containing the version (like 'v2', 'v3.0')
    :returns: True if V3 of the API is being used.
    """
    return auth_version == 'v3.0' or '/v3' in parse.urlparse(auth_url).path


def _get_ksclient(token=None):
    auth_url = CONF.keystone_authtoken.auth_uri
    if not auth_url:
        raise exception.KeystoneFailure(_('Keystone API endpoint is missing'))

    auth_version = CONF.keystone_authtoken.auth_version
    api_v3 = _is_apiv3(auth_url, auth_version)

    if api_v3:
        from keystoneclient.v3 import client
    else:
        from keystoneclient.v2_0 import client

    auth_url = get_keystone_url(auth_url, auth_version)
    try:
        if token:
            return client.Client(token=token, auth_url=auth_url)
        else:
            params = {'username': CONF.keystone_authtoken.admin_user,
                      'password': CONF.keystone_authtoken.admin_password,
                      'tenant_name': CONF.keystone_authtoken.admin_tenant_name,
                      'region_name': CONF.keystone.region_name,
                      'auth_url': auth_url}
            return _get_ksclient_from_conf(client, **params)
    except ksexception.Unauthorized:
        raise exception.KeystoneUnauthorized()
    except ksexception.AuthorizationFailure as err:
        raise exception.KeystoneFailure(_('Could not authorize in Keystone:'
                                          ' %s') % err)


@lockutils.synchronized('keystone_client', 'ironic-')
def _get_ksclient_from_conf(client, **params):
    global _KS_CLIENT
    # NOTE(yuriyz): use Keystone client default gap, to determine whether the
    # given token is about to expire
    if _KS_CLIENT is None or _KS_CLIENT.auth_ref.will_expire_soon():
        _KS_CLIENT = client.Client(**params)
    return _KS_CLIENT


def get_keystone_url(auth_url, auth_version):
    """Gives an http/https url to contact keystone.

    Given an auth_url and auth_version, this method generates the url in
    which keystone can be reached.

    :param auth_url: a http or https url to be inspected (like
        'http://127.0.0.1:9898/').
    :param auth_version: a string containing the version (like v2, v3.0, etc)
    :returns: a string containing the keystone url
    """
    api_v3 = _is_apiv3(auth_url, auth_version)
    api_version = 'v3' if api_v3 else 'v2.0'
    # NOTE(lucasagomes): Get rid of the trailing '/' otherwise urljoin()
    #   fails to override the version in the URL
    return parse.urljoin(auth_url.rstrip('/'), api_version)


def get_service_url(service_type='baremetal', endpoint_type='internal'):
    """Wrapper for get service url from keystone service catalog.

    Given a service_type and an endpoint_type, this method queries keystone
    service catalog and provides the url for the desired endpoint.

    :param service_type: the keystone service for which url is required.
    :param endpoint_type: the type of endpoint for the service.
    :returns: an http/https url for the desired endpoint.
    """
    ksclient = _get_ksclient()

    if not ksclient.has_service_catalog():
        raise exception.KeystoneFailure(_('No Keystone service catalog '
                                          'loaded'))

    try:
        endpoint = ksclient.service_catalog.url_for(
            service_type=service_type,
            endpoint_type=endpoint_type,
            region_name=CONF.keystone.region_name)

    except ksexception.EndpointNotFound:
        raise exception.CatalogNotFound(service_type=service_type,
                                        endpoint_type=endpoint_type)

    return endpoint


def get_admin_auth_token():
    """Get an admin auth_token from the Keystone."""
    ksclient = _get_ksclient()
    return ksclient.auth_token


def token_expires_soon(token, duration=None):
    """Determines if token expiration is about to occur.

    :param duration: time interval in seconds
    :returns: boolean : true if expiration is within the given duration
    """
    ksclient = _get_ksclient(token=token)
    return ksclient.auth_ref.will_expire_soon(stale_duration=duration)
