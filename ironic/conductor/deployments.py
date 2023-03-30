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

"""Functionality related to deploying and undeploying."""

import tempfile

from ironic_lib import metrics_utils
from oslo_db import exception as db_exception
from oslo_log import log
from oslo_utils import excutils

from ironic.common import exception
from ironic.common.glance_service import service_utils as glance_utils
from ironic.common.i18n import _
from ironic.common import states
from ironic.common import swift
from ironic.conductor import notification_utils as notify_utils
from ironic.conductor import steps as conductor_steps
from ironic.conductor import task_manager
from ironic.conductor import utils
from ironic.conf import CONF
from ironic.objects import fields
from ironic.objects import Node

LOG = log.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


def validate_node(task, event='deploy'):
    """Validate that a node is suitable for deployment/rebuilding.

    :param task: a TaskManager instance.
    :param event: event to process: deploy or rebuild.
    :raises: NodeInMaintenance, NodeProtected, InvalidStateRequested
    """
    if task.node.maintenance:
        raise exception.NodeInMaintenance(op=_('provisioning'),
                                          node=task.node.uuid)

    if event == 'rebuild' and task.node.protected:
        raise exception.NodeProtected(node=task.node.uuid)

    if not task.fsm.is_actionable_event(event):
        raise exception.InvalidStateRequested(
            action=event, node=task.node.uuid, state=task.node.provision_state)


@METRICS.timer('start_deploy')
@task_manager.require_exclusive_lock
def start_deploy(task, manager, configdrive=None, event='deploy',
                 deploy_steps=None):
    """Start deployment or rebuilding on a node.

    This function does not check the node suitability for deployment, it's left
    up to the caller.

    :param task: a TaskManager instance.
    :param manager: a ConductorManager to run tasks on.
    :param configdrive: a configdrive, if requested.
    :param event: event to process: deploy or rebuild.
    :param deploy_steps: Optional deploy steps.
    """
    node = task.node

    if event == 'rebuild':
        # Note(gilliard) Clear these to force the driver to
        # check whether they have been changed in glance
        # NOTE(vdrok): If image_source is not from Glance we should
        # not clear kernel and ramdisk as they're input manually
        if glance_utils.is_glance_image(
                node.instance_info.get('image_source')):
            instance_info = node.instance_info
            instance_info.pop('kernel', None)
            instance_info.pop('ramdisk', None)
            node.instance_info = instance_info
    elif CONF.conductor.automatic_lessee:
        # This should only be on deploy...
        project = utils.get_token_project_from_request(task.context)
        if (project and node.lessee is None):
            LOG.debug('Adding lessee $(project)s to node %(uuid)s.',
                      {'project': project,
                       'uuid': node.uuid})
            node.set_driver_internal_info('automatic_lessee', True)
            node.lessee = project
        elif project and node.lessee is not None:
            # Since the model is a bit of a matrix and we're largely
            # just empowering operators, lets at least log a warning
            # since they may need to remedy something here. Or maybe
            # not.
            LOG.warning('Could not automatically save lessee '
                        '$(project)s to node %(uuid)s. Node already '
                        'has a defined lessee of %(lessee)s.',
                        {'project': project,
                         'uuid': node.uuid,
                         'lessee': node.lessee})

    # Infer the image type to make sure the deploy driver
    # validates only the necessary variables for different
    # image types.
    if utils.update_image_type(task.context, task.node):
        node.save()

    try:
        task.driver.power.validate(task)
        task.driver.deploy.validate(task)
        utils.validate_instance_info_traits(task.node)
        conductor_steps.validate_user_deploy_steps_and_templates(
            task, deploy_steps, skip_missing=True)
    except exception.InvalidParameterValue as e:
        raise exception.InstanceDeployFailure(
            _("Failed to validate deploy or power info for node "
              "%(node_uuid)s: %(msg)s") %
            {'node_uuid': node.uuid, 'msg': e}, code=e.code)

    try:
        task.process_event(
            event,
            callback=manager._spawn_worker,
            call_args=(do_node_deploy, task,
                       manager.conductor.id, configdrive, deploy_steps),
            err_handler=utils.provisioning_error_handler)
    except exception.InvalidState:
        raise exception.InvalidStateRequested(
            action=event, node=task.node.uuid,
            state=task.node.provision_state)


