# coding=utf-8

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

import contextlib
import crypt
import datetime
import functools
import os
import secrets
import time

from openstack.baremetal import configdrive as os_configdrive
from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import strutils
from oslo_utils import timeutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import faults
from ironic.common.i18n import _
from ironic.common import network
from ironic.common import nova
from ironic.common import states
from ironic.conductor import notification_utils as notify_utils
from ironic.conductor import task_manager
from ironic.objects import fields
from ironic.objects import node_history

LOG = log.getLogger(__name__)
CONF = cfg.CONF


PASSWORD_HASH_FORMAT = {
    'sha256': crypt.METHOD_SHA256,
    'sha512': crypt.METHOD_SHA512,
}


@task_manager.require_exclusive_lock
def node_set_boot_device(task, device, persistent=False):
    """Set the boot device for a node.

    If the node that the boot device change is being requested for
    is in ADOPTING state, the boot device will not be set as that
    change could potentially result in the future running state of
    an adopted node being modified erroneously.

    :param task: a TaskManager instance.
    :param device: Boot device. Values are vendor-specific.
    :param persistent: Whether to set next-boot, or make the change
        permanent. Default: False.
    :raises: InvalidParameterValue if the validation of the
        ManagementInterface fails.

    """
    task.driver.management.validate(task)
    if task.node.provision_state == states.ADOPTING:
        return

    force_persistent = task.node.driver_info.get(
        'force_persistent_boot_device')
    if force_persistent == 'Always':
        persistent = True
    elif force_persistent == 'Never':
        persistent = False
    elif force_persistent not in (None, 'Default'):
        # Backward compatibility (used to be a boolean and only True mattered)
        if strutils.bool_from_string(force_persistent, strict=False):
            persistent = True

    task.driver.management.set_boot_device(task, device=device,
                                           persistent=persistent)


def node_get_boot_mode(task):
    """Read currently set boot mode from a node.

    Reads the boot mode for a node. If boot mode can't be discovered,
    `None` is returned.

    :param task: a TaskManager instance.
    :raises: DriverOperationError or its derivative in case
             of driver runtime error.
    :raises: UnsupportedDriverExtension if current driver does not have
             management interface or `get_boot_mode()` method is
             not supported.
    :returns: Boot mode. One of :mod:`ironic.common.boot_mode` or `None`
        if boot mode can't be discovered
    """
    task.driver.management.validate(task)
    return task.driver.management.get_boot_mode(task)


# TODO(ietingof): remove `Sets the boot mode...` from the docstring
# once classic drivers are gone
@task_manager.require_exclusive_lock
def node_set_boot_mode(task, mode):
    """Set the boot mode for a node.

    Sets the boot mode for a node if the node's driver interface
    contains a 'management' interface.

    If the node that the boot mode change is being requested for
    is in ADOPTING state, the boot mode will not be set as that
    change could potentially result in the future running state of
    an adopted node being modified erroneously.

    :param task: a TaskManager instance.
    :param mode: Boot mode. Values are one of
        :mod:`ironic.common.boot_modes`
    :raises: InvalidParameterValue if the validation of the
             ManagementInterface fails.
    :raises: DriverOperationError or its derivative in case
             of driver runtime error.
    :raises: UnsupportedDriverExtension if current driver does not have
             vendor interface or method is unsupported.
    """
    if task.node.provision_state == states.ADOPTING:
        return

    task.driver.management.validate(task)
    try:
        supported_boot_modes = (
            task.driver.management.get_supported_boot_modes(task)
        )
    except exception.UnsupportedDriverExtension:
        LOG.debug(
            "Cannot determine supported boot modes of driver "
            "%(driver)s. Will make an attempt to set boot mode %(mode)s",
            {'driver': task.node.driver, 'mode': mode})
        supported_boot_modes = ()

    if supported_boot_modes and mode not in supported_boot_modes:
        msg = _("Unsupported boot mode %(mode)s specified for "
                "node %(node_id)s. Supported boot modes are: "
                "%(modes)s") % {'mode': mode,
                                'modes': ', '.join(supported_boot_modes),
                                'node_id': task.node.uuid}
        raise exception.InvalidParameterValue(msg)

    task.driver.management.set_boot_mode(task, mode=mode)


def node_wait_for_power_state(task, new_state, timeout=None):
    """Wait for node to be in new power state.

    :param task: a TaskManager instance.
    :param new_state: the desired new power state, one of the power states
        in :mod:`ironic.common.states`.
    :param timeout: number of seconds to wait before giving up. If not
        specified, uses the conductor.power_state_change_timeout config value.
    :raises: PowerStateFailure if timed out
    """
    retry_timeout = (timeout or CONF.conductor.power_state_change_timeout)

    def _wait():
        status = task.driver.power.get_power_state(task)
        if status == new_state:
            raise loopingcall.LoopingCallDone(retvalue=status)
        # NOTE(sambetts): Return False to trigger BackOffLoopingCall to start
        # backing off.
        return False

    try:
        timer = loopingcall.BackOffLoopingCall(_wait)
        return timer.start(initial_delay=1, timeout=retry_timeout).wait()
    except loopingcall.LoopingCallTimeOut:
        LOG.error('Timed out after %(retry_timeout)s secs waiting for '
                  '%(state)s on node %(node_id)s.',
                  {'retry_timeout': retry_timeout,
                   'state': new_state, 'node_id': task.node.uuid})
        raise exception.PowerStateFailure(pstate=new_state)


def _calculate_target_state(new_state):
    if new_state in (states.POWER_ON, states.REBOOT, states.SOFT_REBOOT):
        target_state = states.POWER_ON
    elif new_state in (states.POWER_OFF, states.SOFT_POWER_OFF):
        target_state = states.POWER_OFF
    else:
        target_state = None
    return target_state


def _can_skip_state_change(task, new_state):
    """Check if we can ignore the power state change request for the node.

    Check if we should ignore the requested power state change. This can occur
    if the requested power state is already the same as our current state. This
    only works for power on and power off state changes. More complex power
    state changes, like reboot, are not skipped.

    :param task: a TaskManager instance containing the node to act on.
    :param new_state: The requested power state to change to. This can be any
                      power state from ironic.common.states.
    :returns: True if should ignore the requested power state change. False
              otherwise
    """
    # We only ignore certain state changes. So if the desired new_state is not
    # one of them, then we can return early and not do an un-needed
    # get_power_state() call
    if new_state not in (states.POWER_ON, states.POWER_OFF,
                         states.SOFT_POWER_OFF):
        return False

    node = task.node

    def _not_going_to_change():
        # Neither the ironic service nor the hardware has erred. The
        # node is, for some reason, already in the requested state,
        # though we don't know why. eg, perhaps the user previously
        # requested the node POWER_ON, the network delayed those IPMI
        # packets, and they are trying again -- but the node finally
        # responds to the first request, and so the second request
        # gets to this check and stops.
        # This isn't an error, so we'll clear last_error field
        # (from previous operation), log a warning, and return.
        node['last_error'] = None
        # NOTE(dtantsur): under rare conditions we can get out of sync here
        node['power_state'] = curr_state
        node['target_power_state'] = states.NOSTATE
        node.save()
        notify_utils.emit_power_set_notification(
            task, fields.NotificationLevel.INFO,
            fields.NotificationStatus.END, new_state)
        LOG.warning("Not going to change node %(node)s power state because "
                    "current state = requested state = '%(state)s'.",
                    {'node': node.uuid, 'state': curr_state})

    try:
        curr_state = task.driver.power.get_power_state(task)
    except Exception as e:
        with excutils.save_and_reraise_exception():
            error = _(
                "Failed to change power state to '%(target)s'. "
                "Error: %(error)s") % {'target': new_state, 'error': e}
            node_history_record(node, event=error, error=True)
            node['target_power_state'] = states.NOSTATE
            node.save()
            notify_utils.emit_power_set_notification(
                task, fields.NotificationLevel.ERROR,
                fields.NotificationStatus.ERROR, new_state)

    if curr_state == states.POWER_ON:
        if new_state == states.POWER_ON:
            _not_going_to_change()
            return True
    elif curr_state == states.POWER_OFF:
        if new_state in (states.POWER_OFF, states.SOFT_POWER_OFF):
            _not_going_to_change()
            return True

    LOG.info("Node %(node)s current power state is '%(state)s', "
             "requested state is '%(new_state)s'.",
             {'node': node.uuid, 'state': curr_state, 'new_state': new_state})
    return False


