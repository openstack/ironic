# All Rights Reserved.
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

import datetime

from webob import exc
import wsme
from wsme import types as wtypes

from ironic.common.i18n import _


class APIBase(wtypes.Base):

    created_at = wsme.wsattr(datetime.datetime, readonly=True)
    """The time in UTC at which the object is created"""

    updated_at = wsme.wsattr(datetime.datetime, readonly=True)
    """The time in UTC at which the object is updated"""

    def as_dict(self):
        """Render this object as a dict of its fields."""
        return dict((k, getattr(self, k))
                    for k in self.fields
                    if hasattr(self, k) and
                    getattr(self, k) != wsme.Unset)

    def unset_fields_except(self, except_list=None):
        """Unset fields so they don't appear in the message body.

        :param except_list: A list of fields that won't be touched.

        """
        if except_list is None:
            except_list = []

        for k in self.as_dict():
            if k not in except_list:
                setattr(self, k, wsme.Unset)


class Version(object):
    """API Version object."""

    string = 'X-OpenStack-Ironic-API-Version'
    """HTTP Header string carrying the requested version"""

    min_string = 'X-OpenStack-Ironic-API-Minimum-Version'
    """HTTP reponse header"""

    max_string = 'X-OpenStack-Ironic-API-Maximum-Version'
    """HTTP response header"""

    def __init__(self, headers):
        """Create an API Version object from the supplied headers.

        :param headers: webob headers
        :raises: webob.HTTPNotAcceptable
        """
        (self.major, self.minor) = Version.parse_headers(headers)

    def __repr__(self):
        return '%s.%s' % (self.major, self.minor)

    @staticmethod
    def parse_headers(headers):
        """Determine the API version requested based on the headers supplied.

        :param headers: webob headers
        :returns: a tupe of (major, minor) version numbers
        :raises: webob.HTTPNotAcceptable
        """
        try:
            # default to the minimum supported version,  but don't actually
            # import v1.__init__ here because that would be circular...
            version = tuple(int(i) for i in headers.get(
                    Version.string, '1.1').split('.'))
        except ValueError:
            version = ()
        if len(version) != 2:
            raise exc.HTTPNotAcceptable(_(
                "Invalid value for X-OpenStack-Ironic-API-Version "
                "header."))
        return version

    def __lt__(a, b):
        if (a.major == b.major and a.minor < b.minor):
            return True
        return False

    def __gt__(a, b):
        if (a.major == b.major and a.minor > b.minor):
            return True
        return False
