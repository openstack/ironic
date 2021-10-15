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

from ironic.api.controllers import v1
from ironic.api.controllers import version
from ironic.api import method


V1 = v1.Controller()


def root():
    return {
        'name': "OpenStack Ironic API",
        'description': ("Ironic is an OpenStack project which enables the "
                        "provision and management of baremetal machines."),
        'default_version': version.default_version(),
        'versions': version.all_versions()
    }


class RootController(object):

    @method.expose()
    def index(self, *args):
        if args:
            pecan.abort(404)
        return root()

    @pecan.expose()
    def _lookup(self, primary_key, *remainder):
        """Overrides the default routing behavior.

        It redirects the request to the default version of the ironic API
        if the version number is not specified in the url.
        """

        # support paths which are missing the first version element
        if primary_key and primary_key != version.ID_VERSION1:
            remainder = [primary_key] + list(remainder)

        # remove any trailing /
        if remainder and not remainder[-1]:
            remainder = remainder[:-1]

        # but ensure /v1 goes to /v1/
        if not remainder:
            remainder = ['']

        return V1, remainder
