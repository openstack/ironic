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

from ironic.api.controllers import v1
from ironic.api.controllers import version
from ironic.api import method


def root():
    return {
        'name': "OpenStack Ironic API",
        'description': ("Ironic is an OpenStack project which aims to "
                        "provision baremetal machines."),
        'default_version': version.default_version(),
        'versions': version.all_versions()
    }


class RootController(rest.RestController):

    v1 = v1.Controller()

    @method.expose()
    def get(self):
        return root()

    @pecan.expose()
    def _route(self, args, request=None):
        """Overrides the default routing behavior.

        It redirects the request to the default version of the ironic API
        if the version number is not specified in the url.
        """

        if args[0] and args[0] != version.ID_VERSION1:
            args = [version.ID_VERSION1] + args
        return super(RootController, self)._route(args, request)
