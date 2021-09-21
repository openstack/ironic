# Copyright 2018 Red Hat, Inc.
# All Rights Reserved.
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

from oslo_log import log as logging
from oslo_utils import excutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import utils as common_utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import utils as driver_utils

LOG = logging.getLogger(__name__)

warn_about_default_boot_mode = False


def _set_boot_mode_on_bm(task, ironic_boot_mode, fail_if_unsupported=False):
    try:
        manager_utils.node_set_boot_mode(task, ironic_boot_mode)

    except exception.UnsupportedDriverExtension as ex:
        if fail_if_unsupported:
            msg = (_("Baremetal node %(uuid)s boot mode is not set "
                     "to boot mode %(boot_mode)s: %(error)s") %
                   {'uuid': task.node.uuid,
                    'boot_mode': ironic_boot_mode,
                    'error': ex})
            LOG.error(msg)
            raise exception.UnsupportedDriverExtension(msg)

        msg_tmpl = _("Baremetal node %(uuid)s boot mode is not set "
                     "to boot mode %(boot_mode)s. Assuming "
                     "baremetal node is already in %(boot_mode)s or "
                     "driver set boot mode via some other "
                     "mechanism: %(error)s")

        LOG.debug(msg_tmpl, {'uuid': task.node.uuid,
                             'boot_mode': ironic_boot_mode,
                             'error': ex})

    except exception.InvalidParameterValue as ex:
        msg = (_("Node %(uuid)s boot mode is not set. "
                 "Attempt to set %(ironic_boot_mode)s boot mode "
                 "on the baremetal node failed with error %(error)s") %
               {'uuid': task.node.uuid,
                'ironic_boot_mode': ironic_boot_mode,
                'error': ex})
        LOG.error(msg)
        raise exception.InvalidParameterValue(msg)

    else:
        LOG.info("Baremetal node boot mode is set to boot "
                 "mode %(boot_mode)s",
                 {'uuid': task.node.uuid, 'boot_mode': ironic_boot_mode})
        manager_utils.node_cache_boot_mode(task)


def sync_boot_mode(task):
    """Set node's boot mode from bare metal configuration

    Attempt to read currently set boot mode off the bare metal machine.
    Also read node's boot mode configuration:

    * If BM driver does not implement getting boot mode, assume
      BM boot mode is not set and apply the logic that follows
    * If Ironic node boot mode is not set and BM node boot mode is
      not set - set Ironic boot mode to `[deploy]/default_boot_mode`
    * If Ironic node boot mode is not set and BM node boot mode
      is set - set BM node boot mode on the Ironic node
    * If Ironic node boot mode is set and BM node boot mode is
      not set - set Ironic boot mode to BM boot mode
    * If both Ironic and BM node boot modes are set but they
      differ - try to set Ironic boot mode to BM boot mode and fail hard
      if underlying hardware type does not support setting boot mode

    In the end, the new boot mode may be set in
    'driver_internal_info/deploy_boot_mode'.

    :param task: a task object
    """
    node = task.node

    try:
        bm_boot_mode = manager_utils.node_get_boot_mode(task)

    except exception.UnsupportedDriverExtension as ex:
        bm_boot_mode = None

        LOG.debug("Cannot determine node %(uuid)s boot mode: %(error)s",
                  {'uuid': node.uuid, 'error': ex})

    ironic_boot_mode = get_boot_mode_for_deploy(node)

    # NOTE(etingof): the outcome of the branching that follows is that
    # the new boot mode may be set in 'driver_internal_info/deploy_boot_mode'

    if not ironic_boot_mode and not bm_boot_mode:
        driver_internal_info = node.driver_internal_info
        default_boot_mode = CONF.deploy.default_boot_mode
        driver_internal_info['deploy_boot_mode'] = default_boot_mode
        node.driver_internal_info = driver_internal_info
        node.save()

        LOG.debug("Ironic node %(uuid)s boot mode will be set to default "
                  "boot mode %(boot_mode)s",
                  {'uuid': node.uuid, 'boot_mode': default_boot_mode})

        _set_boot_mode_on_bm(task, default_boot_mode)

    elif not ironic_boot_mode and bm_boot_mode:
        driver_internal_info = node.driver_internal_info
        driver_internal_info['deploy_boot_mode'] = bm_boot_mode
        node.driver_internal_info = driver_internal_info
        node.save()

        LOG.debug("Ironic node %(uuid)s boot mode is set to boot mode "
                  "%(boot_mode)s reported by the driver",
                  {'uuid': node.uuid, 'boot_mode': bm_boot_mode})

    elif ironic_boot_mode and not bm_boot_mode:
        # NOTE(etingof): if only ironic boot mode is known, try to synchronize
        # (e.g. ironic -> bm) and do not fail if setting boot mode is not
        # supported by the underlying hardware type
        _set_boot_mode_on_bm(task, ironic_boot_mode)

    elif ironic_boot_mode != bm_boot_mode:
        msg = (_("Boot mode %(node_boot_mode)s currently configured "
                 "on node %(uuid)s does not match the boot mode "
                 "%(ironic_boot_mode)s requested for provisioning."
                 "Attempting to set node boot mode to %(ironic_boot_mode)s.") %
               {'uuid': node.uuid, 'node_boot_mode': bm_boot_mode,
                'ironic_boot_mode': ironic_boot_mode})
        LOG.info(msg)

        # NOTE(etingof): if boot modes are known and different, try
        # to synchronize them (e.g. ironic -> bm) and fail hard if
        # underlying hardware type does not support setting boot mode as
        # it seems to be a hopeless misconfiguration
        _set_boot_mode_on_bm(task, ironic_boot_mode, fail_if_unsupported=True)


