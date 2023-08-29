# Copyright 2014 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from http import client as http_client
import os
import ssl

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_serialization import jsonutils
from oslo_utils import strutils
import requests
import tenacity

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import utils
from ironic.conf import CONF

LOG = log.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

DEFAULT_IPA_PORTAL_PORT = 3260

REBOOT_COMMAND = 'run_image'


def get_client(task):
    """Get client for this node."""
    try:
        return task.cached_agent_client
    except AttributeError:
        task.cached_agent_client = AgentClient()
        return task.cached_agent_client


def get_command_error(command):
    """Extract an error string from the command result.

    :param command: Command information from the agent.
    :return: Error string.
    """
    error = command.get('command_error')
    if error is None:
        LOG.error('Agent returned invalid response: missing command_error in '
                  '%s', command)
        return _('Invalid agent response')

    if isinstance(error, dict):
        return error.get('details') or error.get('message') or str(error)
    else:
        return error


def _sanitize_for_logging(var):
    if not var:
        return var
    elif isinstance(var, str):
        return strutils.mask_password(var)
    else:
        return utils.remove_large_keys(strutils.mask_dict_password(var))


class AgentClient(object):
    """Client for interacting with nodes via a REST API."""
    @METRICS.timer('AgentClient.__init__')
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})

    def _get_command_url(self, node):
        """Get URL endpoint for agent command request"""
        agent_url = node.driver_internal_info.get('agent_url')
        if not agent_url:
            raise exception.AgentConnectionFailed(_('Agent driver requires '
                                                    'agent_url in '
                                                    'driver_internal_info'))
        return ('%(agent_url)s/%(api_version)s/commands/' %
                {'agent_url': agent_url,
                 'api_version': CONF.agent.agent_api_version})

    def _get_command_body(self, method, params):
        """Generate command body from method and params"""
        return jsonutils.dumps({
            'name': method,
            'params': params,
        })

    def _get_verify(self, node):
        # False is a valid value, don't use 'or'
        value = node.driver_internal_info.get('agent_verify_ca')
        if value is None:
            value = node.driver_info.get('agent_verify_ca')
        if value is None:
            value = CONF.agent.verify_ca

        if isinstance(value, str):
            try:
                value = strutils.bool_from_string(value, strict=True)
            except ValueError:
                if not os.path.exists(value):
                    raise exception.InvalidParameterValue(
                        _('Agent CA %s is neither a path nor a boolean')
                        % value)
        return value

    def _raise_if_typeerror(self, result, node, method):
        error = result.get('command_error')
        if error and error.get('type') == 'TypeError':
            LOG.error('Agent command %(method)s for node %(node)s failed. '
                      'Internal TypeError detected: Error %(error)s',
                      {'method': method, 'node': node.uuid, 'error': error})
            raise exception.AgentAPIError(node=node.uuid,
                                          status=error.get('code'),
                                          error=get_command_error(result))

    @METRICS.timer('AgentClient._wait_for_command')
    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(
            exception.AgentCommandTimeout),
        stop=tenacity.stop_after_attempt(CONF.agent.command_wait_attempts),
        wait=tenacity.wait_fixed(CONF.agent.command_wait_interval),
        reraise=True)
    def _wait_for_command(self, node, method):
        """Wait for a command to complete.

        :param node: A Node object.
        :param method: A string represents the command executed by agent.
        :raises: AgentCommandTimeout if timeout is reached.
        """
        # NOTE(dtantsur): this function uses AgentCommandTimeout on every
        # failure, but unless the timeout is reached, the exception is caught
        # and retried by the @retry decorator above.
        result = self.get_last_command_status(node, method)
        if result is None:
            raise exception.AgentCommandTimeout(command=method, node=node.uuid)

        if result.get('command_status') == 'RUNNING':
            LOG.debug('Command %(cmd)s has not finished yet for node %(node)s',
                      {'cmd': method, 'node': node.uuid})
            raise exception.AgentCommandTimeout(command=method, node=node.uuid)
        else:
            LOG.debug('Command %(cmd)s has finished for node %(node)s with '
                      'result %(result)s',
                      {'cmd': method, 'node': node.uuid, 'result': result})
            self._raise_if_typeerror(result, node, method)
            return result

    @METRICS.timer('AgentClient._command')
    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(
            exception.AgentConnectionFailed),
        stop=tenacity.stop_after_attempt(CONF.agent.max_command_attempts),
        reraise=True)
    def _command(self, node, method, params, wait=False, poll=False):
        """Sends command to agent.

        :param node: A Node object.
        :param method: A string represents the command to be executed by
                       agent.
        :param params: A dictionary containing params used to form the request
                       body.
        :param wait: True to wait for the command to finish executing, False
                     otherwise.
        :param poll: Whether to poll the command until completion. Provides
                     a better alternative to `wait` for long-running commands.
        :raises: IronicException when failed to issue the request or there was
                 a malformed response from the agent.
        :raises: AgentAPIError when agent failed to execute specified command.
        :raises: AgentInProgress when the command fails to execute as the agent
                 is presently executing the prior command.
        :returns: A dict containing command result from agent, see
                  get_commands_status for a sample.
        """
        assert not (wait and poll)

        url = self._get_command_url(node)
        body = self._get_command_body(method, params)
        request_params = {
            'wait': str(wait).lower()
        }
        agent_token = node.driver_internal_info.get('agent_secret_token')
        if agent_token:
            request_params['agent_token'] = agent_token
        LOG.debug('Executing agent command %(method)s for node %(node)s '
                  'with params %(params)s',
                  {'node': node.uuid, 'method': method,
                   'params': _sanitize_for_logging(request_params)})

        try:
            response = self.session.post(
                url, params=request_params, data=body,
                verify=self._get_verify(node),
                timeout=CONF.agent.command_timeout)
        except (requests.ConnectionError, requests.Timeout, ssl.SSLError) as e:
            result = self._handle_timeout_on_command_execution(node, method,
                                                               params, e)
            response = None
        except requests.RequestException as e:
            msg = (_('Error invoking agent command %(method)s for node '
                     '%(node)s. Error: %(error)s') %
                   {'method': method, 'node': node.uuid, 'error': e})
            LOG.error(msg)
            raise exception.IronicException(msg)

        if response is not None:
            # TODO(russellhaering): real error handling
            try:
                result = response.json()
            except ValueError:
                msg = _(
                    'Unable to decode response as JSON.\n'
                    'Request URL: %(url)s\nRequest body: "%(body)s"\n'
                    'Response status code: %(code)s\n'
                    'Response: "%(response)s"'
                ) % ({'response': response.text, 'body': body, 'url': url,
                      'code': response.status_code})
                LOG.error(msg)
                raise exception.IronicException(msg)

        error = result.get('command_error')
        LOG.debug('Agent command %(method)s for node %(node)s returned '
                  'result %(res)s, error %(error)s, HTTP status code %(code)s',
                  {'node': node.uuid, 'method': method,
                   'res': _sanitize_for_logging(result.get('command_result')),
                   'error': error,
                   'code': response.status_code if response is not None
                   else 'unknown'})
        if (response is not None
                and response.status_code >= http_client.BAD_REQUEST):
            faultstring = result.get('faultstring')
            if 'agent_token' in faultstring:
                LOG.error('Agent command %(method)s for node %(node)s '
                          'failed. Expected 2xx HTTP status code, got '
                          '%(code)d. Error suggests an older ramdisk '
                          'which does not support ``agent_token``. '
                          'This is a fatal error.',
                          {'method': method, 'node': node.uuid,
                           'code': response.status_code})
            else:
                LOG.error('Agent command %(method)s for node %(node)s failed. '
                          'Expected 2xx HTTP status code, got %(code)d.',
                          {'method': method, 'node': node.uuid,
                           'code': response.status_code})
            if (response.status_code == http_client.CONFLICT
                or 'agent is busy' in faultstring.lower()):
                # HTTP 409 check as an explicit check of if the agent
                # is already busy.
                # NOTE(TheJulia): The agent sends upper case A as of
                # late victoria, but lower case the entire message
                # for compatability with pre-late victoria agents
                # which returns HTTP 409.
                raise exception.AgentInProgress(node=node.uuid,
                                                command=method,
                                                error=faultstring)
            raise exception.AgentAPIError(node=node.uuid,
                                          status=response.status_code,
                                          error=faultstring)

        self._raise_if_typeerror(result, node, method)

        if poll:
            result = self._wait_for_command(node, method)

        return result

    @METRICS.timer('AgentClient.get_commands_status')
    def get_commands_status(self, node, retry_connection=True,
                            expect_errors=False):
        """Get command status from agent.

        :param node: A Node object.
        :param retry_connection: Whether to retry connection problems.
        :param expect_errors: If True, do not log connection problems as
            errors.
        :return: A list of command results, each result is related to a
            command been issued to agent. A typical result can be:

            ::

              {
                'command_name': <command name related to the result>,
                'command_params': <params related with the command>,
                'command_status': <current command status,
                                  e.g. 'RUNNING', 'SUCCEEDED', 'FAILED'>,
                'command_error': <error message if command execution
                                 failed>,
                'command_result': <command result if command execution
                                  succeeded, the value is command specific,
                                  e.g.:
                                  * a dictionary containing keys clean_result
                                    and clean_step for the command
                                    clean.execute_clean_step;
                                  * a dictionary containing keys deploy_result
                                    and deploy_step for the command
                                    deploy.execute_deploy_step;
                                  * a string representing result message for
                                    the command standby.cache_image;
                                  * None for the command standby.sync.>
              }
        """
        url = self._get_command_url(node)
        LOG.debug('Fetching status of agent commands for node %s', node.uuid)

        def _get():
            try:
                return self.session.get(url,
                                        verify=self._get_verify(node),
                                        timeout=CONF.agent.command_timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                msg = (_('Failed to connect to the agent running on node '
                         '%(node)s to collect commands status. '
                         'Error: %(error)s') %
                       {'node': node.uuid, 'error': e})
                logging_call = LOG.debug if expect_errors else LOG.error
                logging_call(msg)
                raise exception.AgentConnectionFailed(reason=msg)

        if retry_connection:
            _get = tenacity.retry(
                retry=tenacity.retry_if_exception_type(
                    exception.AgentConnectionFailed),
                stop=tenacity.stop_after_attempt(
                    CONF.agent.max_command_attempts),
                reraise=True)(_get)

        result = _get().json()['commands']
        status = '; '.join('%(cmd)s: result "%(res)s", error "%(err)s"' %
                           {'cmd': r.get('command_name'),
                            'res': _sanitize_for_logging(
                                r.get('command_result')),
                            'err': r.get('command_error')}
                           for r in result)
        LOG.debug('Status of agent commands for node %(node)s: %(status)s',
                  {'node': node.uuid, 'status': status})
        return result

    def _status_if_last_command_matches(self, node, method, params):
        """Return the status of the given command if it's the last running."""
        try:
            method = method.split('.', 1)[1]
        except IndexError:
            pass

        commands = self.get_commands_status(node)
        if not commands:
            return None

        # TODO(dtantsur): a more reliable way to detect repeated execution
        # would be to pass a sort of require ID to the agent.

        command = commands[-1]
        if command['command_name'] != method:
            LOG.debug('Command %(cmd)s is not currently executing, the last '
                      'command is %(curr)s',
                      {'cmd': method, 'curr': command['command_name']})
            return None

        if command['command_status'] != 'RUNNING':
            LOG.debug('Command %(cmd)s is not currently executing, its status '
                      'is %(curr)s',
                      {'cmd': method, 'curr': command['command_status']})
            return None

        return command

    def _handle_timeout_on_command_execution(self, node, method, params,
                                             error):
        result = None
        # NOTE(dtantsur): it is possible, especially with eventlet+TLS, that
        # agent receives a command but fails to return the result to Ironic.
        # To avoid a failure, check if the last command is the one we're trying
        # to execute.
        try:
            result = self._status_if_last_command_matches(node, method, params)
        except Exception as e:
            msg = (_('Failed to connect to the agent running on node '
                     '%(node)s for checking the last command status '
                     'after failing to invoke command %(method)s. '
                     'Error: %(error)s') %
                   {'node': node.uuid, 'method': method, 'error': e})
            LOG.error(msg)

        if result is None:
            msg = (_('Failed to connect to the agent running on node %(node)s '
                     'for invoking command %(method)s. Error: %(error)s') %
                   {'node': node.uuid, 'method': method, 'error': error})
            LOG.error(msg)
            raise exception.AgentConnectionFailed(reason=msg)

        return result

    def get_last_command_status(self, node, method):
        """Get the last status for the given command.

        :param node: A Node object.
        :param method: Command name.
        :returns: A dict containing command status from agent or None
            if the command was not found.
        """
        try:
            method = method.split('.', 1)[1]
        except IndexError:
            pass

        commands = self.get_commands_status(node)
        try:
            return next(c for c in reversed(commands)
                        if c.get('command_name') == method)
        except StopIteration:
            LOG.debug('Command %(cmd)s is not in the executing commands list '
                      'for node %(node)s',
                      {'cmd': method, 'node': node.uuid})
            return None

    @METRICS.timer('AgentClient.install_bootloader')
    def install_bootloader(self, node, root_uuid, target_boot_mode,
                           efi_system_part_uuid=None,
                           prep_boot_part_uuid=None,
                           software_raid=False):
        """Install a boot loader on the image.

        :param node: A node object.
        :param root_uuid: The UUID of the root partition.
        :param target_boot_mode: The target deployment boot mode.
        :param efi_system_part_uuid: The UUID of the efi system partition
               where the bootloader will be installed to, only used for uefi
               boot mode.
        :param prep_boot_part_uuid: The UUID of the PReP Boot partition where
               the bootloader will be installed to when local booting a
               partition image on a ppc64* system.
        :raises: IronicException when failed to issue the request or there was
                 a malformed response from the agent.
        :raises: AgentAPIError when agent failed to execute specified command.
        :raises: AgentInProgress when the command fails to execute as the agent
                 is presently executing the prior command.
        :returns: A dict containing command response from agent.
                  See :func:`get_commands_status` for a command result sample.
        """
        params = {'root_uuid': root_uuid,
                  'efi_system_part_uuid': efi_system_part_uuid,
                  'prep_boot_part_uuid': prep_boot_part_uuid,
                  'target_boot_mode': target_boot_mode
                  }

        # NOTE(TheJulia): This command explicitly sends a larger timeout
        # factor to the _command call such that the agent ramdisk has enough
        # time to perform its work.
        # TODO(TheJulia): We should likely split install_bootloader into many
        # commands at some point, even though that would not be backwards
        # compatible. We could at least begin to delineate the commands apart
        # over the next cycle or two so we don't need a command timeout
        # extension factor.
        try:
            return self._command(node=node,
                                 method='image.install_bootloader',
                                 params=params,
                                 poll=True)
        except exception.AgentAPIError:
            # NOTE(arne_wiebalck): If for software RAID and 'uefi' as the boot
            # mode, we find that the IPA does not yet support the additional
            # 'target_boot_mode' parameter, we need to fail. For 'bios' boot
            # mode on the other hand we can retry without the parameter,
            # since 'bios' is the default value the IPA will use.
            if target_boot_mode == 'uefi' and software_raid:
                LOG.error('Unable to pass UEFI boot mode to an out of date '
                          'agent ramdisk. Please contact the administrator '
                          'to update the ramdisk to contain an '
                          'ironic-python-agent version of at least 6.0.0.')
                raise
            else:
                params = {'root_uuid': root_uuid,
                          'efi_system_part_uuid': efi_system_part_uuid,
                          'prep_boot_part_uuid': prep_boot_part_uuid
                          }
                LOG.warning('Failed to install bootloader on first attempt '
                            'for node %(node)s. Falling back to older IPA '
                            'format.', {'node': node.uuid})
                return self._command(node=node,
                                     method='image.install_bootloader',
                                     params=params,
                                     poll=True)

    @METRICS.timer('AgentClient.get_clean_steps')
    def get_clean_steps(self, node, ports):
        """Get clean steps from agent.

        :param node: A node object.
        :param ports: Ports associated with the node.
        :raises: IronicException when failed to issue the request or there was
                 a malformed response from the agent.
        :raises: AgentAPIError when agent failed to execute specified command.
        :raises: AgentInProgress when the command fails to execute as the agent
                 is presently executing the prior command.
        :returns: A dict containing command response from agent.
            See :func:`get_commands_status` for a command result sample.
            The value of key command_result is in the form of:

            ::

              {
                'clean_steps': <a list of clean steps>,
                'hardware_manager_version': <manager version>
              }

        """
        params = {
            'node': node.as_dict(secure=True),
            'ports': [port.as_dict() for port in ports]
        }
        return self._command(node=node,
                             method='clean.get_clean_steps',
                             params=params,
                             wait=True)

    @METRICS.timer('AgentClient.execute_clean_step')
    def execute_clean_step(self, step, node, ports):
        """Execute specified clean step.

        :param step: A clean step dictionary to execute.
        :param node: A Node object.
        :param ports: Ports associated with the node.
        :raises: IronicException when failed to issue the request or there was
                 a malformed response from the agent.
        :raises: AgentAPIError when agent failed to execute specified command.
        :raises: AgentInProgress when the command fails to execute as the agent
                 is presently executing the prior command.
        :returns: A dict containing command response from agent.
            See :func:`get_commands_status` for a command result sample.
            The value of key command_result is in the form of:

            ::

              {
                'clean_result': <the result of execution, step specific>,
                'clean_step': <the clean step issued to agent>
              }

        """
        params = {
            'step': step,
            'node': node.as_dict(secure=True),
            'ports': [port.as_dict() for port in ports],
            'clean_version': node.driver_internal_info.get(
                'hardware_manager_version')
        }
        return self._command(node=node,
                             method='clean.execute_clean_step',
                             params=params)

    @METRICS.timer('AgentClient.get_deploy_steps')
    def get_deploy_steps(self, node, ports):
        """Get deploy steps from agent.

        :param node: A node object.
        :param ports: Ports associated with the node.
        :raises: IronicException when failed to issue the request or there was
                 a malformed response from the agent.
        :raises: AgentAPIError when agent failed to execute specified command.
        :returns: A dict containing command response from agent.
            See :func:`get_commands_status` for a command result sample.
            The value of key command_result is in the form of:

            ::

              {
                'deploy_steps': <a list of deploy steps>,
                'hardware_manager_version': <manager version>
              }

        """
        params = {
            'node': node.as_dict(secure=True),
            'ports': [port.as_dict() for port in ports]
        }
        return self._command(node=node,
                             method='deploy.get_deploy_steps',
                             params=params,
                             wait=True)

    @METRICS.timer('AgentClient.execute_deploy_step')
    def execute_deploy_step(self, step, node, ports):
        """Execute specified deploy step.

        :param step: A deploy step dictionary to execute.
        :param node: A Node object.
        :param ports: Ports associated with the node.
        :raises: IronicException when failed to issue the request or there was
                 a malformed response from the agent.
        :raises: AgentAPIError when agent failed to execute specified command.
        :raises: AgentInProgress when the command fails to execute as the agent
                 is presently executing the prior command.
        :returns: A dict containing command response from agent.
            See :func:`get_commands_status` for a command result sample.
            The value of key command_result is in the form of:

            ::

              {
                'deploy_result': <the result of execution, step specific>,
                'deploy_step': <the deploy step issued to agent>
              }

        """
        params = {
            'step': step,
            'node': node.as_dict(secure=True, mask_configdrive=False),
            'ports': [port.as_dict() for port in ports],
            'deploy_version': node.driver_internal_info.get(
                'hardware_manager_version')
        }
        return self._command(node=node,
                             method='deploy.execute_deploy_step',
                             params=params)

    @METRICS.timer('AgentClient.get_service_steps')
    def get_service_steps(self, node, ports):
        """Get service steps from agent.

        :param node: A node object.
        :param ports: Ports associated with the node.
        :raises: IronicException when failed to issue the request or there was
                 a malformed response from the agent.
        :raises: AgentAPIError when agent failed to execute specified command.
        :raises: AgentInProgress when the command fails to execute as the agent
                 is presently executing the prior command.
        :returns: A dict containing command response from agent.
            See :func:`get_commands_status` for a command result sample.
            The value of key command_result is in the form of:

            ::

              {
                'service_steps': <a list of service steps>,
                'hardware_manager_version': <manager version>
              }

        """
        params = {
            'node': node.as_dict(secure=True),
            'ports': [port.as_dict() for port in ports]
        }
        try:
            response = self._command(node=node,
                                     method='service.get_service_steps',
                                     params=params,
                                     wait=True)
        except exception.AgentAPIError:
            # NOTE(TheJulia): This seems logical to do to handle an
            # older ironic-python-agent, since the net-effect will be
            # "there is nothing we can issue to the agent".
            # TODO(TheJulia): Once we know the version where this *is*
            # supported, we should actually update this log message.
            # We won't know that until after the initial merge.
            LOG.warning('Unable to retrieve service steps for node %s.'
                        'Please upgrade your ironic-python-agent.',
                        node.uuid)
            response = {
                'service_steps': [],
                'hardware_manager_version': 0,
            }
        return response

    @METRICS.timer('AgentClient.execute_service_step')
    def execute_service_step(self, step, node, ports):
        """Execute specified service step.

        :param step: A service step dictionary to execute.
        :param node: A Node object.
        :param ports: Ports associated with the node.
        :raises: IronicException when failed to issue the request or there was
                 a malformed response from the agent.
        :raises: AgentAPIError when agent failed to execute specified command.
        :raises: AgentInProgress when the command fails to execute as the agent
                 is presently executing the prior command.
        :returns: A dict containing command response from agent.
            See :func:`get_commands_status` for a command result sample.
            The value of key command_result is in the form of:

            ::

              {
                'service_result': <the result of execution, step specific>,
                'service_step': <the service step issued to agent>
              }

        """
        params = {
            'step': step,
            'node': node.as_dict(secure=True),
            'ports': [port.as_dict() for port in ports],
            'service_version': node.driver_internal_info.get(
                'hardware_manager_version')
        }
        return self._command(node=node,
                             method='service.execute_service_step',
                             params=params)

    @METRICS.timer('AgentClient.get_partition_uuids')
    def get_partition_uuids(self, node):
        """Get deploy steps from agent.

        :param node: A node object.
        :raises: IronicException when failed to issue the request or there was
                 a malformed response from the agent.
        :raises: AgentAPIError when agent failed to execute specified command.
        :raises: AgentInProgress when the command fails to execute as the agent
                 is presently executing the prior command.
        :returns: A dict containing command response from agent.

        """
        return self._command(node=node,
                             method='standby.get_partition_uuids',
                             params={},
                             wait=True)

    @METRICS.timer('AgentClient.power_off')
    def power_off(self, node):
        """Soft powers off the bare metal node by shutting down ramdisk OS.

        :param node: A Node object.
        :raises: IronicException when failed to issue the request or there was
                 a malformed response from the agent.
        :raises: AgentAPIError when agent failed to execute specified command.
        :raises: AgentInProgress when the command fails to execute as the agent
                 is presently executing the prior command.
        :returns: A dict containing command response from agent.
                  See :func:`get_commands_status` for a command result sample.
        """
        return self._command(node=node,
                             method='standby.power_off',
                             params={})

    @METRICS.timer('AgentClient.reboot')
    def reboot(self, node):
        """Soft reboots the bare metal node by shutting down ramdisk OS.

        :param node: A Node object.
        :raises: IronicException when failed to issue the request or there was
                 a malformed response from the agent.
        :raises: AgentAPIError when agent failed to execute specified command.
        :raises: AgentInProgress when the command fails to execute as the agent
                 is presently executing the prior command.
        :returns: A dict containing command response from agent.
                  See :func:`get_commands_status` for a command result sample.
        """
        return self._command(node=node,
                             method='standby.%s' % REBOOT_COMMAND,
                             params={})

    @METRICS.timer('AgentClient.sync')
    def sync(self, node):
        """Flush file system buffers forcing changed blocks to disk.

        :param node: A Node object.
        :raises: IronicException when failed to issue the request or there was
                 a malformed response from the agent.
        :raises: AgentAPIError when agent failed to execute specified command.
        :raises: AgentInProgress when the command fails to execute as the agent
                 is presently executing the prior command.
        :returns: A dict containing command response from agent.
                  See :func:`get_commands_status` for a command result sample.
        """
        return self._command(node=node,
                             method='standby.sync',
                             params={},
                             wait=True)

    @METRICS.timer('AgentClient.collect_system_logs')
    def collect_system_logs(self, node):
        """Collect and package diagnostic and support data from the ramdisk.

        :param node: A Node object.
        :raises: IronicException when failed to issue the request or there was
                 a malformed response from the agent.
        :raises: AgentAPIError when agent failed to execute specified command.
        :raises: AgentInProgress when the command fails to execute as the agent
                 is presently executing the prior command.
        :returns: A dict containing command response from agent.
                  See :func:`get_commands_status` for a command result sample.
        """
        return self._command(node=node,
                             method='log.collect_system_logs',
                             params={},
                             wait=True)

    @METRICS.timer('AgentClient.finalize_rescue')
    def finalize_rescue(self, node):
        """Instruct the ramdisk to finalize entering of rescue mode.

        :param node: A Node object.
        :raises: IronicException if rescue_password is missing, or when failed
                 to issue the request, or there was a malformed response from
                 the agent.
        :raises: AgentAPIError when agent failed to execute specified command.
        :raises: AgentInProgress when the command fails to execute as the agent
                 is presently executing the prior command.
        :raises: InstanceRescueFailure when the agent ramdisk is too old
                 to support transmission of the rescue password.
        :returns: A dict containing command response from agent.
                  See :func:`get_commands_status` for a command result sample.
        """
        rescue_pass = node.instance_info.get('hashed_rescue_password')
        # TODO(TheJulia): Remove fallback to use the fallback_rescue_password
        # in the Victoria cycle.
        fallback_rescue_pass = node.instance_info.get(
            'rescue_password')
        if not rescue_pass:
            raise exception.IronicException(_('Agent rescue requires '
                                              'rescue_password in '
                                              'instance_info'))
        params = {'rescue_password': rescue_pass,
                  'hashed': True}
        try:
            return self._command(node=node,
                                 method='rescue.finalize_rescue',
                                 params=params)
        except exception.AgentAPIError:
            if CONF.conductor.require_rescue_password_hashed:
                raise exception.InstanceRescueFailure(
                    _('Unable to rescue node due to an out of date agent '
                      'ramdisk. Please contact the administrator to update '
                      'the rescue ramdisk to contain an ironic-python-agent '
                      'version of at least 6.0.0.'))
            else:
                params = {'rescue_password': fallback_rescue_pass}
                return self._command(node=node,
                                     method='rescue.finalize_rescue',
                                     params=params)
