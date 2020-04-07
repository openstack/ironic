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

from unittest import mock

from ironic.common import context
from ironic.db import api as dbapi
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


class TestDeployTemplateObject(db_base.DbTestCase, obj_utils.SchemasTestMixIn):

    def setUp(self):
        super(TestDeployTemplateObject, self).setUp()
        self.ctxt = context.get_admin_context()
        self.fake_template = db_utils.get_test_deploy_template()

    @mock.patch.object(dbapi.IMPL, 'create_deploy_template', autospec=True)
    def test_create(self, mock_create):
        template = objects.DeployTemplate(context=self.context,
                                          **self.fake_template)

        mock_create.return_value = db_utils.get_test_deploy_template()

        template.create()

        args, _kwargs = mock_create.call_args
        self.assertEqual(1, mock_create.call_count)

        self.assertEqual(self.fake_template['name'], template.name)
        self.assertEqual(self.fake_template['steps'], template.steps)
        self.assertEqual(self.fake_template['extra'], template.extra)

    @mock.patch.object(dbapi.IMPL, 'update_deploy_template', autospec=True)
    def test_save(self, mock_update):
        template = objects.DeployTemplate(context=self.context,
                                          **self.fake_template)
        template.obj_reset_changes()

        mock_update.return_value = db_utils.get_test_deploy_template(
            name='CUSTOM_DT2')

        template.name = 'CUSTOM_DT2'
        template.save()

        mock_update.assert_called_once_with(
            self.fake_template['uuid'],
            {'name': 'CUSTOM_DT2', 'version': objects.DeployTemplate.VERSION})

        self.assertEqual('CUSTOM_DT2', template.name)

    @mock.patch.object(dbapi.IMPL, 'destroy_deploy_template', autospec=True)
    def test_destroy(self, mock_destroy):
        template = objects.DeployTemplate(context=self.context,
                                          id=self.fake_template['id'])

        template.destroy()

        mock_destroy.assert_called_once_with(self.fake_template['id'])

    @mock.patch.object(dbapi.IMPL, 'get_deploy_template_by_id', autospec=True)
    def test_get_by_id(self, mock_get):
        mock_get.return_value = self.fake_template

        template = objects.DeployTemplate.get_by_id(
            self.context, self.fake_template['id'])

        mock_get.assert_called_once_with(self.fake_template['id'])
        self.assertEqual(self.fake_template['name'], template.name)
        self.assertEqual(self.fake_template['uuid'], template.uuid)
        self.assertEqual(self.fake_template['steps'], template.steps)
        self.assertEqual(self.fake_template['extra'], template.extra)

    @mock.patch.object(dbapi.IMPL, 'get_deploy_template_by_uuid',
                       autospec=True)
    def test_get_by_uuid(self, mock_get):
        mock_get.return_value = self.fake_template

        template = objects.DeployTemplate.get_by_uuid(
            self.context, self.fake_template['uuid'])

        mock_get.assert_called_once_with(self.fake_template['uuid'])
        self.assertEqual(self.fake_template['name'], template.name)
        self.assertEqual(self.fake_template['uuid'], template.uuid)
        self.assertEqual(self.fake_template['steps'], template.steps)
        self.assertEqual(self.fake_template['extra'], template.extra)

    @mock.patch.object(dbapi.IMPL, 'get_deploy_template_by_name',
                       autospec=True)
    def test_get_by_name(self, mock_get):
        mock_get.return_value = self.fake_template

        template = objects.DeployTemplate.get_by_name(
            self.context, self.fake_template['name'])

        mock_get.assert_called_once_with(self.fake_template['name'])
        self.assertEqual(self.fake_template['name'], template.name)
        self.assertEqual(self.fake_template['uuid'], template.uuid)
        self.assertEqual(self.fake_template['steps'], template.steps)
        self.assertEqual(self.fake_template['extra'], template.extra)

    @mock.patch.object(dbapi.IMPL, 'get_deploy_template_list', autospec=True)
    def test_list(self, mock_list):
        mock_list.return_value = [self.fake_template]

        templates = objects.DeployTemplate.list(self.context)

        mock_list.assert_called_once_with(limit=None, marker=None,
                                          sort_dir=None, sort_key=None)
        self.assertEqual(1, len(templates))
        self.assertEqual(self.fake_template['name'], templates[0].name)
        self.assertEqual(self.fake_template['uuid'], templates[0].uuid)
        self.assertEqual(self.fake_template['steps'], templates[0].steps)
        self.assertEqual(self.fake_template['extra'], templates[0].extra)

    @mock.patch.object(dbapi.IMPL, 'get_deploy_template_list_by_names',
                       autospec=True)
    def test_list_by_names(self, mock_list):
        mock_list.return_value = [self.fake_template]

        names = [self.fake_template['name']]
        templates = objects.DeployTemplate.list_by_names(self.context, names)

        mock_list.assert_called_once_with(names)
        self.assertEqual(1, len(templates))
        self.assertEqual(self.fake_template['name'], templates[0].name)
        self.assertEqual(self.fake_template['uuid'], templates[0].uuid)
        self.assertEqual(self.fake_template['steps'], templates[0].steps)
        self.assertEqual(self.fake_template['extra'], templates[0].extra)

    @mock.patch.object(dbapi.IMPL, 'get_deploy_template_by_uuid',
                       autospec=True)
    def test_refresh(self, mock_get):
        uuid = self.fake_template['uuid']
        mock_get.side_effect = [dict(self.fake_template),
                                dict(self.fake_template, name='CUSTOM_DT2')]

        template = objects.DeployTemplate.get_by_uuid(self.context, uuid)

        self.assertEqual(self.fake_template['name'], template.name)

        template.refresh()

        self.assertEqual('CUSTOM_DT2', template.name)
        expected = [mock.call(uuid), mock.call(uuid)]
        self.assertEqual(expected, mock_get.call_args_list)
        self.assertEqual(self.context, template._context)
