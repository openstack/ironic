# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Tests for manipulating Nodes via the DB API"""

import datetime
from unittest import mock

from oslo_utils import timeutils
from oslo_utils import uuidutils
from sqlalchemy.orm import exc as sa_exc

from ironic.common import exception
from ironic.common import states
from ironic.db.sqlalchemy.models import NodeInventory
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils


class DbNodeTestCase(base.DbTestCase):

    def test_create_node(self):
        node = utils.create_test_node()
        self.assertEqual([], node.tags)
        self.assertEqual([], node.traits)

    def test_create_node_with_tags(self):
        self.assertRaises(exception.InvalidParameterValue,
                          utils.create_test_node,
                          tags=['tag1', 'tag2'])

    def test_create_node_with_traits(self):
        self.assertRaises(exception.InvalidParameterValue,
                          utils.create_test_node,
                          traits=['trait1', 'trait2'])

    def test_create_node_already_exists(self):
        utils.create_test_node()
        self.assertRaises(exception.NodeAlreadyExists,
                          utils.create_test_node)

    def test_create_node_instance_already_associated(self):
        instance = uuidutils.generate_uuid()
        utils.create_test_node(uuid=uuidutils.generate_uuid(),
                               instance_uuid=instance)
        self.assertRaises(exception.InstanceAssociated,
                          utils.create_test_node,
                          uuid=uuidutils.generate_uuid(),
                          instance_uuid=instance)

    def test_create_node_name_duplicate(self):
        node = utils.create_test_node(name='spam')
        self.assertRaises(exception.DuplicateName,
                          utils.create_test_node,
                          name=node.name)

    def test_get_node_by_id(self):
        node = utils.create_test_node()
        self.dbapi.set_node_tags(node.id, ['tag1', 'tag2'])
        utils.create_test_node_traits(node_id=node.id,
                                      traits=['trait1', 'trait2'])
        res = self.dbapi.get_node_by_id(node.id)
        self.assertEqual(node.id, res.id)
        self.assertEqual(node.uuid, res.uuid)
        self.assertCountEqual(['tag1', 'tag2'], [tag.tag for tag in res.tags])
        self.assertCountEqual(['trait1', 'trait2'],
                              [trait.trait for trait in res.traits])

    def test_get_node_by_uuid(self):
        node = utils.create_test_node()
        self.dbapi.set_node_tags(node.id, ['tag1', 'tag2'])
        utils.create_test_node_traits(node_id=node.id,
                                      traits=['trait1', 'trait2'])
        res = self.dbapi.get_node_by_uuid(node.uuid)
        self.assertEqual(node.id, res.id)
        self.assertEqual(node.uuid, res.uuid)
        self.assertCountEqual(['tag1', 'tag2'], [tag.tag for tag in res.tags])
        self.assertCountEqual(['trait1', 'trait2'],
                              [trait.trait for trait in res.traits])

    def test_get_node_by_name(self):
        node = utils.create_test_node()
        self.dbapi.set_node_tags(node.id, ['tag1', 'tag2'])
        utils.create_test_node_traits(node_id=node.id,
                                      traits=['trait1', 'trait2'])
        res = self.dbapi.get_node_by_name(node.name)
        self.assertEqual(node.id, res.id)
        self.assertEqual(node.uuid, res.uuid)
        self.assertEqual(node.name, res.name)
        self.assertCountEqual(['tag1', 'tag2'], [tag.tag for tag in res.tags])
        self.assertCountEqual(['trait1', 'trait2'],
                              [trait.trait for trait in res.traits])

    def test_get_node_that_does_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node_by_id, 99)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node_by_uuid,
                          '12345678-9999-0000-aaaa-123456789012')
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node_by_name,
                          'spam-eggs-bacon-spam')

    def test_get_nodeinfo_list_defaults(self):
        node_id_list = []
        for i in range(1, 6):
            node = utils.create_test_node(uuid=uuidutils.generate_uuid())
            node_id_list.append(node.id)
        res = [i[0] for i in self.dbapi.get_nodeinfo_list()]
        self.assertEqual(sorted(res), sorted(node_id_list))

    def test_get_nodeinfo_list_with_cols(self):
        uuids = {}
        extras = {}
        for i in range(1, 6):
            uuid = uuidutils.generate_uuid()
            extra = {'foo': i}
            node = utils.create_test_node(extra=extra, uuid=uuid)
            uuids[node.id] = uuid
            extras[node.id] = extra
        res = self.dbapi.get_nodeinfo_list(columns=['id', 'extra', 'uuid'])
        self.assertEqual(extras, dict((r[0], r[1]) for r in res))
        self.assertEqual(uuids, dict((r[0], r[2]) for r in res))

    def test_get_nodeinfo_list_with_filters(self):
        node1 = utils.create_test_node(
            driver='driver-one',
            instance_uuid=uuidutils.generate_uuid(),
            reservation='fake-host',
            uuid=uuidutils.generate_uuid())
        node2 = utils.create_test_node(
            driver='driver-two',
            uuid=uuidutils.generate_uuid(),
            maintenance=True,
            fault='boom',
            resource_class='foo',
            conductor_group='group1')
        node3 = utils.create_test_node(
            driver='driver-one',
            uuid=uuidutils.generate_uuid(),
            reservation='another-fake-host')

        res = self.dbapi.get_nodeinfo_list(filters={'driver': 'driver-one'})
        self.assertEqual(sorted([node1.id, node3.id]),
                         sorted([r[0] for r in res]))

        res = self.dbapi.get_nodeinfo_list(filters={'driver': 'bad-driver'})
        self.assertEqual([], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'associated': True})
        self.assertEqual([node1.id], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'associated': False})
        self.assertEqual(sorted([node2.id, node3.id]),
                         sorted([r[0] for r in res]))

        res = self.dbapi.get_nodeinfo_list(filters={'reserved': True})
        self.assertEqual(sorted([node1.id, node3.id]),
                         sorted([r[0] for r in res]))

        res = self.dbapi.get_nodeinfo_list(filters={'reserved': False})
        self.assertEqual([node2.id], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'maintenance': True})
        self.assertEqual([node2.id], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'maintenance': False})
        self.assertEqual(sorted([node1.id, node3.id]),
                         sorted([r[0] for r in res]))

        res = self.dbapi.get_nodeinfo_list(filters={'fault': 'boom'})
        self.assertEqual([node2.id], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'fault': 'moob'})
        self.assertEqual([], [r.id for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'resource_class': 'foo'})
        self.assertEqual([node2.id], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(
            filters={'conductor_group': 'group1'})
        self.assertEqual([node2.id], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(
            filters={'conductor_group': 'group2'})
        self.assertEqual([], [r.id for r in res])

        res = self.dbapi.get_nodeinfo_list(
            filters={'reserved_by_any_of': ['fake-host',
                                            'another-fake-host']})
        self.assertEqual(sorted([node1.id, node3.id]),
                         sorted([r[0] for r in res]))

        res = self.dbapi.get_nodeinfo_list(filters={'id': node1.id})
        self.assertEqual([node1.id], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'uuid': node1.uuid})
        self.assertEqual([node1.id], [r[0] for r in res])

        # ensure unknown filters explode
        filters = {'bad_filter': 'foo'}
        self.assertRaisesRegex(ValueError,
                               'bad_filter',
                               self.dbapi.get_nodeinfo_list,
                               filters=filters)

        # even with good filters present
        filters = {'bad_filter': 'foo', 'id': node1.id}
        self.assertRaisesRegex(ValueError,
                               'bad_filter',
                               self.dbapi.get_nodeinfo_list,
                               filters=filters)

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_get_nodeinfo_list_provision(self, mock_utcnow):
        past = datetime.datetime(2000, 1, 1, 0, 0)
        next = past + datetime.timedelta(minutes=8)
        present = past + datetime.timedelta(minutes=10)
        mock_utcnow.return_value = past

        # node with provision_updated timeout
        node1 = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                       provision_updated_at=past,
                                       provision_state=states.DEPLOYING)
        # node with None in provision_updated_at
        node2 = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                       provision_state=states.DEPLOYWAIT)
        # node without timeout
        utils.create_test_node(uuid=uuidutils.generate_uuid(),
                               provision_updated_at=next)

        mock_utcnow.return_value = present
        res = self.dbapi.get_nodeinfo_list(filters={'provisioned_before': 300})
        self.assertEqual([node1.id], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'provision_state':
                                                    states.DEPLOYWAIT})
        self.assertEqual([node2.id], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(
            filters={'provision_state_in': [states.ACTIVE, states.DEPLOYING]})
        self.assertEqual([node1.id], [r[0] for r in res])

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_get_nodeinfo_list_inspection(self, mock_utcnow):
        past = datetime.datetime(2000, 1, 1, 0, 0)
        next = past + datetime.timedelta(minutes=8)
        present = past + datetime.timedelta(minutes=10)
        mock_utcnow.return_value = past

        # node with provision_updated timeout
        node1 = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                       inspection_started_at=past)
        # node with None in provision_updated_at
        node2 = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                       provision_state=states.INSPECTING)
        # node without timeout
        utils.create_test_node(uuid=uuidutils.generate_uuid(),
                               inspection_started_at=next)

        mock_utcnow.return_value = present
        res = self.dbapi.get_nodeinfo_list(
            filters={'inspection_started_before': 300})
        self.assertEqual([node1.id], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'provision_state':
                                                    states.INSPECTING})
        self.assertEqual([node2.id], [r[0] for r in res])

    def test_get_nodeinfo_list_description(self):
        node1 = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                       description='Hello')
        node2 = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                       description='World!')
        res = self.dbapi.get_nodeinfo_list(
            filters={'description_contains': 'Hello'})
        self.assertEqual([node1.id], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'description_contains':
                                                    'World!'})
        self.assertEqual([node2.id], [r[0] for r in res])

    def test_get_node_list(self):
        uuids = []
        for i in range(1, 6):
            node = utils.create_test_node(uuid=uuidutils.generate_uuid())
            uuids.append(str(node['uuid']))
        res = self.dbapi.get_node_list()
        res_uuids = [r.uuid for r in res]
        self.assertCountEqual(uuids, res_uuids)
        for r in res:
            self.assertEqual([], r.tags)
            self.assertEqual([], r.traits)

    def test_get_node_list_includes_traits(self):
        uuids = []
        for i in range(1, 6):
            node = utils.create_test_node(uuid=uuidutils.generate_uuid())
            uuids.append(str(node['uuid']))
            self.dbapi.set_node_traits(node.id, ['trait1', 'trait2'], '1.35')

        res = self.dbapi.get_node_list()
        res_uuids = [r.uuid for r in res]
        self.assertCountEqual(uuids, res_uuids)
        for r in res:
            self.assertEqual([], r.tags)
            self.assertEqual(2, len(r.traits))

    def test_get_node_list_with_filters(self):
        ch1 = utils.create_test_chassis(uuid=uuidutils.generate_uuid())
        ch2 = utils.create_test_chassis(uuid=uuidutils.generate_uuid())

        node1 = utils.create_test_node(
            driver='driver-one',
            instance_uuid=uuidutils.generate_uuid(),
            reservation='fake-host',
            uuid=uuidutils.generate_uuid(),
            chassis_id=ch1['id'])
        node2 = utils.create_test_node(
            driver='driver-two',
            uuid=uuidutils.generate_uuid(),
            chassis_id=ch2['id'],
            maintenance=True,
            fault='boom',
            resource_class='foo',
            conductor_group='group1',
            power_state='power on')

        res = self.dbapi.get_node_list(filters={'chassis_uuid': ch1['uuid']})
        self.assertEqual([node1.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'chassis_uuid': ch2['uuid']})
        self.assertEqual([node2.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'driver': 'driver-one'})
        self.assertEqual([node1.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'driver': 'bad-driver'})
        self.assertEqual([], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'associated': True})
        self.assertEqual([node1.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'associated': False})
        self.assertEqual([node2.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'reserved': True})
        self.assertEqual([node1.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'reserved': False})
        self.assertEqual([node2.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'maintenance': True})
        self.assertEqual([node2.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'maintenance': False})
        self.assertEqual([node1.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'fault': 'boom'})
        self.assertEqual([node2.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'fault': 'moob'})
        self.assertEqual([], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'resource_class': 'foo'})
        self.assertEqual([node2.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'conductor_group': 'group1'})
        self.assertEqual([node2.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'conductor_group': 'group2'})
        self.assertEqual([], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'id': node1.id})
        self.assertEqual([node1.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'uuid': node1.uuid})
        self.assertEqual([node1.id], [r.id for r in res])

        uuids = [uuidutils.generate_uuid(),
                 node1.uuid,
                 uuidutils.generate_uuid()]
        res = self.dbapi.get_node_list(filters={'uuid_in': uuids})
        self.assertEqual([node1.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'with_power_state': True})
        self.assertEqual([node2.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'with_power_state': False})
        self.assertEqual([node1.id], [r.id for r in res])

        # ensure unknown filters explode
        filters = {'bad_filter': 'foo'}
        self.assertRaisesRegex(ValueError,
                               'bad_filter',
                               self.dbapi.get_node_list,
                               filters=filters)

        # even with good filters present
        filters = {'bad_filter': 'foo', 'id': node1.id}
        self.assertRaisesRegex(ValueError,
                               'bad_filter',
                               self.dbapi.get_node_list,
                               filters=filters)

    def test_get_node_list_filter_by_project(self):
        utils.create_test_node(uuid=uuidutils.generate_uuid())
        node2 = utils.create_test_node(
            uuid=uuidutils.generate_uuid(),
            owner='project1',
            lessee='project2',
        )
        node3 = utils.create_test_node(
            uuid=uuidutils.generate_uuid(),
            owner='project2',
        )
        node4 = utils.create_test_node(
            uuid=uuidutils.generate_uuid(),
            owner='project1',
            lessee='project3',
        )

        res = self.dbapi.get_node_list(filters={'project': 'project1'})
        self.assertEqual([node2.id, node4.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'project': 'project2'})
        self.assertEqual([node2.id, node3.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'project': 'project3'})
        self.assertEqual([node4.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'project': 'flargle'})
        self.assertEqual([], [r.id for r in res])

    def test_get_node_list_description(self):
        node1 = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                       description='Hello')
        node2 = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                       description='World!')
        res = self.dbapi.get_node_list(filters={
            'description_contains': 'Hello'})
        self.assertEqual([node1.id], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={
            'description_contains': 'World!'})
        self.assertEqual([node2.id], [r.id for r in res])

    def test_get_node_list_chassis_not_found(self):
        self.assertRaises(exception.ChassisNotFound,
                          self.dbapi.get_node_list,
                          {'chassis_uuid': uuidutils.generate_uuid()})

    def test_get_node_list_requested_fields_with_traits(self):
        # Checks to to ensure we're not returning a node object with all
        # fields populated as this is a high overhead for SQLAlchemy to do
        # all of the object conversions, when we have fields which were not
        # requested nor required.
        # Modeled after the nova query which is used to collect node state
        uuids = []
        for i in range(1, 6):
            node = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                          provision_state=states.AVAILABLE,
                                          power_state=states.POWER_OFF,
                                          target_power_state=None,
                                          target_provision_state=None,
                                          last_error=None,
                                          maintenance=False,
                                          properties={'cpu': 'x86_64'},
                                          instance_uuid=None,
                                          resource_class='CUSTOM_BAREMETAL',
                                          # Code requires the fields below
                                          owner='fred',
                                          lessee='marsha',
                                          # Fields that should not be
                                          # present in the obejct.
                                          driver_internal_info={
                                              'cat': 'meow'},
                                          internal_info={'corgi': 'rocks'},
                                          deploy_interface='purring_machine')
            # Add some traits for good measure
            self.dbapi.set_node_traits(node.id, ['trait1', 'trait2'], '1.35')
            uuids.append(str(node['uuid']))
        req_fields = ['uuid',
                      'power_state',
                      'target_power_state',
                      'provision_state',
                      'target_provision_state',
                      'last_error',
                      'maintenance',
                      'properties',
                      'instance_uuid',
                      'resource_class',
                      'traits',
                      'version',
                      'updated_at',
                      'created_at']

        res = self.dbapi.get_node_list(fields=req_fields)
        res_uuids = [r.uuid for r in res]
        self.assertCountEqual(uuids, res_uuids)
        for r in res:
            self.assertIsNotNone(r.traits)
            self.assertIsNotNone(r.version)
            self.assertEqual(states.AVAILABLE, r.provision_state)
            self.assertEqual(states.POWER_OFF, r.power_state)
            self.assertIsNone(r.target_power_state)
            self.assertIsNone(r.target_provision_state)
            self.assertIsNone(r.last_error)
            self.assertFalse(r.maintenance)
            self.assertIsNone(r.instance_uuid)
            self.assertEqual('CUSTOM_BAREMETAL', r.resource_class)
            self.assertEqual('trait1', r.traits[0]['trait'])
            self.assertEqual('trait2', r.traits[1]['trait'])
            # These always need to be returned, even if not requested.
            # These should always be empty values as they are not populated
            # due to the object not returning a value in the field to save on
            # excess un-necessary data conversions.

            def _attempt_field_access(obj, field):
                return obj[field]

            for field in ['driver_internal_info', 'internal_info',
                          'deploy_interface', 'boot_interface',
                          'driver', 'extra']:
                try:
                    self.assertRaises(sa_exc.DetachedInstanceError,
                                      _attempt_field_access, r, field)
                except AttributeError:
                    pass

    def test_get_node_list_requested_fields_no_traits(self):
        # The join for traits handling requires some special handling
        # so in this case we execute without traits being joined in.
        uuids = []
        for i in range(1, 3):
            node = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                          provision_state=states.AVAILABLE,
                                          last_error=None,
                                          maintenance=False,
                                          resource_class='CUSTOM_BAREMETAL',
                                          # Code requires the fields below
                                          owner='fred',
                                          lessee='marsha',
                                          # Fields that should not be
                                          # present in the object.
                                          driver_internal_info={
                                              'cat': 'meow'},
                                          internal_info={'corgi': 'rocks'},
                                          deploy_interface='purring_machine')
            utils.create_test_node_traits(node_id=node.id,
                                          traits=['atrait'])

            uuids.append(str(node['uuid']))
        req_fields = ['uuid',
                      'provision_state',
                      'last_error',
                      'owner',
                      'lessee',
                      'version']

        res = self.dbapi.get_node_list(fields=req_fields)
        res_uuids = [r.uuid for r in res]
        self.assertCountEqual(uuids, res_uuids)
        for r in res:
            self.assertIsNotNone(r.version)
            self.assertEqual(states.AVAILABLE, r.provision_state)
            self.assertIsNone(r.last_error)
            # These always need to be returned, even if not requested.
            self.assertEqual('fred', r.owner)
            self.assertEqual('marsha', r.lessee)
            # These should always be empty values as they are not populated
            # due to the object not returning a value in the field to save on
            # excess un-necessary data conversions.

            def _attempt_field_access(obj, field):
                return obj[field]

            for field in ['driver_internal_info', 'internal_info',
                          'deploy_interface', 'boot_interface',
                          'driver', 'extra', 'power_state',
                          'traits']:
                try:
                    self.assertRaises(sa_exc.DetachedInstanceError,
                                      _attempt_field_access, r, field)
                except AttributeError:
                    # We expect an AttributeError, in addition to
                    # SQLAlchemy raising an exception.
                    pass

    def test_get_node_by_instance(self):
        node = utils.create_test_node(
            instance_uuid='12345678-9999-0000-aaaa-123456789012')
        self.dbapi.set_node_tags(node.id, ['tag1', 'tag2'])
        utils.create_test_node_traits(node_id=node.id,
                                      traits=['trait1', 'trait2'])

        res = self.dbapi.get_node_by_instance(node.instance_uuid)
        self.assertEqual(node.uuid, res.uuid)
        self.assertCountEqual(['tag1', 'tag2'], [tag.tag for tag in res.tags])
        self.assertCountEqual(['trait1', 'trait2'],
                              [trait.trait for trait in res.traits])

    def test_get_node_by_instance_wrong_uuid(self):
        utils.create_test_node(
            instance_uuid='12345678-9999-0000-aaaa-123456789012')

        self.assertRaises(exception.InstanceNotFound,
                          self.dbapi.get_node_by_instance,
                          '12345678-9999-0000-bbbb-123456789012')

    def test_get_node_by_instance_invalid_uuid(self):
        self.assertRaises(exception.InvalidUUID,
                          self.dbapi.get_node_by_instance,
                          'fake_uuid')

    def test_destroy_node(self):
        node = utils.create_test_node()

        self.dbapi.destroy_node(node.id)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node_by_id, node.id)

    def test_destroy_node_by_uuid(self):
        node = utils.create_test_node()

        self.dbapi.destroy_node(node.uuid)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node_by_uuid, node.uuid)

    def test_destroy_node_that_does_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.destroy_node,
                          '12345678-9999-0000-aaaa-123456789012')

    def test_ports_get_destroyed_after_destroying_a_node(self):
        node = utils.create_test_node()

        port = utils.create_test_port(node_id=node.id)

        self.dbapi.destroy_node(node.id)

        self.assertRaises(exception.PortNotFound,
                          self.dbapi.get_port_by_id, port.id)

    def test_ports_get_destroyed_after_destroying_a_node_by_uuid(self):
        node = utils.create_test_node()

        port = utils.create_test_port(node_id=node.id)

        self.dbapi.destroy_node(node.uuid)

        self.assertRaises(exception.PortNotFound,
                          self.dbapi.get_port_by_id, port.id)

    def test_tags_get_destroyed_after_destroying_a_node(self):
        node = utils.create_test_node()

        tag = utils.create_test_node_tag(node_id=node.id)

        self.assertTrue(self.dbapi.node_tag_exists(node.id, tag.tag))
        self.dbapi.destroy_node(node.id)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.node_tag_exists, node.id, tag.tag)

    def test_tags_get_destroyed_after_destroying_a_node_by_uuid(self):
        node = utils.create_test_node()

        tag = utils.create_test_node_tag(node_id=node.id)

        self.assertTrue(self.dbapi.node_tag_exists(node.id, tag.tag))
        self.dbapi.destroy_node(node.uuid)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.node_tag_exists, node.id, tag.tag)

    def test_volume_connector_get_destroyed_after_destroying_a_node(self):
        node = utils.create_test_node()

        connector = utils.create_test_volume_connector(node_id=node.id)

        self.dbapi.destroy_node(node.id)

        self.assertRaises(exception.VolumeConnectorNotFound,
                          self.dbapi.get_volume_connector_by_id, connector.id)

    def test_volume_connector_get_destroyed_after_destroying_a_node_uuid(self):
        node = utils.create_test_node()

        connector = utils.create_test_volume_connector(node_id=node.id)

        self.dbapi.destroy_node(node.uuid)

        self.assertRaises(exception.VolumeConnectorNotFound,
                          self.dbapi.get_volume_connector_by_id, connector.id)

    def test_volume_target_gets_destroyed_after_destroying_a_node(self):
        node = utils.create_test_node()

        target = utils.create_test_volume_target(node_id=node.id)

        self.dbapi.destroy_node(node.id)

        self.assertRaises(exception.VolumeTargetNotFound,
                          self.dbapi.get_volume_target_by_id, target.id)

    def test_volume_target_gets_destroyed_after_destroying_a_node_uuid(self):
        node = utils.create_test_node()

        target = utils.create_test_volume_target(node_id=node.id)

        self.dbapi.destroy_node(node.uuid)

        self.assertRaises(exception.VolumeTargetNotFound,
                          self.dbapi.get_volume_target_by_id, target.id)

    def test_traits_get_destroyed_after_destroying_a_node(self):
        node = utils.create_test_node()

        trait = utils.create_test_node_trait(node_id=node.id)

        self.assertTrue(self.dbapi.node_trait_exists(node.id, trait.trait))
        self.dbapi.destroy_node(node.id)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.node_trait_exists, node.id, trait.trait)

    def test_traits_get_destroyed_after_destroying_a_node_by_uuid(self):
        node = utils.create_test_node()

        trait = utils.create_test_node_trait(node_id=node.id)

        self.assertTrue(self.dbapi.node_trait_exists(node.id, trait.trait))
        self.dbapi.destroy_node(node.uuid)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.node_trait_exists, node.id, trait.trait)

    def test_allocations_get_destroyed_after_destroying_a_node_by_uuid(self):
        node = utils.create_test_node()

        allocation = utils.create_test_allocation(node_id=node.id)
        node = self.dbapi.update_node(node.id,
                                      {'allocation_id': allocation.id})

        self.dbapi.destroy_node(node.uuid)
        self.assertRaises(exception.AllocationNotFound,
                          self.dbapi.get_allocation_by_id, allocation.id)

    def test_history_get_destroyed_after_destroying_a_node_by_uuid(self):
        node = utils.create_test_node()

        history = utils.create_test_history(node_id=node.id)

        self.dbapi.destroy_node(node.uuid)
        self.assertRaises(exception.NodeHistoryNotFound,
                          self.dbapi.get_node_history_by_id, history.id)

    def test_inventory_updated_for_node(self):
        node = utils.create_test_node()

        first_timestamp = datetime.datetime(2000, 1, 1, 0, 0)
        second_timestamp = first_timestamp + datetime.timedelta(minutes=8)
        utils.create_test_inventory(node_id=node.id,
                                    id=1,
                                    created_at=first_timestamp)
        utils.create_test_inventory(node_id=node.id,
                                    id=2,
                                    inventory={"inventory": "test2"},
                                    created_at=second_timestamp)

        node_inventory = self.dbapi.get_node_inventory_by_node_id(
            node_id=node.id)
        expected_inventory = NodeInventory(node_id=node.id,
                                           id=2,
                                           inventory_data={"inventory":
                                                           "test2"},
                                           created_at=second_timestamp,
                                           plugin_data={"pdata":
                                                        {"plugin": "data"}},
                                           version='1.0')
        self.assertJsonEqual(expected_inventory, node_inventory)

    def test_inventory_get_destroyed_after_destroying_a_node_by_uuid(self):
        node = utils.create_test_node()

        utils.create_test_inventory(node_id=node.id)

        self.dbapi.destroy_node(node.uuid)
        self.assertRaises(exception.NodeInventoryNotFound,
                          self.dbapi.get_node_inventory_by_node_id, node.id)

    def test_firmware_component_list_after_destroying_a_node_by_uuid(self):
        node = utils.create_test_node()

        utils.create_test_firmware_component(node_id=node.id)

        self.dbapi.destroy_node(node.uuid)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_firmware_component_list, node.id)

    def test_update_node(self):
        node = utils.create_test_node()

        old_extra = node.extra
        new_extra = {'foo': 'bar'}
        self.assertNotEqual(old_extra, new_extra)

        res = self.dbapi.update_node(node.id, {'extra': new_extra})
        self.assertEqual(new_extra, res.extra)
        self.assertEqual([], res.tags)
        self.assertEqual([], res.traits)

    def test_update_node_with_tags(self):
        node = utils.create_test_node()
        tag = utils.create_test_node_tag(node_id=node.id)

        old_extra = node.extra
        new_extra = {'foo': 'bar'}
        self.assertNotEqual(old_extra, new_extra)

        res = self.dbapi.update_node(node.id, {'extra': new_extra})
        self.assertEqual([tag.tag], [t.tag for t in res.tags])

    def test_update_node_with_traits(self):
        node = utils.create_test_node()
        trait = utils.create_test_node_trait(node_id=node.id)

        old_extra = node.extra
        new_extra = {'foo': 'bar'}
        self.assertNotEqual(old_extra, new_extra)

        res = self.dbapi.update_node(node.id, {'extra': new_extra})
        self.assertEqual([trait.trait], [t.trait for t in res.traits])

    def test_update_node_not_found(self):
        node_uuid = uuidutils.generate_uuid()
        new_extra = {'foo': 'bar'}
        self.assertRaises(exception.NodeNotFound, self.dbapi.update_node,
                          node_uuid, {'extra': new_extra})

    def test_update_node_uuid(self):
        node = utils.create_test_node()
        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.update_node, node.id,
                          {'uuid': ''})

    def test_update_node_associate_and_disassociate(self):
        node = utils.create_test_node()
        new_i_uuid = uuidutils.generate_uuid()
        res = self.dbapi.update_node(node.id, {'instance_uuid': new_i_uuid})
        self.assertEqual(new_i_uuid, res.instance_uuid)
        res = self.dbapi.update_node(node.id, {'instance_uuid': None})
        self.assertIsNone(res.instance_uuid)

    def test_update_node_instance_already_associated(self):
        node1 = utils.create_test_node(uuid=uuidutils.generate_uuid())
        new_i_uuid = uuidutils.generate_uuid()
        self.dbapi.update_node(node1.id, {'instance_uuid': new_i_uuid})
        node2 = utils.create_test_node(uuid=uuidutils.generate_uuid())
        self.assertRaises(exception.InstanceAssociated,
                          self.dbapi.update_node,
                          node2.id,
                          {'instance_uuid': new_i_uuid})

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_update_node_provision(self, mock_utcnow):
        mocked_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = mocked_time
        node = utils.create_test_node()
        res = self.dbapi.update_node(node.id, {'provision_state': 'fake'})
        self.assertEqual(mocked_time,
                         timeutils.normalize_time(res['provision_updated_at']))

    def test_update_node_name_duplicate(self):
        node1 = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                       name='spam')
        node2 = utils.create_test_node(uuid=uuidutils.generate_uuid())
        self.assertRaises(exception.DuplicateName,
                          self.dbapi.update_node,
                          node2.id,
                          {'name': node1.name})

    def test_update_node_no_provision(self):
        node = utils.create_test_node()
        res = self.dbapi.update_node(node.id, {'extra': {'foo': 'bar'}})
        self.assertIsNone(res['provision_updated_at'])
        self.assertIsNone(res['inspection_started_at'])

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_update_node_inspection_started_at(self, mock_utcnow):
        mocked_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = mocked_time
        node = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                      inspection_started_at=mocked_time)
        res = self.dbapi.update_node(node.id, {'provision_state': 'fake'})
        result = res['inspection_started_at']
        self.assertEqual(mocked_time,
                         timeutils.normalize_time(result))
        self.assertIsNone(res['inspection_finished_at'])

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_update_node_inspection_finished_at(self, mock_utcnow):
        mocked_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = mocked_time
        node = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                      inspection_finished_at=mocked_time)
        res = self.dbapi.update_node(node.id, {'provision_state': 'fake'})
        result = res['inspection_finished_at']
        self.assertEqual(mocked_time,
                         timeutils.normalize_time(result))
        self.assertIsNone(res['inspection_started_at'])

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_update_node_inspection_finished_at_inspecting(self, mock_utcnow):
        mocked_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = mocked_time
        node = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                      inspection_finished_at=mocked_time,
                                      provision_state=states.INSPECTING)
        res = self.dbapi.update_node(node.id,
                                     {'provision_state': states.MANAGEABLE})
        result = res['inspection_finished_at']
        self.assertEqual(mocked_time,
                         timeutils.normalize_time(result))
        self.assertIsNone(res['inspection_started_at'])

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_update_node_inspection_finished_at_inspectwait(self,
                                                            mock_utcnow):
        mocked_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = mocked_time
        node = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                      inspection_finished_at=mocked_time,
                                      provision_state=states.INSPECTWAIT)
        res = self.dbapi.update_node(node.id,
                                     {'provision_state': states.MANAGEABLE})
        result = res['inspection_finished_at']
        self.assertEqual(mocked_time,
                         timeutils.normalize_time(result))
        self.assertIsNone(res['inspection_started_at'])

    def test_update_node_inspection_started_at_inspecting(self):
        mocked_time = datetime.datetime(2000, 1, 1, 0, 0)
        node = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                      inspection_started_at=mocked_time,
                                      provision_state=states.INSPECTING)
        res = self.dbapi.update_node(node.id,
                                     {'provision_state': states.INSPECTFAIL})
        self.assertIsNone(res['inspection_started_at'])

    def test_update_node_inspection_started_at_inspectwait(self):
        mocked_time = datetime.datetime(2000, 1, 1, 0, 0)
        node = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                      inspection_started_at=mocked_time,
                                      provision_state=states.INSPECTWAIT)
        res = self.dbapi.update_node(node.id,
                                     {'provision_state': states.INSPECTFAIL})
        self.assertIsNone(res['inspection_started_at'])

    def test_reserve_node(self):
        node = utils.create_test_node()
        self.dbapi.set_node_tags(node.id, ['tag1', 'tag2'])
        utils.create_test_node_traits(node_id=node.id,
                                      traits=['trait1', 'trait2'])
        uuid = node.uuid

        r1 = 'fake-reservation'

        # reserve the node
        res = self.dbapi.reserve_node(r1, uuid)
        self.assertCountEqual(['tag1', 'tag2'], [tag.tag for tag in res.tags])
        self.assertCountEqual(['trait1', 'trait2'],
                              [trait.trait for trait in res.traits])

        # check reservation
        res = self.dbapi.get_node_by_uuid(uuid)
        self.assertEqual(r1, res.reservation)

    def test_release_reservation(self):
        node = utils.create_test_node()
        uuid = node.uuid

        r1 = 'fake-reservation'
        self.dbapi.reserve_node(r1, uuid)

        # release reservation
        self.dbapi.release_node(r1, uuid)
        res = self.dbapi.get_node_by_uuid(uuid)
        self.assertIsNone(res.reservation)

    def test_reservation_of_reserved_node_fails(self):
        node = utils.create_test_node()
        uuid = node.uuid

        r1 = 'fake-reservation'
        r2 = 'another-reservation'

        # reserve the node
        self.dbapi.reserve_node(r1, uuid)

        # another host fails to reserve or release
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.reserve_node,
                          r2, uuid)
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.release_node,
                          r2, uuid)

    def test_reservation_after_release(self):
        node = utils.create_test_node()
        uuid = node.uuid

        r1 = 'fake-reservation'
        r2 = 'another-reservation'

        self.dbapi.reserve_node(r1, uuid)
        self.dbapi.release_node(r1, uuid)

        # another host succeeds
        self.dbapi.reserve_node(r2, uuid)
        res = self.dbapi.get_node_by_uuid(uuid)
        self.assertEqual(r2, res.reservation)

    def test_reservation_in_exception_message(self):
        node = utils.create_test_node()
        uuid = node.uuid

        r = 'fake-reservation'
        self.dbapi.reserve_node(r, uuid)
        exc = self.assertRaises(exception.NodeLocked, self.dbapi.reserve_node,
                                'another', uuid)
        self.assertIn(r, str(exc))

    def test_reservation_non_existent_node(self):
        node = utils.create_test_node()
        self.dbapi.destroy_node(node.id)

        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.reserve_node, 'fake', node.id)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.reserve_node, 'fake', node.uuid)

    def test_release_non_existent_node(self):
        node = utils.create_test_node()
        self.dbapi.destroy_node(node.id)

        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.release_node, 'fake', node.id)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.release_node, 'fake', node.uuid)

    def test_release_non_locked_node(self):
        node = utils.create_test_node()

        self.assertIsNone(node.reservation)
        self.assertRaises(exception.NodeNotLocked,
                          self.dbapi.release_node, 'fake', node.id)
        self.assertRaises(exception.NodeNotLocked,
                          self.dbapi.release_node, 'fake', node.uuid)

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_touch_node_provisioning(self, mock_utcnow):
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = test_time
        node = utils.create_test_node()
        # assert provision_updated_at is None
        self.assertIsNone(node.provision_updated_at)

        self.dbapi.touch_node_provisioning(node.uuid)
        node = self.dbapi.get_node_by_uuid(node.uuid)
        # assert provision_updated_at has been updated
        self.assertEqual(test_time,
                         timeutils.normalize_time(node.provision_updated_at))

    def test_touch_node_provisioning_not_found(self):
        self.assertRaises(
            exception.NodeNotFound,
            self.dbapi.touch_node_provisioning, uuidutils.generate_uuid())

    def test_get_node_by_port_addresses(self):
        wrong_node = utils.create_test_node(
            driver='driver-one',
            uuid=uuidutils.generate_uuid())
        node = utils.create_test_node(
            driver='driver-two',
            uuid=uuidutils.generate_uuid())
        addresses = []
        for i in (1, 2, 3):
            address = '52:54:00:cf:2d:4%s' % i
            utils.create_test_port(uuid=uuidutils.generate_uuid(),
                                   node_id=node.id, address=address)
            if i > 1:
                addresses.append(address)
        utils.create_test_port(uuid=uuidutils.generate_uuid(),
                               node_id=wrong_node.id,
                               address='aa:bb:cc:dd:ee:ff')

        res = self.dbapi.get_node_by_port_addresses(addresses)
        self.assertEqual(node.uuid, res.uuid)
        self.assertEqual([], res.traits)

    def test_get_node_by_port_addresses_not_found(self):
        node = utils.create_test_node(
            driver='driver',
            uuid=uuidutils.generate_uuid())
        utils.create_test_port(uuid=uuidutils.generate_uuid(),
                               node_id=node.id,
                               address='aa:bb:cc:dd:ee:ff')

        self.assertRaisesRegex(exception.NodeNotFound,
                               'was not found',
                               self.dbapi.get_node_by_port_addresses,
                               ['11:22:33:44:55:66'])

    def test_get_node_by_port_addresses_multiple_found(self):
        node1 = utils.create_test_node(
            driver='driver',
            uuid=uuidutils.generate_uuid())
        node2 = utils.create_test_node(
            driver='driver',
            uuid=uuidutils.generate_uuid())
        addresses = ['52:54:00:cf:2d:4%s' % i for i in (1, 2)]
        utils.create_test_port(uuid=uuidutils.generate_uuid(),
                               node_id=node1.id,
                               address=addresses[0])
        utils.create_test_port(uuid=uuidutils.generate_uuid(),
                               node_id=node2.id,
                               address=addresses[1])

        self.assertRaisesRegex(exception.NodeNotFound,
                               'Multiple nodes',
                               self.dbapi.get_node_by_port_addresses,
                               addresses)

    def test_check_node_list(self):
        node1 = utils.create_test_node(uuid=uuidutils.generate_uuid())
        node2 = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                       name='node_2')
        node3 = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                       name='node_3')

        mapping = self.dbapi.check_node_list([node1.uuid, node2.name,
                                              node3.uuid])
        self.assertEqual({node1.uuid: node1.uuid,
                          node2.name: node2.uuid,
                          node3.uuid: node3.uuid},
                         mapping)

    def test_check_node_list_non_existing(self):
        node1 = utils.create_test_node(uuid=uuidutils.generate_uuid())
        node2 = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                       name='node_2')
        uuid = uuidutils.generate_uuid()

        exc = self.assertRaises(exception.NodeNotFound,
                                self.dbapi.check_node_list,
                                [node1.uuid, uuid, 'could-be-a-name',
                                 node2.name])
        self.assertIn(uuid, str(exc))
        self.assertIn('could-be-a-name', str(exc))

    def test_check_node_list_impossible(self):
        node1 = utils.create_test_node(uuid=uuidutils.generate_uuid())

        exc = self.assertRaises(exception.NodeNotFound,
                                self.dbapi.check_node_list,
                                [node1.uuid, 'this/cannot/be/a/name'])
        self.assertIn('this/cannot/be/a/name', str(exc))

    def test_node_provision_state_count(self):
        active_nodes = 5
        manageable_nodes = 3
        deploywait_nodes = 1
        for i in range(0, active_nodes):
            utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                   provision_state=states.ACTIVE)
        for i in range(0, manageable_nodes):
            utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                   provision_state=states.MANAGEABLE)
        for i in range(0, deploywait_nodes):
            utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                   provision_state=states.DEPLOYWAIT)

        self.assertEqual(
            active_nodes,
            self.dbapi.count_nodes_in_provision_state(states.ACTIVE)
        )
        self.assertEqual(
            manageable_nodes,
            self.dbapi.count_nodes_in_provision_state(states.MANAGEABLE)
        )
        self.assertEqual(
            deploywait_nodes,
            self.dbapi.count_nodes_in_provision_state(states.DEPLOYWAIT)
        )
        total = active_nodes + manageable_nodes + deploywait_nodes
        self.assertEqual(
            total,
            self.dbapi.count_nodes_in_provision_state([
                states.ACTIVE,
                states.MANAGEABLE,
                states.DEPLOYWAIT
            ])
        )
