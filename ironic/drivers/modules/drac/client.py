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

"""
Wrapper for pywsman.Client
"""

import time
from xml.etree import ElementTree

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LW
from ironic.drivers.modules.drac import common as drac_common

pywsman = importutils.try_import('pywsman')

opts = [
    cfg.IntOpt('client_retry_count',
               default=5,
               help=_('In case there is a communication failure, the DRAC '
                      'client resends the request as many times as '
                      'defined in this setting.')),
    cfg.IntOpt('client_retry_delay',
               default=5,
               help=_('In case there is a communication failure, the DRAC '
                      'client waits for as many seconds as defined '
                      'in this setting before resending the request.'))
]

CONF = cfg.CONF
opt_group = cfg.OptGroup(name='drac',
                         title='Options for the DRAC driver')
CONF.register_group(opt_group)
CONF.register_opts(opts, opt_group)

LOG = logging.getLogger(__name__)

_SOAP_ENVELOPE_URI = 'http://www.w3.org/2003/05/soap-envelope'

# Filter Dialects, see (Section 2.3.1):
# http://en.community.dell.com/techcenter/extras/m/white_papers/20439105.aspx
_FILTER_DIALECT_MAP = {'cql': 'http://schemas.dmtf.org/wbem/cql/1/dsp0202.pdf',
                       'wql': 'http://schemas.microsoft.com/wbem/wsman/1/WQL'}

# ReturnValue constants
RET_SUCCESS = '0'
RET_ERROR = '2'
RET_CREATED = '4096'


def get_wsman_client(node):
    """Return a DRAC client object.

    Given an ironic node object, this method gives back a
    Client object which is a wrapper for pywsman.Client.

    :param node: an ironic node object.
    :returns: a Client object.
    :raises: InvalidParameterValue if some mandatory information
             is missing on the node or on invalid inputs.
    """
    driver_info = drac_common.parse_driver_info(node)
    client = Client(**driver_info)
    return client


def retry_on_empty_response(client, action, *args, **kwargs):
    """Wrapper to retry an action on failure."""

    func = getattr(client, action)
    for i in range(CONF.drac.client_retry_count):
        response = func(*args, **kwargs)
        if response:
            return response
        else:
            LOG.warning(_LW('Empty response on calling %(action)s on client. '
                            'Last error (cURL error code): %(last_error)s, '
                            'fault string: "%(fault_string)s" '
                            'response_code: %(response_code)s. '
                            'Retry attempt %(count)d') %
                        {'action': action,
                         'last_error': client.last_error(),
                         'fault_string': client.fault_string(),
                         'response_code': client.response_code(),
                         'count': i + 1})

            time.sleep(CONF.drac.client_retry_delay)