@METRICS.timer('do_node_deploy')
@task_manager.require_exclusive_lock
def do_node_deploy(task, conductor_id=None, configdrive=None,
                   deploy_steps=None):
    """Prepare the environment and deploy a node."""
    node = task.node
    utils.wipe_deploy_internal_info(task)
    try:
        if configdrive:
            _store_configdrive(node, configdrive)
    except (exception.SwiftOperationError, exception.ConfigInvalid) as e:
        with excutils.save_and_reraise_exception():
            utils.deploying_error_handler(
                task,
                ('Error while uploading the configdrive for %(node)s '
                 'to Swift') % {'node': node.uuid},
                _('Failed to upload the configdrive to Swift: %s') % e,
                clean_up=False)
    except db_exception.DBDataError as e:
        with excutils.save_and_reraise_exception():
            # NOTE(hshiina): This error happens when the configdrive is
            #                too large. Remove the configdrive from the
            #                object to update DB successfully in handling
            #                the failure.
            node.obj_reset_changes()
            utils.deploying_error_handler(
                task,
                ('Error while storing the configdrive for %(node)s into '
                 'the database: %(err)s') % {'node': node.uuid, 'err': e},
                _("Failed to store the configdrive in the database. "
                  "%s") % e,
                clean_up=False)
    except Exception as e:
        with excutils.save_and_reraise_exception():
            utils.deploying_error_handler(
                task,
                ('Unexpected error while preparing the configdrive for '
                 'node %(node)s') % {'node': node.uuid},
                _("Failed to prepare the configdrive. Exception: %s") % e,
                traceback=True, clean_up=False)

    try:
        task.driver.deploy.prepare(task)
    except exception.IronicException as e:
        with excutils.save_and_reraise_exception():
            utils.deploying_error_handler(
                task,
                ('Error while preparing to deploy to node %(node)s: '
                 '%(err)s') % {'node': node.uuid, 'err': e},
                _("Failed to prepare to deploy: %s") % e,
                clean_up=False)
    except Exception as e:
        with excutils.save_and_reraise_exception():
            utils.deploying_error_handler(
                task,
                ('Unexpected error while preparing to deploy to node '
                 '%(node)s') % {'node': node.uuid},
                _("Failed to prepare to deploy. Exception: %s") % e,
                traceback=True, clean_up=False)

    try:
        # If any deploy steps provided by user, save them to node. They will be
        # validated & processed later together with driver and deploy template
        # steps.
        if deploy_steps:
            node.set_driver_internal_info('user_deploy_steps', deploy_steps)
            node.save()
        # This gets the deploy steps (if any) from driver, deploy template and
        # deploy_steps argument and updates them in the node's
        # driver_internal_info['deploy_steps']. In-band steps are skipped since
        # we know that an agent is not running yet.
        conductor_steps.set_node_deployment_steps(task, skip_missing=True)
    except exception.InstanceDeployFailure as e:
        with excutils.save_and_reraise_exception():
            utils.deploying_error_handler(
                task,
                'Error while getting deploy steps; cannot deploy to node '
                '%(node)s: %(err)s' % {'node': node.uuid, 'err': e},
                _("Cannot get deploy steps; failed to deploy: %s") % e)

    if not node.driver_internal_info.get('deploy_steps'):
        msg = _('Error while getting deploy steps: no steps returned for '
                'node %s') % node.uuid
        utils.deploying_error_handler(
            task, msg,
            _("No deploy steps returned by the driver"))
        raise exception.InstanceDeployFailure(msg)

    if conductor_id is not None:
        # Update conductor_affinity to reference this conductor's ID
        # since there may be local persistent state
        node.conductor_affinity = conductor_id
        node.save()

    do_next_deploy_step(task, 0)


@utils.fail_on_error(utils.deploying_error_handler,
                     _("Unexpected error when processing next deploy step"),
                     traceback=True)
