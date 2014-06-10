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

from ironic.common import exception
from ironic.openstack.common import importutils

pywsman = importutils.try_import('pywsman')


class Client(object):

    def __init__(self, drac_host, drac_port, drac_path, drac_protocol,
                 drac_username, drac_password):
        pywsman_client = pywsman.Client(drac_host, drac_port, drac_path,
                                        drac_protocol, drac_username,
                                        drac_password)
        # TODO(ifarkas): Add support for CACerts
        pywsman.wsman_transport_set_verify_peer(pywsman_client, False)

        self.client = pywsman_client

    def wsman_enumerate(self, resource_uri, options, filter=None):
        """Enumerates a remote WS-Man class.

        :param resource_uri: URI of the resource.
        :param options: client options.
        :param filter: filter for enumeration.
        :returns: array of xml responses received.
        """
        options.set_flags(pywsman.FLAG_ENUMERATION_OPTIMIZATION)
        options.set_max_elements(100)

        partial_responses = []
        doc = self.client.enumerate(options, filter, resource_uri)
        root = self._get_root(doc)
        partial_responses.append(root)

        while doc.context() is not None:
            doc = self.client.pull(options, None, resource_uri,
                                   str(doc.context()))
            root = self._get_root(doc)
            partial_responses.append(root)

        return partial_responses

    def wsman_invoke(self, resource_uri, options, method):
        """Invokes a remote WS-Man method.

        :param resource_uri: URI of the resource.
        :param options: client options.
        :param method: name of the method to invoke.
        :returns: xml response received.
        """
        doc = self.client.invoke(options, resource_uri, method)
        root = self._get_root(doc)

        return root

    def _get_root(self, doc):
        if doc is None or doc.root() is None:
            raise exception.DracClientError(
                    last_error=self.client.last_error(),
                    fault_string=self.client.fault_string(),
                    response_code=self.client.response_code())

        return doc.root()
