#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import pecan
from pecan import rest

import wsme
from wsme import types as wtypes
import wsmeext.pecan as wsme_pecan

from ironic.api.controllers.v1 import base
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import link
from ironic.api.controllers.v1 import node
from ironic.api.controllers.v1 import utils
from ironic.common import exception
from ironic import objects
from ironic.openstack.common import log

LOG = log.getLogger(__name__)


class Chassis(base.APIBase):
    """API representation of a chassis.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of
    a chassis.
    """

    # NOTE: translate 'id' publicly to 'uuid' internally
    uuid = wtypes.text
    "The UUID of the chassis"

    description = wtypes.text
    "The description of the chassis"

    extra = {wtypes.text: wtypes.text}
    "The metadata of the chassis"

    links = [link.Link]
    "A list containing a self link and associated chassis links"

    nodes = [link.Link]
    "Links to the collection of nodes contained in this chassis"

    def __init__(self, **kwargs):
        self.fields = objects.Chassis.fields.keys()
        for k in self.fields:
            setattr(self, k, kwargs.get(k))

    @classmethod
    def convert_with_links(cls, rpc_chassis):
        chassis = Chassis.from_rpc_object(rpc_chassis)
        chassis.links = [link.Link.make_link('self', pecan.request.host_url,
                                             'chassis', chassis.uuid),
                         link.Link.make_link('bookmark',
                                             pecan.request.host_url,
                                             'chassis', chassis.uuid,
                                             bookmark=True)
                        ]
        chassis.nodes = [link.Link.make_link('self', pecan.request.host_url,
                                             'chassis',
                                              chassis.uuid + "/nodes"),
                         link.Link.make_link('bookmark',
                                             pecan.request.host_url,
                                             'chassis',
                                             chassis.uuid + "/nodes",
                                             bookmark=True)
                        ]
        return chassis


class ChassisCollection(collection.Collection):
    """API representation of a collection of chassis."""

    chassis = [Chassis]
    "A list containing chassis objects"

    def __init__(self, **kwargs):
        self._type = 'chassis'

    @classmethod
    def convert_with_links(cls, chassis, limit, **kwargs):
        collection = ChassisCollection()
        collection.chassis = [Chassis.convert_with_links(ch) for ch in chassis]
        collection.next = collection.get_next(limit, **kwargs)
        return collection


class ChassisController(rest.RestController):
    """REST controller for Chassis."""

    _custom_actions = {
        'nodes': ['GET'],
    }

    @wsme_pecan.wsexpose(ChassisCollection, int, unicode, unicode, unicode)
    def get_all(self, limit=None, marker=None, sort_key='id', sort_dir='asc'):
        """Retrieve a list of chassis."""
        limit = utils.validate_limit(limit)
        sort_dir = utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.Chassis.get_by_uuid(pecan.request.context,
                                                     marker)

        chassis = pecan.request.dbapi.get_chassis_list(limit, marker_obj,
                                                       sort_key=sort_key,
                                                       sort_dir=sort_dir)
        return ChassisCollection.convert_with_links(chassis, limit,
                                                    sort_key=sort_key,
                                                    sort_dir=sort_dir)

    @wsme_pecan.wsexpose(Chassis, unicode)
    def get_one(self, uuid):
        """Retrieve information about the given chassis."""
        rpc_chassis = objects.Chassis.get_by_uuid(pecan.request.context, uuid)
        return Chassis.convert_with_links(rpc_chassis)

    @wsme.validate(Chassis)
    @wsme_pecan.wsexpose(Chassis, body=Chassis)
    def post(self, chassis):
        """Create a new chassis."""
        try:
            new_chassis = pecan.request.dbapi.create_chassis(chassis.as_dict())
        except exception.IronicException as e:
            LOG.exception(e)
            raise wsme.exc.ClientSideError(_("Invalid data"))
        return Chassis.convert_with_links(new_chassis)

    @wsme_pecan.wsexpose(Chassis, unicode, body=[unicode])
    def patch(self, uuid, patch):
        """Update an existing chassis."""
        chassis = objects.Chassis.get_by_uuid(pecan.request.context, uuid)
        chassis_dict = chassis.as_dict()

        utils.validate_patch(patch)
        try:
            patched_chassis = jsonpatch.apply_patch(chassis_dict,
                                                    jsonpatch.JsonPatch(patch))
        except jsonpatch.JsonPatchException as e:
            LOG.exception(e)
            raise wsme.exc.ClientSideError(_("Patching Error: %s") % e)

        defaults = objects.Chassis.get_defaults()
        for key in defaults:
            # Internal values that shouldn't be part of the patch
            if key in ['id', 'updated_at', 'created_at']:
                continue

            # In case of a remove operation, add the missing fields back
            # to the document with their default value
            if key in chassis_dict and key not in patched_chassis:
                patched_chassis[key] = defaults[key]

            # Update only the fields that have changed
            if chassis[key] != patched_chassis[key]:
                chassis[key] = patched_chassis[key]

        chassis.save()
        return Chassis.convert_with_links(chassis)

    @wsme_pecan.wsexpose(None, unicode, status_code=204)
    def delete(self, uuid):
        """Delete a chassis."""
        pecan.request.dbapi.destroy_chassis(uuid)

    @wsme_pecan.wsexpose(node.NodeCollection, unicode, int, unicode,
                         unicode, unicode)
    def nodes(self, chassis_uuid, limit=None, marker=None,
              sort_key='id', sort_dir='asc'):
        """Retrieve a list of nodes contained in the chassis."""
        limit = utils.validate_limit(limit)
        sort_dir = utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.Node.get_by_uuid(pecan.request.context,
                                                  marker)

        nodes = pecan.request.dbapi.get_nodes_by_chassis(chassis_uuid, limit,
                                                         marker_obj,
                                                         sort_key=sort_key,
                                                         sort_dir=sort_dir)
        collection = node.NodeCollection()
        collection.nodes = [node.Node.convert_with_links(n) for n in nodes]
        resource_url = '/'.join(['chassis', chassis_uuid, 'nodes'])
        collection.next = collection.get_next(limit, url=resource_url,
                                              sort_key=sort_key,
                                              sort_dir=sort_dir)
        return collection
