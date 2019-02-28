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

"""Tests for manipulating DeployTemplates via the DB API"""

from oslo_db import exception as db_exc
from oslo_utils import uuidutils
import six

from ironic.common import exception
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils as db_utils


class DbDeployTemplateTestCase(base.DbTestCase):

    def setUp(self):
        super(DbDeployTemplateTestCase, self).setUp()
        self.template = db_utils.create_test_deploy_template()

    def test_create(self):
        self.assertEqual('CUSTOM_DT1', self.template.name)
        self.assertEqual(1, len(self.template.steps))
        step = self.template.steps[0]
        self.assertEqual(self.template.id, step.deploy_template_id)
        self.assertEqual('raid', step.interface)
        self.assertEqual('create_configuration', step.step)
        self.assertEqual({'logical_disks': []}, step.args)
        self.assertEqual(10, step.priority)
        self.assertEqual({}, self.template.extra)

    def test_create_no_steps(self):
        uuid = uuidutils.generate_uuid()
        template = db_utils.create_test_deploy_template(
            uuid=uuid, name='CUSTOM_DT2', steps=[])
        self.assertEqual([], template.steps)

    def test_create_duplicate_uuid(self):
        self.assertRaises(exception.DeployTemplateAlreadyExists,
                          db_utils.create_test_deploy_template,
                          uuid=self.template.uuid, name='CUSTOM_DT2')

    def test_create_duplicate_name(self):
        uuid = uuidutils.generate_uuid()
        self.assertRaises(exception.DeployTemplateDuplicateName,
                          db_utils.create_test_deploy_template,
                          uuid=uuid, name=self.template.name)

    def test_create_invalid_step_no_interface(self):
        uuid = uuidutils.generate_uuid()
        template = db_utils.get_test_deploy_template(uuid=uuid,
                                                     name='CUSTOM_DT2')
        del template['steps'][0]['interface']
        self.assertRaises(db_exc.DBError,
                          self.dbapi.create_deploy_template,
                          template)

    def test_update_name(self):
        values = {'name': 'CUSTOM_DT2'}
        template = self.dbapi.update_deploy_template(self.template.id, values)
        self.assertEqual('CUSTOM_DT2', template.name)

    def test_update_steps_replace(self):
        step = {'interface': 'bios', 'step': 'apply_configuration',
                'args': {}, 'priority': 50}
        values = {'steps': [step]}
        template = self.dbapi.update_deploy_template(self.template.id, values)
        self.assertEqual(1, len(template.steps))
        step = template.steps[0]
        self.assertEqual('bios', step.interface)
        self.assertEqual('apply_configuration', step.step)
        self.assertEqual({}, step.args)
        self.assertEqual(50, step.priority)

    def test_update_steps_add(self):
        step = {'interface': 'bios', 'step': 'apply_configuration',
                'args': {}, 'priority': 50}
        values = {'steps': [self.template.steps[0], step]}
        template = self.dbapi.update_deploy_template(self.template.id, values)
        self.assertEqual(2, len(template.steps))
        step0 = template.steps[0]
        self.assertEqual(self.template.steps[0].id, step0.id)
        self.assertEqual('raid', step0.interface)
        self.assertEqual('create_configuration', step0.step)
        self.assertEqual({'logical_disks': []}, step0.args)
        self.assertEqual(10, step0.priority)
        step1 = template.steps[1]
        self.assertNotEqual(self.template.steps[0].id, step1.id)
        self.assertEqual('bios', step1.interface)
        self.assertEqual('apply_configuration', step1.step)
        self.assertEqual({}, step1.args)
        self.assertEqual(50, step1.priority)

    def test_update_steps_replace_args(self):
        step = self.template.steps[0]
        step['args'] = {'foo': 'bar'}
        values = {'steps': [step]}
        template = self.dbapi.update_deploy_template(self.template.id, values)
        self.assertEqual(1, len(template.steps))
        step = template.steps[0]
        self.assertEqual({'foo': 'bar'}, step.args)

    def test_update_steps_remove_all(self):
        values = {'steps': []}
        template = self.dbapi.update_deploy_template(self.template.id, values)
        self.assertEqual([], template.steps)

    def test_update_extra(self):
        values = {'extra': {'foo': 'bar'}}
        template = self.dbapi.update_deploy_template(self.template.id, values)
        self.assertEqual({'foo': 'bar'}, template.extra)

    def test_update_duplicate_name(self):
        uuid = uuidutils.generate_uuid()
        template2 = db_utils.create_test_deploy_template(uuid=uuid,
                                                         name='CUSTOM_DT2')
        values = {'name': self.template.name}
        self.assertRaises(exception.DeployTemplateDuplicateName,
                          self.dbapi.update_deploy_template, template2.id,
                          values)

    def test_update_not_found(self):
        self.assertRaises(exception.DeployTemplateNotFound,
                          self.dbapi.update_deploy_template, 123, {})

    def test_update_uuid_not_allowed(self):
        uuid = uuidutils.generate_uuid()
        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.update_deploy_template,
                          self.template.id, {'uuid': uuid})

    def test_destroy(self):
        self.dbapi.destroy_deploy_template(self.template.id)
        # Attempt to retrieve the template to verify it is gone.
        self.assertRaises(exception.DeployTemplateNotFound,
                          self.dbapi.get_deploy_template_by_id,
                          self.template.id)
        # Ensure that the destroy_deploy_template returns the
        # expected exception.
        self.assertRaises(exception.DeployTemplateNotFound,
                          self.dbapi.destroy_deploy_template,
                          self.template.id)

    def test_get_deploy_template_by_id(self):
        res = self.dbapi.get_deploy_template_by_id(self.template.id)
        self.assertEqual(self.template.id, res.id)
        self.assertEqual(self.template.name, res.name)
        self.assertEqual(1, len(res.steps))
        self.assertEqual(self.template.id, res.steps[0].deploy_template_id)
        self.assertRaises(exception.DeployTemplateNotFound,
                          self.dbapi.get_deploy_template_by_id, -1)

    def test_get_deploy_template_by_uuid(self):
        res = self.dbapi.get_deploy_template_by_uuid(self.template.uuid)
        self.assertEqual(self.template.id, res.id)
        invalid_uuid = uuidutils.generate_uuid()
        self.assertRaises(exception.DeployTemplateNotFound,
                          self.dbapi.get_deploy_template_by_uuid, invalid_uuid)

    def test_get_deploy_template_by_name(self):
        res = self.dbapi.get_deploy_template_by_name(self.template.name)
        self.assertEqual(self.template.id, res.id)
        self.assertRaises(exception.DeployTemplateNotFound,
                          self.dbapi.get_deploy_template_by_name, 'bogus')

    def _template_list_preparation(self):
        uuids = [six.text_type(self.template.uuid)]
        for i in range(1, 3):
            template = db_utils.create_test_deploy_template(
                uuid=uuidutils.generate_uuid(),
                name='CUSTOM_DT%d' % (i + 1))
            uuids.append(six.text_type(template.uuid))
        return uuids

    def test_get_deploy_template_list(self):
        uuids = self._template_list_preparation()
        res = self.dbapi.get_deploy_template_list()
        res_uuids = [r.uuid for r in res]
        six.assertCountEqual(self, uuids, res_uuids)

    def test_get_deploy_template_list_sorted(self):
        uuids = self._template_list_preparation()
        res = self.dbapi.get_deploy_template_list(sort_key='uuid')
        res_uuids = [r.uuid for r in res]
        self.assertEqual(sorted(uuids), res_uuids)

        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.get_deploy_template_list, sort_key='foo')

    def test_get_deploy_template_list_by_names(self):
        self._template_list_preparation()
        names = ['CUSTOM_DT2', 'CUSTOM_DT3']
        res = self.dbapi.get_deploy_template_list_by_names(names=names)
        res_names = [r.name for r in res]
        six.assertCountEqual(self, names, res_names)

    def test_get_deploy_template_list_by_names_no_match(self):
        self._template_list_preparation()
        names = ['CUSTOM_FOO']
        res = self.dbapi.get_deploy_template_list_by_names(names=names)
        self.assertEqual([], res)
