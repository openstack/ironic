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

"""Tests for manipulating Runbooks via the DB API"""

from oslo_db import exception as db_exc
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils as db_utils


class DbRunbookTestCase(base.DbTestCase):

    def setUp(self):
        super(DbRunbookTestCase, self).setUp()
        self.runbook = db_utils.create_test_runbook()

    def test_create(self):
        self.assertEqual('CUSTOM_DT1', self.runbook.name)
        self.assertEqual(1, len(self.runbook.steps))
        step = self.runbook.steps[0]
        self.assertEqual(self.runbook.id, step.runbook_id)
        self.assertEqual('raid', step.interface)
        self.assertEqual('create_configuration', step.step)
        self.assertEqual({'logical_disks': []}, step.args)
        self.assertEqual({}, self.runbook.extra)

    def test_create_no_steps(self):
        uuid = uuidutils.generate_uuid()
        runbook = db_utils.create_test_runbook(
            uuid=uuid, name='CUSTOM_DT2', steps=[])
        self.assertEqual([], runbook.steps)

    def test_create_duplicate_uuid(self):
        self.assertRaises(exception.RunbookAlreadyExists,
                          db_utils.create_test_runbook,
                          uuid=self.runbook.uuid, name='CUSTOM_DT2')

    def test_create_duplicate_name(self):
        uuid = uuidutils.generate_uuid()
        self.assertRaises(exception.RunbookDuplicateName,
                          db_utils.create_test_runbook,
                          uuid=uuid, name=self.runbook.name)

    def test_create_invalid_step_no_interface(self):
        uuid = uuidutils.generate_uuid()
        runbook = db_utils.get_test_runbook(uuid=uuid,
                                            name='CUSTOM_DT2')
        del runbook['steps'][0]['interface']
        self.assertRaises(db_exc.DBError,
                          self.dbapi.create_runbook,
                          runbook)

    def test_update_name(self):
        values = {'name': 'CUSTOM_DT2'}
        runbook = self.dbapi.update_runbook(self.runbook.id, values)
        self.assertEqual('CUSTOM_DT2', runbook.name)

    def test_update_steps_replace(self):
        step = {'interface': 'bios', 'step': 'apply_configuration',
                'args': {}, 'order': 1}
        values = {'steps': [step]}
        runbook = self.dbapi.update_runbook(self.runbook.id, values)
        self.assertEqual(1, len(runbook.steps))
        step = runbook.steps[0]
        self.assertEqual('bios', step.interface)
        self.assertEqual('apply_configuration', step.step)
        self.assertEqual({}, step.args)
        self.assertEqual(1, step.order)

    def test_update_steps_add(self):
        step = {'interface': 'bios', 'step': 'apply_configuration',
                'args': {}, 'order': 1}
        values = {'steps': [self.runbook.steps[0], step]}
        runbook = self.dbapi.update_runbook(self.runbook.id, values)
        self.assertEqual(2, len(runbook.steps))
        step0 = runbook.steps[0]
        self.assertEqual(self.runbook.steps[0].id, step0.id)
        self.assertEqual('raid', step0.interface)
        self.assertEqual('create_configuration', step0.step)
        self.assertEqual({'logical_disks': []}, step0.args)
        step1 = runbook.steps[1]
        self.assertNotEqual(self.runbook.steps[0].id, step1.id)
        self.assertEqual('bios', step1.interface)
        self.assertEqual('apply_configuration', step1.step)
        self.assertEqual({}, step1.args)
        self.assertEqual(1, step1.order)

    def test_update_steps_replace_args(self):
        step = self.runbook.steps[0]
        step['args'] = {'foo': 'bar'}
        values = {'steps': [step]}
        runbook = self.dbapi.update_runbook(self.runbook.id, values)
        self.assertEqual(1, len(runbook.steps))
        step = runbook.steps[0]
        self.assertEqual({'foo': 'bar'}, step.args)

    def test_update_steps_remove_all(self):
        values = {'steps': []}
        runbook = self.dbapi.update_runbook(self.runbook.id, values)
        self.assertEqual([], runbook.steps)

    def test_update_extra(self):
        values = {'extra': {'foo': 'bar'}}
        runbook = self.dbapi.update_runbook(self.runbook.id, values)
        self.assertEqual({'foo': 'bar'}, runbook.extra)

    def test_update_duplicate_name(self):
        uuid = uuidutils.generate_uuid()
        runbook2 = db_utils.create_test_runbook(uuid=uuid,
                                                name='CUSTOM_DT2')
        values = {'name': self.runbook.name}
        self.assertRaises(exception.RunbookDuplicateName,
                          self.dbapi.update_runbook, runbook2.id,
                          values)

    def test_update_not_found(self):
        self.assertRaises(exception.RunbookNotFound,
                          self.dbapi.update_runbook, 123, {})

    def test_update_uuid_not_allowed(self):
        uuid = uuidutils.generate_uuid()
        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.update_runbook,
                          self.runbook.id, {'uuid': uuid})

    def test_destroy(self):
        self.dbapi.destroy_runbook(self.runbook.id)
        # Attempt to retrieve the runbook to verify it is gone.
        self.assertRaises(exception.RunbookNotFound,
                          self.dbapi.get_runbook_by_id,
                          self.runbook.id)
        # Ensure that the destroy_runbook returns the
        # expected exception.
        self.assertRaises(exception.RunbookNotFound,
                          self.dbapi.destroy_runbook,
                          self.runbook.id)

    def test_get_runbook_by_id(self):
        res = self.dbapi.get_runbook_by_id(self.runbook.id)
        self.assertEqual(self.runbook.id, res.id)
        self.assertEqual(self.runbook.name, res.name)
        self.assertEqual(1, len(res.steps))
        self.assertEqual(self.runbook.id, res.steps[0].runbook_id)
        self.assertRaises(exception.RunbookNotFound,
                          self.dbapi.get_runbook_by_id, -1)

    def test_get_runbook_by_uuid(self):
        res = self.dbapi.get_runbook_by_uuid(self.runbook.uuid)
        self.assertEqual(self.runbook.id, res.id)
        invalid_uuid = uuidutils.generate_uuid()
        self.assertRaises(exception.RunbookNotFound,
                          self.dbapi.get_runbook_by_uuid, invalid_uuid)

    def test_get_runbook_by_name(self):
        res = self.dbapi.get_runbook_by_name(self.runbook.name)
        self.assertEqual(self.runbook.id, res.id)
        self.assertRaises(exception.RunbookNotFound,
                          self.dbapi.get_runbook_by_name, 'bogus')

    def _runbook_list_preparation(self):
        uuids = [str(self.runbook.uuid)]
        for i in range(1, 3):
            runbook = db_utils.create_test_runbook(
                uuid=uuidutils.generate_uuid(),
                name='CUSTOM_DT%d' % (i + 1))
            uuids.append(str(runbook.uuid))
        return uuids

    def test_get_runbook_list(self):
        uuids = self._runbook_list_preparation()
        res = self.dbapi.get_runbook_list()
        res_uuids = [r.uuid for r in res]
        self.assertCountEqual(uuids, res_uuids)

    def test_get_runbook_list_sorted(self):
        uuids = self._runbook_list_preparation()
        res = self.dbapi.get_runbook_list(sort_key='uuid')
        res_uuids = [r.uuid for r in res]
        self.assertEqual(sorted(uuids), res_uuids)

        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.get_runbook_list, sort_key='foo')

    def test_get_runbook_list_by_names(self):
        self._runbook_list_preparation()
        names = ['CUSTOM_DT2', 'CUSTOM_DT3']
        res = self.dbapi.get_runbook_list_by_names(names=names)
        res_names = [r.name for r in res]
        self.assertCountEqual(names, res_names)

    def test_get_runbook_list_by_names_no_match(self):
        self._runbook_list_preparation()
        names = ['CUSTOM_FOO']
        res = self.dbapi.get_runbook_list_by_names(names=names)
        self.assertEqual([], res)