class Client(object):

    def __init__(self, drac_host, drac_port, drac_path, drac_protocol,
                 drac_username, drac_password):
        pywsman_client = pywsman.Client(drac_host, drac_port, drac_path,
                                        drac_protocol, drac_username,
                                        drac_password)
        # TODO(ifarkas): Add support for CACerts
        pywsman.wsman_transport_set_verify_peer(pywsman_client, False)
        pywsman.wsman_transport_set_verify_host(pywsman_client, False)

        self.client = pywsman_client

    def wsman_enumerate(self, resource_uri, filter_query=None,
                        filter_dialect='cql'):
        """Enumerates a remote WS-Man class.

        :param resource_uri: URI of the resource.
        :param filter_query: the query string.
        :param filter_dialect: the filter dialect. Valid options are:
                               'cql' and 'wql'. Defaults to 'cql'.
        :raises: DracClientError on an error from pywsman library.
        :raises: DracInvalidFilterDialect if an invalid filter dialect
                 was specified.
        :returns: an ElementTree object of the response received.
        """
        options = pywsman.ClientOptions()

        filter_ = None
        if filter_query is not None:
            try:
                filter_dialect = _FILTER_DIALECT_MAP[filter_dialect]
            except KeyError:
                valid_opts = ', '.join(_FILTER_DIALECT_MAP)
                raise exception.DracInvalidFilterDialect(
                    invalid_filter=filter_dialect, supported=valid_opts)

            filter_ = pywsman.Filter()
            filter_.simple(filter_dialect, filter_query)

        options.set_flags(pywsman.FLAG_ENUMERATION_OPTIMIZATION)
        options.set_max_elements(100)

        doc = retry_on_empty_response(self.client, 'enumerate',
                                      options, filter_, resource_uri)
        root = self._get_root(doc)
        LOG.debug("WSMAN enumerate returned raw XML: %s",
                  ElementTree.tostring(root))

        final_xml = root
        find_query = './/{%s}Body' % _SOAP_ENVELOPE_URI
        insertion_point = final_xml.find(find_query)
        while doc.context() is not None:
            doc = retry_on_empty_response(self.client, 'pull', options, None,
                                          resource_uri, str(doc.context()))
            root = self._get_root(doc)
            LOG.debug("WSMAN pull returned raw XML: %s",
                      ElementTree.tostring(root))

            for result in root.findall(find_query):
                for child in list(result):
                    insertion_point.append(child)

        return final_xml

    def wsman_invoke(self, resource_uri, method, selectors=None,
                     properties=None, expected_return=None):
        """Invokes a remote WS-Man method.

        :param resource_uri: URI of the resource.
        :param method: name of the method to invoke.
        :param selectors: dictionary of selectors.
        :param properties: dictionary of properties.
        :param expected_return: expected return value.
        :raises: DracClientError on an error from pywsman library.
        :raises: DracOperationFailed on error reported back by DRAC.
        :raises: DracUnexpectedReturnValue on return value mismatch.
        :returns: an ElementTree object of the response received.
        """
        if selectors is None:
            selectors = {}

        if properties is None:
            properties = {}

        options = pywsman.ClientOptions()

        for name, value in selectors.items():
            options.add_selector(name, value)

        # NOTE(ifarkas): manually constructing the XML doc should be deleted
        #                once pywsman supports passing a list as a property.
        #                For now this is only a fallback method: in case no
        #                list provided, the supported pywsman API will be used.
        list_included = any([isinstance(prop_item, list) for prop_item
                             in properties.values()])
        if list_included:
            xml_doc = pywsman.XmlDoc('%s_INPUT' % method, resource_uri)
            xml_root = xml_doc.root()

            for name, value in properties.items():
                if isinstance(value, list):
                    for item in value:
                        xml_root.add(resource_uri, str(name), str(item))
                else:
                    xml_root.add(resource_uri, name, value)
            LOG.debug(('WSMAN invoking: %(resource_uri)s:%(method)s'
                       '\nselectors: %(selectors)r\nxml: %(xml)s'),
                      {
                          'resource_uri': resource_uri,
                          'method': method,
                          'selectors': selectors,
                          'xml': xml_root.string()})

        else:
            xml_doc = None

            for name, value in properties.items():
                options.add_property(name, value)

            LOG.debug(('WSMAN invoking: %(resource_uri)s:%(method)s'
                       '\nselectors: %(selectors)r\properties: %(props)r') % {
                           'resource_uri': resource_uri,
                           'method': method,
                           'selectors': selectors,
                           'props': properties})

        doc = retry_on_empty_response(self.client, 'invoke', options,
                                      resource_uri, method, xml_doc)
        root = self._get_root(doc)
        LOG.debug("WSMAN invoke returned raw XML: %s",
                  ElementTree.tostring(root))

        return_value = drac_common.find_xml(root, 'ReturnValue',
                                            resource_uri).text
        if return_value == RET_ERROR:
            messages = drac_common.find_xml(root, 'Message',
                                            resource_uri, True)
            message_args = drac_common.find_xml(root, 'MessageArguments',
                                                resource_uri, True)

            if message_args:
                messages = [m.text % p.text for (m, p) in
                            zip(messages, message_args)]
            else:
                messages = [m.text for m in messages]

            raise exception.DracOperationFailed(message='%r' % messages)

        if expected_return and return_value != expected_return:
            raise exception.DracUnexpectedReturnValue(
                expected_return_value=expected_return,
                actual_return_value=return_value)

        return root

    def _get_root(self, doc):
        if doc is None or doc.root() is None:
            raise exception.DracClientError(
                last_error=self.client.last_error(),
                fault_string=self.client.fault_string(),
                response_code=self.client.response_code())
        root = doc.root()
        return ElementTree.fromstring(root.string())
