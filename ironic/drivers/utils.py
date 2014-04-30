# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

from ironic.common import exception
from ironic.drivers import base


def _raise_unsupported_error(method=None):
    if method:
        raise exception.UnsupportedDriverExtension(_(
            "Unsupported method (%s) passed through to vendor extension.")
            % method)
    raise exception.InvalidParameterValue(_(
        "Method not specified when calling vendor extension."))


class MixinVendorInterface(base.VendorInterface):
    """Wrapper around multiple VendorInterfaces."""

    def __init__(self, mapping, driver_passthru_mapping=None):
        """Wrapper around multiple VendorInterfaces.

        :param mapping: dict of {'method': interface} specifying how to combine
                        multiple vendor interfaces into one vendor driver.
        :param driver_passthru_mapping: dict of {'method': interface}
                                        specifying how to map
                                        driver_vendor_passthru calls to
                                        interfaces.

        """
        self.mapping = mapping
        self.driver_level_mapping = driver_passthru_mapping or {}

    def _map(self, **kwargs):
        method = kwargs.get('method')
        return self.mapping.get(method) or _raise_unsupported_error(method)

    def validate(self, *args, **kwargs):
        """Call validate on the appropriate interface only.

        :raises: UnsupportedDriverExtension if 'method' can not be mapped to
                 the supported interfaces.
        :raises: InvalidParameterValue if **kwargs does not contain 'method'.

        """
        route = self._map(**kwargs)
        route.validate(*args, **kwargs)

    def vendor_passthru(self, task, **kwargs):
        """Call vendor_passthru on the appropriate interface only.

        Returns or raises according to the requested vendor_passthru method.

        :raises: UnsupportedDriverExtension if 'method' can not be mapped to
                 the supported interfaces.
        :raises: InvalidParameterValue if **kwargs does not contain 'method'.

        """
        route = self._map(**kwargs)
        return route.vendor_passthru(task, **kwargs)

    def driver_vendor_passthru(self, context, method, **kwargs):
        """Call driver_vendor_passthru on a mapped interface based on the
        specified method.

        Returns or raises according to the requested driver_vendor_passthru

        :raises: UnsupportedDriverExtension if 'method' cannot be mapped to
                 a supported interface.
        """
        iface = self.driver_level_mapping.get(method)
        if iface is None:
            _raise_unsupported_error(method)

        return iface.driver_vendor_passthru(context, method, **kwargs)


def get_node_mac_addresses(task, node):
    """Get all MAC addresses for a node.

    :param task: a TaskManager instance.
    :param node: the Node to act upon.
    :returns: A list of MAC addresses in the format xx:xx:xx:xx:xx:xx.
    """
    for r in task.resources:
        if r.node.id == node.id:
            return [p.address for p in r.ports]
