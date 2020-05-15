# Copyright 2016 Hewlett Packard Enterprise Development Company LP.
# Copyright 2017 IBM Corp
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

import datetime
import json

from cinderclient import exceptions as cinder_exceptions
from cinderclient.v3 import client
from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import keystone
from ironic.conf import CONF

LOG = log.getLogger(__name__)

AVAILABLE = 'available'
IN_USE = 'in-use'

_CINDER_SESSION = None


def _get_cinder_session():
    global _CINDER_SESSION
    if not _CINDER_SESSION:
        _CINDER_SESSION = keystone.get_session('cinder')
    return _CINDER_SESSION


def get_client(context):
    """Get a cinder client connection.

    :param context: request context,
                    instance of ironic.common.context.RequestContext
    :returns: A cinder client.
    """
    service_auth = keystone.get_auth('cinder')
    session = _get_cinder_session()

    # TODO(pas-ha) use versioned endpoint data to select required
    # cinder api version
    cinder_url = keystone.get_endpoint('cinder', session=session,
                                       auth=service_auth)
    # TODO(pas-ha) investigate possibility of passing a user context here,
    # similar to what neutron/glance-related code does
    # NOTE(pas-ha) cinderclient has both 'connect_retries' (passed to
    # ksa.Adapter) and 'retries' (used in its subclass of ksa.Adapter) options.
    # The first governs retries on establishing the HTTP connection,
    # the second governs retries on OverLimit exceptions from API.
    # The description of [cinder]/retries fits the first,
    # so this is what we pass.
    return client.Client(session=session, auth=service_auth,
                         endpoint_override=cinder_url,
                         connect_retries=CONF.cinder.retries,
                         global_request_id=context.global_id)


def is_volume_available(volume):
    """Check if a volume is available for a connection.

    :param volume: The object representing the volume.

    :returns: Boolean if volume is available.
    """
    return (volume.status == AVAILABLE
            or (volume.status == IN_USE
                and volume.multiattach))


def is_volume_attached(node, volume):
    """Check if a volume is attached to the supplied node.

    :param node: The object representing the node.
    :param volume: The object representing the volume from cinder.

    :returns: Boolean indicating if the volume is attached. Returns True if
              cinder shows the volume as presently attached, otherwise
              returns False.
    """
    attachments = volume.attachments
    if attachments is not None:
        for attachment in attachments:
            if attachment.get('server_id') in (node.instance_uuid, node.uuid):
                return True
    return False


def _get_attachment_id(node, volume):
    """Return the attachment ID for a node to a volume.

    :param node: The object representing the node.
    :param volume: The object representing the volume from cinder.

    :returns: The UUID of the attachment in cinder, if present. Otherwise
        returns None.
    """
    # NOTE(TheJulia): This is under the belief that there is a single
    # attachment for each node that represents all possible attachment
    # information as multiple types can be submitted in a single request.
    attachments = volume.attachments
    if attachments is None:
        return
    for attachment in attachments:
        if attachment.get('server_id') in (node.instance_uuid, node.uuid):
            return attachment.get('attachment_id')


def _create_metadata_dictionary(node, action):
    """Create a volume metadata dictionary.

    :param node: Object representing a node.
    :param action: String value representing the last action.

    :returns: Dictionary with a json representation of
              the metadata to send to cinder as it does
              not support nested dictionaries.
    """
    label = "ironic_node_%s" % node.uuid
    data = {'instance_uuid': node.instance_uuid or node.uuid,
            'last_seen': datetime.datetime.utcnow().isoformat(),
            'last_action': action}
    return {label: json.dumps(data)}


def _init_client(task):
    """Obtain cinder client and return it for use.

    :param task: TaskManager instance representing the operation.

    :returns: A cinder client.
    :raises: StorageError If an exception is encountered creating the client.
    """
    node = task.node
    try:
        return get_client(task.context)
    except Exception as e:
        msg = (_('Failed to initialize cinder client for operations on node '
                 '%(uuid)s: %(err)s') % {'uuid': node.uuid, 'err': e})
        LOG.error(msg)
        raise exception.StorageError(msg)


