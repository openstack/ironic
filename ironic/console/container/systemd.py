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
Systemd Quadlet console container provider.
"""
import json
import os
import re

from oslo_concurrency import processutils
from oslo_log import log as logging

from ironic.common import exception
from ironic.common import utils
from ironic.conf import CONF
from ironic.console.container import base

LOG = logging.getLogger(__name__)

TEMPLATE_PREFIX = 'ironic-console'

# "podman port" output is of the format
# 5900/tcp -> 127.0.0.1:12345
#             ^^^^^^^^^ ^^^^^
PORT_RE = re.compile('^5900/tcp -> (.*):([0-9]+)$')


class SystemdConsoleContainer(base.BaseConsoleContainer):
    """Console container provider which uses Systemd Quadlets."""

    unit_dir = None

    def __init__(self):

        # confirm podman and systemctl are available
        try:
            utils.execute('systemctl', '--version')
        except processutils.ProcessExecutionError as e:
            LOG.exception('systemctl not available, '
                          'this provider cannot be used.')
            raise exception.ConsoleContainerError(provider='systemd', reason=e)
        try:
            utils.execute('podman', '--version')
        except processutils.ProcessExecutionError as e:
            LOG.exception('podman not available, '
                          'it is mandatory to use this provider.')
            raise exception.ConsoleContainerError(provider='systemd', reason=e)

    def _init_unit_dir(self, unit_dir=None):

        if unit_dir:
            self.unit_dir = unit_dir

        elif not self.unit_dir:

            # Write container files to
            # /etc/containers/systemd/users/{uid}/containers/systemd
            # Containers are stateless and can be run rootless as user
            # containers.
            uid = str(os.getuid())
            user_dir = os.path.join('/etc/containers/systemd/users', uid)
            if not os.path.isdir(user_dir):
                reason = (f'Directory {user_dir} must exist and be writable '
                          f'by user {uid}')
                raise exception.ConsoleContainerError(
                    provider='systemd', reason=reason)

            self.unit_dir = os.path.join(
                '/etc/containers/systemd/users', uid, 'containers/systemd')

        if not os.path.exists(self.unit_dir):
            try:
                os.makedirs(self.unit_dir)
            except OSError as e:
                LOG.exception(
                    'Could not initialize console containers')
                raise exception.ConsoleContainerError(
                    provider='systemd', reason=e)

    def _container_path(self, identifier):
        """Build a container path.

        :param identifier: Optional identifier to include in the path
        :returns: A quadlet .container file path
        """
        return os.path.join(
            self.unit_dir, f'{TEMPLATE_PREFIX}-{identifier}.container')

    def _unit_name(self, identifier):
        """Build a unit name.

        :param identifier: Optional identifier to include in the name
        :returns: Unit service name which corresponds to a .container file
        """
        return f'{TEMPLATE_PREFIX}-{identifier}.service'

    def _container_name(self, identifier):
        """Build a container name.

        :param identifier: Optional identifier to include in the name
        :returns: The name of the podman container created by systemd
                  quadlet container
        """
        return f'systemd-{TEMPLATE_PREFIX}-{identifier}'

    def _reload(self):
        """Call systemctl --user daemon-reload

        :raises: ConsoleContainerError
        """
        try:
            utils.execute('systemctl', '--user', 'daemon-reload')
        except processutils.ProcessExecutionError as e:
            LOG.exception('Problem calling systemctl daemon-reload')
            raise exception.ConsoleContainerError(provider='systemd', reason=e)

    def _start(self, unit):
        """Call systemctl --user start.

        :param unit: Name of the unit to start
        :raises: ConsoleContainerError
        """
        try:
            utils.execute('systemctl', '--user', 'start', unit)
        except processutils.ProcessExecutionError as e:
            LOG.exception('Problem calling systemctl start')
            raise exception.ConsoleContainerError(provider='systemd', reason=e)

    def _stop(self, unit):
        """Call systemctl --user stop.

        :param unit: Name of the unit to stop
        :raises: ConsoleContainerError
        """
        try:
            utils.execute('systemctl', '--user', 'stop', unit)
        except processutils.ProcessExecutionError as e:
            LOG.exception('Problem calling systemctl stop')
            raise exception.ConsoleContainerError(provider='systemd', reason=e)

    def _host_port(self, container):
        """Extract running host and port from a container.

        Calls 'podman port' and parses the result.

        :param container: container name
        :returns: Tuple of host IP address and published port
        :raises: ConsoleContainerError
        """
        try:
            out, _ = utils.execute('podman', 'port', container)
            match = PORT_RE.match(out)
            if match:
                return match.group(1), int(match.group(2))
            raise exception.ConsoleContainerError(
                provider='systemd',
                reason=f'Could not detect port in the output: {out}')

        except processutils.ProcessExecutionError as e:
            LOG.exception('Problem calling podman port %s', container)
            raise exception.ConsoleContainerError(provider='systemd', reason=e)

    def _write_container_file(self, identifier, app_name, app_info):
        """Create quadlet container file.

        :param identifier: Unique container identifier
        :param app_name: Sets container environment APP value
        :param app_info: Sets container environment APP_INFO value
        :raises: ConsoleContainerError
        """
        try:
            container_file = self._container_path(identifier)

            # TODO(stevebaker) Support bind-mounting certificate files to
            # handle verified BMC certificates

            params = {
                'description': 'A VNC server which displays a console '
                               f'for node {identifier}',
                'image': CONF.vnc.console_image,
                'port': CONF.vnc.systemd_container_publish_port,
                'app': app_name,
                'app_info': json.dumps(app_info),
                'read_only': CONF.vnc.read_only,
            }

            LOG.debug('Writing %s', container_file)
            with open(container_file, 'wt') as fp:
                fp.write(utils.render_template(
                    CONF.vnc.systemd_container_template, params=params))

        except OSError as e:
            LOG.exception('Could not start console container')
            raise exception.ConsoleContainerError(provider='systemd', reason=e)

    def _delete_container_file(self, identifier):
        """Delete container file.

        :param identifier: Unique container identifier
        :raises: ConsoleContainerError
        """
        container_file = self._container_path(identifier)

        try:
            if os.path.exists(container_file):
                LOG.debug('Removing file %s', container_file)
                os.remove(container_file)
        except OSError as e:
            LOG.exception('Could not stop console containers')
            raise exception.ConsoleContainerError(provider='systemd', reason=e)

    def start_container(self, task, app_name, app_info):
        """Stop a console container for a node.

        Any existing running container for this node will be stopped.

        :param task: A TaskManager instance.
        :raises: ConsoleContainerError
        """
        self._init_unit_dir()
        node = task.node
        uuid = node.uuid

        LOG.debug('Starting console container for node %s', uuid)

        self._write_container_file(
            identifier=uuid, app_name=app_name, app_info=app_info)

        # notify systemd to changed file
        self._reload()

        # start the container
        unit = self._unit_name(uuid)
        try:
            self._start(unit)
        except Exception as e:
            try:
                self._delete_container_file(uuid)
                pass
            except Exception:
                pass
            raise e

        container = self._container_name(uuid)

        return self._host_port(container)

    def _stop_container(self, identifier):
        """Stop a console container for a node.

        Any existing running container for this node will be stopped.

        :param identifier: Unique container identifier
        :raises: ConsoleContainerError
        """
        unit = self._unit_name(identifier)
        try:
            # stop any running container
            self._stop(unit)
        except Exception:
            pass

        self._delete_container_file(identifier)

    def stop_container(self, task):
        """Stop a console container for a node.

        Any existing running container for this node will be stopped.

        :param task: A TaskManager instance.
        :raises: ConsoleContainerError
        """
        self._init_unit_dir()
        node = task.node
        uuid = node.uuid
        LOG.debug('Stopping console container for node %s', uuid)
        self._stop_container(uuid)
        # notify systemd to changed file
        self._reload()

    def stop_all_containers(self):
        """Stops all running console containers

        This is run on conductor startup and graceful shutdown to ensure
        no console containers are running.
        :raises: ConsoleContainerError
        """
        LOG.debug('Stopping all console containers')
        self._init_unit_dir()
        stop_count = 0
        if not os.path.exists(self.unit_dir):
            # No unit state, so assume no containers are running
            return

        for filename in os.listdir(self.unit_dir):
            if not filename.startswith(TEMPLATE_PREFIX):
                # ignore containers this isn't managing
                continue

            stop_count = stop_count + 1
            try:
                # get the identifier from the filename and stop the container
                identifier = filename.split(
                    f'{TEMPLATE_PREFIX}-')[1].split('.container')[0]
                self._stop_container(identifier)
            except Exception:
                pass

        if stop_count > 0:
            try:
                # notify systemd to changed file
                self._reload()
            except Exception:
                pass
