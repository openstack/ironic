# -*- encoding: utf-8 -*-
#
# Copyright © 2012 New Dream Network, LLC (DreamHost)
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

import pecan
from pecan import rest
from wsme import types as wtypes

from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers import v1
from ironic.api.controllers.v1 import versions
from ironic.api import expose

ID_VERSION1 = 'v1'


class Version(base.APIBase):
    """An API version representation.

    This class represents an API version, including the minimum and
    maximum minor versions that are supported within the major version.
    """

    id = wtypes.text
    """The ID of the (major) version, also acts as the release number"""

    links = [link.Link]
    """A Link that point to a specific version of the API"""

    status = wtypes.text
    """Status of the version.

    One of:
    * CURRENT - the latest version of API,
    * SUPPORTED - supported, but not latest, version of API,
    * DEPRECATED - supported, but deprecated, version of API.
    """

    version = wtypes.text
    """The current, maximum supported (major.minor) version of API."""

    min_version = wtypes.text
    """Minimum supported (major.minor) version of API."""

    def __init__(self, id, min_version, version, status='CURRENT'):
        self.id = id
        self.links = [link.Link.make_link('self', pecan.request.public_url,
                                          self.id, '', bookmark=True)]
        self.status = status
        self.version = version
        self.min_version = min_version


class Root(base.APIBase):

    name = wtypes.text
    """The name of the API"""

    description = wtypes.text
    """Some information about this API"""

    versions = [Version]
    """Links to all the versions available in this API"""

    default_version = Version
    """A link to the default version of the API"""

    @staticmethod
    def convert():
        root = Root()
        root.name = "OpenStack Ironic API"
        root.description = ("Ironic is an OpenStack project which aims to "
                            "provision baremetal machines.")
        root.default_version = Version(ID_VERSION1,
                                       versions.MIN_VERSION_STRING,
                                       versions.MAX_VERSION_STRING)
        root.versions = [root.default_version]
        return root


class RootController(rest.RestController):

    _versions = [ID_VERSION1]
    """All supported API versions"""

    _default_version = ID_VERSION1
    """The default API version"""

    v1 = v1.Controller()

    @expose.expose(Root)
    def get(self):
        # NOTE: The reason why convert() it's being called for every
        #       request is because we need to get the host url from
        #       the request object to make the links.
        return Root.convert()

    @pecan.expose()
    def _route(self, args, request=None):
        """Overrides the default routing behavior.

        It redirects the request to the default version of the ironic API
        if the version number is not specified in the url.
        """

        if args[0] and args[0] not in self._versions:
            args = [self._default_version] + args
        return super(RootController, self)._route(args, request)
