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
import inspect

import six

from ironic.common import exception
from ironic.common.i18n import _
from ironic import objects
from ironic.objects import notification
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
        if key == 'traits':
            # convert list of strings to object
            raw_traits = db_node['traits']
            trait_list = []
            for raw_trait in raw_traits:
                trait = objects.Trait(ctxt, trait=raw_trait)
                trait_list.append(trait)
            node.traits = objects.TraitList(ctxt, objects=trait_list)
            node.traits.obj_reset_changes()
        else:
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


def get_test_volume_connector(ctxt, **kw):
    """Return a VolumeConnector object with appropriate attributes.

    NOTE: The object leaves the attributes marked as changed, such
    that a create() could be used to commit it to the DB.
    """
    db_volume_connector = db_utils.get_test_volume_connector(**kw)
    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del db_volume_connector['id']
    volume_connector = objects.VolumeConnector(ctxt)
    for key in db_volume_connector:
        setattr(volume_connector, key, db_volume_connector[key])
    return volume_connector


def create_test_volume_connector(ctxt, **kw):
    """Create and return a test volume connector object.

    Create a volume connector in the DB and return a VolumeConnector object
    with appropriate attributes.
    """
    volume_connector = get_test_volume_connector(ctxt, **kw)
    volume_connector.create()
    return volume_connector


def get_test_volume_target(ctxt, **kw):
    """Return a VolumeTarget object with appropriate attributes.

    NOTE: The object leaves the attributes marked as changed, such
    that a create() could be used to commit it to the DB.
    """
    db_volume_target = db_utils.get_test_volume_target(**kw)
    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del db_volume_target['id']
    volume_target = objects.VolumeTarget(ctxt)
    for key in db_volume_target:
        setattr(volume_target, key, db_volume_target[key])
    return volume_target


def create_test_volume_target(ctxt, **kw):
    """Create and return a test volume target object.

    Create a volume target in the DB and return a VolumeTarget object with
    appropriate attributes.
    """
    volume_target = get_test_volume_target(ctxt, **kw)
    volume_target.create()
    return volume_target


def get_test_bios_setting(ctxt, **kw):
    """Return a BiosSettingList object with appropriate attributes.

    NOTE: The object leaves the attributes marked as changed, such
    that a create() could be used to commit it to the DB.
    """
    kw['object_type'] = 'bios'
    db_bios_setting = db_utils.get_test_bios_setting(**kw)
    bios_setting = objects.BIOSSetting(ctxt)
    for key in db_bios_setting:
        setattr(bios_setting, key, db_bios_setting[key])
    return bios_setting


def create_test_bios_setting(ctxt, **kw):
    """Create and return a test bios setting list object.

    Create a BIOS setting list in the DB and return a BIOSSettingList
    object with appropriate attributes.
    """
    bios_setting = get_test_bios_setting(ctxt, **kw)
    bios_setting.create()
    return bios_setting


def create_test_conductor(ctxt, **kw):
    """Register and return a test conductor object."""
    args = db_utils.get_test_conductor(**kw)
    conductor = objects.Conductor.register(ctxt, args['hostname'],
                                           args['drivers'],
                                           args['conductor_group'],
                                           update_existing=True)
    return conductor


def get_test_allocation(ctxt, **kw):
    """Return an Allocation object with appropriate attributes.

    NOTE: The object leaves the attributes marked as changed, such
    that a create() could be used to commit it to the DB.
    """
    kw['object_type'] = 'allocation'
    get_db_allocation_checked = check_keyword_arguments(
        db_utils.get_test_allocation)
    db_allocation = get_db_allocation_checked(**kw)

    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del db_allocation['id']
    allocation = objects.Allocation(ctxt)
    for key in db_allocation:
        setattr(allocation, key, db_allocation[key])
    return allocation


def create_test_allocation(ctxt, **kw):
    """Create and return a test allocation object.

    Create an allocation in the DB and return an Allocation object with
    appropriate attributes.
    """
    allocation = get_test_allocation(ctxt, **kw)
    allocation.create()
    return allocation


def get_test_deploy_template(ctxt, **kw):
    """Return a DeployTemplate object with appropriate attributes.

    NOTE: The object leaves the attributes marked as changed, such
    that a create() could be used to commit it to the DB.
    """
    db_template = db_utils.get_test_deploy_template(**kw)
    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del db_template['id']
    if 'steps' not in kw:
        for step in db_template['steps']:
            del step['id']
            del step['deploy_template_id']
    else:
        for kw_step, template_step in zip(kw['steps'], db_template['steps']):
            if 'id' not in kw_step and 'id' in template_step:
                del template_step['id']
    template = objects.DeployTemplate(ctxt)
    for key in db_template:
        setattr(template, key, db_template[key])
    return template


def create_test_deploy_template(ctxt, **kw):
    """Create and return a test deploy template object.

    NOTE: The object leaves the attributes marked as changed, such
    that a create() could be used to commit it to the DB.
    """
    template = get_test_deploy_template(ctxt, **kw)
    template.create()
    return template


def get_payloads_with_schemas(from_module):
    """Get the Payload classes with SCHEMAs defined.

    :param from_module: module from which to get the classes.
    :returns: list of Payload classes that have SCHEMAs defined.

    """
    payloads = []
    for name, payload in inspect.getmembers(from_module, inspect.isclass):
        # Assume that Payload class names end in 'Payload'.
        if name.endswith("Payload"):
            base_classes = inspect.getmro(payload)
            if notification.NotificationPayloadBase not in base_classes:
                # The class may have the desired name but it isn't a REAL
                # Payload class; skip it.
                continue

            # First class is this payload class, parent class is the 2nd
            # one in the tuple
            parent = base_classes[1]
            if (not hasattr(parent, 'SCHEMA')
                or parent.SCHEMA != payload.SCHEMA):
                payloads.append(payload)

    return payloads


class SchemasTestMixIn(object):
    def _check_payload_schemas(self, from_module, fields):
        """Assert that the Payload SCHEMAs have the expected properties.

           A payload's SCHEMA should:

           1. Have each of its keys in the payload's fields
           2. Have each member of the schema match with a corresponding field
           in the object
        """
        resource = from_module.__name__.split('.')[-1]
        payloads = get_payloads_with_schemas(from_module)
        for payload in payloads:
            for schema_key in payload.SCHEMA:
                self.assertIn(schema_key, payload.fields,
                              "for %s, schema key %s is not in fields"
                              % (payload, schema_key))
                key = payload.SCHEMA[schema_key][1]
                self.assertIn(key, fields,
                              "for %s, schema key %s has invalid %s "
                              "field %s" % (payload, schema_key, resource,
                                            key))
