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

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_serialization import jsonutils
import requests

from ironic.common import exception
from ironic.common.i18n import _
from ironic.conf import CONF

LOG = log.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

DEFAULT_IPA_PORTAL_PORT = 3260


class AgentClient(object):
    """Client for interacting with nodes via a REST API."""
    @METRICS.timer('AgentClient.__init__')
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})

    def _get_command_url(self, node):
        agent_url = node.driver_internal_info.get('agent_url')
        if not agent_url:
            raise exception.IronicException(_('Agent driver requires '
                                              'agent_url in '
                                              'driver_internal_info'))
        return ('%(agent_url)s/%(api_version)s/commands' %
                {'agent_url': agent_url,
                 'api_version': CONF.agent.agent_api_version})

    def _get_command_body(self, method, params):
        return jsonutils.dumps({
            'name': method,
            'params': params,
        })

    @METRICS.timer('AgentClient._command')
    def _command(self, node, method, params, wait=False):
        url = self._get_command_url(node)
        body = self._get_command_body(method, params)
        request_params = {
            'wait': str(wait).lower()
        }
        LOG.debug('Executing agent command %(method)s for node %(node)s',
                  {'node': node.uuid, 'method': method})

        try:
            response = self.session.post(url, params=request_params, data=body)
        except requests.RequestException as e:
            msg = (_('Error invoking agent command %(method)s for node '
                     '%(node)s. Error: %(error)s') %
                   {'method': method, 'node': node.uuid, 'error': e})
            LOG.error(msg)
            raise exception.IronicException(msg)

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

        LOG.debug('Agent command %(method)s for node %(node)s returned '
                  'result %(res)s, error %(error)s, HTTP status code %(code)d',
                  {'node': node.uuid, 'method': method,
                   'res': result.get('command_result'),
                   'error': result.get('command_error'),
                   'code': response.status_code})
        return result

    @METRICS.timer('AgentClient.get_commands_status')
    def get_commands_status(self, node):
        url = self._get_command_url(node)
        LOG.debug('Fetching status of agent commands for node %s', node.uuid)
        resp = self.session.get(url)
        result = resp.json()['commands']
        status = '; '.join('%(cmd)s: result "%(res)s", error "%(err)s"' %
                           {'cmd': r.get('command_name'),
                            'res': r.get('command_result'),
                            'err': r.get('command_error')}
                           for r in result)
        LOG.debug('Status of agent commands for node %(node)s: %(status)s',
                  {'node': node.uuid, 'status': status})
        return result

    @METRICS.timer('AgentClient.prepare_image')
    def prepare_image(self, node, image_info, wait=False):
        """Call the `prepare_image` method on the node."""
        LOG.debug('Preparing image %(image)s on node %(node)s.',
                  {'image': image_info.get('id'),
                   'node': node.uuid})
        params = {'image_info': image_info}

        # this should be an http(s) URL
        configdrive = node.instance_info.get('configdrive')
        if configdrive is not None:
            params['configdrive'] = configdrive

        return self._command(node=node,
                             method='standby.prepare_image',
                             params=params,
                             wait=wait)

    @METRICS.timer('AgentClient.start_iscsi_target')
    def start_iscsi_target(self, node, iqn,
                           portal_port=DEFAULT_IPA_PORTAL_PORT,
                           wipe_disk_metadata=False):
        """Expose the node's disk as an ISCSI target.

        :param node: an Ironic node object
        :param iqn: iSCSI target IQN
        :param portal_port: iSCSI portal port
        :param wipe_disk_metadata: True if the agent should wipe first the
                                   disk magic strings like the partition
                                   table, RAID or filesystem signature.
        """
        params = {'iqn': iqn,
                  'portal_port': portal_port,
                  'wipe_disk_metadata': wipe_disk_metadata}
        return self._command(node=node,
                             method='iscsi.start_iscsi_target',
                             params=params,
                             wait=True)

    @METRICS.timer('AgentClient.install_bootloader')
    def install_bootloader(self, node, root_uuid, efi_system_part_uuid=None):
        """Install a boot loader on the image."""
        params = {'root_uuid': root_uuid,
                  'efi_system_part_uuid': efi_system_part_uuid}
        return self._command(node=node,
                             method='image.install_bootloader',
                             params=params,
                             wait=True)

    @METRICS.timer('AgentClient.get_clean_steps')
    def get_clean_steps(self, node, ports):
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

    @METRICS.timer('AgentClient.power_off')
    def power_off(self, node):
        """Soft powers off the bare metal node by shutting down ramdisk OS."""
        return self._command(node=node,
                             method='standby.power_off',
                             params={})

    @METRICS.timer('AgentClient.sync')
    def sync(self, node):
        """Flush file system buffers forcing changed blocks to disk."""
        return self._command(node=node,
                             method='standby.sync',
                             params={},
                             wait=True)

    @METRICS.timer('AgentClient.collect_system_logs')
    def collect_system_logs(self, node):
        """Collect and package diagnostic and support data from the ramdisk."""
        return self._command(node=node,
                             method='log.collect_system_logs',
                             params={},
                             wait=True)