def attach_volumes(task, volume_list, connector):
    """Attach volumes to a node.

       Enumerate through the provided list of volumes and attach the volumes
       to the node defined in the task utilizing the provided connector
       information.

       If an attachment appears to already exist, we will skip attempting to
       attach the volume. If use of the volume fails, a user may need to
       remove any lingering pre-existing/unused attachment records since
       we have no way to validate if the connector profile data differs
       from what was provided to cinder.

       :param task: TaskManager instance representing the operation.
       :param volume_list: List of volume_id UUID values representing volumes.
       :param connector: Dictionary object representing the node sufficiently
                         to attach a volume. This value can vary based upon
                         the node's configuration, capability, and ultimately
                         the back-end storage driver. As cinder was designed
                         around iSCSI, the 'ip' and 'initiator' keys are
                         generally expected by cinder drivers.
                         For FiberChannel, the key 'wwpns' can be used
                         with a list of port addresses.
                         Some drivers support a 'multipath' boolean key,
                         although it is generally False. The 'host' key
                         is generally used for logging by drivers.
                         Example::

                             {
                             'wwpns': ['list','of','port','wwns'],
                             'ip': 'ip address',
                             'initiator': 'initiator iqn',
                             'multipath': False,
                             'host': 'hostname',
                             }

       :raises: StorageError If storage subsystem exception is raised.
       :returns: List of connected volumes, including volumes that were
                 already connected to desired nodes. The returned list
                 can be relatively consistent depending on the end storage
                 driver that the volume is configured for, however
                 the 'driver_volume_type' key should not be relied upon
                 as it is a free-form value returned by the driver.
                 The accompanying 'data' key contains the actual target
                 details which will indicate either target WWNs and a LUN
                 or a target portal and IQN. It also always contains
                 volume ID in cinder and ironic. Except for these two IDs,
                 each driver may return somewhat different data although
                 the same keys are used if the target is FC or iSCSI,
                 so any logic should be based upon the returned contents.
                 For already attached volumes, the structure contains
                 'already_attached': True key-value pair. In such case,
                 connection info for the node is already in the database,
                 'data' structure contains only basic info of volume ID in
                 cinder and ironic, so any logic based on that should
                 retrieve it from the database. Example::

                   [{
                   'driver_volume_type': 'fibre_channel'
                   'data': {
                       'encrypted': False,
                       'target_lun': 1,
                       'target_wwn': ['1234567890123', '1234567890124'],
                       'volume_id': '00000000-0000-0000-0000-000000000001',
                       'ironic_volume_id':
                       '11111111-0000-0000-0000-000000000001'}
                   },
                   {
                   'driver_volume_type': 'iscsi'
                   'data': {
                       'target_iqn': 'iqn.2010-10.org.openstack:volume-000002',
                       'target_portal': '127.0.0.0.1:3260',
                       'volume_id': '00000000-0000-0000-0000-000000000002',
                       'ironic_volume_id':
                       '11111111-0000-0000-0000-000000000002',
                       'target_lun': 2}
                   },
                   {
                   'already_attached': True
                   'data': {
                       'volume_id': '00000000-0000-0000-0000-000000000002',
                       'ironic_volume_id':
                       '11111111-0000-0000-0000-000000000002'}
                   }]
       """
    node = task.node
    client = _init_client(task)

    connected = []
    for volume_id in volume_list:
        try:
            volume = client.volumes.get(volume_id)
        except cinder_exceptions.ClientException as e:
            msg = (_('Failed to get volume %(vol_id)s from cinder for node '
                     '%(uuid)s: %(err)s') %
                   {'vol_id': volume_id, 'uuid': node.uuid, 'err': e})
            LOG.error(msg)
            raise exception.StorageError(msg)
        if is_volume_attached(node, volume):
            LOG.debug('Volume %(vol_id)s is already attached to node '
                      '%(uuid)s. Skipping attachment.',
                      {'vol_id': volume_id, 'uuid': node.uuid})

            # NOTE(jtaryma): Actual connection info of already connected
            # volume will be provided by nova. Adding this dictionary to
            # 'connected' list so it contains also already connected volumes.
            connection = {'data': {'ironic_volume_uuid': volume.id,
                                   'volume_id': volume_id},
                          'already_attached': True}
            connected.append(connection)
            continue

        try:
            client.volumes.reserve(volume_id)
        except cinder_exceptions.ClientException as e:
            msg = (_('Failed to reserve volume %(vol_id)s for node %(node)s: '
                     '%(err)s)') %
                   {'vol_id': volume_id, 'node': node.uuid, 'err': e})
            LOG.error(msg)
            raise exception.StorageError(msg)

        try:
            # Provide connector information to cinder
            connection = client.volumes.initialize_connection(volume_id,
                                                              connector)
        except cinder_exceptions.ClientException as e:
            msg = (_('Failed to initialize connection for volume '
                     '%(vol_id)s to node %(node)s: %(err)s') %
                   {'vol_id': volume_id, 'node': node.uuid, 'err': e})
            LOG.error(msg)
            raise exception.StorageError(msg)

        if 'volume_id' not in connection['data']:
            connection['data']['volume_id'] = volume_id
        connection['data']['ironic_volume_uuid'] = volume.id
        connected.append(connection)

        LOG.info('Successfully initialized volume %(vol_id)s for '
                 'node %(node)s.', {'vol_id': volume_id, 'node': node.uuid})

        instance_uuid = node.instance_uuid or node.uuid

        try:
            # NOTE(TheJulia): The final step of the cinder volume
            # attachment process involves updating the volume
            # database record to indicate that the attachment has
            # been completed, which moves the volume to the
            # 'attached' state. This action also sets a mountpoint
            # for the volume, as cinder requires a mointpoint to
            # attach the volume, thus we send 'mount_volume'.
            client.volumes.attach(volume_id, instance_uuid,
                                  'ironic_mountpoint')

        except cinder_exceptions.ClientException as e:
            msg = (_('Failed to inform cinder that the attachment for volume '
                     '%(vol_id)s for node %(node)s has been completed: '
                     '%(err)s') %
                   {'vol_id': volume_id, 'node': node.uuid, 'err': e})
            LOG.error(msg)
            raise exception.StorageError(msg)

        try:
            # Set metadata to assist a user in volume identification
            client.volumes.set_metadata(
                volume_id,
                _create_metadata_dictionary(node, 'attached'))

        except cinder_exceptions.ClientException as e:
            LOG.warning('Failed to update volume metadata for volume '
                        '%(vol_id)s for node %(node)s: %(err)s',
                        {'vol_id': volume_id, 'node': node.uuid, 'err': e})
    return connected


