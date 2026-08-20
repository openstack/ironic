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

import json
import os
import socket
import tempfile
import time
from unittest import mock
import yaml

from oslo_concurrency import processutils
from oslo_config import cfg

from ironic.common import console_factory
from ironic.common import exception
from ironic.common import utils
from ironic.console.container import container
from ironic.console.container import fake
from ironic.console.container import kubernetes
from ironic.console.container import systemd
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
        mock_exec.assert_has_calls([
            mock.call('journalctl', '--user', '--no-pager', '-u', unit,
                      check_exit_code=False),
            mock.call('systemctl', '--user', 'stop', unit)
        ])

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

        mock_exec.return_value = ("5900/tcp -> 192.0.2.1:33819", None)
        container = self.provider._container_name("1234")
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
    @mock.patch.object(systemd.SystemdConsoleContainer, '_wait_for_listen',
                       autospec=True)
    def test_start_container(self, mock_wait, mock_exec):
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

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_start_container_failed(self, mock_exec):
        uuid = '1234'
        task = mock.Mock(node=mock.Mock(uuid=uuid))

        container_path = self.provider._container_path(uuid)

        mock_exec.side_effect = [
            (None, None),
            processutils.ProcessExecutionError(
                stderr='ouch'
            ),
            ("unit not running", None),
            ("things happened", None)
        ]

        # start the container and assert the host / port
        self.assertRaises(
            exception.ConsoleContainerError,
            self.provider.start_container, task, 'fake', {})
        # assert the created file was cleaned up
        self.assertFalse(os.path.isfile(container_path))

        # assert all the expected calls
        mock_exec.assert_has_calls([
            mock.call('systemctl', '--user', 'daemon-reload'),
            mock.call('systemctl', '--user', 'start',
                      'ironic-console-1234.service'),
            mock.call('systemctl', '--user', 'status',
                      'ironic-console-1234.service', check_exit_code=False),
            mock.call('journalctl', '--user', '--no-pager', '-u',
                      'ironic-console-1234.service', check_exit_code=False)
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_stop_container(self, mock_exec):
        uuid = '1234'
        task = mock.Mock(node=mock.Mock(uuid=uuid))

        container_path = self.provider._container_path(uuid)

        mock_exec.reset_mock()
        mock_exec.side_effect = [
            (None, None),
            (None, None),
            (None, None),
        ]
        # stop the container
        self.provider.stop_container(task)

        # assert the container file is deleted
        self.assertFalse(os.path.exists(container_path))

        # assert expected stop calls
        mock_exec.assert_has_calls([
            mock.call('journalctl', '--user', '--no-pager', '-u',
                      'ironic-console-1234.service', check_exit_code=False),
            mock.call('systemctl', '--user', 'stop',
                      'ironic-console-1234.service'),
            mock.call('systemctl', '--user', 'daemon-reload'),
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_stop_container_failed(self, mock_exec):
        uuid = '1234'
        task = mock.Mock(node=mock.Mock(uuid=uuid))

        container_path = self.provider._container_path(uuid)

        mock_exec.reset_mock()
        mock_exec.side_effect = [
            (None, None),
            processutils.ProcessExecutionError(
                stderr='ouch'
            ),
            ("unit in unknown state", None),
            (None, None)
        ]
        # stop the container
        self.provider.stop_container(task)

        # assert the container file is deleted
        self.assertFalse(os.path.exists(container_path))

        # assert expected stop calls
        mock_exec.assert_has_calls([
            mock.call('journalctl', '--user', '--no-pager', '-u',
                      'ironic-console-1234.service', check_exit_code=False),
            mock.call('systemctl', '--user', 'stop',
                      'ironic-console-1234.service'),
            mock.call('systemctl', '--user', 'status',
                      'ironic-console-1234.service', check_exit_code=False),
            mock.call('systemctl', '--user', 'daemon-reload'),
        ])

    @mock.patch('time.sleep', autospec=True)
    @mock.patch('socket.create_connection', autospec=True)
    def test__wait_for_listen_success(self, mock_create_connection,
                                      mock_sleep):
        mock_socket = mock.MagicMock()
        mock_socket.recv.return_value = b'x' * 12
        mock_create_connection.return_value.__enter__.return_value = (
            mock_socket)

        self.provider._wait_for_listen('127.0.0.1', 5900)

        mock_create_connection.assert_called_once_with(('127.0.0.1', 5900),
                                                       timeout=1)
        mock_socket.recv.assert_called_once_with(12)
        mock_sleep.assert_not_called()

    @mock.patch('time.sleep', autospec=True)
    @mock.patch('socket.create_connection', autospec=True)
    def test__wait_for_listen_retry(self, mock_create_connection, mock_sleep):
        mock_socket = mock.MagicMock()
        mock_socket.recv.return_value = b'x' * 12
        mock_create_connection.side_effect = [
            socket.error,
            socket.error,
            mock.MagicMock(__enter__=mock.MagicMock(return_value=mock_socket))
        ]

        self.provider._wait_for_listen('127.0.0.1', 5900)

        self.assertEqual(3, mock_create_connection.call_count)
        self.assertEqual(2, mock_sleep.call_count)
        mock_socket.recv.assert_called_once_with(12)

    @mock.patch('time.sleep', autospec=True)
    @mock.patch('socket.create_connection', autospec=True)
    def test__wait_for_listen_timeout(self, mock_create_connection,
                                      mock_sleep):
        mock_create_connection.side_effect = socket.error

        self.assertRaisesRegex(
            exception.ConsoleContainerError,
            "RFB data not returned by 127.0.0.1:5900",
            self.provider._wait_for_listen, '127.0.0.1', 5900)

        self.assertEqual(10, mock_create_connection.call_count)
        # time.sleep is called after each failed attempt
        self.assertEqual(10, mock_sleep.call_count)

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(systemd.SystemdConsoleContainer, '_wait_for_listen',
                       autospec=True)
    def test_stop_all_containers(self, mock_wait, mock_exec):
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
            (None, None),
            (None, None),
            (None, None),
        ]

        self.provider.stop_all_containers()
        # assert all containers stopped
        mock_exec.assert_has_calls([
            mock.call('journalctl', '--user', '--no-pager', '-u',
                      'ironic-console-1234.service', check_exit_code=False),
            mock.call('systemctl', '--user', 'stop',
                      'ironic-console-1234.service'),
        ])
        mock_exec.assert_has_calls([
            mock.call('journalctl', '--user', '--no-pager', '-u',
                      'ironic-console-asdf.service', check_exit_code=False),
            mock.call('systemctl', '--user', 'stop',
                      'ironic-console-asdf.service'),
        ])
        mock_exec.assert_has_calls([
            mock.call('journalctl', '--user', '--no-pager', '-u',
                      'ironic-console-foobar.service', check_exit_code=False),
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


class TestKubernetesConsoleContainer(base.TestCase):

    def setUp(self):
        super(TestKubernetesConsoleContainer, self).setUp()
        _reset_provider("kubernetes")
        self.addCleanup(_reset_provider, "fake")

        CONF.set_override("console_image", "test-image", "vnc")

        # The __init__ of the provider calls _render_template, so we need to
        # mock it here.
        with mock.patch.object(utils, "render_template", autospec=True):
            with mock.patch.object(
                utils, "execute", autospec=True
            ) as mock_exec:
                self.provider = (
                    console_factory.ConsoleContainerFactory().provider
                )
                mock_exec.assert_has_calls(
                    [
                        mock.call("kubectl", "version"),
                    ]
                )

    def test__render_template(self):
        CONF.set_override("read_only", True, group="vnc")

        uuid = "1234"
        app_name = "fake-app"
        app_info = {"foo": "bar"}

        rendered = self.provider._render_template(
            uuid=uuid, app_name=app_name, app_info=app_info
        )

        self.assertEqual(
            """apiVersion: v1
kind: Secret
metadata:
  name: "ironic-console-1234"
  namespace: openstack
  labels:
    app: ironic
    component: ironic-console
    conductor: "fake-mini"
stringData:
  app-info: '{"foo": "bar"}'
---
apiVersion: v1
kind: Pod
metadata:
  name: "ironic-console-1234"
  namespace: openstack
  labels:
    app: ironic
    component: ironic-console
    conductor: "fake-mini"
spec:
  containers:
    - name: x11vnc
      image: "test-image"
      imagePullPolicy: Always
      ports:
        - containerPort: 5900
      resources:
        requests:
          cpu: 250m
          memory: 256Mi
        limits:
          cpu: 500m
          memory: 1024Mi
      env:
        - name: APP
          value: "fake-app"
        - name: READ_ONLY
          value: "True"
        - name: APP_INFO
          valueFrom:
            secretKeyRef:
              name: "ironic-console-1234"
              key: app-info""",
            rendered,
        )

    @mock.patch.object(utils, "execute", autospec=True)
    def test__apply(self, mock_exec):
        manifest = "fake-manifest"
        self.provider._apply(manifest)

        mock_exec.assert_called_once_with(
            "kubectl", "apply", "-f", "-", process_input=manifest
        )

    @mock.patch.object(utils, "execute", autospec=True)
    def test__apply_failure(self, mock_exec):
        manifest = "fake-manifest"
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stderr="ouch"
        )

        self.assertRaisesRegex(
            exception.ConsoleContainerError,
            "ouch",
            self.provider._apply,
            manifest,
        )

    @mock.patch.object(utils, "execute", autospec=True)
    def test__delete_by_name(self, mock_exec):
        self.provider._delete(
            "pod", "test-namespace", resource_name="test-pod"
        )
        mock_exec.assert_called_once_with(
            "kubectl",
            "delete",
            "-n",
            "test-namespace",
            "pod",
            "--ignore-not-found=true",
            "test-pod",
        )

    @mock.patch.object(utils, "execute", autospec=True)
    def test__delete_by_selector(self, mock_exec):
        self.provider._delete("pod", "test-namespace", selector="app=ironic")
        mock_exec.assert_called_once_with(
            "kubectl",
            "delete",
            "-n",
            "test-namespace",
            "pod",
            "--ignore-not-found=true",
            "-l",
            "app=ironic",
        )

    def test__delete_no_name_or_selector(self):
        self.assertRaisesRegex(
            exception.ConsoleContainerError,
            "Delete must be called with either a resource name or selector",
            self.provider._delete,
            "pod",
            "test-namespace",
        )

    @mock.patch.object(utils, "execute", autospec=True)
    def test__delete_failure(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stderr="ouch"
        )
        self.assertRaisesRegex(
            exception.ConsoleContainerError,
            "ouch",
            self.provider._delete,
            "pod",
            "test-namespace",
            resource_name="test-pod",
        )

    @mock.patch.object(utils, "execute", autospec=True)
    def test__get_pod_node_ip(self, mock_exec):
        mock_exec.return_value = ("192.168.1.100", "")
        ip = self.provider._get_pod_node_ip("test-pod", "test-namespace")
        self.assertEqual("192.168.1.100", ip)
        mock_exec.assert_called_once_with(
            "kubectl",
            "get",
            "pod",
            "test-pod",
            "-n",
            "test-namespace",
            "-o",
            "jsonpath={.status.podIP}",
        )

    @mock.patch.object(utils, "execute", autospec=True)
    def test__get_pod_node_ip_failure(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stderr="ouch"
        )
        self.assertRaisesRegex(
            exception.ConsoleContainerError,
            "ouch",
            self.provider._get_pod_node_ip,
            "test-pod",
            "test-namespace",
        )

    @mock.patch.object(utils, "execute", autospec=True)
    @mock.patch.object(time, "sleep", autospec=True)
    def test__wait_for_pod_ready(self, mock_sleep, mock_exec):
        pod_ready_status = {
            "status": {"conditions": [{"type": "Ready", "status": "True"}]}
        }
        mock_exec.return_value = (json.dumps(pod_ready_status), "")

        self.provider._wait_for_pod_ready("test-pod", "test-namespace")

        mock_exec.assert_called_once_with(
            "kubectl",
            "get",
            "pod",
            "test-pod",
            "-n",
            "test-namespace",
            "-o",
            "json",
        )
        mock_sleep.assert_not_called()

    @mock.patch.object(utils, "execute", autospec=True)
    @mock.patch.object(time, "sleep", autospec=True)
    @mock.patch.object(time, "time", autospec=True, side_effect=[1, 2, 3, 4])
    def test__wait_for_pod_ready_polling(
        self, mock_time, mock_sleep, mock_exec
    ):
        pod_not_ready_status = {
            "status": {"conditions": [{"type": "Ready", "status": "False"}]}
        }
        pod_ready_status = {
            "status": {"conditions": [{"type": "Ready", "status": "True"}]}
        }
        mock_exec.side_effect = [
            (json.dumps(pod_not_ready_status), ""),
            (json.dumps(pod_ready_status), ""),
        ]

        self.provider._wait_for_pod_ready("test-pod", "test-namespace")

        self.assertEqual(2, mock_exec.call_count)
        mock_sleep.assert_called_once_with(kubernetes.POD_READY_POLL_INTERVAL)

    @mock.patch.object(time, "time", autospec=True, side_effect=[0, 121])
    @mock.patch.object(utils, "execute", autospec=True)
    def test__wait_for_pod_ready_timeout(self, mock_exec, mock_time):
        pod_not_ready_status = {
            "status": {"conditions": [{"type": "Ready", "status": "False"}]}
        }
        mock_exec.return_value = (json.dumps(pod_not_ready_status), "")

        self.assertRaisesRegex(
            exception.ConsoleContainerError,
            "did not become ready",
            self.provider._wait_for_pod_ready,
            "test-pod",
            "test-namespace",
        )

    @mock.patch.object(time, "time", autospec=True, side_effect=[0, 121])
    @mock.patch.object(utils, "execute", autospec=True)
    def test__wait_for_pod_ready_exec_error(self, mock_exec, mock_time):
        mock_exec.side_effect = processutils.ProcessExecutionError()
        self.assertRaisesRegex(
            exception.ConsoleContainerError,
            "did not become ready",
            self.provider._wait_for_pod_ready,
            "test-pod",
            "test-namespace",
        )

    def test__get_resources_from_yaml_single_doc_no_kind(self):
        rendered_yaml = """
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  containers:
    - name: my-container
      image: nginx
"""
        resources = list(
            self.provider._get_resources_from_yaml(rendered_yaml)
        )
        self.assertEqual(
            [
                {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {"name": "my-pod"},
                    "spec": {
                        "containers": [
                            {"image": "nginx", "name": "my-container"}
                        ]
                    },
                }
            ],
            resources,
        )

    def test__get_resources_from_yaml_multi_doc_no_kind(self):
        rendered_yaml = """
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
---
apiVersion: v1
kind: Service
metadata:
  name: my-service
"""
        resources = list(
            self.provider._get_resources_from_yaml(rendered_yaml)
        )
        self.assertEqual(
            [
                {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {"name": "my-pod"},
                },
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {"name": "my-service"},
                },
            ],
            resources,
        )

    def test__get_resources_from_yaml_single_doc_with_kind_match(self):
        rendered_yaml = """
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
"""
        resources = list(
            self.provider._get_resources_from_yaml(rendered_yaml, kind="Pod")
        )
        self.assertEqual(
            [
                {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {"name": "my-pod"},
                }
            ],
            resources,
        )

    def test__get_resources_from_yaml_single_doc_with_kind_no_match(self):
        rendered_yaml = """
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
"""
        resources = list(
            self.provider._get_resources_from_yaml(
                rendered_yaml, kind="Service"
            )
        )
        self.assertEqual(0, len(resources))

    def test__get_resources_from_yaml_multi_doc_with_kind_match_some(self):
        rendered_yaml = """
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
---
apiVersion: v1
kind: Service
metadata:
  name: my-service
---
apiVersion: v1
kind: Pod
metadata:
  name: another-pod
"""
        resources = list(
            self.provider._get_resources_from_yaml(rendered_yaml, kind="Pod")
        )
        self.assertEqual(
            [
                {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {"name": "my-pod"},
                },
                {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {"name": "another-pod"},
                },
            ],
            resources,
        )

    def test__get_resources_from_yaml_multi_doc_with_kind_no_match_all(self):
        rendered_yaml = """
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
---
apiVersion: v1
kind: Service
metadata:
  name: my-service
"""
        resources = list(
            self.provider._get_resources_from_yaml(
                rendered_yaml, kind="Deployment"
            )
        )
        self.assertEqual(0, len(resources))

    def test__get_resources_from_yaml_empty_documents(self):
        rendered_yaml = """
---
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
---

---
apiVersion: v1
kind: Service
metadata:
  name: my-service
---
"""
        resources = list(
            self.provider._get_resources_from_yaml(rendered_yaml)
        )
        self.assertEqual(
            [
                {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {"name": "my-pod"},
                },
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {"name": "my-service"},
                },
            ],
            resources,
        )

    def test__get_resources_from_yaml_invalid_yaml(self):
        rendered_yaml = """
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
---
   - bad: indent
  - invalid: yaml

"""
        try:
            list(self.provider._get_resources_from_yaml(rendered_yaml))
            raise Exception("Expected YAMLError")
        except yaml.YAMLError:
            pass

    def test__get_resources_from_yaml_document_safe_load_none(self):
        # This can happen if a document is just whitespace or comments
        rendered_yaml = """
# This is a comment
---
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
"""
        resources = list(
            self.provider._get_resources_from_yaml(rendered_yaml)
        )
        self.assertEqual(
            [
                {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {"name": "my-pod"},
                }
            ],
            resources,
        )

    def test__get_resources_from_yaml_empty_string(self):
        rendered_yaml = ""
        resources = list(
            self.provider._get_resources_from_yaml(rendered_yaml)
        )
        self.assertEqual(0, len(resources))

    def test__get_resources_from_yaml_whitespace_string(self):
        rendered_yaml = "   \n\n"
        resources = list(
            self.provider._get_resources_from_yaml(rendered_yaml)
        )
        self.assertEqual(0, len(resources))

    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_get_pod_node_ip",
        autospec=True,
    )
    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_wait_for_pod_ready",
        autospec=True,
    )
    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_get_resources_from_yaml",
        autospec=True,
    )
    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer, "_apply", autospec=True
    )
    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_render_template",
        autospec=True,
    )
    def test_start_container(
        self,
        mock_render,
        mock_apply,
        mock_get_resources,
        mock_wait,
        mock_get_ip,
    ):
        task = mock.Mock(node=mock.Mock(uuid="1234"))
        app_name = "test-app"
        app_info = {"foo": "bar"}

        mock_render.return_value = "fake-manifest"
        mock_get_resources.return_value = [
            {
                "kind": "Pod",
                "metadata": {
                    "name": "test-pod",
                    "namespace": "test-namespace",
                },
            }
        ]
        mock_get_ip.return_value = "192.168.1.100"

        host, port = self.provider.start_container(task, app_name, app_info)

        self.assertEqual(("192.168.1.100", 5900), (host, port))
        mock_render.assert_called_once_with(
            self.provider, "1234", app_name, app_info
        )
        mock_apply.assert_called_once_with(self.provider, "fake-manifest")
        mock_get_resources.assert_called_once_with(
            self.provider, "fake-manifest", kind="Pod"
        )
        mock_wait.assert_called_once_with(
            self.provider, "test-pod", "test-namespace"
        )
        mock_get_ip.assert_called_once_with(
            self.provider, "test-pod", "test-namespace"
        )

    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_stop_container",
        autospec=True,
    )
    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_get_pod_node_ip",
        autospec=True,
    )
    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_wait_for_pod_ready",
        autospec=True,
    )
    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_get_resources_from_yaml",
        autospec=True,
    )
    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer, "_apply", autospec=True
    )
    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_render_template",
        autospec=True,
    )
    def test_start_container_failure(
        self,
        mock_render,
        mock_apply,
        mock_get_resources,
        mock_wait,
        mock_get_ip,
        mock_stop,
    ):
        task = mock.Mock(node=mock.Mock(uuid="1234"))
        mock_render.return_value = "fake-manifest"
        mock_get_resources.return_value = [
            {"metadata": {"name": "test-pod", "namespace": "test-ns"}}
        ]
        mock_wait.side_effect = exception.ConsoleContainerError(reason="boom")

        self.assertRaises(
            exception.ConsoleContainerError,
            self.provider.start_container,
            task,
            "app",
            {},
        )
        mock_stop.assert_called_once_with(self.provider, "1234")
        mock_get_ip.assert_not_called()

    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_stop_container",
        autospec=True,
    )
    def test_stop_container(self, mock_stop_container):
        task = mock.Mock(node=mock.Mock(uuid="1234"))
        self.provider.stop_container(task)
        mock_stop_container.assert_called_once_with(self.provider, "1234")

    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer, "_delete", autospec=True
    )
    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_get_resources_from_yaml",
        autospec=True,
    )
    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_render_template",
        autospec=True,
    )
    def test__stop_container(
        self, mock_render, mock_get_resources, mock_delete
    ):
        uuid = "1234"
        mock_render.return_value = "fake-manifest"
        mock_get_resources.return_value = [
            {
                "kind": "Secret",
                "metadata": {
                    "name": "ironic-console-1234",
                    "namespace": "test-namespace",
                },
            },
            {
                "kind": "Pod",
                "metadata": {
                    "name": "ironic-console-1234",
                    "namespace": "test-namespace",
                },
            },
        ]

        self.provider._stop_container(uuid)

        mock_render.assert_called_once_with(self.provider, uuid)
        mock_get_resources.assert_called_once_with(
            self.provider, "fake-manifest"
        )
        mock_delete.assert_has_calls(
            [
                mock.call(
                    self.provider,
                    "Pod",
                    "test-namespace",
                    resource_name="ironic-console-1234",
                ),
                mock.call(
                    self.provider,
                    "Secret",
                    "test-namespace",
                    resource_name="ironic-console-1234",
                ),
            ]
        )
        self.assertEqual(2, mock_delete.call_count)

    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer, "_delete", autospec=True
    )
    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_labels_to_selector",
        autospec=True,
    )
    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_get_resources_from_yaml",
        autospec=True,
    )
    @mock.patch.object(
        kubernetes.KubernetesConsoleContainer,
        "_render_template",
        autospec=True,
    )
    def test_stop_all_containers(
        self,
        mock_render,
        mock_get_resources,
        mock_labels_to_selector,
        mock_delete,
    ):
        mock_render.return_value = "fake-manifest"
        mock_get_resources.return_value = [
            {
                "kind": "Secret",
                "metadata": {
                    "namespace": "test-ns",
                    "labels": {"app": "ironic"},
                },
            },
            {
                "kind": "Pod",
                "metadata": {
                    "namespace": "test-ns",
                    "labels": {"app": "ironic"},
                },
            },
        ]
        mock_labels_to_selector.return_value = "app=ironic"

        self.provider.stop_all_containers()

        mock_render.assert_called_once_with(self.provider)
        mock_get_resources.assert_called_once_with(
            self.provider, "fake-manifest"
        )
        mock_labels_to_selector.assert_has_calls(
            [
                mock.call(self.provider, {"app": "ironic"}),
                mock.call(self.provider, {"app": "ironic"}),
            ]
        )
        mock_delete.assert_has_calls(
            [
                mock.call(
                    self.provider, "Pod", "test-ns", selector="app=ironic"
                ),
                mock.call(
                    self.provider, "Secret", "test-ns", selector="app=ironic"
                ),
            ]
        )


