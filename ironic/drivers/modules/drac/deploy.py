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

"""
DRAC deploy interface
"""

from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import iscsi_deploy

_OOB_CLEAN_STEPS = [
    {'interface': 'raid', 'step': 'create_configuration'},
    {'interface': 'raid', 'step': 'delete_configuration'}
]


class DracDeploy(iscsi_deploy.ISCSIDeploy):

    def prepare_cleaning(self, task):
        """Prepare environment for cleaning

        Boot into the agent to prepare for cleaning if in-band cleaning step
        is requested.

        :param task: a TaskManager instance containing the node to act on.
        :returns: states.CLEANWAIT if there is any in-band clean step to
                  signify an asynchronous prepare.
        """
        node = task.node

        inband_steps = [step for step
                        in node.driver_internal_info.get('clean_steps', [])
                        if {'interface': step['interface'],
                            'step': step['step']} not in _OOB_CLEAN_STEPS]

        if ('agent_cached_clean_steps' not in node.driver_internal_info or
            inband_steps):
                return deploy_utils.prepare_inband_cleaning(task,
                                                            manage_boot=True)