def is_secure_boot_requested(node):
    """Returns True if secure_boot is requested for deploy.

    This method checks node property for secure_boot and returns True
    if it is requested.

    :param node: a single Node.
    :raises: InvalidParameterValue if the capabilities string is not a
             dictionary or is malformed.
    :returns: True if secure_boot is requested.
    """

    capabilities = common_utils.parse_instance_info_capabilities(node)
    sec_boot = capabilities.get('secure_boot', 'false').lower()

    return sec_boot == 'true'


def is_trusted_boot_requested(node):
    """Returns True if trusted_boot is requested for deploy.

    This method checks instance property for trusted_boot and returns True
    if it is requested.

    :param node: a single Node.
    :raises: InvalidParameterValue if the capabilities string is not a
             dictionary or is malformed.
    :returns: True if trusted_boot is requested.
    """

    capabilities = common_utils.parse_instance_info_capabilities(node)
    trusted_boot = capabilities.get('trusted_boot', 'false').lower()

    return trusted_boot == 'true'


def get_boot_mode_for_deploy(node):
    """Returns the boot mode that would be used for deploy.

    This method returns boot mode to be used for deploy.
    It returns 'uefi' if 'secure_boot' is set to 'true' or returns 'bios' if
    'trusted_boot' is set to 'true' in 'instance_info/capabilities' of node.
    Otherwise it returns value of 'boot_mode' in 'properties/capabilities'
    of node if set. If that is not set, it returns boot mode in
    'internal_driver_info/deploy_boot_mode' for the node.
    If that is not set, it returns boot mode in
    'instance_info/deploy_boot_mode' for the node.
    It would return None if boot mode is present neither in 'capabilities' of
    node 'properties' nor in node's 'internal_driver_info' nor in node's
    'instance_info' (which could also be None).

    :param node: an ironic node object.
    :returns: 'bios', 'uefi' or None
    :raises: InvalidParameterValue, if the node boot mode disagrees with
        the boot mode set to node properties/capabilities
    """

    if is_secure_boot_requested(node):
        LOG.debug('Deploy boot mode is uefi for %s.', node.uuid)
        return 'uefi'

    if is_trusted_boot_requested(node):
        # TODO(lintan) Trusted boot also supports uefi, but at the moment,
        # it should only boot with bios.
        LOG.debug('Deploy boot mode is bios for %s.', node.uuid)
        return 'bios'

    # NOTE(etingof):
    # The search for a boot mode should be in the priority order:
    #
    # 1) instance_info.capabilities
    # 2) instance_info.deploy_boot_mode (deprecated in Wallaby)
    # 3) properties.capabilities
    # 4) driver_internal_info.deploy_boot_mode (internal)
    #
    # Because:
    #
    # (1) and (2) are deleted during teardown
    # (4) will never be touched if node properties/capabilities
    #     are still present.
    # (3) becomes operational default as the last resort

    inst_boot_mode = (
        common_utils.parse_instance_info_capabilities(node).get('boot_mode')
    )
    cap_boot_mode = driver_utils.get_node_capability(node, 'boot_mode')

    old_boot_mode = node.instance_info.get('deploy_boot_mode')
    if old_boot_mode:
        LOG.warning('Using instance_info/deploy_boot_mode is deprecated, '
                    'please use instance_info/capabilities with boot mode '
                    'for node %s', node.uuid)

    boot_mode = (
        inst_boot_mode
        or old_boot_mode
        or cap_boot_mode
        or node.driver_internal_info.get('deploy_boot_mode')
    )

    if not boot_mode:
        return

    boot_mode = boot_mode.lower()

    # NOTE(etingof):
    # Make sure that the ultimate boot_mode agrees with the one set to
    # node properties/capabilities. This locks down node to use only
    # boot mode specified in properties/capabilities.
    # TODO(etingof): this logic will have to go away when we switch to traits
    if cap_boot_mode:
        cap_boot_mode = cap_boot_mode.lower()
        if cap_boot_mode != boot_mode:
            msg = (_("Node %(uuid)s boot mode %(boot_mode)s violates "
                     "node properties/capabilities %(caps)s") %
                   {'uuid': node.uuid,
                    'boot_mode': boot_mode,
                    'caps': cap_boot_mode})
            LOG.error(msg)
            raise exception.InvalidParameterValue(msg)

    LOG.debug('Deploy boot mode is %(boot_mode)s for %(node)s.',
              {'boot_mode': boot_mode, 'node': node.uuid})

    return boot_mode


