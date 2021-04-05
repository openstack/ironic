# Copyright 2017 Red Hat, Inc.
# All Rights Reserved.
# Copyright (c) 2020-2021 Dell Inc. or its subsidiaries.
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

import collections
import os
from urllib import parse as urlparse

from oslo_log import log
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import strutils
import rfc3986
import tenacity

from ironic.common import exception
from ironic.common.i18n import _
from ironic.conf import CONF

sushy = importutils.try_import('sushy')

LOG = log.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'redfish_address': _('The URL address to the Redfish controller. It '
                         'must include the authority portion of the URL. '
                         'If the scheme is missing, https is assumed. '
                         'For example: https://mgmt.vendor.com. '
                         'If a path is added, it will be used as the API '
                         'endpoint root_prefix. Required'),
}

OPTIONAL_PROPERTIES = {
    'redfish_system_id': _('The canonical path to the ComputerSystem '
                           'resource that the driver will interact with. '
                           'It should include the root service, version and '
                           'the unique resource path to a ComputerSystem '
                           'within the same authority as the redfish_address '
                           'property. For example: /redfish/v1/Systems/1. '
                           'This property is only required if target BMC '
                           'manages more than one ComputerSystem. Otherwise '
                           'ironic will pick the only available '
                           'ComputerSystem automatically.'),
    'redfish_username': _('User account with admin/server-profile access '
                          'privilege. Although this property is not '
                          'mandatory it\'s highly recommended to set a '
                          'username. Optional'),
    'redfish_password': _('User account password. Although this property is '
                          'not mandatory, it\'s highly recommended to set a '
                          'password. Optional'),
    'redfish_verify_ca': _('Either a Boolean value, a path to a CA_BUNDLE '
                           'file or directory with certificates of trusted '
                           'CAs. If set to True the driver will verify the '
                           'host certificates; if False the driver will '
                           'ignore verifying the SSL certificate. If it\'s '
                           'a path the driver will use the specified '
                           'certificate or one of the certificates in the '
                           'directory. Defaults to True. Optional'),
    'redfish_auth_type': _('Redfish HTTP client authentication method. Can be '
                           '"basic", "session" or "auto". If not set, the '
                           'default value is taken from Ironic '
                           'configuration as ``[redfish]auth_type`` option.')
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)


def parse_driver_info(node):
    """Parse the information required for Ironic to connect to Redfish.

    :param node: an Ironic node object
    :returns: dictionary of parameters
    :raises: InvalidParameterValue on malformed parameter(s)
    :raises: MissingParameterValue on missing parameter(s)
    """
    driver_info = node.driver_info or {}
    missing_info = [key for key in REQUIRED_PROPERTIES
                    if not driver_info.get(key)]
    if missing_info:
        raise exception.MissingParameterValue(_(
            'Missing the following Redfish properties in node '
            '%(node)s driver_info: %(info)s') % {'node': node.uuid,
                                                 'info': missing_info})

    # Validate the Redfish address
    address = driver_info['redfish_address']
    try:
        parsed = rfc3986.uri_reference(address)
    except TypeError:
        raise exception.InvalidParameterValue(
            _('Invalid Redfish address %(address)s set in '
              'driver_info/redfish_address on node %(node)s') %
            {'address': address, 'node': node.uuid})

    if not parsed.scheme or not parsed.authority:
        address = 'https://%s' % address
        parsed = rfc3986.uri_reference(address)
    # TODO(vdrok): Workaround this check, in py3 we need to use validator class
    if not parsed.is_valid(require_scheme=True, require_authority=True):
        raise exception.InvalidParameterValue(
            _('Invalid Redfish address %(address)s set in '
              'driver_info/redfish_address on node %(node)s') %
            {'address': address, 'node': node.uuid})
    address = '{}://{}'.format(parsed.scheme, parsed.authority)

    # Obtain the Redfish root prefix from the address path
    # If not specified, default to '/redfish/v1/'
    root_prefix = parsed.path

    redfish_system_id = driver_info.get('redfish_system_id')
    if redfish_system_id is not None:
        try:
            redfish_system_id = urlparse.quote(redfish_system_id)
        except (TypeError, AttributeError):
            raise exception.InvalidParameterValue(
                _('Invalid value "%(value)s" set in '
                  'driver_info/redfish_system_id on node %(node)s. '
                  'The value should be a path (string) to the resource '
                  'that the driver will interact with. For example: '
                  '/redfish/v1/Systems/1') %
                {'value': driver_info['redfish_system_id'], 'node': node.uuid})

    # Check if verify_ca is a Boolean or a file/directory in the file-system
    verify_ca = driver_info.get('redfish_verify_ca', True)
    if isinstance(verify_ca, str):
        if os.path.isdir(verify_ca) or os.path.isfile(verify_ca):
            pass
        else:
            try:
                verify_ca = strutils.bool_from_string(verify_ca, strict=True)
            except ValueError:
                raise exception.InvalidParameterValue(
                    _('Invalid value type set in driver_info/'
                      'redfish_verify_ca on node %(node)s. '
                      'The value should be a Boolean or the path '
                      'to a file/directory, not "%(value)s"'
                      ) % {'value': verify_ca, 'node': node.uuid})
    elif isinstance(verify_ca, bool):
        # If it's a boolean it's grand, we don't need to do anything
        pass
    else:
        raise exception.InvalidParameterValue(
            _('Invalid value type set in driver_info/redfish_verify_ca '
              'on node %(node)s. The value should be a Boolean or the path '
              'to a file/directory, not "%(value)s"') % {'value': verify_ca,
                                                         'node': node.uuid})

    auth_type = driver_info.get('redfish_auth_type', CONF.redfish.auth_type)
    if auth_type not in ('basic', 'session', 'auto'):
        raise exception.InvalidParameterValue(
            _('Invalid value "%(value)s" set in '
              'driver_info/redfish_auth_type on node %(node)s. '
              'The value should be one of "basic", "session" or "auto".') %
            {'value': auth_type, 'node': node.uuid})

    sushy_params = {'address': address,
                    'system_id': redfish_system_id,
                    'username': driver_info.get('redfish_username'),
                    'password': driver_info.get('redfish_password'),
                    'verify_ca': verify_ca,
                    'auth_type': auth_type,
                    'node_uuid': node.uuid}
    if root_prefix:
        sushy_params['root_prefix'] = root_prefix

    return sushy_params


