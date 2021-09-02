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

import collections

from oslo_config import cfg
from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.objects import deploy_template

LOG = log.getLogger(__name__)
CONF = cfg.CONF


CLEANING_INTERFACE_PRIORITY = {
    # When two clean steps have the same priority, their order is determined
    # by which interface is implementing the clean step. The clean step of the
    # interface with the highest value here, will be executed first in that
    # case.
    'power': 5,
    'management': 4,
    'deploy': 3,
    'bios': 2,
    'raid': 1,
}

DEPLOYING_INTERFACE_PRIORITY = {
    # When two deploy steps have the same priority, their order is determined
    # by which interface is implementing the step. The step of the interface
    # with the highest value here, will be executed first in that case.
    # TODO(rloo): If we think it makes sense to have the interface priorities
    # the same for cleaning & deploying, replace the two with one e.g.
    # 'INTERFACE_PRIORITIES'.
    'power': 5,
    'management': 4,
    'deploy': 3,
    'bios': 2,
    'raid': 1,
}


def _clean_step_key(step):
    """Sort by priority, then interface priority in event of tie.

    :param step: cleaning step dict to get priority for.
    """
    return (step.get('priority'),
            CLEANING_INTERFACE_PRIORITY[step.get('interface')])


def _deploy_step_key(step):
    """Sort by priority, then interface priority in event of tie.

    :param step: deploy step dict to get priority for.
    """
    return (step.get('priority'),
            DEPLOYING_INTERFACE_PRIORITY[step.get('interface')])


def _sorted_steps(steps, sort_step_key):
    """Return a sorted list of steps.

    :param sort_step_key: If set, this is a method (key) used to sort the steps
        from highest priority to lowest priority. For steps having the same
        priority, they are sorted from highest interface priority to lowest.
    :returns: A list of sorted step dictionaries.
    """
    # Sort the steps from higher priority to lower priority
    return sorted(steps, key=sort_step_key, reverse=True)


def is_equivalent(step1, step2):
    """Compare steps, ignoring their priority."""
    return (step1.get('interface') == step2.get('interface')
            and step1.get('step') == step2.get('step'))


def find_step(steps, step):
    """Find an identical step in the list of steps."""
    return next((x for x in steps if is_equivalent(x, step)), None)


def _get_steps(task, interfaces, get_method, enabled=False,
               sort_step_key=None, prio_overrides=None):
    """Get steps for task.node.

    :param task: A TaskManager object
    :param interfaces: A dictionary of (key) interfaces and their
        (value) priorities. These are the interfaces that will have steps of
        interest. The priorities are used for deciding the priorities of steps
        having the same priority.
    :param get_method: The method used to get the steps from the node's
        interface; a string.
    :param enabled: If True, returns only enabled (priority > 0) steps. If
        False, returns all steps.
    :param sort_step_key: If set, this is a method (key) used to sort the steps
        from highest priority to lowest priority. For steps having the same
        priority, they are sorted from highest interface priority to lowest.
    :param prio_overrides: An optional dictionary of priority overrides for
        steps, e.g:
        {'deploy.erase_devices_metadata': '123',
         'management.reset_bios_to_default': '234'}
    :raises: NodeCleaningFailure or InstanceDeployFailure if there was a
        problem getting the steps.
    :returns: A list of step dictionaries
    """
    # Get steps from each interface
    steps = list()
    for interface in interfaces:
        interface = getattr(task.driver, interface)
        if interface:
            interface_steps = [x for x in getattr(interface, get_method)(task)
                               if not enabled or x['priority'] > 0]
            steps.extend(interface_steps)
    if prio_overrides is not None:
        for step in steps:
            override_key = '%(interface)s.%(step)s' % step
            override_value = prio_overrides.get(override_key)
            if override_value:
                step["priority"] = int(override_value)
    if sort_step_key:
        steps = _sorted_steps(steps, sort_step_key)
    return steps