@task_manager.require_exclusive_lock
def node_power_action(task, new_state, timeout=None):
    """Change power state or reset for a node.

    Perform the requested power action if the transition is required.

    :param task: a TaskManager instance containing the node to act on.
    :param new_state: Any power state from ironic.common.states.
    :param timeout: timeout (in seconds) positive integer (> 0) for any
      power state. ``None`` indicates to use default timeout.
    :raises: InvalidParameterValue when the wrong state is specified
             or the wrong driver info is specified.
    :raises: StorageError when a failure occurs updating the node's
             storage interface upon setting power on.
    :raises: other exceptions by the node's power driver if something
             wrong occurred during the power action.

    """
    notify_utils.emit_power_set_notification(
        task, fields.NotificationLevel.INFO, fields.NotificationStatus.START,
        new_state)
    node = task.node

    if _can_skip_state_change(task, new_state):
        return
    target_state = _calculate_target_state(new_state)

    # Set the target_power_state and clear any last_error, if we're
    # starting a new operation. This will expose to other processes
    # and clients that work is in progress.
    node['target_power_state'] = target_state
    node['last_error'] = None
    driver_internal_info = node.driver_internal_info
    driver_internal_info['last_power_state_change'] = str(
        timeutils.utcnow().isoformat())
    node.driver_internal_info = driver_internal_info
    # NOTE(dtantsur): wipe token on shutting down, otherwise a reboot in
    # fast-track (or an accidentally booted agent) will cause subsequent
    # actions to fail.
    if new_state in (states.POWER_OFF, states.SOFT_POWER_OFF,
                     states.REBOOT, states.SOFT_REBOOT):
        wipe_internal_info_on_power_off(node)
    node.save()

    # take power action
    try:
        if (target_state == states.POWER_ON
                and node.provision_state == states.ACTIVE):
            task.driver.storage.attach_volumes(task)

        if new_state != states.REBOOT:
            task.driver.power.set_power_state(task, new_state, timeout=timeout)
        else:
            # TODO(TheJulia): We likely ought to consider toggling
            # volume attachments, although we have no mechanism to
            # really verify what cinder has connector wise.
            task.driver.power.reboot(task, timeout=timeout)
    except Exception as e:
        with excutils.save_and_reraise_exception():
            node['target_power_state'] = states.NOSTATE
            error = _(
                "Failed to change power state to '%(target_state)s' "
                "by '%(new_state)s'. Error: %(error)s") % {
                    'target_state': target_state,
                    'new_state': new_state,
                    'error': e}
            node_history_record(node, event=error, error=True)
            node.save()
            notify_utils.emit_power_set_notification(
                task, fields.NotificationLevel.ERROR,
                fields.NotificationStatus.ERROR, new_state)
    else:
        # success!
        node['power_state'] = target_state
        node['target_power_state'] = states.NOSTATE
        node.save()
        if node.instance_uuid:
            nova.power_update(
                task.context, node.instance_uuid, target_state)
        notify_utils.emit_power_set_notification(
            task, fields.NotificationLevel.INFO, fields.NotificationStatus.END,
            new_state)
        LOG.info('Successfully set node %(node)s power state to '
                 '%(target_state)s by %(new_state)s.',
                 {'node': node.uuid,
                  'target_state': target_state,
                  'new_state': new_state})
        # NOTE(TheJulia): Similarly to power-on, when we power-off
        # a node, we should detach any volume attachments.
        if (target_state == states.POWER_OFF
                and node.provision_state == states.ACTIVE):
            try:
                task.driver.storage.detach_volumes(task)
            except exception.StorageError as e:
                LOG.warning("Volume detachment for node %(node)s "
                            "failed. Error: %(error)s",
                            {'node': node.uuid, 'error': e})


@task_manager.require_exclusive_lock
def cleanup_after_timeout(task):
    """Cleanup deploy task after timeout.

    :param task: a TaskManager instance.
    """
    msg = (_('Timeout reached while waiting for callback for node %s')
           % task.node.uuid)
    deploying_error_handler(task, msg, msg)


def provisioning_error_handler(e, node, provision_state,
                               target_provision_state):
    """Set the node's provisioning states if error occurs.

    This hook gets called upon an exception being raised when spawning
    the worker to do some provisioning to a node like deployment, tear down,
    or cleaning.

    :param e: the exception object that was raised.
    :param node: an Ironic node object.
    :param provision_state: the provision state to be set on
        the node.
    :param target_provision_state: the target provision state to be
        set on the node.

    """
    if isinstance(e, exception.NoFreeConductorWorker):
        # NOTE(tenbrae): there is no need to clear conductor_affinity
        #             because it isn't updated on a failed deploy
        node.provision_state = provision_state
        node.target_provision_state = target_provision_state
        error = (_("No free conductor workers available"))
        node_history_record(node, event=error, event_type=states.PROVISIONING,
                            error=True)
        node.save()
        LOG.warning("No free conductor workers available to perform "
                    "an action on node %(node)s, setting node's "
                    "provision_state back to %(prov_state)s and "
                    "target_provision_state to %(tgt_prov_state)s.",
                    {'node': node.uuid, 'prov_state': provision_state,
                     'tgt_prov_state': target_provision_state})


def cleanup_cleanwait_timeout(task):
    """Cleanup a cleaning task after timeout.

    :param task: a TaskManager instance.
    """
    last_error = (_("Timeout reached while cleaning the node. Please "
                    "check if the ramdisk responsible for the cleaning is "
                    "running on the node. Failed on step %(step)s.") %
                  {'step': task.node.clean_step})
    logmsg = ("Cleaning for node %(node)s failed. %(error)s" %
              {'node': task.node.uuid, 'error': last_error})
    # NOTE(rloo): this is called from the periodic task for cleanwait timeouts,
    # via the task manager's process_event(). The node has already been moved
    # to CLEANFAIL, so the error handler doesn't need to set the fail state.
    cleaning_error_handler(task, logmsg, errmsg=last_error,
                           set_fail_state=False)


