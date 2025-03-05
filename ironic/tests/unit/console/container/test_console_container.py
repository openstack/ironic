#
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

import os
import tempfile
from unittest import mock

from oslo_concurrency import processutils
from oslo_config import cfg

from ironic.common import console_factory
from ironic.common import exception
from ironic.common import utils
from ironic.console.container import fake
from ironic.tests import base

CONF = cfg.CONF


def _reset_provider(provider_name):
    CONF.set_override('container_provider', provider_name, 'vnc')
    console_factory.ConsoleContainerFactory._provider = None


class TestConsoleContainerFactory(base.TestCase):

    def setUp(self):
        super(TestConsoleContainerFactory, self).setUp()
        _reset_provider('fake')

    def test_factory(self):
        provider = console_factory.ConsoleContainerFactory().provider

        self.assertIsInstance(provider, fake.FakeConsoleContainer)

        provider2 = console_factory.ConsoleContainerFactory().provider
        self.assertEqual(provider, provider2)


class TestSystemdConsoleContainer(base.TestCase):

    def setUp(self):
        super(TestSystemdConsoleContainer, self).setUp()
        _reset_provider('systemd')
        self.addCleanup(_reset_provider, 'fake')
        self.tempdir = tempfile.mkdtemp()
        self.addCleanup(lambda: utils.rmtree_without_raise(self.tempdir))
        os.environ['XDG_RUNTIME_DIR'] = self.tempdir
        with mock.patch.object(utils, 'execute', autospec=True) as mock_exec:
            self.provider = console_factory.ConsoleContainerFactory().provider
            mock_exec.assert_has_calls([
                mock.call('systemctl', '--version'),
                mock.call('podman', '--version'),
            ])
        # Override unit directory with tempdir
        self.provider._init_unit_dir(self.tempdir)

    def test__container_path(self):
        self.assertEqual(
            f'{self.tempdir}/ironic-console-1234.container',
            self.provider._container_path('1234'))

    def test__unit_name(self):
        self.assertEqual(
            'ironic-console-1234.service',
            self.provider._unit_name('1234')
        )

    def test__container_name(self):
        self.assertEqual(
            'systemd-ironic-console-1234',
            self.provider._container_name('1234')
        )

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__reload(self, mock_exec):

        mock_exec.return_value = (None, None)
        self.provider._reload()

        # assert successful call
        mock_exec.assert_called_once_with(
            'systemctl', '--user', 'daemon-reload')

        mock_exec.side_effect = [
            processutils.ProcessExecutionError(
                stderr='ouch'
            ),
            (None, None)
        ]
        # assert failed call
        self.assertRaisesRegex(exception.ConsoleContainerError, 'ouch',
                               self.provider._reload)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__start(self, mock_exec):

        mock_exec.return_value = (None, None)
        unit = self.provider._unit_name('1234')
        self.provider._start(unit)

        # assert successful call
        mock_exec.assert_called_once_with(
            'systemctl', '--user', 'start', unit)

        mock_exec.side_effect = [
            processutils.ProcessExecutionError(
                stderr='ouch'
            ),
            (None, None)
        ]
        # assert failed call
        self.assertRaisesRegex(exception.ConsoleContainerError, 'ouch',
                               self.provider._start, unit)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__stop(self, mock_exec):

        mock_exec.return_value = (None, None)
        unit = self.provider._unit_name('1234')
        self.provider._stop(unit)

        # assert successful call
        mock_exec.assert_called_once_with('systemctl', '--user', 'stop', unit)

        mock_exec.side_effect = [
            processutils.ProcessExecutionError(
                stderr='ouch'
            ),
            (None, None)
        ]
        # assert failed call
        self.assertRaisesRegex(exception.ConsoleContainerError, 'ouch',
                               self.provider._stop, unit)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__host_port(self, mock_exec):

        mock_exec.return_value = ('5900/tcp -> 192.0.2.1:33819', None)
        container = self.provider._container_name('1234')
        self.assertEqual(
            ('192.0.2.1', 33819),
            self.provider._host_port(container)
        )

        # assert successful call
        mock_exec.assert_called_once_with('podman', 'port', container)

        # assert failed parsing response
        mock_exec.return_value = ('5900/tcp -> asdkljffo872', None)
        self.assertRaisesRegex(exception.ConsoleContainerError,
                               'Could not detect port',
                               self.provider._host_port, container)

        mock_exec.side_effect = [
            processutils.ProcessExecutionError(
                stderr=f'Error: no container with name or ID "{container}" '
                       'found: no such container'
            ),
            (None, None)
        ]
        # assert failed call
        self.assertRaisesRegex(exception.ConsoleContainerError,
                               'no such container',
                               self.provider._host_port, container)

    def test__write_container_file(self):
        CONF.set_override(
            'systemd_container_publish_port',
            '192.0.2.2::5900',
            group='vnc')
        CONF.set_override(
            'console_image',
            'localhost/ironic-vnc-container',
            group='vnc')
        CONF.set_override(
            'read_only',
            True,
            group='vnc')

        uuid = '1234'
        container_path = self.provider._container_path(uuid)
        self.provider._write_container_file(
            identifier=uuid, app_name='fake', app_info={})

        # assert the file is correct
        with open(container_path, "r") as f:
            self.assertEqual(
                """[Unit]
Description=A VNC server which displays a console for node 1234

[Container]
Image=localhost/ironic-vnc-container
PublishPort=192.0.2.2::5900
Environment=APP=fake
Environment=APP_INFO='{}'
Environment=READ_ONLY=True

[Install]
WantedBy=default.target""", f.read())

    def test_delete_container_file(self):
        uuid = '1234'
        self.provider._write_container_file(
            uuid, app_name='fake', app_info={})

        container_path = self.provider._container_path(uuid)

        # initial state file exists
        self.assertTrue(os.path.isfile(container_path))

        self.provider._delete_container_file(uuid)

        # assert file was deleted
        self.assertFalse(os.path.exists(container_path))

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_start_stop_container(self, mock_exec):
        uuid = '1234'
        task = mock.Mock(node=mock.Mock(uuid=uuid))

        container_path = self.provider._container_path(uuid)

        mock_exec.side_effect = [
            (None, None),
            (None, None),
            ('5900/tcp -> 192.0.2.1:33819', None)
        ]

        # start the container and assert the host / port
        self.assertEqual(
            ('192.0.2.1', 33819),
            self.provider.start_container(task, 'fake', {})
        )
        # assert the created file
        self.assertTrue(os.path.isfile(container_path))

        # assert all the expected calls
        mock_exec.assert_has_calls([
            mock.call('systemctl', '--user', 'daemon-reload'),
            mock.call('systemctl', '--user', 'start',
                      'ironic-console-1234.service'),
            mock.call('podman', 'port', 'systemd-ironic-console-1234')
        ])

        mock_exec.reset_mock()
        mock_exec.side_effect = [
            (None, None),
            (None, None),
        ]
        # stop the container
        self.provider.stop_container(task)

        # assert the container file is deleted
        self.assertFalse(os.path.exists(container_path))

        # assert expected stop calls
        mock_exec.assert_has_calls([
            mock.call('systemctl', '--user', 'stop',
                      'ironic-console-1234.service'),
            mock.call('systemctl', '--user', 'daemon-reload'),
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_stop_all_containers(self, mock_exec):
        # set up initial state with 3 running containers
        t1 = mock.Mock(node=mock.Mock(uuid='1234'))
        t2 = mock.Mock(node=mock.Mock(uuid='asdf'))
        t3 = mock.Mock(node=mock.Mock(uuid='foobar'))
        mock_exec.side_effect = [
            (None, None),
            (None, None),
            ('5900/tcp -> 192.0.2.1:33819', None),
            (None, None),
            (None, None),
            ('5900/tcp -> 192.0.2.1:33820', None),
            (None, None),
            (None, None),
            ('5900/tcp -> 192.0.2.1:33821', None),
        ]
        self.provider.start_container(t1, 'fake', {})
        self.provider.start_container(t2, 'fake', {})
        self.provider.start_container(t3, 'fake', {})

        mock_exec.reset_mock()
        mock_exec.side_effect = [
            (None, None),
            (None, None),
            (None, None),
            (None, None),
        ]

        self.provider.stop_all_containers()
        # assert all containers stopped
        mock_exec.assert_has_calls([
            mock.call('systemctl', '--user', 'stop',
                      'ironic-console-1234.service'),
        ])
        mock_exec.assert_has_calls([
            mock.call('systemctl', '--user', 'stop',
                      'ironic-console-asdf.service'),
        ])
        mock_exec.assert_has_calls([
            mock.call('systemctl', '--user', 'stop',
                      'ironic-console-foobar.service'),
        ])
        mock_exec.assert_has_calls([
            mock.call('systemctl', '--user', 'daemon-reload')
        ])

        # stop all containers again and confirm nothing was stopped because
        # all of the files are deleted
        mock_exec.reset_mock()
        self.provider.stop_all_containers()
        mock_exec.assert_not_called()
