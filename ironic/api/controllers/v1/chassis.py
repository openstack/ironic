# Copyright 2013 Red Hat, Inc.
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

import jsonpatch
import six

import pecan
from pecan import rest

import wsme
from wsme import types as wtypes
import wsmeext.pecan as wsme_pecan

from ironic.api.controllers.v1 import base
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import link
from ironic.api.controllers.v1 import node
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.common import exception
from ironic import objects
from ironic.openstack.common import excutils
from ironic.openstack.common import log

LOG = log.getLogger(__name__)


class ChassisPatchType(types.JsonPatchType):
    pass


class Chassis(base.APIBase):
    """API representation of a chassis.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of
    a chassis.
    """

    uuid = types.uuid
    "The UUID of the chassis"

    description = wtypes.text
    "The description of the chassis"

    extra = {wtypes.text: types.MultiType(wtypes.text, six.integer_types)}
    "The metadata of the chassis"

    links = wsme.wsattr([link.Link], readonly=True)
    "A list containing a self link and associated chassis links"

    nodes = wsme.wsattr([link.Link], readonly=True)
    "Links to the collection of nodes contained in this chassis"

    def __init__(self, **kwargs):
        self.fields = objects.Chassis.fields.keys()
        for k in self.fields:
            setattr(self, k, kwargs.get(k))

    @classmethod
    def convert_with_links(cls, rpc_chassis, expand=True):
        chassis = Chassis(**rpc_chassis.as_dict())
        if not expand:
            chassis.unset_fields_except(['uuid', 'description'])
        else:
            chassis.nodes = [link.Link.make_link('self',
                                                 pecan.request.host_url,
                                                 'chassis',
                                                 chassis.uuid + "/nodes"),
                             link.Link.make_link('bookmark',
                                                 pecan.request.host_url,
                                                 'chassis',
                                                 chassis.uuid + "/nodes",
                                                 bookmark=True)
                            ]
        chassis.links = [link.Link.make_link('self',
                                             pecan.request.host_url,
                                             'chassis', chassis.uuid),
                         link.Link.make_link('bookmark',
                                             pecan.request.host_url,
                                             'chassis', chassis.uuid)
                        ]
        return chassis


class ChassisCollection(collection.Collection):
    """API representation of a collection of chassis."""

    chassis = [Chassis]
    "A list containing chassis objects"

    def __init__(self, **kwargs):
        self._type = 'chassis'

    @classmethod
    def convert_with_links(cls, chassis, limit, url=None,
                           expand=False, **kwargs):
        collection = ChassisCollection()
        collection.chassis = [Chassis.convert_with_links(ch, expand)
                              for ch in chassis]
        url = url or None
        collection.next = collection.get_next(limit, url=url, **kwargs)
        return collection


class ChassisController(rest.RestController):
    """REST controller for Chassis."""

    nodes = node.NodesController(from_chassis=True)
    "Expose nodes as a sub-element of chassis"

    _custom_actions = {
        'detail': ['GET'],
    }

    def _get_chassis_collection(self, marker, limit, sort_key, sort_dir,
                                expand=False, resource_url=None):
        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)
        marker_obj = None
        if marker:
            marker_obj = objects.Chassis.get_by_uuid(pecan.request.context,
                                                     marker)
        chassis = pecan.request.dbapi.get_chassis_list(limit, marker_obj,
                                                       sort_key=sort_key,
                                                       sort_dir=sort_dir)
        return ChassisCollection.convert_with_links(chassis, limit,
                                                    url=resource_url,
                                                    expand=expand,
                                                    sort_key=sort_key,
                                                    sort_dir=sort_dir)

    @wsme_pecan.wsexpose(ChassisCollection, types.uuid,
                         int, wtypes.text, wtypes.text)
    def get_all(self, marker=None, limit=None, sort_key='id', sort_dir='asc'):
        """Retrieve a list of chassis.

        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        """
        return self._get_chassis_collection(marker, limit, sort_key, sort_dir)

    @wsme_pecan.wsexpose(ChassisCollection, types.uuid, int,
                         wtypes.text, wtypes.text)
    def detail(self, marker=None, limit=None, sort_key='id', sort_dir='asc'):
        """Retrieve a list of chassis with detail.

        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        """
        # /detail should only work agaist collections
        parent = pecan.request.path.split('/')[:-1][-1]
        if parent != "chassis":
            raise exception.HTTPNotFound

        expand = True
        resource_url = '/'.join(['chassis', 'detail'])
        return self._get_chassis_collection(marker, limit, sort_key, sort_dir,
                                            expand, resource_url)

    @wsme_pecan.wsexpose(Chassis, types.uuid)
    def get_one(self, chassis_uuid):
        """Retrieve information about the given chassis.

        :param chassis_uuid: UUID of a chassis.
        """
        rpc_chassis = objects.Chassis.get_by_uuid(pecan.request.context,
                                                  chassis_uuid)
        return Chassis.convert_with_links(rpc_chassis)

    @wsme_pecan.wsexpose(Chassis, body=Chassis, status_code=201)
    def post(self, chassis):
        """Create a new chassis.

        :param chassis: a chassis within the request body.
        """
        try:
            new_chassis = pecan.request.dbapi.create_chassis(chassis.as_dict())
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.exception(e)
        return Chassis.convert_with_links(new_chassis)

    @wsme.validate(types.uuid, [ChassisPatchType])
    @wsme_pecan.wsexpose(Chassis, types.uuid, body=[ChassisPatchType])
    def patch(self, chassis_uuid, patch):
        """Update an existing chassis.

        :param chassis_uuid: UUID of a chassis.
        :param patch: a json PATCH document to apply to this chassis.
        """
        rpc_chassis = objects.Chassis.get_by_uuid(pecan.request.context,
                                                  chassis_uuid)
        try:
            chassis = Chassis(**jsonpatch.apply_patch(rpc_chassis.as_dict(),
                                                   jsonpatch.JsonPatch(patch)))
        except api_utils.JSONPATCH_EXCEPTIONS as e:
            raise exception.PatchError(patch=patch, reason=e)

        # Update only the fields that have changed
        for field in objects.Chassis.fields:
            if rpc_chassis[field] != getattr(chassis, field):
                rpc_chassis[field] = getattr(chassis, field)

        rpc_chassis.save()
        return Chassis.convert_with_links(rpc_chassis)

    @wsme_pecan.wsexpose(None, types.uuid, status_code=204)
    def delete(self, chassis_uuid):
        """Delete a chassis.

        :param chassis_uuid: UUID of a chassis.
        """
        pecan.request.dbapi.destroy_chassis(chassis_uuid)