def cleaning_error_handler(task, logmsg, errmsg=None, traceback=False,
                           tear_down_cleaning=True, set_fail_state=True,
                           set_maintenance=None):
    """Put a failed node in CLEANFAIL and maintenance (if needed).

    :param task: a TaskManager instance.
    :param logmsg: Message to be logged.
    :param errmsg: Message for the user. Optional, if not provided `logmsg` is
        used.
    :param traceback: Whether to log a traceback. Defaults to False.
    :param tear_down_cleaning: Whether to clean up the PXE and DHCP files after
        cleaning. Default to True.
    :param set_fail_state: Whether to set node to failed state. Default to
        True.
    :param set_maintenance: Whether to set maintenance mode. If None,
        maintenance mode will be set if and only if a clean step is being
        executed on a node.
    """
    if set_maintenance is None:
        set_maintenance = bool(task.node.clean_step)

    errmsg = errmsg or logmsg
    LOG.error(logmsg, exc_info=traceback)
    node = task.node
    if set_maintenance:
        node.fault = faults.CLEAN_FAILURE
        node.maintenance = True

    if tear_down_cleaning:
        try:
            task.driver.deploy.tear_down_cleaning(task)
        except Exception as e:
            msg2 = ('Failed to tear down cleaning on node %(uuid)s, '
                    'reason: %(err)s' % {'err': e, 'uuid': node.uuid})
            LOG.exception(msg2)
            errmsg = _('%s. Also failed to tear down cleaning.') % errmsg

    if node.provision_state in (
            states.CLEANING,
            states.CLEANWAIT,
            states.CLEANFAIL):
        # Clear clean step, msg should already include current step
        node.clean_step = {}
        info = node.driver_internal_info
        # Clear any leftover metadata about cleaning
        info.pop('clean_step_index', None)
        info.pop('cleaning_reboot', None)
        info.pop('cleaning_polling', None)
        info.pop('skip_current_clean_step', None)
        # We don't need to keep the old agent URL
        # as it should change upon the next cleaning attempt.
        info.pop('agent_url', None)
        node.driver_internal_info = info
    # For manual cleaning, the target provision state is MANAGEABLE, whereas
    # for automated cleaning, it is AVAILABLE.
    manual_clean = node.target_provision_state == states.MANAGEABLE
    node_history_record(node, event=errmsg, event_type=states.CLEANING,
                        error=True)
    # NOTE(dtantsur): avoid overwriting existing maintenance_reason
    if not node.maintenance_reason and set_maintenance:
        node.maintenance_reason = errmsg
    node.save()

    if set_fail_state and node.provision_state != states.CLEANFAIL:
        target_state = states.MANAGEABLE if manual_clean else None
        task.process_event('fail', target_state=target_state)


def wipe_internal_info_on_power_off(node):
    """Wipe information that should not survive reboot/power off."""
    driver_internal_info = node.driver_internal_info
    # DHCP may result in a new IP next time.
    driver_internal_info.pop('agent_url', None)
    if not is_agent_token_pregenerated(node):
        # Wipe the token if it's not pre-generated, otherwise we'll refuse to
        # generate it again for the newly booted agent.
        driver_internal_info.pop('agent_secret_token', False)
    # Wipe cached steps since they may change after reboot.
    driver_internal_info.pop('agent_cached_deploy_steps', None)
    driver_internal_info.pop('agent_cached_clean_steps', None)
    # Remove TLS certificate since it's regenerated on each run.
    driver_internal_info.pop('agent_verify_ca', None)
    node.driver_internal_info = driver_internal_info


def wipe_token_and_url(task):
    """Remove agent URL and token from the task."""
    info = task.node.driver_internal_info
    info.pop('agent_secret_token', None)
    info.pop('agent_secret_token_pregenerated', None)
    # Remove agent_url since it will be re-asserted
    # upon the next deployment attempt.
    info.pop('agent_url', None)
    # Remove TLS certificate since it's regenerated on each run.
    info.pop('agent_verify_ca', None)
    task.node.driver_internal_info = info


def wipe_deploy_internal_info(task):
    """Remove temporary deployment fields from driver_internal_info."""
    if not fast_track_able(task):
        wipe_token_and_url(task)
    # Clear any leftover metadata about deployment.
    info = task.node.driver_internal_info
    info['deploy_steps'] = None
    info.pop('user_deploy_steps', None)
    info.pop('agent_cached_deploy_steps', None)
    info.pop('deploy_step_index', None)
    info.pop('deployment_reboot', None)
    info.pop('deployment_polling', None)
    info.pop('skip_current_deploy_step', None)
    info.pop('steps_validated', None)
    task.node.driver_internal_info = info


def wipe_cleaning_internal_info(task):
    """Remove temporary cleaning fields from driver_internal_info."""
    if not fast_track_able(task):
        wipe_token_and_url(task)
    info = task.node.driver_internal_info
    info['clean_steps'] = None
    info.pop('agent_cached_clean_steps', None)
    info.pop('clean_step_index', None)
    info.pop('cleaning_reboot', None)
    info.pop('cleaning_polling', None)
    info.pop('cleaning_disable_ramdisk', None)
    info.pop('skip_current_clean_step', None)
    info.pop('steps_validated', None)
    task.node.driver_internal_info = info


def deploying_error_handler(task, logmsg, errmsg=None, traceback=False,
                            clean_up=True):
    """Put a failed node in DEPLOYFAIL.

    :param task: the task
    :param logmsg: message to be logged
    :param errmsg: message for the user
    :param traceback: Boolean; True to log a traceback
    :param clean_up: Boolean; True to clean up
    """
    errmsg = errmsg or logmsg
    node = task.node
    LOG.error(logmsg, exc_info=traceback)
    node_history_record(node, event=errmsg, event_type=states.DEPLOYING,
                        error=True)
    node.save()

    cleanup_err = None
    if clean_up:
        try:
            task.driver.deploy.clean_up(task)
        except Exception as e:
            msg = ('Cleanup failed for node %(node)s; reason: %(err)s'
                   % {'node': node.uuid, 'err': e})
            LOG.exception(msg)
            if isinstance(e, exception.IronicException):
                addl = _('Also failed to clean up due to: %s') % e
            else:
                addl = _('An unhandled exception was encountered while '
                         'aborting. More information may be found in the log '
                         'file.')
            cleanup_err = '%(err)s. %(add)s' % {'err': errmsg, 'add': addl}

    node.refresh()
    if node.provision_state in (
            states.DEPLOYING,
            states.DEPLOYWAIT,
            states.DEPLOYFAIL):
        # Clear deploy step; we leave the list of deploy steps
        # in node.driver_internal_info for debugging purposes.
        node.deploy_step = {}
        wipe_deploy_internal_info(task)

    if cleanup_err:
        node_history_record(node, event=cleanup_err,
                            event_type=states.DEPLOYING,
                            error=True)
    node.save()

    # NOTE(tenbrae): there is no need to clear conductor_affinity
    task.process_event('fail')