@task_manager.require_exclusive_lock
def do_next_deploy_step(task, step_index):
    """Do deployment, starting from the specified deploy step.

    :param task: a TaskManager instance with an exclusive lock
    :param step_index: The first deploy step in the list to execute. This
        is the index (from 0) into the list of deploy steps in the node's
        driver_internal_info['deploy_steps']. Is None if there are no steps
        to execute.
    """
    node = task.node

    def _iter_steps():
        if step_index is None:
            return  # short-circuit to the end
        idx = step_index
        # The list can change in-flight, do not cache it!
        while idx < len(node.driver_internal_info['deploy_steps']):
            yield idx, node.driver_internal_info['deploy_steps'][idx]
            idx += 1

    # Execute each step until we hit an async step or run out of steps, keeping
    # in mind that the steps list can be modified in-flight.
    for idx, step in _iter_steps():
        LOG.info('Deploying on node %(node)s, remaining steps: '
                 '%(steps)s', {
                     'node': node.uuid,
                     'steps': node.driver_internal_info['deploy_steps'][idx:],
                 })
        # Save which step we're about to start so we can restart
        # if necessary
        node.deploy_step = step
        node.set_driver_internal_info('deploy_step_index', idx)
        node.save()

        child_node_execution = step.get('execute_on_child_nodes', False)
        result = None
        try:
            if not child_node_execution:
                interface = getattr(task.driver, step.get('interface'))
                LOG.info('Executing %(step)s on node %(node)s',
                         {'step': step, 'node': node.uuid})
                use_step_handler = conductor_steps.use_reserved_step_handler(
                    task, step)
                if use_step_handler:
                    if use_step_handler == conductor_steps.EXIT_STEPS:
                        # Exit the step, i.e. hold step
                        return
                    # if use_step_handler == conductor_steps.USED_HANDLER
                    # Then we have completed the needful in the handler,
                    # but since there is no other value to check now,
                    # we know we just need to skip execute_deploy_step
                else:
                    interface = getattr(task.driver, step.get('interface'))
                    result = interface.execute_deploy_step(task, step)
            else:
                LOG.info('Executing %(step)s on child nodes for node '
                         '%(node)s',
                         {'step': step, 'node': node.uuid})
                result = execute_step_on_child_nodes(task, step)
        except exception.AgentInProgress as e:
            LOG.info('Conductor attempted to process deploy step for '
                     'node %(node)s. Agent indicated it is presently '
                     'executing a command. Error: %(error)s',
                     {'node': task.node.uuid,
                      'error': e})
            node.set_driver_internal_info('skip_current_deploy_step',
                                          False)
            task.process_event('wait')
            return
        except exception.IronicException as e:
            if isinstance(e, exception.AgentConnectionFailed):
                if task.node.driver_internal_info.get('deployment_reboot'):
                    LOG.info('Agent is not yet running on node %(node)s after '
                             'deployment reboot, waiting for agent to come up '
                             'to run next deploy step %(step)s.',
                             {'node': node.uuid, 'step': step})
                    node.set_driver_internal_info('skip_current_deploy_step',
                                                  False)
                    task.process_event('wait')
                    return

            # Avoid double handling of failures. For example, set_failed_state
            # from deploy_utils already calls deploying_error_handler.
            if task.node.provision_state != states.DEPLOYFAIL:
                log_msg = ('Node %(node)s failed deploy step %(step)s: '
                           '%(err)s' % {'node': node.uuid,
                                        'step': node.deploy_step, 'err': e})
                utils.deploying_error_handler(
                    task, log_msg,
                    _("Deploy step %(step)s failed: %(err)s.")
                    % {'step': conductor_steps.step_id(step), 'err': e})
            return
        except Exception as e:
            log_msg = ('Node %(node)s failed deploy step %(step)s with '
                       'unexpected error: %(err)s' %
                       {'node': node.uuid, 'step': node.deploy_step, 'err': e})
            utils.deploying_error_handler(
                task, log_msg,
                _("Deploy step %(step)s failed with %(exc)s: %(err)s.")
                % {'step': conductor_steps.step_id(step), 'err': e,
                   'exc': e.__class__.__name__},
                traceback=True)
            return

        if task.node.provision_state == states.DEPLOYFAIL:
            # NOTE(dtantsur): some deploy steps do not raise but rather update
            # the node and return. Take them into account.
            LOG.debug('Node %s is in error state, not processing '
                      'the remaining deploy steps', task.node)
            return

        # Check if the step is done or not. The step should return
        # states.DEPLOYWAIT if the step is still being executed, or
        # None if the step is done.
        # NOTE(tenbrae): Some drivers may return states.DEPLOYWAIT
        #                eg. if they are waiting for a callback
        if result == states.DEPLOYWAIT:
            # Kill this worker, the async step will make an RPC call to
            # continue_node_deploy() to continue deploying
            LOG.info('Deploy step %(step)s on node %(node)s being '
                     'executed asynchronously, waiting for driver.',
                     {'node': node.uuid, 'step': step})
            if task.node.provision_state != states.DEPLOYWAIT:
                task.process_event('wait')
            return
        elif result is not None:
            # NOTE(rloo): This is an internal/dev error; shouldn't happen.
            log_msg = (_('While executing deploy step %(step)s on node '
                       '%(node)s, step returned unexpected state: %(val)s')
                       % {'step': step, 'node': node.uuid, 'val': result})
            utils.deploying_error_handler(
                task, log_msg,
                _("Failed to deploy: %s") % node.deploy_step)
            return

        LOG.info('Node %(node)s finished deploy step %(step)s',
                 {'node': node.uuid, 'step': step})

    # Finished executing the steps. Clear deploy_step.
    node.deploy_step = None
    utils.wipe_deploy_internal_info(task)
    node.save()

    _start_console_in_deploy(task)

    task.process_event('done')
    LOG.info('Successfully deployed node %(node)s with '
             'instance %(instance)s.',
             {'node': node.uuid, 'instance': node.instance_uuid})