def get_boot_mode(node):
    """Returns the boot mode.

    :param node: an ironic node object.
    :returns: 'bios' or 'uefi'
    :raises: InvalidParameterValue, if the node boot mode disagrees with
        the boot mode set to node properties/capabilities
    """
    boot_mode = get_boot_mode_for_deploy(node)
    if boot_mode:
        return boot_mode
    return CONF.deploy.default_boot_mode


@task_manager.require_exclusive_lock
def configure_secure_boot_if_needed(task):
    """Configures secure boot if it has been requested for the node."""
    if not is_secure_boot_requested(task.node):
        return

    try:
        task.driver.management.set_secure_boot_state(task, True)
    except exception.UnsupportedDriverExtension:
        # TODO(dtantsur): make a failure in Xena
        LOG.warning('Secure boot was requested for node %(node)s but its '
                    'management interface %(driver)s does not support it. '
                    'This warning will become an error in a future release.',
                    {'node': task.node.uuid,
                     'driver': task.node.management_interface})
    except Exception as exc:
        with excutils.save_and_reraise_exception():
            LOG.error('Failed to configure secure boot for node %(node)s: '
                      '%(error)s',
                      {'node': task.node.uuid, 'error': exc},
                      exc_info=not isinstance(exc, exception.IronicException))
    else:
        LOG.info('Secure boot has been enabled for node %s', task.node.uuid)
        manager_utils.node_cache_boot_mode(task)


@task_manager.require_exclusive_lock
def deconfigure_secure_boot_if_needed(task):
    """Deconfigures secure boot if it has been requested for the node."""
    if not is_secure_boot_requested(task.node):
        return

    try:
        task.driver.management.set_secure_boot_state(task, False)
    except exception.UnsupportedDriverExtension:
        # NOTE(dtantsur): don't make it a hard failure to allow tearing down
        # misconfigured nodes.
        LOG.debug('Secure boot was requested for node %(node)s but its '
                  'management interface %(driver)s does not support it.',
                  {'node': task.node.uuid,
                   'driver': task.node.management_interface})
    except Exception as exc:
        with excutils.save_and_reraise_exception():
            LOG.error('Failed to deconfigure secure boot for node %(node)s: '
                      '%(error)s',
                      {'node': task.node.uuid, 'error': exc},
                      exc_info=not isinstance(exc, exception.IronicException))
    else:
        LOG.info('Secure boot has been disabled for node %s', task.node.uuid)
        manager_utils.node_cache_boot_mode(task)