def _get_cleaning_steps(task, enabled=False, sort=True):
    """Get cleaning steps for task.node.

    :param task: A TaskManager object
    :param enabled: If True, returns only enabled (priority > 0) steps. If
        False, returns all clean steps.
    :param sort: If True, the steps are sorted from highest priority to lowest
        priority. For steps having the same priority, they are sorted from
        highest interface priority to lowest.
    :raises: NodeCleaningFailure if there was a problem getting the
        clean steps.
    :returns: A list of clean step dictionaries
    """
    sort_key = _clean_step_key if sort else None
    if CONF.conductor.clean_step_priority_override:
        csp_override = {}
        for element in CONF.conductor.clean_step_priority_override:
            csp_override.update(element)

        cleaning_steps = _get_steps(task, CLEANING_INTERFACE_PRIORITY,
                                    'get_clean_steps', enabled=enabled,
                                    sort_step_key=sort_key,
                                    prio_overrides=csp_override)

        LOG.debug("cleaning_steps after applying "
                  "clean_step_priority_override for node %(node)s: %(step)s",
                  task.node.uuid, cleaning_steps)
    else:
        cleaning_steps = _get_steps(task, CLEANING_INTERFACE_PRIORITY,
                                    'get_clean_steps', enabled=enabled,
                                    sort_step_key=sort_key)
    return cleaning_steps


def _get_deployment_steps(task, enabled=False, sort=True):
    """Get deployment steps for task.node.

    :param task: A TaskManager object
    :param enabled: If True, returns only enabled (priority > 0) steps. If
        False, returns all deploy steps.
    :param sort: If True, the steps are sorted from highest priority to lowest
        priority. For steps having the same priority, they are sorted from
        highest interface priority to lowest.
    :raises: InstanceDeployFailure if there was a problem getting the
        deploy steps.
    :returns: A list of deploy step dictionaries
    """
    sort_key = _deploy_step_key if sort else None
    return _get_steps(task, DEPLOYING_INTERFACE_PRIORITY, 'get_deploy_steps',
                      enabled=enabled, sort_step_key=sort_key)


def set_node_cleaning_steps(task, disable_ramdisk=False):
    """Set up the node with clean step information for cleaning.

    For automated cleaning, get the clean steps from the driver.
    For manual cleaning, the user's clean steps are known but need to be
    validated against the driver's clean steps.

    :param disable_ramdisk: If `True`, only steps with requires_ramdisk=False
        are accepted.
    :raises: InvalidParameterValue if there is a problem with the user's
             clean steps.
    :raises: NodeCleaningFailure if there was a problem getting the
             clean steps.
    """
    node = task.node
    driver_internal_info = node.driver_internal_info

    # For manual cleaning, the target provision state is MANAGEABLE, whereas
    # for automated cleaning, it is AVAILABLE.
    manual_clean = node.target_provision_state == states.MANAGEABLE

    if not manual_clean:
        # Get the prioritized steps for automated cleaning
        driver_internal_info['clean_steps'] = _get_cleaning_steps(task,
                                                                  enabled=True)
    else:
        # For manual cleaning, the list of cleaning steps was specified by the
        # user and already saved in node.driver_internal_info['clean_steps'].
        # Now that we know what the driver's available clean steps are, we can
        # do further checks to validate the user's clean steps.
        steps = node.driver_internal_info['clean_steps']
        driver_internal_info['clean_steps'] = _validate_user_clean_steps(
            task, steps, disable_ramdisk=disable_ramdisk)

    LOG.debug('List of the steps for %(type)s cleaning of node %(node)s: '
              '%(steps)s', {'type': 'manual' if manual_clean else 'automated',
                            'node': node.uuid,
                            'steps': driver_internal_info['clean_steps']})

    node.clean_step = {}
    driver_internal_info['clean_step_index'] = None
    node.driver_internal_info = driver_internal_info
    node.save()


def _get_deployment_templates(task):
    """Get deployment templates for task.node.

    Return deployment templates where the name of the deployment template
    matches one of the node's instance traits (the subset of the node's traits
    requested by the user via a flavor or image).

    :param task: A TaskManager object
    :returns: a list of DeployTemplate objects.
    """
    node = task.node
    if not node.instance_info.get('traits'):
        return []
    instance_traits = node.instance_info['traits']
    return deploy_template.DeployTemplate.list_by_names(task.context,
                                                        instance_traits)