def detach_volumes(task, volume_list, connector, allow_errors=False):
    """Detach a list of volumes from a provided connector detail.

       Enumerates through a provided list of volumes and issues
       detachment requests utilizing the connector information
       that describes the node.

       :param task: The TaskManager task representing the request.
       :param volume_list: The list of volume id values to detach.
       :param connector: Dictionary object representing the node sufficiently
                         to attach a volume. This value can vary based upon
                         the node's configuration, capability, and ultimately
                         the back-end storage driver. As cinder was designed
                         around iSCSI, the 'ip' and 'initiator' keys are
                         generally expected. For FiberChannel, the key
                         'wwpns' can be used with a list of port addresses.
                         Some drivers support a 'multipath' boolean key,
                         although it is generally False. The 'host' key
                         is generally used for logging by drivers.
                         Example::

                             {
                             'wwpns': ['list','of','port','wwns']
                             'ip': 'ip address',
                             'initiator': 'initiator iqn',
                             'multipath': False,
                             'host': 'hostname'
                             }

       :param allow_errors: Boolean value governing if errors that are returned
                            are treated as warnings instead of exceptions.
                            Default False.
       :raises: StorageError
    """
    def _handle_errors(msg):
        if allow_errors:
            LOG.warning(msg)
        else:
            LOG.error(msg)
            raise exception.StorageError(msg)

    client = _init_client(task)
    node = task.node

    for volume_id in volume_list:
        try:
            volume = client.volumes.get(volume_id)
        except cinder_exceptions.ClientException as e:
            _handle_errors(_('Failed to get volume %(vol_id)s from cinder for '
                             'node %(node)s: %(err)s') %
                           {'vol_id': volume_id, 'node': node.uuid, 'err': e})
            # If we do not raise an exception, we should move on to
            # the next volume since the volume could have been deleted
            # before we're attempting to power off the node.
            continue

        if not is_volume_attached(node, volume):
            LOG.debug('Volume %(vol_id)s is not attached to node '
                      '%(uuid)s: Skipping detachment.',
                      {'vol_id': volume_id, 'uuid': node.uuid})
            continue

        try:
            client.volumes.begin_detaching(volume_id)
        except cinder_exceptions.ClientException as e:
            _handle_errors(_('Failed to request detach for volume %(vol_id)s '
                             'from cinder for node %(node)s: %(err)s') %
                           {'vol_id': volume_id, 'node': node.uuid, 'err': e}
                           )
            # NOTE(jtaryma): This operation only updates the volume status, so
            # we can proceed the process of actual detachment if allow_errors
            # is set to True.
        try:
            # Remove the attachment
            client.volumes.terminate_connection(volume_id, connector)
        except cinder_exceptions.ClientException as e:
            _handle_errors(_('Failed to detach volume %(vol_id)s from node '
                             '%(node)s: %(err)s') %
                           {'vol_id': volume_id, 'node': node.uuid, 'err': e})
            # Skip proceeding with this method if we're not raising
            # errors. This will leave the volume in the detaching
            # state, but in that case something very unexpected
            # has occurred.
            continue

        # Attempt to identify the attachment id value to provide
        # accessible relationship data to leave in the cinder API
        # to enable reconciliation.
        attachment_id = _get_attachment_id(node, volume)
        try:
            # Update the API attachment record
            client.volumes.detach(volume_id, attachment_id)
        except cinder_exceptions.ClientException as e:
            _handle_errors(_('Failed to inform cinder that the detachment for '
                             'volume %(vol_id)s from node %(node)s has been '
                             'completed: %(err)s') %
                           {'vol_id': volume_id, 'node': node.uuid, 'err': e})
            # NOTE(jtaryma): This operation mainly updates the volume status,
            # so we can proceed the process of volume updating if allow_errors
            # is set to True.
        try:
            # Set metadata to assist in volume identification.
            client.volumes.set_metadata(
                volume_id,
                _create_metadata_dictionary(node, 'detached'))
        except cinder_exceptions.ClientException as e:
            LOG.warning('Failed to update volume %(vol_id)s metadata for node '
                        '%(node)s: %(err)s',
                        {'vol_id': volume_id, 'node': node.uuid, 'err': e})