def fail_on_error(error_callback, msg, *error_args, **error_kwargs):
    """A decorator for failing operation on failure."""
    def wrapper(func):
        @functools.wraps(func)
        def wrapped(task, *args, **kwargs):
            try:
                return func(task, *args, **kwargs)
            except Exception as exc:
                errmsg = "%s. %s: %s" % (msg, exc.__class__.__name__, exc)
                error_callback(task, errmsg, *error_args, **error_kwargs)

        return wrapped
    return wrapper


def verifying_error_handler(task, logmsg, errmsg=None, traceback=False):

    """Handle errors during verification steps

    :param task: the task
    :param logmsg: message to be logged
    :param errmsg: message for the user
    :param traceback: Boolean; True to log a traceback
    """
    errmsg = errmsg or logmsg
    node = task.node
    LOG.error(logmsg, exc_info=traceback)
    node_history_record(node, event=errmsg, event_type=states.VERIFYING,
                        error=True)
    node.save()

    node.refresh()
    if node.provision_state in (
            states.VERIFYING):
        # Clear verifying step; we leave the list of verify steps
        # in node.driver_internal_info for debugging purposes.
        node.verify_step = {}

    node.save()


@task_manager.require_exclusive_lock
def abort_on_conductor_take_over(task):
    """Set node's state when a task was aborted due to conductor take over.

    :param task: a TaskManager instance.
    """
    msg = _('Operation was aborted due to conductor take over')
    # By this time the "fail" even was processed, so we cannot end up in
    # CLEANING or CLEAN WAIT, only in CLEAN FAIL.
    if task.node.provision_state == states.CLEANFAIL:
        cleaning_error_handler(task, msg, set_fail_state=False)
    else:
        # For aborted deployment (and potentially other operations), just set
        # the last_error accordingly.
        node_history_record(task.node, event=msg, event_type=states.TAKEOVER,
                            error=True)
        task.node.save()

    LOG.warning('Aborted the current operation on node %s due to '
                'conductor take over', task.node.uuid)


def rescuing_error_handler(task, msg, set_fail_state=True):
    """Cleanup rescue task after timeout or failure.

    :param task: a TaskManager instance.
    :param msg: a message to set into node's last_error field
    :param set_fail_state: a boolean flag to indicate if node needs to be
                           transitioned to a failed state. By default node
                           would be transitioned to a failed state.
    """
    node = task.node
    try:
        node_power_action(task, states.POWER_OFF)
        task.driver.rescue.clean_up(task)
        remove_agent_url(node)
        node_history_record(task.node, event=msg, event_type=states.RESCUE,
                            error=True)
    except exception.IronicException as e:
        error = (_('Rescue operation was unsuccessful, clean up '
                   'failed for node: %(error)s') % {'error': e})
        node_history_record(task.node, event=error, event_type=states.RESCUE,
                            error=True)
        LOG.error(('Rescue operation was unsuccessful, clean up failed for '
                   'node %(node)s: %(error)s'),
                  {'node': node.uuid, 'error': e})
    except Exception as e:
        error = (_('Rescue failed, but an unhandled exception was '
                   'encountered while aborting: %(error)s') %
                 {'error': e})
        node_history_record(task.node, event=error, event_type=states.RESCUE,
                            error=True)
        LOG.exception('Rescue failed for node %(node)s, an exception was '
                      'encountered while aborting.', {'node': node.uuid})
    finally:
        remove_agent_url(node)
        node.save()

    if set_fail_state:
        try:
            task.process_event('fail')
        except exception.InvalidState:
            node = task.node
            LOG.error('Internal error. Node %(node)s in provision state '
                      '"%(state)s" could not transition to a failed state.',
                      {'node': node.uuid, 'state': node.provision_state})


@task_manager.require_exclusive_lock
def cleanup_rescuewait_timeout(task):
    """Cleanup rescue task after timeout.

    :param task: a TaskManager instance.
    """
    msg = _('Timeout reached while waiting for rescue ramdisk callback '
            'for node')
    errmsg = msg + ' %(node)s'
    LOG.error(errmsg, {'node': task.node.uuid})
    rescuing_error_handler(task, msg, set_fail_state=False)


def _spawn_error_handler(e, node, operation):
    """Handle error while trying to spawn a process.

    Handle error while trying to spawn a process to perform an
    operation on a node.

    :param e: the exception object that was raised.
    :param node: an Ironic node object.
    :param operation: the operation being performed on the node.
    """
    if isinstance(e, exception.NoFreeConductorWorker):
        error = (_("No free conductor workers available"))
        node_history_record(node, event=error, event_type=states.CONDUCTOR,
                            error=True)
        node.save()
        LOG.warning("No free conductor workers available to perform "
                    "%(operation)s on node %(node)s",
                    {'operation': operation, 'node': node.uuid})


def spawn_cleaning_error_handler(e, node):
    """Handle spawning error for node cleaning."""
    _spawn_error_handler(e, node, states.CLEANING)


def spawn_deploying_error_handler(e, node):
    """Handle spawning error for node deploying."""
    _spawn_error_handler(e, node, states.DEPLOYING)


def spawn_rescue_error_handler(e, node):
    """Handle spawning error for node rescue."""
    if isinstance(e, exception.NoFreeConductorWorker):
        remove_node_rescue_password(node, save=False)
    _spawn_error_handler(e, node, states.RESCUE)


def power_state_error_handler(e, node, power_state):
    """Set the node's power states if error occurs.

    This hook gets called upon an exception being raised when spawning
    the worker thread to change the power state of a node.

    :param e: the exception object that was raised.
    :param node: an Ironic node object.
    :param power_state: the power state to set on the node.

    """
    # NOTE This error will not emit a power state change notification since
    # this is related to spawning the worker thread, not the power state change
    # itself.
    if isinstance(e, exception.NoFreeConductorWorker):
        node.power_state = power_state
        node.target_power_state = states.NOSTATE
        error = (_("No free conductor workers available"))
        node_history_record(node, event=error, event_type=states.CONDUCTOR,
                            error=True)
        node.save()
        LOG.warning("No free conductor workers available to perform "
                    "an action on node %(node)s, setting node's "
                    "power state back to %(power_state)s.",
                    {'node': node.uuid, 'power_state': power_state})


