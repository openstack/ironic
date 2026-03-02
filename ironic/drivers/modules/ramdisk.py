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
Ramdisk Deploy Interface
"""

from oslo_log import log as logging

from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import image_service
from ironic.common import metrics_utils
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import agent_base
from ironic.drivers.modules import deploy_utils

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


class RamdiskDeploy(agent_base.AgentBaseMixin, agent_base.HeartbeatMixin,
                    base.DeployInterface):

    def get_properties(self):
        return {}

    def supports_deploy(self, task):
        """Check if this interface supports the given deployment.

        Ramdisk deploy is appropriate when
        ``ironic_ramdisk_deploy=True`` is present **and** one of
        the following holds:

        * ``boot_iso`` is set in instance_info, or
        * ``kernel`` and ``ramdisk`` are set in instance_info, or
        * ``image_source`` is a Glance image with ``boot_iso_id``
          property, or
        * ``image_source`` is a Glance image with ``kernel_id``
          and ``ramdisk_id`` properties.

        For instance_info cases the sentinel is looked up in
        ``instance_info``; for Glance image cases it is looked up
        in the image properties.

        :param task: A TaskManager instance containing the node to
            act on.
        :returns: True if ramdisk deploy is appropriate.
        """
        instance_info = task.node.instance_info
        if (instance_info.get('boot_iso')
                and instance_info.get('ironic_ramdisk_deploy')):
            return True
        if (instance_info.get('kernel')
                and instance_info.get('ramdisk')
                and instance_info.get('ironic_ramdisk_deploy')):
            return True
        image_source = instance_info.get('image_source')
        if (image_source
                and service_utils.is_glance_image(image_source)):
            try:
                props = deploy_utils.get_image_properties(
                    task.context, image_source)
                if not props.get('ironic_ramdisk_deploy'):
                    return False
                if props.get('boot_iso_id'):
                    return True
                if (props.get('kernel_id')
                        and props.get('ramdisk_id')):
                    return True
            except Exception:
                LOG.warning(
                    'Failed to query Glance image %s '
                    'for ramdisk deploy detection',
                    image_source)
        return False

    def validate(self, task):
        if 'ramdisk_boot' not in task.driver.boot.capabilities:
            raise exception.InvalidParameterValue(
                message=_('Invalid configuration: The boot interface '
                          'must have the `ramdisk_boot` capability. '
                          'You are using an incompatible boot interface.'))
        task.driver.boot.validate(task)

        # Validate node capabilities
        deploy_utils.validate_capabilities(task.node)

    @METRICS.timer('RamdiskDeploy.deploy')
    @base.deploy_step(priority=100)
    @task_manager.require_exclusive_lock
    def deploy(self, task):
        if ('configdrive' in task.node.instance_info
                and 'ramdisk_boot_configdrive' not in
                task.driver.boot.capabilities):
            # TODO(dtantsur): make it an actual error?
            LOG.warning('A configuration drive is present in the ramdisk '
                        'deployment request of node %(node)s with boot '
                        'interface %(drv)s. The configuration drive will be '
                        'ignored for this deployment.',
                        {'node': task.node,
                         'drv': task.node.get_interface('boot')})
        manager_utils.node_power_action(task, states.POWER_OFF)
        # Tenant networks must enable connectivity to the boot
        # location, as reboot() can otherwise be very problematic.
        # IDEA(TheJulia): Maybe a "trusted environment" mode flag
        # that we otherwise fail validation on for drivers that
        # require explicit security postures.
        with manager_utils.power_state_for_network_configuration(task):
            task.driver.network.configure_tenant_networks(task)

        # calling boot.prepare_instance will also set the node
        # to boot, and update the templates accordingly
        task.driver.boot.prepare_instance(task)

        # Power-on the instance, with PXE prepared, we're done.
        manager_utils.node_power_action(task, states.POWER_ON)
        LOG.info('Deployment setup for node %s done', task.node.uuid)
        return None

    @METRICS.timer('RamdiskDeploy.prepare')
    @task_manager.require_exclusive_lock
    def prepare(self, task):
        node = task.node

        deploy_utils.populate_storage_driver_internal_info(task)
        if node.provision_state == states.DEPLOYING:
            # Ask the network interface to validate itself so
            # we can ensure we are able to proceed.
            task.driver.network.validate(task)

            manager_utils.node_power_action(task, states.POWER_OFF)
            # NOTE(TheJulia): If this was any other interface, we would
            # unconfigure tenant networks, add provisioning networks, etc.
            task.driver.storage.attach_volumes(task)
            # Resolve boot image info from Glance when only
            # image_source is provided (e.g. Nova path).
            self._resolve_image_info_from_glance(task)
        if node.provision_state in (states.ACTIVE, states.UNRESCUING):
            # In the event of takeover or unrescue.
            task.driver.boot.prepare_instance(task)

    def _resolve_image_info_from_glance(self, task):
        """Resolve boot_iso or kernel/ramdisk from Glance image properties.

        When only image_source is set (e.g. Nova deploys), query Glance
        for the image properties and populate instance_info with
        boot_iso, or kernel and ramdisk as appropriate.

        :param task: a TaskManager instance.
        """
        node = task.node
        i_info = node.instance_info
        image_source = i_info.get('image_source')

        if (not image_source
                or i_info.get('boot_iso')
                or i_info.get('kernel')
                or not service_utils.is_glance_image(image_source)):
            return

        try:
            img_service = image_service.get_image_service(
                image_source, context=task.context)
            image_props = img_service.show(image_source)['properties']
        except (exception.GlanceConnectionFailed,
                exception.ImageNotAuthorized,
                exception.ImageNotFound,
                exception.Invalid) as e:
            LOG.warning('Failed to get Glance image properties for '
                        'node %(node)s: %(err)s',
                        {'node': node.uuid, 'err': e})
            return

        if image_props.get('boot_iso_id'):
            i_info['boot_iso'] = str(image_props['boot_iso_id'])
            i_info['original_image_source'] = str(image_source)
        elif (image_props.get('kernel_id')
                and image_props.get('ramdisk_id')):
            i_info['kernel'] = str(image_props['kernel_id'])
            i_info['ramdisk'] = str(image_props['ramdisk_id'])
        else:
            return

        # TODO(JayF): Image metadata was already inspected before
        #             prepare was called on the deploy driver, so
        #             we need to clear out invalid metadata that was
        #             gleaned before we got here. Ideally, we'd
        #             improve ordering such that we never need to do this.
        i_info.pop('image_source', None)
        i_info.pop('image_type', None)
        node.del_driver_internal_info('is_whole_disk_image')

        # NOTE(JayF): The presence of i_info[image_source] is taken as
        #             a sentinel value to mean "direct deploy". It cannot
        #             be left in instance_info.
        i_info['original_image_source'] = str(image_source)
        i_info.pop('image_source', None)
        node.instance_info = i_info
        node.save()