class SessionCache(object):
    """Cache of HTTP sessions credentials"""
    AUTH_CLASSES = {}
    if sushy:
        AUTH_CLASSES.update(
            basic=sushy.auth.BasicAuth,
            session=sushy.auth.SessionAuth,
            auto=sushy.auth.SessionOrBasicAuth
        )

    _sessions = collections.OrderedDict()

    def __init__(self, driver_info):
        self._driver_info = driver_info
        self._session_key = tuple(
            self._driver_info.get(key)
            for key in ('address', 'username', 'verify_ca')
        )

    def __enter__(self):
        try:
            return self.__class__._sessions[self._session_key]

        except KeyError:
            auth_type = self._driver_info['auth_type']

            auth_class = self.AUTH_CLASSES[auth_type]

            authenticator = auth_class(
                username=self._driver_info['username'],
                password=self._driver_info['password']
            )

            sushy_params = {'verify': self._driver_info['verify_ca'],
                            'auth': authenticator}
            if 'root_prefix' in self._driver_info:
                sushy_params['root_prefix'] = self._driver_info['root_prefix']
            conn = sushy.Sushy(
                self._driver_info['address'],
                **sushy_params
            )

            if CONF.redfish.connection_cache_size:
                self.__class__._sessions[self._session_key] = conn

                if (len(self.__class__._sessions)
                        > CONF.redfish.connection_cache_size):
                    self._expire_oldest_session()

            return conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        # NOTE(etingof): perhaps this session token is no good
        if isinstance(exc_val, sushy.exceptions.ConnectionError):
            self.__class__._sessions.pop(self._session_key, None)

    @classmethod
    def _expire_oldest_session(cls):
        """Expire oldest session"""
        session_keys = list(cls._sessions)
        session_key = next(iter(session_keys))
        # NOTE(etingof): GC should cause sushy to HTTP DELETE session
        # at BMC. Trouble is that contemporary sushy (1.6.0) does
        # does not do that.
        cls._sessions.pop(session_key, None)


def get_update_service(node):
    """Get a node's update service.

    :param node: an Ironic node object
    :raises: RedfishConnectionError when it fails to connect to Redfish
    :raises: RedfishError when the UpdateService is not registered in Redfish
    """

    try:
        return _get_connection(node, lambda conn: conn.get_update_service())
    except sushy.exceptions.MissingAttributeError as e:
        LOG.error('The Redfish UpdateService was not found for '
                  'node %(node)s. Error %(error)s',
                  {'node': node.uuid, 'error': e})
        raise exception.RedfishError(error=e)