@task_manager.require_exclusive_lock
def validate_port_physnet(task, port_obj):
    """Validate the consistency of physical networks of ports in a portgroup.

    Validate the consistency of a port's physical network with other ports in
    the same portgroup.  All ports in a portgroup should have the same value
    (which may be None) for their physical_network field.

    During creation or update of a port in a portgroup we apply the
    following validation criteria:

    - If the portgroup has existing ports with different physical networks, we
      raise PortgroupPhysnetInconsistent. This shouldn't ever happen.
    - If the port has a physical network that is inconsistent with other
      ports in the portgroup, we raise exception.Conflict.

    If a port's physical network is None, this indicates that ironic's VIF
    attachment mapping algorithm should operate in a legacy (physical
    network unaware) mode for this port or portgroup. This allows existing
    ironic nodes to continue to function after an upgrade to a release
    including physical network support.

    :param task: a TaskManager instance
    :param port_obj: a port object to be validated.
    :raises: Conflict if the port is a member of a portgroup which is on a
             different physical network.
    :raises: PortgroupPhysnetInconsistent if the port's portgroup has
             ports which are not all assigned the same physical network.
    """
    if 'portgroup_id' not in port_obj or not port_obj.portgroup_id:
        return

    delta = port_obj.obj_what_changed()
    # We can skip this step if the port's portgroup membership or physical
    # network assignment is not being changed (during creation these will
    # appear changed).
    if not (delta & {'portgroup_id', 'physical_network'}):
        return

    # Determine the current physical network of the portgroup.
    pg_physnets = network.get_physnets_by_portgroup_id(task,
                                                       port_obj.portgroup_id,
                                                       exclude_port=port_obj)

    if not pg_physnets:
        return

    # Check that the port has the same physical network as any existing
    # member ports.
    pg_physnet = pg_physnets.pop()
    port_physnet = (port_obj.physical_network
                    if 'physical_network' in port_obj else None)
    if port_physnet != pg_physnet:
        portgroup = network.get_portgroup_by_id(task, port_obj.portgroup_id)
        msg = _("Port with physical network %(physnet)s cannot become a "
                "member of port group %(portgroup)s which has ports in "
                "physical network %(pg_physnet)s.")
        raise exception.Conflict(
            msg % {'portgroup': portgroup.uuid, 'physnet': port_physnet,
                   'pg_physnet': pg_physnet})


def remove_node_rescue_password(node, save=True):
    """Helper to remove rescue password from a node.

    Removes rescue password from node. It saves node by default.
    If node should not be saved, then caller needs to explicitly
    indicate it.

    :param node: an Ironic node object.
    :param save: Boolean; True (default) to save the node; False
                 otherwise.
    """
    instance_info = node.instance_info
    if 'rescue_password' in instance_info:
        del instance_info['rescue_password']

    if 'hashed_rescue_password' in instance_info:
        del instance_info['hashed_rescue_password']

    node.instance_info = instance_info
    if save:
        node.save()


def validate_instance_info_traits(node):
    """Validate traits in instance_info.

    All traits in instance_info must also exist as node traits.

    :param node: an Ironic node object.
    :raises: InvalidParameterValue if the instance traits are badly formatted,
        or contain traits that are not set on the node.
    """

    def invalid():
        err = (_("Error parsing traits from Node %(node)s instance_info "
                 "field. A list of strings is expected.")
               % {"node": node.uuid})
        raise exception.InvalidParameterValue(err)

    if not node.instance_info.get('traits'):
        return
    instance_traits = node.instance_info['traits']
    if not isinstance(instance_traits, list):
        invalid()
    if not all(isinstance(t, str) for t in instance_traits):
        invalid()

    node_traits = node.traits.get_trait_names()
    missing = set(instance_traits) - set(node_traits)
    if missing:
        err = (_("Cannot specify instance traits that are not also set on the "
                 "node. Node %(node)s is missing traits %(traits)s") %
               {"node": node.uuid, "traits": ", ".join(missing)})
        raise exception.InvalidParameterValue(err)


def notify_conductor_resume_operation(task, operation):
    """Notify the conductor to resume an operation.

    :param task: the task
    :param operation: the operation, a string
    """
    LOG.debug('Sending RPC to conductor to resume %(op)s steps for node '
              '%(node)s', {'op': operation, 'node': task.node.uuid})
    method = 'continue_node_%s' % operation
    from ironic.conductor import rpcapi
    uuid = task.node.uuid
    rpc = rpcapi.ConductorAPI()
    topic = rpc.get_current_topic()
    # Need to release the lock to let the conductor take it
    task.release_resources()
    getattr(rpc, method)(task.context, uuid, topic=topic)


def notify_conductor_resume_clean(task):
    notify_conductor_resume_operation(task, 'clean')


def notify_conductor_resume_deploy(task):
    notify_conductor_resume_operation(task, 'deploy')


def skip_automated_cleaning(node):
    """Checks if node cleaning needs to be skipped for an specific node.

    :param node: the node to consider
    """
    if node.automated_clean:
        return False
    elif node.automated_clean is None:
        return not CONF.conductor.automated_clean
    else:
        LOG.info("Automated cleaning is disabled via the API for "
                 "node %(node)s",
                 {'node': node.uuid})
        return True


def power_on_node_if_needed(task):
    """Powers on node if it is powered off and has a Smart NIC port

    :param task: A TaskManager object
    :returns: the previous power state or None if no changes were made
    :raises: exception.NetworkError if agent status didn't match the required
        status after max retry attempts.
    """
    if not task.driver.network.need_power_on(task):
        return

    previous_power_state = task.driver.power.get_power_state(task)
    if previous_power_state == states.POWER_OFF:
        node_set_boot_device(
            task, boot_devices.BIOS, persistent=False)
        node_power_action(task, states.POWER_ON)

        # local import is necessary to avoid circular import
        from ironic.common import neutron

        host_id = None
        for port in task.ports:
            if neutron.is_smartnic_port(port):
                link_info = port.local_link_connection
                host_id = link_info['hostname']
                break

        if host_id:
            LOG.debug('Waiting for host %(host)s agent to be down',
                      {'host': host_id})

            client = neutron.get_client(context=task.context)
            neutron.wait_for_host_agent(
                client, host_id, target_state='down')
        return previous_power_state


def restore_power_state_if_needed(task, power_state_to_restore):
    """Change the node's power state if power_state_to_restore is not None

    :param task: A TaskManager object
    :param power_state_to_restore: power state
    """
    if power_state_to_restore:

        # Sleep is required here in order to give neutron agent
        # a chance to apply the changes before powering off.
        # Using twice the polling interval of the agent
        # "CONF.AGENT.polling_interval" would give the agent
        # enough time to apply network changes.
        time.sleep(CONF.agent.neutron_agent_poll_interval * 2)
        node_power_action(task, power_state_to_restore)


@contextlib.contextmanager
def power_state_for_network_configuration(task):
    """Handle the power state for a node reconfiguration.

    Powers the node on if and only if it has a Smart NIC port. Yields for
    the actual reconfiguration, then restores the power state.

    :param task: A TaskManager object.
    """
    previous = power_on_node_if_needed(task)
    yield task
    restore_power_state_if_needed(task, previous)


def build_configdrive(node, configdrive):
    """Build a configdrive from provided meta_data, network_data and user_data.

    If uuid or name are not provided in the meta_data, they're defauled to the
    node's uuid and name accordingly.

    :param node: an Ironic node object.
    :param configdrive: A configdrive as a dict with keys ``meta_data``,
        ``network_data``, ``user_data`` and ``vendor_data`` (all optional).
    :returns: A gzipped and base64 encoded configdrive as a string.
    """
    meta_data = configdrive.setdefault('meta_data', {})
    meta_data.setdefault('uuid', node.uuid)
    if node.name:
        meta_data.setdefault('name', node.name)

    user_data = configdrive.get('user_data')
    if isinstance(user_data, (dict, list)):
        user_data = jsonutils.dump_as_bytes(user_data)
    elif user_data:
        user_data = user_data.encode('utf-8')

    LOG.debug('Building a configdrive for node %s', node.uuid)
    return os_configdrive.build(meta_data, user_data=user_data,
                                network_data=configdrive.get('network_data'),
                                vendor_data=configdrive.get('vendor_data'))


