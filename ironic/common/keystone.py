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
# NOTE(deva): import auth_token so oslo.config pulls in keystone_authtoken
from keystonemiddleware import auth_token  # noqa
from oslo.config import cfg
from six.moves.urllib import parse

from ironic.common import exception
from ironic.common.i18n import _

CONF = cfg.CONF


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
    auth_url = CONF.keystone_authtoken.auth_uri
    if not auth_url:
        raise exception.CatalogFailure(_('Keystone API endpoint is missing'))

    auth_version = CONF.keystone_authtoken.auth_version
    api_v3 = _is_apiv3(auth_url, auth_version)

    if api_v3:
        from keystoneclient.v3 import client
    else:
        from keystoneclient.v2_0 import client

    auth_url = get_keystone_url(auth_url, auth_version)
    try:
        ksclient = client.Client(username=CONF.keystone_authtoken.admin_user,
                        password=CONF.keystone_authtoken.admin_password,
                        tenant_name=CONF.keystone_authtoken.admin_tenant_name,
                        auth_url=auth_url)
    except ksexception.Unauthorized:
        raise exception.CatalogUnauthorized

    except ksexception.AuthorizationFailure as err:
        raise exception.CatalogFailure(_('Could not perform authorization '
                                         'process for service catalog: %s')
                                          % err)

    if not ksclient.has_service_catalog():
        raise exception.CatalogFailure(_('No keystone service catalog loaded'))

    try:
        endpoint = ksclient.service_catalog.url_for(service_type=service_type,
                                                endpoint_type=endpoint_type)
    except ksexception.EndpointNotFound:
        raise exception.CatalogNotFound(service_type=service_type,
                                        endpoint_type=endpoint_type)

    return endpoint
