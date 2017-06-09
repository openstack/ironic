# Copyright 2017 FUJITSU LIMITED
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

from tempest.common import waiters
from tempest import config
from tempest.lib.common.utils import data_utils
from tempest.lib.common.utils import test_utils
from tempest.lib import decorators
from tempest import test

from ironic_tempest_plugin.tests.scenario import baremetal_manager

CONF = config.CONF


class BaremetalBFV(baremetal_manager.BaremetalScenarioTest):
    """Check baremetal instance that can boot from Cinder volume:

    * Create a volume from an image
    * Create a keypair
    * Boot an instance from the volume using the keypair
    * Verify instance IP address
    * Delete instance
    """

    credentials = ['primary', 'admin']

    min_microversion = '1.32'

    @classmethod
    def skip_checks(cls):
        super(BaremetalBFV, cls).skip_checks()
        if CONF.baremetal.use_provision_network:
            msg = 'Ironic boot-from-volume requires a flat network.'
            raise cls.skipException(msg)

    def create_volume(self, size=None, name=None, snapshot_id=None,
                      image_id=None, volume_type=None):
        if size is None:
            size = CONF.volume.volume_size
        if image_id is None:
            image = self.compute_images_client.show_image(image_id)['image']
            min_disk = image.get('minDisk')
            size = max(size, min_disk)
        if name is None:
            name = data_utils.rand_name(self.__class__.__name__ + "-volume")
        kwargs = {'display_name': name,
                  'snapshot_id': snapshot_id,
                  'imageRef': image_id,
                  'volume_type': volume_type,
                  'size': size}
        volume = self.volumes_client.create_volume(**kwargs)['volume']

        self.addCleanup(self.volumes_client.wait_for_resource_deletion,
                        volume['id'])
        self.addCleanup(test_utils.call_and_ignore_notfound_exc,
                        self.volumes_client.delete_volume, volume['id'])
        self.assertEqual(name, volume['name'])
        waiters.wait_for_volume_resource_status(self.volumes_client,
                                                volume['id'], 'available')
        # The volume retrieved on creation has a non-up-to-date status.
        # Retrieval after it becomes active ensures correct details.
        volume = self.volumes_client.show_volume(volume['id'])['volume']
        return volume

    def _create_volume_from_image(self):
        """Create a cinder volume from the default image."""
        image_id = CONF.compute.image_ref
        vol_name = data_utils.rand_name(
            self.__class__.__name__ + '-volume-origin')
        return self.create_volume(name=vol_name, image_id=image_id)

    def _get_bdm(self, source_id, source_type, delete_on_termination=False):
        """Create block device mapping config options dict.

        :param source_id: id of the source device.
        :param source_type: type of the source device.
        :param delete_on_termination: what to do with the volume when
          the instance is terminated.
        :return: a dictionary of configuration options for block
          device mapping.
        """
        bd_map_v2 = [{
            'uuid': source_id,
            'source_type': source_type,
            'destination_type': 'volume',
            'boot_index': 0,
            'delete_on_termination': delete_on_termination}]
        return {'block_device_mapping_v2': bd_map_v2}

    def _boot_instance_from_resource(self, source_id,
                                     source_type,
                                     keypair=None,
                                     delete_on_termination=False):
        """Boot instance from the specified resource."""
        # NOTE(tiendc): Boot to the volume, use image_id=''.
        # We don't pass image_id=None as that will cause the default image
        # to be used.
        create_kwargs = {'image_id': ''}
        create_kwargs.update(self._get_bdm(
            source_id,
            source_type,
            delete_on_termination=delete_on_termination))

        return self.boot_instance(
            clients=self.manager,
            keypair=keypair,
            **create_kwargs
        )

    @decorators.idempotent_id('d6e05e61-8221-44ac-b785-57545f8e0fcf')
    @test.services('compute', 'image', 'network', 'volume')
    def test_baremetal_boot_from_volume(self):
        """Test baremetal node can boot from a cinder volume.

        This test function first creates a cinder volume from an image.
        Then it executes "server create" action with appropriate block
        device mapping config options, the baremetal node will boot
        from the newly created volume. This requires a volume connector
        is created for the node, and the node capabilities flag
        iscsi_boot is set to true.
        """
        # Create volume from image
        volume_origin = self._create_volume_from_image()

        # NOTE: node properties/capabilities for flag iscsi_boot=true,
        # and volume connector should be added by devstack already.

        # Boot instance
        self.keypair = self.create_keypair()
        self.instance, self.node = self._boot_instance_from_resource(
            source_id=volume_origin['id'],
            source_type='volume',
            keypair=self.keypair
        )

        # Get server ip and validate authentication
        ip_address = self.get_server_ip(self.instance)
        self.get_remote_client(ip_address).validate_authentication()

        self.terminate_instance(instance=self.instance)