def get_configdrive_image(node):
    """Get configdrive as an ISO image or a URL.

    Converts the JSON representation into an image. URLs and raw contents
    are returned unchanged.

    :param node: an Ironic node object.
    :returns: A gzipped and base64 encoded configdrive as a string.
    """
    configdrive = node.instance_info.get('configdrive')
    if isinstance(configdrive, dict):
        configdrive = build_configdrive(node, configdrive)
    return configdrive


def fast_track_able(task):
    """Checks if the operation can be a streamlined deployment sequence.

    This is mainly focused on ensuring that we are able to quickly sequence
    through operations if we already have a ramdisk heartbeating through
    external means.

    :param task: Taskmanager object
    :returns: True if [deploy]fast_track is set to True, no iSCSI boot
              configuration is present, and no last_error is present for
              the node indicating that there was a recent failure.
    """
    return (CONF.deploy.fast_track
            # TODO(TheJulia): Network model aside, we should be able to
            # fast-track through initial sequence to complete deployment.
            # This needs to be validated.
            # TODO(TheJulia): Do we need a secondary guard? To prevent
            # driving through this we could query the API endpoint of
            # the agent with a short timeout such as 10 seconds, which
            # would help verify if the node is online.
            # TODO(TheJulia): Should we check the provisioning/deployment
            # networks match config wise? Do we care? #decisionsdecisions
            and task.driver.storage.should_write_image(task)
            and task.node.last_error is None)


def value_within_timeout(value, timeout):
    """Checks if the time is within the previous timeout seconds from now.

    :param value: a string representing date and time or None.
    :param timeout: timeout in seconds.
    """
    # use native datetime objects for conversion and compare
    # slightly odd because py2 compatability :(
    last = datetime.datetime.strptime(value or '1970-01-01T00:00:00.000000',
                                      "%Y-%m-%dT%H:%M:%S.%f")
    # If we found nothing, we assume that the time is essentially epoch.
    time_delta = datetime.timedelta(seconds=timeout)
    last_valid = timeutils.utcnow() - time_delta
    return last_valid <= last


def agent_is_alive(node, timeout=None):
    """Check that the agent is likely alive.

    The method then checks for the last agent heartbeat, and if it occured
    within the timeout set by [deploy]fast_track_timeout, then agent is
    presumed alive.

    :param node: A node object.
    :param timeout: Heartbeat timeout, defaults to `fast_track_timeout`.
    """
    # If no agent_url is present then we have powered down since the
    # last agent heartbeat
    if not node.driver_internal_info.get('agent_url'):
        return False

    return value_within_timeout(
        node.driver_internal_info.get('agent_last_heartbeat'),
        timeout or CONF.deploy.fast_track_timeout)


def is_fast_track(task):
    """Checks a fast track is available.

    This method first ensures that the node and conductor configuration
    is valid to perform a fast track sequence meaning that we already
    have a ramdisk running through another means like discovery.
    If not valid, False is returned.

    The method then checks for the last agent heartbeat, and if it occured
    within the timeout set by [deploy]fast_track_timeout and the power
    state for the machine is POWER_ON, then fast track is permitted.

    :param task: Taskmanager object
    :returns: True if the last heartbeat that was recorded was within
              the [deploy]fast_track_timeout setting.
    """
    if (not fast_track_able(task)
            or task.driver.power.get_power_state(task) != states.POWER_ON):
        if task.node.last_error:
            LOG.debug('Node %(node)s is not fast-track-able because it has '
                      'an error: %(error)s',
                      {'node': task.node.uuid, 'error': task.node.last_error})
        return False

    if agent_is_alive(task.node):
        return True
    else:
        LOG.debug('Node %(node)s should be fast-track-able, but the agent '
                  'doesn\'t seem to be running. Last heartbeat: %(last)s',
                  {'node': task.node.uuid,
                   'last': task.node.driver_internal_info.get(
                       'agent_last_heartbeat')})
        return False


def remove_agent_url(node):
    """Helper to remove the agent_url record."""
    info = node.driver_internal_info
    info.pop('agent_url', None)
    node.driver_internal_info = info


def _get_node_next_steps(task, step_type, skip_current_step=True):
    """Get the task's node's next steps.

    This determines what the next (remaining) steps are, and
    returns the index into the steps list that corresponds to the
    next step. The remaining steps are determined as follows:

    * If no steps have been started yet, all the steps
      must be executed
    * If skip_current_step is False, the remaining steps start
      with the current step. Otherwise, the remaining steps
      start with the step after the current one.

    All the steps are in node.driver_internal_info['<step_type>_steps'].
    node.<step_type>_step is the current step that was just executed
    (or None, {} if no steps have been executed yet).
    node.driver_internal_info['<step_type>_step_index'] is the index
    index into the steps list (or None, doesn't exist if no steps have
    been executed yet) and corresponds to node.<step_type>_step.

    :param task: A TaskManager object
    :param step_type: The type of steps to process: 'clean' or 'deploy'.
    :param skip_current_step: True to skip the current step; False to
                              include it.
    :returns: index of the next step; None if there are none to execute.

    """
    valid_types = set(['clean', 'deploy'])
    if step_type not in valid_types:
        # NOTE(rloo): No need to i18n this, since this would be a
        # developer error; it isn't user-facing.
        raise exception.Invalid(
            'step_type must be one of %(valid)s, not %(step)s'
            % {'valid': valid_types, 'step': step_type})
    node = task.node
    if not getattr(node, '%s_step' % step_type):
        # first time through, all steps need to be done. Return the
        # index of the first step in the list.
        return 0

    ind = node.driver_internal_info.get('%s_step_index' % step_type)
    if ind is None:
        return None

    if skip_current_step:
        ind += 1
    if ind >= len(node.driver_internal_info['%s_steps' % step_type]):
        # no steps left to do
        ind = None
    return ind


def get_node_next_clean_steps(task, skip_current_step=True):
    return _get_node_next_steps(task, 'clean',
                                skip_current_step=skip_current_step)


def get_node_next_deploy_steps(task, skip_current_step=True):
    return _get_node_next_steps(task, 'deploy',
                                skip_current_step=skip_current_step)


def update_next_step_index(task, step_type):
    """Calculate the next step index and update the node.

    :param task: A TaskManager object
    :param step_type: The type of steps to process: 'clean' or 'deploy'.
    :returns: Index of the next step.
    """
    info = task.node.driver_internal_info
    save_required = False

    try:
        skip_current_step = info.pop('skip_current_%s_step' % step_type)
    except KeyError:
        skip_current_step = True
    else:
        save_required = True

    field = ('cleaning_polling' if step_type == 'clean'
             else 'deployment_polling')
    if info.pop(field, None) is not None:
        save_required = True

    if save_required:
        task.node.driver_internal_info = info
        task.node.save()

    return _get_node_next_steps(task, step_type,
                                skip_current_step=skip_current_step)


def add_secret_token(node, pregenerated=False):
    """Adds a secret token to driver_internal_info for IPA verification.

    :param node: Node object
    :param pregenerated: Boolean value, default False, which indicates if
                         the token should be marked as "pregenerated" in
                         order to facilitate virtual media booting where
                         the token is embedded into the configuration.
    """
    token = secrets.token_urlsafe()
    i_info = node.driver_internal_info
    i_info['agent_secret_token'] = token
    if pregenerated:
        i_info['agent_secret_token_pregenerated'] = True
    else:
        i_info.pop('agent_secret_token_pregenerated', None)
    node.driver_internal_info = i_info


