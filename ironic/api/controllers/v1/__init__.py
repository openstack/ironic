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

"""
Version 1 of the Ironic API

NOTE: IN PROGRESS AND NOT FULLY IMPLEMENTED.

Should maintain feature parity with Nova Baremetal Extension.

Specification can be found at ironic/doc/api/v1.rst
"""

import pecan
from pecan import rest
from webob import exc
from wsme import types as wtypes

from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers.v1 import chassis
from ironic.api.controllers.v1 import driver
from ironic.api.controllers.v1 import node
from ironic.api.controllers.v1 import port
from ironic.api import expose
from ironic.common.i18n import _

BASE_VERSION = 1

# NOTE(deva): v1.0 is reserved to indicate Juno's API, but is not presently
#             supported by the API service. All changes between Juno and the
#             point where we added microversioning are considered backwards-
#             compatible, but are not specifically discoverable at this time.
#
#             The v1.1 version indicates this "initial" version as being
#             different from Juno (v1.0), and includes the following changes:
#
# 827db7fe: Add Node.maintenance_reason
# 68eed82b: Add API endpoint to set/unset the node maintenance mode
# bc973889: Add sync and async support for passthru methods
# e03f443b: Vendor endpoints to support different HTTP methods
# e69e5309: Make vendor methods discoverable via the Ironic API
# edf532db: Add logic to store the config drive passed by Nova

# v1.1: API at the point in time when microversioning support was added
MIN_VER_STR = '1.1'

# v1.2: Renamed NOSTATE ("None") to AVAILABLE ("available")
# v1.3: Add node.driver_internal_info
# v1.4: Add MANAGEABLE state
# v1.5: Add logical node names
# v1.6: Add INSPECT* states
MAX_VER_STR = '1.6'


MIN_VER = base.Version({base.Version.string: MIN_VER_STR},
                       MIN_VER_STR, MAX_VER_STR)
MAX_VER = base.Version({base.Version.string: MAX_VER_STR},
                       MIN_VER_STR, MAX_VER_STR)


class MediaType(base.APIBase):
    """A media type representation."""

    base = wtypes.text
    type = wtypes.text

    def __init__(self, base, type):
        self.base = base
        self.type = type


class V1(base.APIBase):
    """The representation of the version 1 of the API."""

    id = wtypes.text
    """The ID of the version, also acts as the release number"""

    media_types = [MediaType]
    """An array of supported media types for this version"""

    links = [link.Link]
    """Links that point to a specific URL for this version and documentation"""

    chassis = [link.Link]
    """Links to the chassis resource"""

    nodes = [link.Link]
    """Links to the nodes resource"""

    ports = [link.Link]
    """Links to the ports resource"""

    drivers = [link.Link]
    """Links to the drivers resource"""

    @staticmethod
    def convert():
        v1 = V1()
        v1.id = "v1"
        v1.links = [link.Link.make_link('self', pecan.request.host_url,
                                        'v1', '', bookmark=True),
                    link.Link.make_link('describedby',
                                        'http://docs.openstack.org',
                                        'developer/ironic/dev',
                                        'api-spec-v1.html',
                                        bookmark=True, type='text/html')
                    ]
        v1.media_types = [MediaType('application/json',
                          'application/vnd.openstack.ironic.v1+json')]
        v1.chassis = [link.Link.make_link('self', pecan.request.host_url,
                                          'chassis', ''),
                      link.Link.make_link('bookmark',
                                           pecan.request.host_url,
                                           'chassis', '',
                                           bookmark=True)
                      ]
        v1.nodes = [link.Link.make_link('self', pecan.request.host_url,
                                        'nodes', ''),
                    link.Link.make_link('bookmark',
                                        pecan.request.host_url,
                                        'nodes', '',
                                        bookmark=True)
                    ]
        v1.ports = [link.Link.make_link('self', pecan.request.host_url,
                                        'ports', ''),
                    link.Link.make_link('bookmark',
                                        pecan.request.host_url,
                                        'ports', '',
                                        bookmark=True)
                    ]
        v1.drivers = [link.Link.make_link('self', pecan.request.host_url,
                                          'drivers', ''),
                      link.Link.make_link('bookmark',
                                          pecan.request.host_url,
                                          'drivers', '',
                                          bookmark=True)
                      ]
        return v1


class Controller(rest.RestController):
    """Version 1 API controller root."""

    nodes = node.NodesController()
    ports = port.PortsController()
    chassis = chassis.ChassisController()
    drivers = driver.DriversController()

    @expose.expose(V1)
    def get(self):
        # NOTE: The reason why convert() it's being called for every
        #       request is because we need to get the host url from
        #       the request object to make the links.
        return V1.convert()

    def _check_version(self, version, headers=None):
        if headers is None:
            headers = {}
        # ensure that major version in the URL matches the header
        if version.major != BASE_VERSION:
            raise exc.HTTPNotAcceptable(_(
                "Mutually exclusive versions requested. Version %(ver)s "
                "requested but not supported by this service. The supported "
                "version range is: [%(min)s, %(max)s].") % {'ver': version,
                'min': MIN_VER_STR, 'max': MAX_VER_STR}, headers=headers)
        # ensure the minor version is within the supported range
        if version < MIN_VER or version > MAX_VER:
            raise exc.HTTPNotAcceptable(_(
                "Version %(ver)s was requested but the minor version is not "
                "supported by this service. The supported version range is: "
                "[%(min)s, %(max)s].") % {'ver': version, 'min': MIN_VER_STR,
                                          'max': MAX_VER_STR}, headers=headers)

    @pecan.expose()
    def _route(self, args):
        v = base.Version(pecan.request.headers, MIN_VER_STR, MAX_VER_STR)

        # Always set the min and max headers
        pecan.response.headers[base.Version.min_string] = MIN_VER_STR
        pecan.response.headers[base.Version.max_string] = MAX_VER_STR

        # assert that requested version is supported
        self._check_version(v, pecan.response.headers)
        pecan.response.headers[base.Version.string] = str(v)
        pecan.request.version = v

        return super(Controller, self)._route(args)


__all__ = (Controller)
