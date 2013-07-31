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

import pecan
from pecan import rest

import wsme
from wsme import types as wtypes
import wsmeext.pecan as wsme_pecan

from ironic import objects

from ironic.api.controllers.v1 import base
from ironic.api.controllers.v1 import link
from ironic.common import exception
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
        return chassis


class ChassisController(rest.RestController):
    """REST controller for Chassis."""

    @wsme_pecan.wsexpose([Chassis])
    def get_all(self):
        """Retrieve a list of chassis."""
        ch_list = []
        for uuid in pecan.request.dbapi.get_chassis_list():
            rpc_chassis = objects.Chassis.get_by_uuid(pecan.request.context,
                                                      uuid)
            ch_list.append(Chassis.convert_with_links(rpc_chassis))
        return ch_list

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

    @wsme_pecan.wsexpose(Chassis, unicode, body=Chassis)
    def patch(self, uuid, delta_chassis):
        """Update an existing chassis."""
        chassis = objects.Chassis.get_by_uuid(pecan.request.context, uuid)
        nn_delta_ch = delta_chassis.as_terse_dict()
        # Ensure immutable keys are not present
        # TODO(lucasagomes): Not sure if 'id' will ever be present here
        # the translation should occur before it reaches this point
        if any(v for v in nn_delta_ch if v in ("id", "uuid")):
            raise wsme.exc.ClientSideError(_("'uuid' is immutable"))

        for k in nn_delta_ch:
            chassis[k] = nn_delta_ch[k]
        chassis.save()

        return Chassis.convert_with_links(chassis)

    @wsme_pecan.wsexpose(None, unicode, status_code=204)
    def delete(self, uuid):
        """Delete a chassis."""
        # TODO(lucasagomes): be more cautious when deleting a chassis
        # which has nodes
        pecan.request.dbapi.destroy_chassis(uuid)