def is_agent_token_present(node):
    """Determines if an agent token is present upon a node.

    :param node: Node object
    :returns: True if an agent_secret_token value is present in a node
              driver_internal_info field.
    """
    # TODO(TheJulia): we should likely record the time when we add the token
    # and then compare if it was in the last ?hour? to act as an additional
    # guard rail, but if we do that we will want to check the last heartbeat
    # because the heartbeat overrides the age of the token.
    # We may want to do this elsewhere or nowhere, just a thought for the
    # future.
    return node.driver_internal_info.get(
        'agent_secret_token', None) is not None


def is_agent_token_valid(node, token):
    """Validates if a supplied token is valid for the node.

    :param node: Node object
    :param token: A token value to validate against the driver_internal_info
                  field agent_secret_token.
    :returns: True if the supplied token matches the token recorded in the
              supplied node object.
    """
    if token is None:
        # No token is never valid.
        return False
    known_token = node.driver_internal_info.get('agent_secret_token', None)
    return known_token == token


def is_agent_token_pregenerated(node):
    """Determines if the token was generated for out of band configuration.

    Ironic supports the ability to provide configuration data to the agent
    through the a virtual floppy or as part of the virtual media image
    which is attached to the BMC.

    This method helps us identify WHEN we did so as we don't need to remove
    records of the token prior to rebooting the token. This is important as
    tokens provided through out of band means presist in the virtual media
    image, are loaded as part of the agent ramdisk, and do not require
    regeneration of the token upon the initial lookup, ultimately making
    the overall usage of virtual media and pregenerated tokens far more
    secure.

    :param node: Node Object
    :returns: True if the token was pregenerated as indicated by the node's
              driver_internal_info field.
              False in all other cases.
    """
    return node.driver_internal_info.get(
        'agent_secret_token_pregenerated', False)


def make_salt():
    """Generate a random salt with the indicator tag for password type.

    :returns: a valid salt for use with crypt.crypt
    """
    return crypt.mksalt(
        method=PASSWORD_HASH_FORMAT[
            CONF.conductor.rescue_password_hash_algorithm])


def hash_password(password=''):
    """Hashes a supplied password.

    :param password: password to be hashed
    """
    return crypt.crypt(password, make_salt())


def get_attached_vif(port):
    """Get any attached vif ID for the port

    :param port: The port object upon which to check for a vif
                 record.
    :returns: Returns a tuple of the vif if found and the use of
              the vif in the form of a string, 'tenant', 'cleaning'
              'provisioning', 'rescuing'.
    :raises: InvalidState exception upon finding a port with a
             transient state vif on the port.
    """

    tenant_vif = port.internal_info.get('tenant_vif_port_id')
    if tenant_vif:
        return (tenant_vif, 'tenant')
    clean_vif = port.internal_info.get('cleaning_vif_port_id')
    if clean_vif:
        return (clean_vif, 'cleaning')
    prov_vif = port.internal_info.get('provisioning_vif_port_id')
    if prov_vif:
        return (prov_vif, 'provisioning')
    rescue_vif = port.internal_info.get('rescuing_vif_port_id')
    if rescue_vif:
        return (rescue_vif, 'rescuing')
    inspection_vif = port.internal_info.get('inspection_vif_port_id')
    if inspection_vif:
        return (inspection_vif, 'inspecting')
    return (None, None)


def store_agent_certificate(node, agent_verify_ca):
    """Store certificate received from the agent and return its path."""
    existing_verify_ca = node.driver_internal_info.get(
        'agent_verify_ca')
    if existing_verify_ca:
        if os.path.exists(existing_verify_ca):
            try:
                with open(existing_verify_ca, 'rt') as fp:
                    existing_text = fp.read()
            except EnvironmentError:
                with excutils.save_and_reraise_exception():
                    LOG.exception('Could not read the existing TLS certificate'
                                  ' for node %s', node.uuid)

            if existing_text.strip() != agent_verify_ca.strip():
                LOG.error('Content mismatch for agent_verify_ca for '
                          'node %s', node.uuid)
                raise exception.InvalidParameterValue(
                    _('Detected change in ramdisk provided "agent_verify_ca"'))
            else:
                return existing_verify_ca
        else:
            LOG.info('Current agent_verify_ca was not found for node '
                     '%s, assuming take over and storing', node.uuid)

    fname = os.path.join(CONF.agent.certificates_path, '%s.crt' % node.uuid)
    try:
        # FIXME(dtantsur): it makes more sense to create this path on conductor
        # start-up, but it requires reworking a ton of unit tests.
        os.makedirs(CONF.agent.certificates_path, exist_ok=True)
        with open(fname, 'wt') as fp:
            fp.write(agent_verify_ca)
    except EnvironmentError:
        with excutils.save_and_reraise_exception():
            LOG.exception('Could not save the TLS certificate for node %s',
                          node.uuid)
    else:
        LOG.debug('Saved the custom certificate for node %(node)s to %(file)s',
                  {'node': node.uuid, 'file': fname})
        return fname


def node_cache_bios_settings(task, node):
    """Do caching of bios settings if supported by driver"""
    try:
        LOG.debug('Getting BIOS info for node %s', node.uuid)
        task.driver.bios.cache_bios_settings(task)
    except exception.UnsupportedDriverExtension:
        LOG.warning('BIOS settings are not supported for node %s, '
                    'skipping', node.uuid)
    # TODO(zshi) remove this check when classic drivers are removed
    except Exception:
        msg = (_('Caching of bios settings failed on node %(node)s.')
               % {'node': node.uuid})
        LOG.exception(msg)


def node_cache_vendor(task):
    """Cache the vendor if it can be detected."""
    properties = task.node.properties
    if properties.get('vendor'):
        return  # assume that vendors don't change on fly

    try:
        # We have no vendor stored, so we'll go ahead and
        # call to store it.
        vendor = task.driver.management.detect_vendor(task)
        if not vendor:
            return

        # This function may be called without an exclusive lock, so get one
        task.upgrade_lock(purpose='caching node vendor')
    except exception.UnsupportedDriverExtension:
        return
    except Exception as exc:
        LOG.warning('Unexpected exception when trying to detect vendor '
                    'for node %(node)s. %(class)s: %(exc)s',
                    {'node': task.node.uuid,
                     'class': type(exc).__name__, 'exc': exc},
                    exc_info=not isinstance(exc, exception.IronicException))
        return

    props = task.node.properties
    props['vendor'] = vendor
    task.node.properties = props
    task.node.save()
    LOG.info("Detected vendor %(vendor)s for node %(node)s",
             {'vendor': vendor, 'node': task.node.uuid})


