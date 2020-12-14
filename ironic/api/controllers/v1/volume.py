# Copyright (c) 2017 Hitachi, Ltd.
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

from http import client as http_client

import pecan
from pecan import rest

from ironic import api
from ironic.api.controllers import link
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api.controllers.v1 import volume_connector
from ironic.api.controllers.v1 import volume_target
from ironic.api import method
from ironic.common import exception


def convert(node_ident=None):
    url = api.request.public_url
    volume = {}
    if node_ident:
        resource = 'nodes'
        rargs = '%s/volume/' % node_ident
    else:
        resource = 'volume'
        rargs = ''

    volume['links'] = [
        link.make_link('self', url, resource, rargs),
        link.make_link('bookmark', url, resource, rargs,
                       bookmark=True)]

    volume['connectors'] = [
        link.make_link('self', url, resource, rargs + 'connectors'),
        link.make_link('bookmark', url, resource, rargs + 'connectors',
                       bookmark=True)]

    volume['targets'] = [
        link.make_link('self', url, resource, rargs + 'targets'),
        link.make_link('bookmark', url, resource, rargs + 'targets',
                       bookmark=True)]

    return volume


class VolumeController(rest.RestController):
    """REST controller for volume root"""

    _subcontroller_map = {
        'connectors': volume_connector.VolumeConnectorsController,
        'targets': volume_target.VolumeTargetsController
    }

    def __init__(self, node_ident=None):
        super(VolumeController, self).__init__()
        self.parent_node_ident = node_ident

    @method.expose()
    def get(self):
        if not api_utils.allow_volume():
            raise exception.NotFound()

        api_utils.check_policy('baremetal:volume:get')

        return convert(self.parent_node_ident)

    @pecan.expose()
    def _lookup(self, subres, *remainder):
        if not api_utils.allow_volume():
            pecan.abort(http_client.NOT_FOUND)
        subcontroller = self._subcontroller_map.get(subres)
        if subcontroller:
            return subcontroller(node_ident=self.parent_node_ident), remainder
