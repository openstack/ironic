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

from ironic.api.controllers import base
from ironic.api.controllers import v1
from ironic.api.controllers import version
from ironic.api import expose


class Root(base.Base):

    name = str
    """The name of the API"""

    description = str
    """Some information about this API"""

    versions = [version.Version]
    """Links to all the versions available in this API"""

    default_version = version.Version
    """A link to the default version of the API"""

    @staticmethod
    def convert():
        root = Root()
        root.name = "OpenStack Ironic API"
        root.description = ("Ironic is an OpenStack project which aims to "
                            "provision baremetal machines.")
        root.default_version = version.default_version()
        root.versions = [root.default_version]
        return root


class RootController(rest.RestController):

    _versions = [version.ID_VERSION1]
    """All supported API versions"""

    _default_version = version.ID_VERSION1
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
