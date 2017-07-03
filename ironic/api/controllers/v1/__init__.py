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

Specification can be found at doc/source/webapi/v1.rst
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
from ironic.api.controllers.v1 import portgroup
from ironic.api.controllers.v1 import ramdisk
from ironic.api.controllers.v1 import utils
from ironic.api.controllers.v1 import versions
from ironic.api.controllers.v1 import volume
from ironic.api import expose
from ironic.common.i18n import _

BASE_VERSION = versions.BASE_VERSION

MIN_VER = base.Version(
    {base.Version.string: versions.MIN_VERSION_STRING},
    versions.MIN_VERSION_STRING, versions.MAX_VERSION_STRING)
MAX_VER = base.Version(
    {base.Version.string: versions.MAX_VERSION_STRING},
    versions.MIN_VERSION_STRING, versions.MAX_VERSION_STRING)


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

    portgroups = [link.Link]
    """Links to the portgroups resource"""

    drivers = [link.Link]
    """Links to the drivers resource"""

    volume = [link.Link]
    """Links to the volume resource"""

    lookup = [link.Link]
    """Links to the lookup resource"""

    heartbeat = [link.Link]
    """Links to the heartbeat resource"""

    @staticmethod
    def convert():
        v1 = V1()
        v1.id = "v1"
        v1.links = [link.Link.make_link('self', pecan.request.public_url,
                                        'v1', '', bookmark=True),
                    link.Link.make_link('describedby',
                                        'https://docs.openstack.org',
                                        '/ironic/latest/contributor/',
                                        'webapi.html',
                                        bookmark=True, type='text/html')
                    ]
        v1.media_types = [MediaType('application/json',
                          'application/vnd.openstack.ironic.v1+json')]
        v1.chassis = [link.Link.make_link('self', pecan.request.public_url,
                                          'chassis', ''),
                      link.Link.make_link('bookmark',
                                          pecan.request.public_url,
                                          'chassis', '',
                                          bookmark=True)
                      ]
        v1.nodes = [link.Link.make_link('self', pecan.request.public_url,
                                        'nodes', ''),
                    link.Link.make_link('bookmark',
                                        pecan.request.public_url,
                                        'nodes', '',
                                        bookmark=True)
                    ]
        v1.ports = [link.Link.make_link('self', pecan.request.public_url,
                                        'ports', ''),
                    link.Link.make_link('bookmark',
                                        pecan.request.public_url,
                                        'ports', '',
                                        bookmark=True)
                    ]
        if utils.allow_portgroups():
            v1.portgroups = [
                link.Link.make_link('self', pecan.request.public_url,
                                    'portgroups', ''),
                link.Link.make_link('bookmark', pecan.request.public_url,
                                    'portgroups', '', bookmark=True)
            ]
        v1.drivers = [link.Link.make_link('self', pecan.request.public_url,
                                          'drivers', ''),
                      link.Link.make_link('bookmark',
                                          pecan.request.public_url,
                                          'drivers', '',
                                          bookmark=True)
                      ]
        if utils.allow_volume():
            v1.volume = [
                link.Link.make_link('self',
                                    pecan.request.public_url,
                                    'volume', ''),
                link.Link.make_link('bookmark',
                                    pecan.request.public_url,
                                    'volume', '',
                                    bookmark=True)
            ]
        if utils.allow_ramdisk_endpoints():
            v1.lookup = [link.Link.make_link('self', pecan.request.public_url,
                                             'lookup', ''),
                         link.Link.make_link('bookmark',
                                             pecan.request.public_url,
                                             'lookup', '',
                                             bookmark=True)
                         ]
            v1.heartbeat = [link.Link.make_link('self',
                                                pecan.request.public_url,
                                                'heartbeat', ''),
                            link.Link.make_link('bookmark',
                                                pecan.request.public_url,
                                                'heartbeat', '',
                                                bookmark=True)
                            ]
        return v1


class Controller(rest.RestController):
    """Version 1 API controller root."""

    nodes = node.NodesController()
    ports = port.PortsController()
    portgroups = portgroup.PortgroupsController()
    chassis = chassis.ChassisController()
    drivers = driver.DriversController()
    volume = volume.VolumeController()
    lookup = ramdisk.LookupController()
    heartbeat = ramdisk.HeartbeatController()

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
                "version range is: [%(min)s, %(max)s].") %
                {'ver': version, 'min': versions.MIN_VERSION_STRING,
                 'max': versions.MAX_VERSION_STRING},
                headers=headers)
        # ensure the minor version is within the supported range
        if version < MIN_VER or version > MAX_VER:
            raise exc.HTTPNotAcceptable(_(
                "Version %(ver)s was requested but the minor version is not "
                "supported by this service. The supported version range is: "
                "[%(min)s, %(max)s].") %
                {'ver': version, 'min': versions.MIN_VERSION_STRING,
                 'max': versions.MAX_VERSION_STRING},
                headers=headers)

    @pecan.expose()
    def _route(self, args, request=None):
        v = base.Version(pecan.request.headers, versions.MIN_VERSION_STRING,
                         versions.MAX_VERSION_STRING)

        # Always set the min and max headers
        pecan.response.headers[base.Version.min_string] = (
            versions.MIN_VERSION_STRING)
        pecan.response.headers[base.Version.max_string] = (
            versions.MAX_VERSION_STRING)

        # assert that requested version is supported
        self._check_version(v, pecan.response.headers)
        pecan.response.headers[base.Version.string] = str(v)
        pecan.request.version = v

        return super(Controller, self)._route(args, request)


__all__ = ('Controller',)
