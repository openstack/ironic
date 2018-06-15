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

from ironic.common import exception
from ironic.common.i18n import _
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers.modules import deploy_utils

LOG = logging.getLogger(__name__)


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

    ironic_boot_mode = deploy_utils.get_boot_mode_for_deploy(node)

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