@task_manager.require_exclusive_lock
def validate_deploy_steps(task):
    """Validate the deploy steps after the ramdisk learns about them."""
    conductor_steps.validate_user_deploy_steps_and_templates(task)
    conductor_steps.set_node_deployment_steps(
        task, reset_current=False)

    task.node.set_driver_internal_info('steps_validated', True)
    task.node.save()


@utils.fail_on_error(utils.deploying_error_handler,
                     _("Unexpected error when processing next deploy step"),
                     traceback=True)
@task_manager.require_exclusive_lock
def continue_node_deploy(task):
    """Continue deployment after finishing an async deploy step.

    This function calculates which step has to run next and passes control
    into do_next_deploy_step. On the first run, deploy steps and templates are
    also validated.

    :param task: a TaskManager instance with an exclusive lock
    """
    node = task.node

    # Agent is now running, we're ready to validate the remaining steps
    if not task.node.driver_internal_info.get('steps_validated'):
        try:
            validate_deploy_steps(task)
        except exception.IronicException as exc:
            msg = _('Failed to validate the final deploy steps list '
                    'for node %(node)s: %(exc)s') % {'node': node.uuid,
                                                     'exc': exc}
            return utils.deploying_error_handler(task, msg)

    next_step_index = utils.update_next_step_index(task, 'deploy')

    do_next_deploy_step(task, next_step_index)


def _get_configdrive_obj_name(node):
    """Generate the object name for the config drive."""
    return 'configdrive-%s' % node.uuid


