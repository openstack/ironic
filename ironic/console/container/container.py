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

"""
Docker compatible engine console container provider.
"""
import json
import os
import shlex

from oslo_concurrency import processutils
from oslo_log import log as logging

from ironic.common import exception
from ironic.common import utils
from ironic.conf import CONF
from ironic.console.container import base

LOG = logging.getLogger(__name__)

NAME_PREFIX = 'ironic-console'

LABEL_PREFIX = 'org.openstack.ironic'


class ContainerConsoleContainer(base.BaseConsoleContainer):
    """Console container provider which uses a Docker compatible engine."""

    provider_name = 'container'

    def __init__(self):
        # confirm the CLI is available and can talk to the engine
        try:
            self._execute('version')
        except processutils.ProcessExecutionError as e:
            LOG.exception('%s not available or the container engine is not '
                          'reachable, this provider cannot be used.',
                          CONF.vnc.container_executable)
            raise exception.ConsoleContainerError(
                provider=self.provider_name, reason=e)
        if not CONF.vnc.console_image:
            raise exception.ConsoleContainerError(
                provider=self.provider_name,
                reason='[vnc]console_image must be set.')
        try:
            self._render_template()
        except Exception as e:
            raise exception.ConsoleContainerError(
                provider=self.provider_name,
                reason=f'Parsing {CONF.vnc.container_command_template} '
                       f'failed: {e}')

    def _execute(self, *args, env=None, **kwargs):
        """Invoke the container CLI with the given arguments.

        :param args: Argument vector for the CLI
        :param env: Dict of extra environment variables for the invocation
        :param kwargs: Extra keyword arguments for utils.execute
        :returns: (stdout, stderr) from process execution
        :raises: ProcessExecutionError
        """
        if CONF.vnc.container_host or env:
            env_variables = os.environ.copy()
            if CONF.vnc.container_host:
                # NOTE(cid): DOCKER_HOST is honoured by the docker CLI,
                # CONTAINER_HOST by the podman CLI (since Podman 4.0, where
                # it also enables remote mode).
                env_variables['DOCKER_HOST'] = CONF.vnc.container_host
                env_variables['CONTAINER_HOST'] = CONF.vnc.container_host
            env_variables.update(env or {})
            kwargs['env_variables'] = env_variables
        return utils.execute(CONF.vnc.container_executable, *args, **kwargs)

    def _container_name(self, uuid):
        """Build a container name.

        :param uuid: Node uuid to include in the name
        :returns: The name of the container for this node, matching the
                  --name rendered by the default command template
        """
        return f'{NAME_PREFIX}-{uuid}'

    def _render_template(self, uuid='', app_name=None):
        """Render the run command template to an argument vector.

        app_info is deliberately not a template variable: it contains BMC
        credentials which must not appear on a command line, so it is
        passed via the CLI process environment instead.

        :param uuid: Unique identifier for the node.
        :param app_name: Name of the application to run in the container.
        :returns: A list of arguments for the container CLI.
        """
        # TODO(cid) Support bind-mounting certificate files to
        # handle verified BMC certificates
        params = {
            'uuid': uuid,
            'image': CONF.vnc.console_image,
            'app': app_name or 'fake',
            'read_only': CONF.vnc.read_only,
            'conductor': CONF.host,
            'publish_port': CONF.vnc.container_publish_port,
            'my_ip': CONF.my_ip,
        }
        rendered = utils.render_template(
            CONF.vnc.container_command_template, params=params)
        return shlex.split(rendered, comments=True)

    def _capture_logs(self, container):
        """Log container output at debug level.

        This is best-effort: under the default template's --rm a container
        which exited on its own may have already removed itself.

        :param container: container name or id
        """
        try:
            # If debug logging is enabled then utils.execute will log the
            # output to the conductor log.
            self._execute('logs', container, check_exit_code=False)
        except Exception:
            LOG.debug('Could not capture logs for container %s', container)

    def _remove_container(self, container):
        """Force-remove a container.

        A container which does not exist is treated as success. Engines
        disagree on the exit code for removing a missing container (Podman
        before 4.2 exits non-zero), so the exit code is ignored entirely: a
        genuine removal failure surfaces as a name collision on the next
        start of this node's container.

        :param container: container name or id
        """
        try:
            self._execute('rm', '--force', container, check_exit_code=False)
        except Exception:
            LOG.exception('Could not remove container %s', container)

    def _host_port(self, container):
        """Extract the published VNC host and port from a container.

        Calls '<executable> port <container> 5900/tcp' and parses the
        'host:port' output, handling IPv4, bracketed IPv6 (Docker 23.0+)
        and unbracketed IPv6 (older Docker, all Podman releases) forms.

        :param container: container name
        :returns: Tuple of host IP address and published port
        :raises: ConsoleContainerError
        """
        try:
            out, _ = self._execute('port', container, '5900/tcp')
        except processutils.ProcessExecutionError as e:
            LOG.exception('Problem calling %s port %s',
                          CONF.vnc.container_executable, container)
            raise exception.ConsoleContainerError(
                provider=self.provider_name, reason=e)

        bindings = []
        for line in out.splitlines():
            # tolerate the '5900/tcp -> host:port' form
            line = line.split('->')[-1].strip()
            host, sep, port = line.rpartition(':')
            if not sep:
                continue
            host = host.strip('[]')
            try:
                bindings.append((host, int(port)))
            except ValueError:
                continue
        if not bindings:
            raise exception.ConsoleContainerError(
                provider=self.provider_name,
                reason='Could not detect a published VNC port in the '
                       f'output: {out}')

        # NOTE(cid): prefer the first IPv4 binding, e.g. for a dual-stack
        # publish.
        host, port = next(
            (b for b in bindings if '.' in b[0] and ':' not in b[0]),
            bindings[0])
        if host in ('0.0.0.0', '::'):
            # NOTE(cid): an unspecified bind address is not consumable by
            # ironic-novncproxy or Nova, substitute the conductor's IP.
            host = CONF.my_ip
        return host, port

    def start_container(self, task, app_name, app_info):
        """Start a console container for a node.

        Any existing container for this node will be removed first, then a
        container is run from the rendered command template, blocking until
        its published VNC endpoint returns RFB data.

        :param task: A TaskManager instance.
        :param app_name: Sets container environment APP value
        :param app_info: Sets container environment APP_INFO value
        :returns: Tuple of host IP address and published port
        :raises: ConsoleContainerError
        """
        uuid = task.node.uuid
        LOG.debug('Starting console container for node %s', uuid)

        container = self._container_name(uuid)
        # NOTE(cid): remove any stale container so a retried start, or a
        # node which has moved between conductors, cannot collide with a
        # leftover name.
        self._remove_container(container)

        run_args = self._render_template(uuid, app_name)
        try:
            # NOTE(cid): app_info contains BMC credentials, so it is
            # supplied through the CLI process environment for the
            # value-less '--env APP_INFO' entry, never on a command line.
            self._execute(*run_args, env={'APP_INFO': json.dumps(app_info)})
            host, port = self._host_port(container)
            self._wait_for_listen(host, port)
        except exception.ConsoleContainerError:
            self._handle_failed_start(container, uuid)
            raise
        except Exception as e:
            self._handle_failed_start(container, uuid)
            raise exception.ConsoleContainerError(
                provider=self.provider_name, reason=e)
        return host, port

    def _handle_failed_start(self, container, uuid):
        """Capture diagnostics and clean up after a failed start.

        :param container: container name
        :param uuid: Node uuid
        """
        LOG.error('Failed to start console container for node %s, '
                  'cleaning up.', uuid)
        self._capture_logs(container)
        self._remove_container(container)

    def stop_container(self, task):
        """Stop a console container for a node.

        Any existing container for this node will be removed. Console
        containers are stateless, so no graceful stop period is needed.

        :param task: A TaskManager instance.
        :raises: ConsoleContainerError
        """
        uuid = task.node.uuid
        LOG.debug('Stopping console container for node %s', uuid)
        container = self._container_name(uuid)
        self._capture_logs(container)
        self._remove_container(container)

    def stop_all_containers(self):
        """Stops all console containers managed by this conductor

        This is run on conductor startup and graceful shutdown to ensure
        no console containers are running. The list is scoped to this
        conductor's label so a shared engine's containers belonging to
        other conductors are never affected. --all also collects exited
        containers, which matters when a custom template omits --rm.

        :raises: ConsoleContainerError
        """
        LOG.debug('Stopping all console containers')
        try:
            out, _ = self._execute(
                'ps', '--all', '--quiet', '--filter',
                f'label={LABEL_PREFIX}.conductor={CONF.host}')
        except processutils.ProcessExecutionError as e:
            # NOTE(cid): a failure to list is surfaced as
            # ConsoleContainerError per the base interface, matching the
            # kubernetes provider; the per-container logs and removals
            # below stay best-effort. This runs from the conductor startup
            # and shutdown hooks in rpc_service, where the startup hook is
            # already gated by the engine reachability check in __init__.
            LOG.exception('Problem listing console containers')
            raise exception.ConsoleContainerError(
                provider=self.provider_name, reason=e)
        for container in out.split():
            self._capture_logs(container)
            self._remove_container(container)
