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

from ironic.common import states

# These flags tell the conductor that we're rebooting inside or after a step.

CLEANING_REBOOT = "cleaning_reboot"
DEPLOYMENT_REBOOT = "deployment_reboot"
SERVICING_REBOOT = "servicing_reboot"

# These flags tell the conductor whether the currently running step should be
# skipped after the agent heartbeats again. Setting them to false causes
# the conductor to re-enter the previously running step after a reboot.

SKIP_CURRENT_CLEAN_STEP = "skip_current_clean_step"
SKIP_CURRENT_DEPLOY_STEP = "skip_current_deploy_step"
SKIP_CURRENT_SERVICE_STEP = "skip_current_service_step"

# These flags tell the conductor that something else (most likely, a periodic
# task in some hardware interface) is polling the step for completion.

CLEANING_POLLING = "cleaning_polling"
DEPLOYMENT_POLLING = "deployment_polling"
SERVICING_POLLING = "servicing_polling"

_ALL_FLAGS = [CLEANING_REBOOT, DEPLOYMENT_REBOOT, SERVICING_REBOOT,
              SKIP_CURRENT_CLEAN_STEP, SKIP_CURRENT_DEPLOY_STEP,
              SKIP_CURRENT_SERVICE_STEP,
              CLEANING_POLLING, DEPLOYMENT_POLLING, SERVICING_POLLING]


def get_return_state(node):
    """Returns state based on operation being invoked.

    :param node: an ironic node object.
    :returns: states.CLEANWAIT if cleaning operation in progress,
              or states.DEPLOYWAIT if deploy operation in progress,
              or states.SERVICEWAIT if servicing in progress.
    """
    # FIXME(dtantsur): this distinction is rather useless, create a new
    # constant to use for all step types?
    if node.clean_step:
        return states.CLEANWAIT
    elif node.service_step:
        return states.SERVICEWAIT
    else:
        # TODO(dtantsur): ideally, check for node.deploy_step and raise
        # something if this function is called without any step field set.
        # Unfortunately, a lot of unit tests rely on exactly this.
        return states.DEPLOYWAIT


def _check_agent_token_prior_to_agent_reboot(node):
    """Removes the agent token if it was not pregenerated.

    Removal of the agent token in cases where it is not pregenerated
    is a vital action prior to rebooting the agent, as without doing
    so the agent will be unable to establish communication with
    the ironic API after the reboot. Effectively locking itself out
    as in cases where the value is not pregenerated, it is not
    already included in the payload and must be generated again
    upon lookup.

    :param node: The Node object.
    """
    if not node.driver_internal_info.get('agent_secret_token_pregenerated',
                                         False):
        node.del_driver_internal_info('agent_secret_token')


def _step_type(node, step_type):
    if step_type:
        return step_type
    if node.clean_step:
        return 'clean'
    elif node.service_step:
        return 'service'
    else:
        return 'deploy'


def set_node_flags(node, reboot=None, skip_current_step=None, polling=None,
                   step_type=None):
    """Sets appropriate reboot flags in driver_internal_info based on operation

    :param node: an ironic node object.
    :param reboot: Boolean value to set for node's driver_internal_info flag
        cleaning_reboot, servicing_reboot or deployment_reboot based on the
        operation in progress. If it is None, corresponding reboot flag is
        not set in node's driver_internal_info.
    :param skip_current_step: Boolean value to set for node's
        driver_internal_info flag skip_current_clean_step,
        skip_current_service_step or skip_current_deploy_step based on the
        operation in progress. If it is None, corresponding skip step flag is
        not set in node's driver_internal_info.
    :param polling: Boolean value to set for node's driver_internal_info flag
        deployment_polling, servicing_polling or cleaning_polling. If it is
        None, the corresponding polling flag is not set in the node's
        driver_internal_info.
    :param step_type: The type of steps to process: 'clean', 'service'
        or 'deploy'. If None, detected from the node.
    """
    step_type = _step_type(node, step_type)
    if step_type == 'clean':
        reboot_field = CLEANING_REBOOT
        skip_field = SKIP_CURRENT_CLEAN_STEP
        polling_field = CLEANING_POLLING
    elif step_type == 'service':
        reboot_field = SERVICING_REBOOT
        skip_field = SKIP_CURRENT_SERVICE_STEP
        polling_field = SERVICING_POLLING
    else:
        reboot_field = DEPLOYMENT_REBOOT
        skip_field = SKIP_CURRENT_DEPLOY_STEP
        polling_field = DEPLOYMENT_POLLING

    if reboot is not None:
        node.set_driver_internal_info(reboot_field, reboot)
        if reboot:
            # If rebooting, we must ensure that we check and remove
            # an agent token if necessary.
            _check_agent_token_prior_to_agent_reboot(node)
    if skip_current_step is not None:
        node.set_driver_internal_info(skip_field, skip_current_step)
    if polling is not None:
        node.set_driver_internal_info(polling_field, polling)
    node.save()


def remove_node_flags(node):
    """Remove all flags for the node.

    :param node: A Node object
    """
    for flag in _ALL_FLAGS:
        node.del_driver_internal_info(flag)


def prepare_node_for_next_step(node, step_type=None):
    """Remove the flags responsible for the next step.

    Cleans the polling and the skip-next step flags.

    :param node: A Node object
    :param step_type: The type of steps to process: 'clean', 'service'
        or 'deploy'. If None, detected from the node.
    :returns: The last value of the skip-next flag.
    """
    step_type = _step_type(node, step_type)
    skip_current_step = node.del_driver_internal_info(
        'skip_current_%s_step' % step_type, True)
    if step_type == 'clean':
        node.del_driver_internal_info(CLEANING_POLLING)
    elif step_type == 'service':
        node.del_driver_internal_info(SERVICING_POLLING)
    else:
        node.del_driver_internal_info(DEPLOYMENT_POLLING)
    return skip_current_step