def _get_steps_from_deployment_templates(task, templates):
    """Get deployment template steps for task.node.

    Given a list of deploy template objects, return a list of all deploy steps
    combined.

    :param task: A TaskManager object
    :param templates: a list of deploy templates
    :returns: A list of deploy step dictionaries
    """
    steps = []
    # NOTE(mgoddard): The steps from the object include id, created_at, etc.,
    # which we don't want to include when we assign them to
    # node.driver_internal_info. Include only the relevant fields.
    step_fields = ('interface', 'step', 'args', 'priority')
    for template in templates:
        steps.extend([{key: step[key] for key in step_fields}
                      for step in template.steps])
    return steps


def _get_validated_steps_from_templates(task, skip_missing=False):
    """Return a list of validated deploy steps from deploy templates.

    Deployment template steps are those steps defined in deployment templates
    where the name of the deployment template matches one of the node's
    instance traits (the subset of the node's traits requested by the user via
    a flavor or image). There may be many such matching templates, each with a
    list of steps to execute.

    This method gathers the steps from all matching deploy templates for a
    node, and validates those steps against the node's driver interfaces,
    raising an error if validation fails.

    :param task: A TaskManager object
    :raises: InvalidParameterValue if validation of steps fails.
    :raises: InstanceDeployFailure if there was a problem getting the
        deploy steps.
    :returns: A list of validated deploy step dictionaries
    """
    # Gather deploy templates matching the node's instance traits.
    templates = _get_deployment_templates(task)

    # Gather deploy steps from deploy templates.
    user_steps = _get_steps_from_deployment_templates(task, templates)

    # Validate the steps.
    error_prefix = (_('Validation of deploy steps from deploy templates '
                      'matching this node\'s instance traits failed. Matching '
                      'deploy templates: %(templates)s. Errors: ') %
                    {'templates': ','.join(t.name for t in templates)})
    return _validate_user_deploy_steps(task, user_steps,
                                       error_prefix=error_prefix,
                                       skip_missing=skip_missing)


def _get_all_deployment_steps(task, skip_missing=False):
    """Get deployment steps for task.node.

    Deployment steps from matching deployment templates are combined with those
    from driver interfaces and all enabled steps returned in priority order.

    :param task: A TaskManager object
    :raises: InstanceDeployFailure if there was a problem getting the
        deploy steps.
    :returns: A list of deploy step dictionaries
    """
    # Get deploy steps provided by user via argument if any. These steps
    # override template and driver steps when overlap.
    user_steps = _get_validated_user_deploy_steps(
        task, skip_missing=skip_missing)

    # Gather deploy steps from deploy templates and validate.
    # NOTE(mgoddard): although we've probably just validated the templates in
    # do_node_deploy, they may have changed in the DB since we last checked, so
    # validate again.
    template_steps = _get_validated_steps_from_templates(
        task, skip_missing=skip_missing)

    # Take only template steps that are not already provided by user
    user_step_keys = {(s['interface'], s['step']) for s in user_steps}
    new_template_steps = [s for s in template_steps
                          if (s['interface'], s['step']) not in user_step_keys]
    user_steps.extend(new_template_steps)

    # Gather enabled deploy steps from drivers.
    driver_steps = _get_deployment_steps(task, enabled=True, sort=False)

    # Remove driver steps that have been disabled or overridden by user steps.
    user_step_keys = {(s['interface'], s['step']) for s in user_steps}
    steps = [s for s in driver_steps
             if (s['interface'], s['step']) not in user_step_keys]

    # Add enabled user steps.
    enabled_user_steps = [s for s in user_steps if s['priority'] > 0]
    steps.extend(enabled_user_steps)

    return _sorted_steps(steps, _deploy_step_key)


def set_node_deployment_steps(task, reset_current=True, skip_missing=False):
    """Set up the node with deployment step information for deploying.

    Get the deploy steps from the driver.

    :param reset_current: Whether to reset the current step to the first one.
    :raises: InstanceDeployFailure if there was a problem getting the
             deployment steps.
    """
    node = task.node
    driver_internal_info = node.driver_internal_info
    driver_internal_info['deploy_steps'] = _get_all_deployment_steps(
        task, skip_missing=skip_missing)

    LOG.debug('List of the deploy steps for node %(node)s: '
              '%(steps)s', {'node': node.uuid,
                            'steps': driver_internal_info['deploy_steps']})
    if reset_current:
        node.deploy_step = {}
        driver_internal_info['deploy_step_index'] = None
    node.driver_internal_info = driver_internal_info
    node.save()


