# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


import ddt
from keystoneauth1 import exceptions as kaexception
import mock
import requests


from ironic.common import context
from ironic.common import keystone
from ironic.common import nova
from ironic.tests import base


@mock.patch.object(keystone, 'get_session', autospec=True)
@mock.patch.object(keystone, 'get_adapter', autospec=True)
class TestNovaAdapter(base.TestCase):

    def test_get_nova_adapter(self, mock_adapter, mock_nova_session):
        nova._NOVA_ADAPTER = None
        mock_session_obj = mock.Mock()
        expected = {'session': mock_session_obj,
                    'auth': None,
                    'version': "2.1"}
        mock_nova_session.return_value = mock_session_obj
        nova._get_nova_adapter()
        mock_nova_session.assert_called_once_with('nova')
        mock_adapter.assert_called_once_with(group='nova', **expected)

        """Check if existing adapter is used."""
        mock_nova_session.reset_mock()
        nova._get_nova_adapter()
        mock_nova_session.assert_not_called()


@ddt.ddt
@mock.patch.object(nova, 'LOG', autospec=True)
class NovaApiTestCase(base.TestCase):
    def setUp(self):
        super(NovaApiTestCase, self).setUp()

        self.api = nova
        self.ctx = context.get_admin_context()

    @ddt.unpack
    # one @ddt.data element comprises:
    # - nova_result: POST response JSON dict
    # - resp_status: POST response status_code
    # - exp_ret: Expected bool return value from power_update()
    @ddt.data([{'events': [{'status': 'completed',
                            'tag': 'POWER_OFF',
                            'name': 'power-update',
                            'server_uuid': '1234',
                            'code': 200}]},
               200, True],
              [{'events': [{'code': 422}]}, 207, False],
              [{'events': [{'code': 404}]}, 207, False],
              [{'events': [{'code': 400}]}, 207, False],
              # This (response 207, event code 200) will never happen IRL
              [{'events': [{'code': 200}]}, 207, True])
    @mock.patch.object(nova, '_get_nova_adapter')
    def test_power_update(self, nova_result, resp_status, exp_ret,
                          mock_adapter, mock_log):
        server_ids = ['server-id-1', 'server-id-2']
        nova_adapter = mock.Mock()
        with mock.patch.object(nova_adapter, 'post') as mock_post_event:
            post_resp_mock = requests.Response()

            def json_func():
                return nova_result
            post_resp_mock.json = json_func
            post_resp_mock.status_code = resp_status
            mock_adapter.return_value = nova_adapter
            mock_post_event.return_value = post_resp_mock
            for server in server_ids:
                result = self.api.power_update(self.ctx, server, 'power on')
                self.assertEqual(exp_ret, result)

        mock_adapter.assert_has_calls([mock.call(), mock.call()])
        req_url = '/os-server-external-events'
        mock_post_event.assert_has_calls([
            mock.call(req_url,
                      json={'events': [{'name': 'power-update',
                                        'server_uuid': 'server-id-1',
                                        'tag': 'POWER_ON'}]},
                      microversion='2.76',
                      global_request_id=self.ctx.global_id,
                      raise_exc=False),
            mock.call(req_url,
                      json={'events': [{'name': 'power-update',
                                        'server_uuid': 'server-id-2',
                                        'tag': 'POWER_ON'}]},
                      microversion='2.76',
                      global_request_id=self.ctx.global_id,
                      raise_exc=False)
        ])
        if not exp_ret:
            expected = ('Nova event: %s returned with failed status.',
                        nova_result['events'][0])
            mock_log.warning.assert_called_with(*expected)
        else:
            expected = ("Nova event response: %s.", nova_result['events'][0])
            mock_log.debug.assert_called_with(*expected)

    @mock.patch.object(nova, '_get_nova_adapter')
    def test_invalid_power_update(self, mock_adapter, mock_log):
        nova_adapter = mock.Mock()
        with mock.patch.object(nova_adapter, 'post') as mock_post_event:
            result = self.api.power_update(self.ctx, 'server', None)
            self.assertFalse(result)
            expected = ('Invalid Power State %s.', None)
            mock_log.error.assert_called_once_with(*expected)

        mock_adapter.assert_not_called()
        mock_post_event.assert_not_called()

    def test_power_update_failed(self, mock_log):
        nova_adapter = nova._get_nova_adapter()
        event = [{'name': 'power-update',
                  'server_uuid': 'server-id-1',
                  'tag': 'POWER_OFF'}]
        nova_result = requests.Response()
        with mock.patch.object(nova_adapter, 'post') as mock_post_event:
            for stat_code in (500, 404, 400):
                mock_log.reset_mock()
                nova_result.status_code = stat_code
                type(nova_result).text = mock.PropertyMock(return_value="blah")
                mock_post_event.return_value = nova_result
                result = self.api.power_update(
                    self.ctx, 'server-id-1', 'power off')
                self.assertFalse(result)
                expected = ("Failed to notify nova on event: %s. %s.",
                            event[0], "blah")
                mock_log.warning.assert_called_once_with(*expected)

        mock_post_event.assert_has_calls([
            mock.call('/os-server-external-events',
                      json={'events': event},
                      microversion='2.76',
                      global_request_id=self.ctx.global_id,
                      raise_exc=False)
        ])

    @ddt.data({'events': [{}]},
              {'events': []},
              {'events': None},
              {})
    @mock.patch.object(nova, '_get_nova_adapter')
    def test_power_update_invalid_reponse_format(self, nova_result,
                                                 mock_adapter, mock_log):
        nova_adapter = mock.Mock()
        with mock.patch.object(nova_adapter, 'post') as mock_post_event:
            post_resp_mock = requests.Response()

            def json_func():
                return nova_result

            post_resp_mock.json = json_func
            post_resp_mock.status_code = 207
            mock_adapter.return_value = nova_adapter
            mock_post_event.return_value = post_resp_mock
            result = self.api.power_update(self.ctx, 'server-id-1', 'power on')
            self.assertFalse(result)

        mock_adapter.assert_has_calls([mock.call()])
        req_url = '/os-server-external-events'
        mock_post_event.assert_has_calls([
            mock.call(req_url,
                      json={'events': [{'name': 'power-update',
                                        'server_uuid': 'server-id-1',
                                        'tag': 'POWER_ON'}]},
                      microversion='2.76',
                      global_request_id=self.ctx.global_id,
                      raise_exc=False),
        ])
        self.assertIn('Invalid response', mock_log.error.call_args[0][0])

    @mock.patch.object(keystone, 'get_adapter', autospec=True)
    def test_power_update_failed_no_nova(self, mock_adapter, mock_log):
        self.config(send_power_notifications=False, group="nova")
        result = self.api.power_update(self.ctx, 'server-id-1', 'power off')
        self.assertFalse(result)
        mock_adapter.assert_not_called()

    @mock.patch.object(nova, '_get_nova_adapter')
    def test_power_update_failed_no_nova_auth_url(self, mock_adapter,
                                                  mock_log):
        server = 'server-id-1'
        emsg = 'An auth plugin is required to determine endpoint URL'
        side_effect = kaexception.MissingAuthPlugin(emsg)
        mock_nova = mock.Mock()
        mock_adapter.return_value = mock_nova
        mock_nova.post.side_effect = side_effect
        result = self.api.power_update(self.ctx, server, 'power off')
        msg = ('Could not connect to Nova to send a power notification, '
               'please check configuration. %s', side_effect)
        self.assertFalse(result)
        mock_log.warning.assert_called_once_with(*msg)
        mock_adapter.assert_called_once_with()
