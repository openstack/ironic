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
        raise exception.InvalidParameterValue(_(
            "Unsupported method (%s) passed through to vendor extension.")
            % method)
    raise exception.InvalidParameterValue(_(
        "Method not specified when calling vendor extension."))


class MixinVendorInterface(base.VendorInterface):
    """Wrapper around multiple VendorInterfaces."""

    def __init__(self, mapping):
        self.mapping = mapping

    def _map(self, **kwargs):
        """Map methods to interfaces.

        :returns: an instance of a VendorInterface
        :raises: InvalidParameterValue if **kwargs does not contain 'method'
                 or if the method can not be mapped to an interface.
        """
        method = kwargs.get('method')
        return self.mapping.get(method) or _raise_unsupported_error(method)

    def validate(self, *args, **kwargs):
        """Call validate on the appropriate interface only."""
        route = self._map(**kwargs)
        route.validate(*args, **kwargs)

    def vendor_passthru(self, task, node, **kwargs):
        """Call vendor_passthru on the appropriate interface only."""
        route = self._map(**kwargs)
        return route.vendor_passthru(task, node, **kwargs)