def _step_id(step):
    """Return the 'ID' of a deploy step.

    The ID is a string, <interface>.<step>.

    :param step: the step dictionary.
    :return: the step's ID string.
    """
    return '.'.join([step['interface'], step['step']])


def _validate_deploy_steps_unique(user_steps):
    """Validate that deploy steps from deploy templates are unique.

    :param user_steps: a list of user steps. A user step is a dictionary
        with required keys 'interface', 'step', 'args', and 'priority'::

              { 'interface': <driver_interface>,
                'step': <name_of_step>,
                'args': {<arg1>: <value1>, ..., <argn>: <valuen>},
                'priority': <priority_of_step> }

        For example::

              { 'interface': deploy',
                'step': 'upgrade_firmware',
                'args': {'force': True},
                'priority': 10 }

    :return: a list of validation error strings for the steps.
    """
    # Check for duplicate steps. Each interface/step combination can be
    # specified at most once.
    errors = []
    counter = collections.Counter(_step_id(step) for step in user_steps)
    duplicates = {step_id for step_id, count in counter.items() if count > 1}
    if duplicates:
        err = (_('deploy steps from all deploy templates matching this '
                 'node\'s instance traits cannot have the same interface '
                 'and step. Duplicate deploy steps for %(duplicates)s') %
               {'duplicates': ', '.join(duplicates)})
        errors.append(err)
    return errors


def _validate_user_step(task, user_step, driver_step, step_type,
                        disable_ramdisk=False):
    """Validate a user-specified step.

    :param task: A TaskManager object
    :param user_step: a user step dictionary with required keys 'interface'
        and 'step', and optional keys 'args' and 'priority'::

              { 'interface': <driver_interface>,
                'step': <name_of_step>,
                'args': {<arg1>: <value1>, ..., <argn>: <valuen>},
                'priority': <optional_priority> }

        For example::

              { 'interface': deploy',
                'step': 'upgrade_firmware',
                'args': {'force': True} }

    :param driver_step: a driver step dictionary::

              { 'interface': <driver_interface>,
                'step': <name_of_step>,
                'priority': <integer>
                'abortable': Optional for clean steps, absent for deploy steps.
                             <Boolean>.
                'argsinfo': Optional. A dictionary of
                            {<arg_name>:<arg_info_dict>} entries.
                            <arg_info_dict> is a dictionary with
                            { 'description': <description>,
                              'required': <Boolean> } }

        For example::

              { 'interface': deploy',
                'step': 'upgrade_firmware',
                'priority': 10,
                'abortable': True,
                'argsinfo': {
                    'force': { 'description': 'Whether to force the upgrade',
                               'required': False } } }

    :param step_type: either 'clean' or 'deploy'.
    :param disable_ramdisk: If `True`, only steps with requires_ramdisk=False
        are accepted. Only makes sense for manual cleaning at the moment.
    :return: a list of validation error strings for the step.
    """
    errors = []
    # Check that the user-specified arguments are valid
    argsinfo = driver_step.get('argsinfo') or {}
    user_args = user_step.get('args') or {}
    unexpected = set(user_args) - set(argsinfo)
    if unexpected:
        error = (_('%(type)s step %(step)s has these unexpected arguments: '
                   '%(unexpected)s') %
                 {'type': step_type, 'step': user_step,
                  'unexpected': ', '.join(unexpected)})
        errors.append(error)

    if step_type == 'clean' or user_step['priority'] > 0:
        # Check that all required arguments were specified by the user
        missing = []
        for (arg_name, arg_info) in argsinfo.items():
            if arg_info.get('required', False) and arg_name not in user_args:
                msg = arg_name
                if arg_info.get('description'):
                    msg += ' (%(desc)s)' % {'desc': arg_info['description']}
                missing.append(msg)
        if missing:
            error = (_('%(type)s step %(step)s is missing these required '
                       'arguments: %(miss)s') %
                     {'type': step_type, 'step': user_step,
                      'miss': ', '.join(missing)})
            errors.append(error)
        if disable_ramdisk and driver_step.get('requires_ramdisk', True):
            error = _('clean step %s requires booting a ramdisk') % user_step
            errors.append(error)

    if step_type == 'clean':
        # Copy fields that should not be provided by a user
        user_step['abortable'] = driver_step.get('abortable', False)
        user_step['priority'] = driver_step.get('priority', 0)
    elif user_step['priority'] > 0:
        # 'core' deploy steps can only be disabled.

        # NOTE(mgoddard): we'll need something a little more sophisticated to
        # track core steps once we split out the single core step.
        is_core = (driver_step['interface'] == 'deploy'
                   and driver_step['step'] == 'deploy')
        if is_core:
            error = (_('deploy step %(step)s on interface %(interface)s is a '
                       'core step and cannot be overridden by user steps. It '
                       'may be disabled by setting the priority to 0') %
                     {'step': user_step['step'],
                      'interface': user_step['interface']})
            errors.append(error)

    return errors