def node_cache_boot_mode(task):
    """Cache boot_mode and secure_boot state if supported by driver.

    Cache current boot_mode and secure_boot in ironic's node representation

    :param task: a TaskManager instance containing the node to check.
    """
    # Try to retrieve boot mode and secure_boot state
    try:
        boot_mode = task.driver.management.get_boot_mode(task)
    except exception.UnsupportedDriverExtension:
        boot_mode = None
    except Exception as exc:
        LOG.warning('Unexpected exception when trying to detect boot_mode '
                    'for node %(node)s. %(class)s: %(exc)s',
                    {'node': task.node.uuid,
                     'class': type(exc).__name__, 'exc': exc},
                    exc_info=not isinstance(exc, exception.IronicException))
        return
    try:
        secure_boot = task.driver.management.get_secure_boot_state(task)
    except exception.UnsupportedDriverExtension:
        secure_boot = None
    except Exception as exc:
        LOG.warning('Unexpected exception when trying to detect secure_boot '
                    'state for node %(node)s. %(class)s: %(exc)s',
                    {'node': task.node.uuid,
                     'class': type(exc).__name__, 'exc': exc},
                    exc_info=not isinstance(exc, exception.IronicException))
        return

    if (boot_mode != task.node.boot_mode
        or secure_boot != task.node.secure_boot):
        # Update node if current values different from node's last known info.
        # Get exclusive lock in case we don't have one already.
        task.upgrade_lock(purpose='caching boot_mode or secure_boot state')
        task.node.boot_mode = boot_mode
        task.node.secure_boot = secure_boot
        task.node.save()
        LOG.info("Updated boot_mode %(boot_mode)s, secure_boot %(secure_boot)s"
                 "for node %(node)s",
                 {'boot_mode': boot_mode, 'secure_boot': secure_boot,
                  'node': task.node.uuid})


def node_change_boot_mode(task, target_boot_mode):
    """Change boot mode to requested state for node

    :param task: a TaskManager instance containing the node to act on.
    :param target_boot_mode: Any boot mode in :mod:`ironic.common.boot_modes`.
    """
    try:
        current_boot_mode = task.driver.management.get_boot_mode(task)
    except Exception as exc:
        current_boot_mode = None
        LOG.warning('Unexpected exception when trying to detect boot_mode '
                    'while changing boot mode for node '
                    '%(node)s. %(class)s: %(exc)s',
                    {'node': task.node.uuid,
                     'class': type(exc).__name__, 'exc': exc},
                    exc_info=not isinstance(exc, exception.IronicException))

    if (current_boot_mode is not None
        and target_boot_mode == current_boot_mode):
        LOG.info("Target boot mode '%(target)s', and current boot mode "
                 "'%(current)s' are identical. No change being made "
                 "for node %(node)s",
                 {'target': target_boot_mode, 'current': current_boot_mode,
                  'node': task.node.uuid})
        return
    try:
        task.driver.management.set_boot_mode(task, mode=target_boot_mode)
    except Exception as exc:
        LOG.error('Unexpected exception when trying to change boot_mode '
                  'to %(target)s for node %(node)s. %(class)s: %(exc)s',
                  {'node': task.node.uuid, 'target': target_boot_mode,
                   'class': type(exc).__name__, 'exc': exc},
                  exc_info=not isinstance(exc, exception.IronicException))
        task.node.last_error = (
            "Failed to change boot mode to '%(target)s'. "
            "Error: %(err)s" % {'target': target_boot_mode, 'err': exc})
        task.node.save()
    else:
        LOG.info("Changed boot_mode to %(mode)s for node %(node)s",
                 {'mode': target_boot_mode, 'node': task.node.uuid})
        task.node.boot_mode = target_boot_mode
        task.node.save()


def node_change_secure_boot(task, secure_boot_target):
    """Change secure_boot state to requested state for node

    :param task: a TaskManager instance containing the node to act on.
    :param secure_boot_target: Target secure_boot state
                                     OneOf(True => on, False => off)
    :type secure_boot_target: boolean
    """
    try:
        secure_boot_current = task.driver.management.get_secure_boot_state(
            task)
    except Exception as exc:
        secure_boot_current = None
        LOG.warning('Unexpected exception when trying to detect secure_boot '
                    'state while changing secure_boot for node '
                    '%(node)s. %(class)s: %(exc)s',
                    {'node': task.node.uuid,
                     'class': type(exc).__name__, 'exc': exc},
                    exc_info=not isinstance(exc, exception.IronicException))

    if (secure_boot_current is not None
        and secure_boot_target == secure_boot_current):
        LOG.info("Target secure_boot state '%(target)s', and current "
                 "secure_boot state '%(current)s' are identical. "
                 "No change being made for node %(node)s",
                 {'target': secure_boot_target,
                  'current': secure_boot_current,
                  'node': task.node.uuid})
        return
    try:
        task.driver.management.set_secure_boot_state(task, secure_boot_target)
    except Exception as exc:
        LOG.error('Unexpected exception when trying to change secure_boot '
                  'to %(target)s for node %(node)s. %(class)s: %(exc)s',
                  {'node': task.node.uuid, 'target': secure_boot_target,
                   'class': type(exc).__name__, 'exc': exc},
                  exc_info=not isinstance(exc, exception.IronicException))
        task.node.last_error = (
            "Failed to change secure_boot state to '%(target)s'. "
            "Error: %(err)s" % {'target': secure_boot_target, 'err': exc})
        task.node.save()
    else:
        LOG.info("Changed secure_boot state to %(state)s for node %(node)s",
                 {'state': secure_boot_target, 'node': task.node.uuid})
        task.node.secure_boot = secure_boot_target
        task.node.save()


def node_history_record(node, conductor=None, event=None,
                        event_type=None, user=None,
                        error=False):
    """Records a node history record

    Adds an entry to the node history table with the appropriate fields
    populated to ensure consistent experience by also updating the
    node ``last_error`` field. Please note the event is only recorded
    if the ``[conductor]node_history_max_size`` parameter is set to a
    value greater than ``0``.

    :param node: A node object from a task object. Required.
    :param conductor: The hostname of the conductor. If not specified
                      this value is populated with the conductor FQDN.
    :param event: The text to record to the node history table.
                  If no value is supplied, the method silently returns
                  to the caller.
    :param event_type: The type activity where the event was encountered,
                       either "provisioning", "monitoring", "cleaning",
                       or whatever text the a driver author wishes to supply
                       based upon the activity. The purpose is to help guide
                       an API consumer/operator to have a better contextual
                       understanding of what was going on *when* the "event"
                       occured.
    :param user: The user_id value which triggered the request,
                 if available.
    :param error: Boolean value, default false, to signify if the event
                  is an error which should be recorded in the node
                  ``last_error`` field.
    :returns: None. No value is returned by this method.
    """
    if not event:
        # No error has occured, apparently.
        return
    if error:
        # When the task exits out or is saved, the event
        # or error is saved, but that is outside of ceating an
        # entry in the history table.
        node.last_error = event
    if not conductor:
        conductor = CONF.host
    if CONF.conductor.node_history:
        # If the maximum number of entries is not set to zero,
        # then we should record the entry.
        # NOTE(TheJulia): DB API automatically adds in a uuid.
        # TODO(TheJulia): At some point, we should allow custom severity.
        node_history.NodeHistory(
            node_id=node.id,
            conductor=CONF.host,
            user=user,
            severity=error and "ERROR" or "INFO",
            event=event,
            event_type=event_type or "UNKNOWN").create()