def get_system(node):
    """Get a Redfish System that represents a node.

    :param node: an Ironic node object
    :raises: RedfishConnectionError when it fails to connect to Redfish
    :raises: RedfishError if the System is not registered in Redfish
    """
    driver_info = parse_driver_info(node)
    system_id = driver_info['system_id']

    try:
        return _get_connection(
            node,
            lambda conn, system_id: conn.get_system(system_id),
            system_id)
    except sushy.exceptions.ResourceNotFoundError as e:
        LOG.error('The Redfish System "%(system)s" was not found for '
                  'node %(node)s. Error %(error)s',
                  {'system': system_id or '<default>',
                   'node': node.uuid, 'error': e})
        raise exception.RedfishError(error=e)


def get_task_monitor(node, uri):
    """Get a TaskMonitor for a node.

    :param node: an Ironic node object
    :param uri: the URI of a TaskMonitor
    :raises: RedfishConnectionError when it fails to connect to Redfish
    :raises: RedfishError when the TaskMonitor is not available in Redfish
    """

    try:
        return _get_connection(node, lambda conn: conn.get_task_monitor(uri))
    except sushy.exceptions.ResourceNotFoundError as e:
        LOG.error('The Redfish TaskMonitor "%(uri)s" was not found for '
                  'node %(node)s. Error %(error)s',
                  {'uri': uri, 'node': node.uuid, 'error': e})
        raise exception.RedfishError(error=e)


def _get_connection(node, lambda_fun, *args):
    """Get a Redfish connection to a node.

    This method gets a Redfish connection to a node by calling the passed
    lambda function, and returns the sushy object returned by the function.

    :param node: an Ironic node object
    :param lambda_fun: the function to call to retrieve the desired sushy
                       object
    :param args: the arguments to pass to the function
    :returns: the sushy object returned by the lambda function
    :raises: RedfishConnectionError when it fails to connect to Redfish
    """
    driver_info = parse_driver_info(node)

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(
            exception.RedfishConnectionError),
        stop=tenacity.stop_after_attempt(CONF.redfish.connection_attempts),
        wait=tenacity.wait_fixed(CONF.redfish.connection_retry_interval),
        reraise=True)
    def _get_cached_connection(lambda_fun, *args):
        try:
            with SessionCache(driver_info) as conn:
                return lambda_fun(conn, *args)

        # TODO(lucasagomes): We should look at other types of
        # ConnectionError such as AuthenticationError or SSLError and stop
        # retrying on them
        except sushy.exceptions.ConnectionError as e:
            LOG.warning('For node %(node)s, got a connection error from '
                        'Redfish at address "%(address)s" using auth type '
                        '"%(auth_type)s". Error: %(error)s',
                        {'address': driver_info['address'],
                         'auth_type': driver_info['auth_type'],
                         'node': node.uuid, 'error': e})
            raise exception.RedfishConnectionError(node=node.uuid, error=e)

    try:
        return _get_cached_connection(lambda_fun, *args)
    except exception.RedfishConnectionError as e:
        with excutils.save_and_reraise_exception():
            LOG.error('Failed to connect to Redfish at %(address)s for '
                      'node %(node)s. Error: %(error)s',
                      {'address': driver_info['address'],
                       'node': node.uuid, 'error': e})


def get_enabled_macs(task, system):
    """Get information on MAC addresses of enabled ports using Redfish.

    :param task: a TaskManager instance containing the node to act on.
    :param system: a Redfish System object
    :returns: a dictionary containing MAC addresses of enabled interfaces
        in a {'mac': 'state'} format
    """

    if (system.ethernet_interfaces
            and system.ethernet_interfaces.summary):
        macs = system.ethernet_interfaces.summary

        # Identify ports for the NICs being in 'enabled' state
        enabled_macs = {nic_mac: nic_state
                        for nic_mac, nic_state in macs.items()
                        if nic_state == sushy.STATE_ENABLED}
        return enabled_macs
    else:
        LOG.debug("No ethernet interface information is available "
                  "for node %(node)s", {'node': task.node.uuid})


def wait_until_get_system_ready(node):
    """Wait until Redfish system is ready.

    :param node: an Ironic node object
    :raises: RedfishConnectionError on time out.
    """
    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(
            exception.RedfishConnectionError),
        stop=tenacity.stop_after_attempt(CONF.redfish.connection_attempts),
        wait=tenacity.wait_fixed(CONF.redfish.connection_retry_interval),
        reraise=True)
    def _get_system(driver_info, system_id):
        try:
            with SessionCache(driver_info) as conn:
                return conn.get_system(system_id)
        except sushy.exceptions.BadRequestError as e:
            err_msg = ("System is not ready for node %(node)s, with error"
                       "%(error)s, so retrying it",
                       {'node': node.uuid, 'error': e})
            LOG.warning(err_msg)
            raise exception.RedfishConnectionError(node=node.uuid, error=e)
    driver_info = parse_driver_info(node)
    system_id = driver_info['system_id']
    return _get_system(driver_info, system_id)