def _validate_user_steps(task, user_steps, driver_steps, step_type,
                         error_prefix=None, skip_missing=False,
                         disable_ramdisk=False):
    """Validate the user-specified steps.

    :param task: A TaskManager object
    :param user_steps: a list of user steps. A user step is a dictionary
        with required keys 'interface' and 'step', and optional keys 'args'
        and 'priority'::

              { 'interface': <driver_interface>,
                'step': <name_of_step>,
                'args': {<arg1>: <value1>, ..., <argn>: <valuen>},
                'priority': <optional_priority> }

        For example::

              { 'interface': deploy',
                'step': 'upgrade_firmware',
                'args': {'force': True} }

    :param driver_steps: a list of driver steps::

              { 'interface': <driver_interface>,
                'step': <name_of_step>,
                'priority': <integer>
                'abortable': Optional for clean steps, absent for deploy steps.
                             <Boolean>.
                'argsinfo': Optional. A dictionary of
                            {<arg_name>:<arg_info_dict>} entries.
                            <arg_info_dict> is a dictionary with
                            { 'description': <description>,
                              'required': <Boolean> } }

        For example::

              { 'interface': deploy',
                'step': 'upgrade_firmware',
                'priority': 10,
                'abortable': True,
                'argsinfo': {
                    'force': { 'description': 'Whether to force the upgrade',
                               'required': False } } }

    :param step_type: either 'clean' or 'deploy'.
    :param error_prefix: String to use as a prefix for exception messages, or
        None.
    :param skip_missing: Whether to silently ignore unknown steps.
    :param disable_ramdisk: If `True`, only steps with requires_ramdisk=False
        are accepted. Only makes sense for manual cleaning at the moment.
    :raises: InvalidParameterValue if validation of steps fails.
    :raises: NodeCleaningFailure or InstanceDeployFailure if
        there was a problem getting the steps from the driver.
    :return: validated steps updated with information from the driver
    """

    errors = []

    # Convert driver steps to a dict.
    driver_steps = {_step_id(s): s for s in driver_steps}

    result = []

    for user_step in user_steps:
        # Check if this user-specified step isn't supported by the driver
        try:
            driver_step = driver_steps[_step_id(user_step)]
        except KeyError:
            if skip_missing:
                LOG.debug('%(type)s step %(step)s is not currently known for '
                          'node %(node)s, delaying its validation until '
                          'in-band steps are loaded',
                          {'type': step_type.capitalize(),
                           'step': user_step, 'node': task.node.uuid})
            else:
                error = (_('node does not support this %(type)s step: '
                           '%(step)s')
                         % {'type': step_type, 'step': user_step})
                errors.append(error)
            continue

        step_errors = _validate_user_step(task, user_step, driver_step,
                                          step_type, disable_ramdisk)
        errors.extend(step_errors)
        result.append(user_step)

    if step_type == 'deploy':
        # Deploy steps should be unique across all combined templates or passed
        # deploy_steps argument.
        dup_errors = _validate_deploy_steps_unique(result)
        errors.extend(dup_errors)

    if errors:
        err = error_prefix or ''
        err += '; '.join(errors)
        raise exception.InvalidParameterValue(err=err)

    return result