def _store_configdrive(node, configdrive):
    """Handle the storage of the config drive.

    If configured, the config drive data are uploaded to a swift endpoint.
    The Node's instance_info is updated to include either the temporary
    Swift URL from the upload, or if no upload, the actual config drive data.

    :param node: an Ironic node object.
    :param configdrive: A gzipped and base64 encoded configdrive.
    :raises: SwiftOperationError if an error occur when uploading the
             config drive to the swift endpoint.
    :raises: ConfigInvalid if required keystone authorization credentials
             with swift are missing.


    """
    if CONF.deploy.configdrive_use_object_store:
        # Don't store the JSON source in swift.
        if isinstance(configdrive, dict):
            configdrive = utils.build_configdrive(node, configdrive)

        # NOTE(lucasagomes): No reason to use a different timeout than
        # the one used for deploying the node
        timeout = (CONF.conductor.configdrive_swift_temp_url_duration
                   or CONF.conductor.deploy_callback_timeout
                   # The documented default in ironic.conf.conductor
                   or 1800)
        container = CONF.conductor.configdrive_swift_container
        object_name = _get_configdrive_obj_name(node)

        object_headers = {'X-Delete-After': str(timeout)}

        with tempfile.NamedTemporaryFile(dir=CONF.tempdir,
                                         mode="wt") as fileobj:
            fileobj.write(configdrive)
            fileobj.flush()

            swift_api = swift.SwiftAPI()
            swift_api.create_object(container, object_name, fileobj.name,
                                    object_headers=object_headers)
            configdrive = swift_api.get_temp_url(container, object_name,
                                                 timeout)

    i_info = node.instance_info
    i_info['configdrive'] = configdrive
    node.instance_info = i_info
    node.save()


def _start_console_in_deploy(task):
    """Start console at the end of deployment.

    Console is stopped at tearing down not to be exposed to an instance user.
    Then, restart at deployment.

    :param task: a TaskManager instance with an exclusive lock
    """

    if not task.node.console_enabled:
        return

    notify_utils.emit_console_notification(
        task, 'console_restore', fields.NotificationStatus.START)
    try:
        task.driver.console.start_console(task)
    except Exception as err:
        msg = (_('Failed to start console while deploying the '
                 'node %(node)s: %(err)s.') % {'node': task.node.uuid,
                                               'err': err})
        LOG.error(msg)
        task.node.last_error = msg
        task.node.console_enabled = False
        task.node.save()
        notify_utils.emit_console_notification(
            task, 'console_restore', fields.NotificationStatus.ERROR)
    else:
        notify_utils.emit_console_notification(
            task, 'console_restore', fields.NotificationStatus.END)


def execute_step_on_child_nodes(task, step):
    """Execute a requested step against a child node.

    :param task: The TaskManager object for the parent node.
    :param step: The requested step to be executed.
    :returns: None on Success, the resulting error message if a
              failure has occured.
    """
    # NOTE(TheJulia): We could just use nodeinfo list calls against
    # dbapi.
    # NOTE(TheJulia): We validate the data in advance in the API
    # with the original request context.
    eocn = step.get('execute_on_child_nodes')
    child_nodes = step.get('limit_child_node_execution', [])
    filters = {'parent_node': task.node.uuid}
    if eocn and len(child_nodes) >= 1:
        filters['uuid_in'] = child_nodes

    child_nodes = Node.list(
        task.context,
        filters=filters,
        fields=['uuid']
    )
    for child_node in child_nodes:
        result = None
        LOG.info('Executing step %(step)s on child node %(node)s for parent '
                 'node %(parent_node)s',
                 {'step': step,
                  'node': child_node.uuid,
                  'parent_node': task.node.uuid})
        with task_manager.acquire(task.context,
                                  child_node.uuid,
                                  purpose='execute step') as child_task:
            interface = getattr(child_task.driver, step.get('interface'))
            LOG.info('Executing %(step)s on node %(node)s',
                     {'step': step, 'node': child_task.node.uuid})
            if not conductor_steps.use_reserved_step_handler(child_task, step):
                result = interface.execute_clean_step(child_task, step)
            if result is not None:
                if (result == states.DEPLOYWAIT
                    and CONF.conductor.permit_child_node_step_async_result):
                    # Operator has chosen to permit this due to some reason
                    # NOTE(TheJulia): This is where we would likely wire agent
                    # error handling if we ever implicitly allowed child node
                    # deploys to take place with the agent from a parent node
                    # being deployed.
                    continue
                msg = (_('While executing step %(step)s on child node '
                         '%(node)s, step returned invalid value: %(val)s')
                       % {'step': step, 'node': child_task.node.uuid,
                          'val': result})
                LOG.error(msg)
                # Only None or states.DEPLOYWAIT are possible paths forward
                # in the parent step execution code, so returning the message
                # means it will be logged.
                return msg
