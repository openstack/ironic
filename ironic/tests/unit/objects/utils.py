# Copyright 2014 Rackspace Hosting
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
"""Ironic object test utilities."""
import six

from ironic.common import exception
from ironic.common.i18n import _
from ironic import objects
from ironic.tests.unit.db import utils as db_utils


def check_keyword_arguments(func):
    @six.wraps(func)
    def wrapper(**kw):
        obj_type = kw.pop('object_type')
        result = func(**kw)

        extra_args = set(kw) - set(result)
        if extra_args:
            raise exception.InvalidParameterValue(
                _("Unknown keyword arguments (%(extra)s) were passed "
                  "while creating a test %(object_type)s object.") %
                {"extra": ", ".join(extra_args),
                 "object_type": obj_type})

        return result

    return wrapper


def get_test_node(ctxt, **kw):
    """Return a Node object with appropriate attributes.

    NOTE: The object leaves the attributes marked as changed, such
    that a create() could be used to commit it to the DB.
    """
    kw['object_type'] = 'node'
    get_db_node_checked = check_keyword_arguments(db_utils.get_test_node)
    db_node = get_db_node_checked(**kw)

    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del db_node['id']
    node = objects.Node(ctxt)
    for key in db_node:
        setattr(node, key, db_node[key])
    return node


def create_test_node(ctxt, **kw):
    """Create and return a test node object.

    Create a node in the DB and return a Node object with appropriate
    attributes.
    """
    node = get_test_node(ctxt, **kw)
    node.create()
    return node


def get_test_port(ctxt, **kw):
    """Return a Port object with appropriate attributes.

    NOTE: The object leaves the attributes marked as changed, such
    that a create() could be used to commit it to the DB.
    """
    kw['object_type'] = 'port'
    get_db_port_checked = check_keyword_arguments(
        db_utils.get_test_port)
    db_port = get_db_port_checked(**kw)

    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del db_port['id']
    port = objects.Port(ctxt)
    for key in db_port:
        setattr(port, key, db_port[key])
    return port


def create_test_port(ctxt, **kw):
    """Create and return a test port object.

    Create a port in the DB and return a Port object with appropriate
    attributes.
    """
    port = get_test_port(ctxt, **kw)
    port.create()
    return port


def get_test_chassis(ctxt, **kw):
    """Return a Chassis object with appropriate attributes.

    NOTE: The object leaves the attributes marked as changed, such
    that a create() could be used to commit it to the DB.
    """
    kw['object_type'] = 'chassis'
    get_db_chassis_checked = check_keyword_arguments(
        db_utils.get_test_chassis)
    db_chassis = get_db_chassis_checked(**kw)

    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del db_chassis['id']
    chassis = objects.Chassis(ctxt)
    for key in db_chassis:
        setattr(chassis, key, db_chassis[key])
    return chassis


def create_test_chassis(ctxt, **kw):
    """Create and return a test chassis object.

    Create a chassis in the DB and return a Chassis object with appropriate
    attributes.
    """
    chassis = get_test_chassis(ctxt, **kw)
    chassis.create()
    return chassis


def get_test_portgroup(ctxt, **kw):
    """Return a Portgroup object with appropriate attributes.

    NOTE: The object leaves the attributes marked as changed, such
    that a create() could be used to commit it to the DB.
    """
    kw['object_type'] = 'portgroup'
    get_db_port_group_checked = check_keyword_arguments(
        db_utils.get_test_portgroup)
    db_portgroup = get_db_port_group_checked(**kw)

    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del db_portgroup['id']
    portgroup = objects.Portgroup(ctxt)
    for key in db_portgroup:
        setattr(portgroup, key, db_portgroup[key])
    return portgroup


def create_test_portgroup(ctxt, **kw):
    """Create and return a test portgroup object.

    Create a portgroup in the DB and return a Portgroup object with appropriate
    attributes.
    """
    portgroup = get_test_portgroup(ctxt, **kw)
    portgroup.create()
    return portgroup