def _validate_user_clean_steps(task, user_steps, disable_ramdisk=False):
    """Validate the user-specified clean steps.

    :param task: A TaskManager object
    :param user_steps: a list of clean steps. A clean step is a dictionary
        with required keys 'interface' and 'step', and optional key 'args'::

              { 'interface': <driver_interface>,
                'step': <name_of_clean_step>,
                'args': {<arg1>: <value1>, ..., <argn>: <valuen>} }

            For example::

              { 'interface': 'deploy',
                'step': 'upgrade_firmware',
                'args': {'force': True} }
    :param disable_ramdisk: If `True`, only steps with requires_ramdisk=False
        are accepted.
    :raises: InvalidParameterValue if validation of clean steps fails.
    :raises: NodeCleaningFailure if there was a problem getting the
        clean steps from the driver.
    :return: validated clean steps update with information from the driver
    """
    driver_steps = _get_cleaning_steps(task, enabled=False, sort=False)
    return _validate_user_steps(task, user_steps, driver_steps, 'clean',
                                disable_ramdisk=disable_ramdisk)


def _validate_user_deploy_steps(task, user_steps, error_prefix=None,
                                skip_missing=False):
    """Validate the user-specified deploy steps.

    :param task: A TaskManager object
    :param user_steps: a list of deploy steps. A deploy step is a dictionary
        with required keys 'interface', 'step', 'args', and 'priority'::

              { 'interface': <driver_interface>,
                'step': <name_of_deploy_step>,
                'args': {<arg1>: <value1>, ..., <argn>: <valuen>},
                'priority': <priority_of_deploy_step> }

            For example::

              { 'interface': 'bios',
                'step': 'apply_configuration',
                'args': { 'settings': [ { 'foo': 'bar' } ] },
                'priority': 150 }
    :param error_prefix: String to use as a prefix for exception messages, or
        None.
    :raises: InvalidParameterValue if validation of deploy steps fails.
    :raises: InstanceDeployFailure if there was a problem getting the deploy
        steps from the driver.
    :return: validated deploy steps update with information from the driver
    """
    driver_steps = _get_deployment_steps(task, enabled=False, sort=False)
    return _validate_user_steps(task, user_steps, driver_steps, 'deploy',
                                error_prefix=error_prefix,
                                skip_missing=skip_missing)


def _get_validated_user_deploy_steps(task, deploy_steps=None,
                                     skip_missing=False):
    """Validate the deploy steps for a node.

    :param task: A TaskManager object
    :param deploy_steps: Deploy steps to validate. Optional. If not provided
        then will check node's driver internal info.
    :param skip_missing: whether skip missing steps that are not yet available
        at the time of validation.
    :raises: InvalidParameterValue if deploy steps are unsupported by the
        node's driver interfaces.
    :raises: InstanceDeployFailure if there was a problem getting the deploy
        steps from the driver.
    """
    if not deploy_steps:
        deploy_steps = task.node.driver_internal_info.get('user_deploy_steps')

    if deploy_steps:
        error_prefix = (_('Validation of deploy steps from "deploy steps" '
                          'argument failed.'))
        return _validate_user_deploy_steps(task, deploy_steps,
                                           error_prefix=error_prefix,
                                           skip_missing=skip_missing)
    else:
        return []


def validate_user_deploy_steps_and_templates(task, deploy_steps=None,
                                             skip_missing=False):
    """Validate the user deploy steps and the deploy templates for a node.

    :param task: A TaskManager object
    :param deploy_steps: Deploy steps to validate. Optional. If not provided
        then will check node's driver internal info.
    :param skip_missing: whether skip missing steps that are not yet available
        at the time of validation.
    :raises: InvalidParameterValue if the instance has traits that map to
        deploy steps that are unsupported by the node's driver interfaces or
        user deploy steps are unsupported by the node's driver interfaces
    :raises: InstanceDeployFailure if there was a problem getting the deploy
        steps from the driver.
    """
    # Gather deploy steps from matching deploy templates and validate them.
    _get_validated_steps_from_templates(task, skip_missing=skip_missing)
    # Validate steps from passed argument or stored on the node.
    _get_validated_user_deploy_steps(task, deploy_steps, skip_missing)
