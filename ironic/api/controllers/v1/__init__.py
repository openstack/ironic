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

from ironic import api
from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers.v1 import allocation
from ironic.api.controllers.v1 import chassis
from ironic.api.controllers.v1 import conductor
from ironic.api.controllers.v1 import deploy_template
from ironic.api.controllers.v1 import driver
from ironic.api.controllers.v1 import event
from ironic.api.controllers.v1 import node
from ironic.api.controllers.v1 import port
from ironic.api.controllers.v1 import portgroup
from ironic.api.controllers.v1 import ramdisk
from ironic.api.controllers.v1 import utils
from ironic.api.controllers.v1 import versions
from ironic.api.controllers.v1 import volume
from ironic.api.controllers import version
from ironic.api import expose
from ironic.common.i18n import _

BASE_VERSION = versions.BASE_VERSION


def min_version():
    return base.Version(
        {base.Version.string: versions.min_version_string()},
        versions.min_version_string(), versions.max_version_string())


def max_version():
    return base.Version(
        {base.Version.string: versions.max_version_string()},
        versions.min_version_string(), versions.max_version_string())


class MediaType(base.Base):
    """A media type representation."""

    base = str
    type = str

    def __init__(self, base, type):
        self.base = base
        self.type = type


class V1(base.Base):
    """The representation of the version 1 of the API."""

    id = str
    """The ID of the version, also acts as the release number"""

    media_types = [MediaType]
    """An array of supported media types for this version"""

    links = None
    """Links that point to a specific URL for this version and documentation"""

    chassis = None
    """Links to the chassis resource"""

    nodes = None
    """Links to the nodes resource"""

    ports = None
    """Links to the ports resource"""

    portgroups = None
    """Links to the portgroups resource"""

    drivers = None
    """Links to the drivers resource"""

    volume = None
    """Links to the volume resource"""

    lookup = None
    """Links to the lookup resource"""

    heartbeat = None
    """Links to the heartbeat resource"""

    conductors = None
    """Links to the conductors resource"""

    allocations = None
    """Links to the allocations resource"""

    deploy_templates = None
    """Links to the deploy_templates resource"""

    version = version.Version
    """Version discovery information."""

    events = None
    """Links to the events resource"""

    @staticmethod
    def convert():
        v1 = V1()
        v1.id = "v1"
        v1.links = [link.make_link('self', api.request.public_url,
                                   'v1', '', bookmark=True),
                    link.make_link('describedby',
                                   'https://docs.openstack.org',
                                   '/ironic/latest/contributor/',
                                   'webapi.html',
                                   bookmark=True, type='text/html')
                    ]
        v1.media_types = [MediaType('application/json',
                          'application/vnd.openstack.ironic.v1+json')]
        v1.chassis = [link.make_link('self', api.request.public_url,
                                     'chassis', ''),
                      link.make_link('bookmark',
                                     api.request.public_url,
                                     'chassis', '',
                                     bookmark=True)
                      ]
        v1.nodes = [link.make_link('self', api.request.public_url,
                                   'nodes', ''),
                    link.make_link('bookmark',
                                   api.request.public_url,
                                   'nodes', '',
                                   bookmark=True)
                    ]
        v1.ports = [link.make_link('self', api.request.public_url,
                                   'ports', ''),
                    link.make_link('bookmark',
                                   api.request.public_url,
                                   'ports', '',
                                   bookmark=True)
                    ]
        if utils.allow_portgroups():
            v1.portgroups = [
                link.make_link('self', api.request.public_url,
                               'portgroups', ''),
                link.make_link('bookmark', api.request.public_url,
                               'portgroups', '', bookmark=True)
            ]
        v1.drivers = [link.make_link('self', api.request.public_url,
                                     'drivers', ''),
                      link.make_link('bookmark',
                                     api.request.public_url,
                                     'drivers', '',
                                     bookmark=True)
                      ]
        if utils.allow_volume():
            v1.volume = [
                link.make_link('self',
                               api.request.public_url,
                               'volume', ''),
                link.make_link('bookmark',
                               api.request.public_url,
                               'volume', '',
                               bookmark=True)
            ]
        if utils.allow_ramdisk_endpoints():
            v1.lookup = [link.make_link('self', api.request.public_url,
                                        'lookup', ''),
                         link.make_link('bookmark',
                                        api.request.public_url,
                                        'lookup', '',
                                        bookmark=True)
                         ]
            v1.heartbeat = [link.make_link('self',
                                           api.request.public_url,
                                           'heartbeat', ''),
                            link.make_link('bookmark',
                                           api.request.public_url,
                                           'heartbeat', '',
                                           bookmark=True)
                            ]
        if utils.allow_expose_conductors():
            v1.conductors = [link.make_link('self',
                                            api.request.public_url,
                                            'conductors', ''),
                             link.make_link('bookmark',
                                            api.request.public_url,
                                            'conductors', '',
                                            bookmark=True)
                             ]
        if utils.allow_allocations():
            v1.allocations = [link.make_link('self',
                                             api.request.public_url,
                                             'allocations', ''),
                              link.make_link('bookmark',
                                             api.request.public_url,
                                             'allocations', '',
                                             bookmark=True)
                              ]
        if utils.allow_expose_events():
            v1.events = [link.make_link('self', api.request.public_url,
                                        'events', ''),
                         link.make_link('bookmark',
                                        api.request.public_url,
                                        'events', '',
                                        bookmark=True)
                         ]
        if utils.allow_deploy_templates():
            v1.deploy_templates = [
                link.make_link('self',
                               api.request.public_url,
                               'deploy_templates', ''),
                link.make_link('bookmark',
                               api.request.public_url,
                               'deploy_templates', '',
                               bookmark=True)
            ]
        v1.version = version.default_version()
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
    conductors = conductor.ConductorsController()
    allocations = allocation.AllocationsController()
    events = event.EventsController()
    deploy_templates = deploy_template.DeployTemplatesController()

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
                {'ver': version, 'min': versions.min_version_string(),
                 'max': versions.max_version_string()},
                headers=headers)
        # ensure the minor version is within the supported range
        if version < min_version() or version > max_version():
            raise exc.HTTPNotAcceptable(_(
                "Version %(ver)s was requested but the minor version is not "
                "supported by this service. The supported version range is: "
                "[%(min)s, %(max)s].") %
                {'ver': version, 'min': versions.min_version_string(),
                 'max': versions.max_version_string()},
                headers=headers)

    @pecan.expose()
    def _route(self, args, request=None):
        v = base.Version(api.request.headers, versions.min_version_string(),
                         versions.max_version_string())

        # Always set the min and max headers
        api.response.headers[base.Version.min_string] = (
            versions.min_version_string())
        api.response.headers[base.Version.max_string] = (
            versions.max_version_string())

        # assert that requested version is supported
        self._check_version(v, api.response.headers)
        api.response.headers[base.Version.string] = str(v)
        api.request.version = v

        return super(Controller, self)._route(args, request)


__all__ = ('Controller',)