class TestContainerConsoleContainer(base.TestCase):

    def setUp(self):
        super(TestContainerConsoleContainer, self).setUp()
        _reset_provider('container')
        self.addCleanup(_reset_provider, 'fake')

        CONF.set_override('console_image', 'test-image', 'vnc')

        # The __init__ of the provider renders the real default template,
        # which validates that it exists and parses.
        with mock.patch.object(utils, 'execute', autospec=True) as mock_exec:
            self.provider = console_factory.ConsoleContainerFactory().provider
            mock_exec.assert_has_calls([
                mock.call('docker', 'version'),
            ])

    def test_init_cli_failure(self):
        # construct the provider directly so the provider's own error
        # handling is exercised, not the factory's catch-all wrapper
        with mock.patch.object(utils, 'execute', autospec=True) as mock_exec:
            mock_exec.side_effect = processutils.ProcessExecutionError(
                stderr='ouch'
            )
            self.assertRaisesRegex(
                exception.ConsoleContainerError, 'ouch',
                container.ContainerConsoleContainer)

    def test_init_cli_missing(self):
        with mock.patch.object(utils, 'execute', autospec=True) as mock_exec:
            mock_exec.side_effect = FileNotFoundError(
                2, 'No such file or directory', 'docker')
            self.assertRaisesRegex(
                exception.ConsoleContainerError, 'docker',
                container.ContainerConsoleContainer)

    def test_init_no_image(self):
        CONF.set_override('console_image', None, 'vnc')
        with mock.patch.object(utils, 'execute', autospec=True):
            self.assertRaisesRegex(
                exception.ConsoleContainerError,
                r'console_image must be set',
                container.ContainerConsoleContainer)

    def test_init_bad_template(self):
        with mock.patch.object(utils, 'execute', autospec=True):
            with mock.patch.object(utils, 'render_template', autospec=True,
                                   side_effect=Exception('bad template')):
                self.assertRaisesRegex(
                    exception.ConsoleContainerError, 'bad template',
                    container.ContainerConsoleContainer)

    def test__container_name(self):
        self.assertEqual(
            'ironic-console-1234',
            self.provider._container_name('1234')
        )

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__execute(self, mock_exec):
        mock_exec.return_value = ('', '')
        self.provider._execute('ps')

        # no container_host, no env: the CLI process environment is
        # left alone
        mock_exec.assert_called_once_with('docker', 'ps')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__execute_executable(self, mock_exec):
        CONF.set_override('container_executable', 'podman', 'vnc')
        mock_exec.return_value = ('', '')
        self.provider._execute('version')

        mock_exec.assert_called_once_with('podman', 'version')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__execute_container_host(self, mock_exec):
        CONF.set_override(
            'container_host', 'unix:///run/podman/podman.sock', 'vnc')
        mock_exec.return_value = ('', '')
        self.provider._execute('ps')

        env = mock_exec.call_args.kwargs['env_variables']
        self.assertEqual('unix:///run/podman/podman.sock', env['DOCKER_HOST'])
        self.assertEqual(
            'unix:///run/podman/podman.sock', env['CONTAINER_HOST'])

    def test__render_template(self):
        CONF.set_override('read_only', True, 'vnc')
        CONF.set_override(
            'container_publish_port', '192.0.2.2::5900', 'vnc')

        self.assertEqual([
            'run', '--detach', '--rm',
            '--name', 'ironic-console-1234',
            '--label', 'org.openstack.ironic.console=true',
            '--label', 'org.openstack.ironic.conductor=fake-mini',
            '--label', 'org.openstack.ironic.node=1234',
            '--publish', '192.0.2.2::5900',
            '--pull', 'missing',
            '--env', 'APP=fake-app',
            '--env', 'APP_INFO',
            '--env', 'READ_ONLY=True',
            'test-image',
        ], self.provider._render_template('1234', app_name='fake-app'))

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__host_port_ipv4(self, mock_exec):
        mock_exec.return_value = ('192.0.2.1:33819\n', None)
        self.assertEqual(
            ('192.0.2.1', 33819),
            self.provider._host_port('ironic-console-1234'))

        mock_exec.assert_called_once_with(
            'docker', 'port', 'ironic-console-1234', '5900/tcp')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__host_port_unspecified_ipv4(self, mock_exec):
        CONF.set_override('my_ip', '203.0.113.5')
        mock_exec.return_value = ('0.0.0.0:33819\n', None)
        self.assertEqual(
            ('203.0.113.5', 33819),
            self.provider._host_port('ironic-console-1234'))

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__host_port_bracketed_ipv6(self, mock_exec):
        # Docker 23.0+ brackets IPv6 addresses
        mock_exec.return_value = ('[2001:db8::1]:33819\n', None)
        self.assertEqual(
            ('2001:db8::1', 33819),
            self.provider._host_port('ironic-console-1234'))

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__host_port_unbracketed_ipv6(self, mock_exec):
        # older Docker and all Podman releases do not bracket IPv6
        mock_exec.return_value = ('2001:db8::1:33819\n', None)
        self.assertEqual(
            ('2001:db8::1', 33819),
            self.provider._host_port('ironic-console-1234'))

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__host_port_unspecified_ipv6(self, mock_exec):
        CONF.set_override('my_ip', '203.0.113.5')
        mock_exec.return_value = (':::33819\n', None)
        self.assertEqual(
            ('203.0.113.5', 33819),
            self.provider._host_port('ironic-console-1234'))

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__host_port_dual_stack_prefers_ipv4(self, mock_exec):
        mock_exec.return_value = ('[2001:db8::1]:33819\n'
                                  '192.0.2.1:33820\n', None)
        self.assertEqual(
            ('192.0.2.1', 33820),
            self.provider._host_port('ironic-console-1234'))

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__host_port_arrow_form(self, mock_exec):
        mock_exec.return_value = ('5900/tcp -> 192.0.2.1:33819\n', None)
        self.assertEqual(
            ('192.0.2.1', 33819),
            self.provider._host_port('ironic-console-1234'))

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__host_port_no_binding(self, mock_exec):
        mock_exec.return_value = ('asdkljffo872\n', None)
        self.assertRaisesRegex(
            exception.ConsoleContainerError,
            'Could not detect a published VNC port',
            self.provider._host_port, 'ironic-console-1234')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__host_port_failure(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stderr='ouch'
        )
        self.assertRaisesRegex(
            exception.ConsoleContainerError, 'ouch',
            self.provider._host_port, 'ironic-console-1234')

    @mock.patch.object(container.ContainerConsoleContainer,
                       '_wait_for_listen', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_start_container(self, mock_exec, mock_wait):
        CONF.set_override(
            'container_publish_port', '192.0.2.2::5900', 'vnc')
        task = mock.Mock(node=mock.Mock(uuid='1234'))

        mock_exec.side_effect = [
            (None, None),                 # rm of any stale container
            ('cid123\n', None),           # run
            ('192.0.2.2:33819\n', None),  # port
        ]

        self.assertEqual(
            ('192.0.2.2', 33819),
            self.provider.start_container(task, 'fake-app', {'foo': 'bar'}))

        mock_exec.assert_has_calls([
            mock.call('docker', 'rm', '--force', 'ironic-console-1234',
                      check_exit_code=False),
            mock.call(
                'docker', 'run', '--detach', '--rm',
                '--name', 'ironic-console-1234',
                '--label', 'org.openstack.ironic.console=true',
                '--label', 'org.openstack.ironic.conductor=fake-mini',
                '--label', 'org.openstack.ironic.node=1234',
                '--publish', '192.0.2.2::5900',
                '--pull', 'missing',
                '--env', 'APP=fake-app',
                '--env', 'APP_INFO',
                '--env', 'READ_ONLY=False',
                'test-image',
                env_variables=mock.ANY),
            mock.call('docker', 'port', 'ironic-console-1234', '5900/tcp'),
        ])
        mock_wait.assert_called_once_with(self.provider, '192.0.2.2', 33819)

        # app_info is passed through the CLI process environment, never
        # on the command line
        run_call = mock_exec.call_args_list[1]
        self.assertNotIn('{"foo": "bar"}', run_call.args)
        self.assertEqual(
            '{"foo": "bar"}', run_call.kwargs['env_variables']['APP_INFO'])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_start_container_run_failed(self, mock_exec):
        task = mock.Mock(node=mock.Mock(uuid='1234'))

        mock_exec.side_effect = [
            (None, None),  # rm of any stale container
            processutils.ProcessExecutionError(stderr='ouch'),  # run
            ('a log line', None),  # logs
            (None, None),  # rm
        ]

        self.assertRaisesRegex(
            exception.ConsoleContainerError, 'ouch',
            self.provider.start_container, task, 'fake-app', {})

        mock_exec.assert_has_calls([
            mock.call('docker', 'logs', 'ironic-console-1234',
                      check_exit_code=False),
            mock.call('docker', 'rm', '--force', 'ironic-console-1234',
                      check_exit_code=False),
        ])

    @mock.patch.object(container.ContainerConsoleContainer,
                       '_wait_for_listen', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_start_container_wait_failed(self, mock_exec, mock_wait):
        task = mock.Mock(node=mock.Mock(uuid='1234'))

        mock_exec.side_effect = [
            (None, None),                 # rm of any stale container
            ('cid123\n', None),           # run
            ('192.0.2.1:33819\n', None),  # port
            ('a log line', None),         # logs
            (None, None),                 # rm
        ]
        mock_wait.side_effect = exception.ConsoleContainerError(
            provider='container', reason='RFB data not returned')

        self.assertRaisesRegex(
            exception.ConsoleContainerError, 'RFB data not returned',
            self.provider.start_container, task, 'fake-app', {})

        mock_exec.assert_has_calls([
            mock.call('docker', 'logs', 'ironic-console-1234',
                      check_exit_code=False),
            mock.call('docker', 'rm', '--force', 'ironic-console-1234',
                      check_exit_code=False),
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_stop_container(self, mock_exec):
        task = mock.Mock(node=mock.Mock(uuid='1234'))
        mock_exec.return_value = (None, None)

        self.provider.stop_container(task)

        mock_exec.assert_has_calls([
            mock.call('docker', 'logs', 'ironic-console-1234',
                      check_exit_code=False),
            mock.call('docker', 'rm', '--force', 'ironic-console-1234',
                      check_exit_code=False),
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_stop_container_absent(self, mock_exec):
        task = mock.Mock(node=mock.Mock(uuid='1234'))
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stderr='no such container'
        )

        # an already-absent container is treated as success
        self.provider.stop_container(task)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_stop_all_containers(self, mock_exec):
        mock_exec.side_effect = [
            ('abc123\ndef456\n', None),  # ps
            (None, None),                # logs abc123
            (None, None),                # rm abc123
            (None, None),                # logs def456
            (None, None),                # rm def456
        ]

        self.provider.stop_all_containers()

        mock_exec.assert_has_calls([
            mock.call('docker', 'ps', '--all', '--quiet', '--filter',
                      'label=org.openstack.ironic.conductor=fake-mini'),
            mock.call('docker', 'logs', 'abc123', check_exit_code=False),
            mock.call('docker', 'rm', '--force', 'abc123',
                      check_exit_code=False),
            mock.call('docker', 'logs', 'def456', check_exit_code=False),
            mock.call('docker', 'rm', '--force', 'def456',
                      check_exit_code=False),
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_stop_all_containers_none(self, mock_exec):
        mock_exec.return_value = ('', None)

        self.provider.stop_all_containers()

        mock_exec.assert_called_once_with(
            'docker', 'ps', '--all', '--quiet', '--filter',
            'label=org.openstack.ironic.conductor=fake-mini')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_stop_all_containers_failed(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError(
            stderr='ouch'
        )
        self.assertRaisesRegex(
            exception.ConsoleContainerError, 'ouch',
            self.provider.stop_all_containers)
