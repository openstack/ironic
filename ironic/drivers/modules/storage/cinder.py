# Copyright 2016 Hewlett Packard Enterprise Development Company LP.
# Copyright 2016 IBM Corp
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

from oslo_config import cfg
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import strutils
import retrying

from ironic.common import cinder
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import pxe_utils
from ironic.common import states
from ironic.drivers import base
from ironic.drivers import utils
from ironic import objects

CONF = cfg.CONF

LOG = log.getLogger(__name__)

# NOTE(TheJulia): Sets containing known valid types that align with
# _generate_connector() and the volume connection information spec.
VALID_ISCSI_TYPES = ('iqn',)
# TODO(TheJulia): FCoE?
VALID_FC_TYPES = ('wwpn', 'wwnn')


class CinderStorage(base.StorageInterface):
    """A storage_interface driver supporting Cinder."""

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return {}

    def _fail_validation(self, task, reason,
                         exception=exception.InvalidParameterValue):
        msg = (_("Failed to validate cinder storage interface for node "
                 "%(node)s. %(reason)s") %
               {'node': task.node.uuid, 'reason': reason})
        LOG.error(msg)
        raise exception(msg)

    def _validate_connectors(self, task):
        """Validate connector information helper.

        Enumerates through all connector objects, and identifies if
        iSCSI or Fibre Channel connectors are present.

        :param task: The task object.
        :raises InvalidParameterValue: If iSCSI is identified and
                                       iPXE is disabled.
        :raises StorageError: If the number of wwpns is not equal to
                              the number of wwnns
        :returns: Dictionary containing iscsi_found and fc_found
                  keys with boolean values representing if the
                  helper found that connector type configured
                  for the node.
        """

        node = task.node
        iscsi_uuids_found = []
        wwpn_found = 0
        wwnn_found = 0
        ipxe_enabled = pxe_utils.is_ipxe_enabled(task)
        for connector in task.volume_connectors:
            if (connector.type in VALID_ISCSI_TYPES
                    and connector.connector_id is not None):
                iscsi_uuids_found.append(connector.uuid)
                if not ipxe_enabled:
                    msg = _("The [pxe]/ipxe_enabled option must "
                            "be set to True or the boot interface "
                            "must be set to ``ipxe`` to support network "
                            "booting to an iSCSI volume.")
                    self._fail_validation(task, msg)

            if (connector.type in VALID_FC_TYPES
                    and connector.connector_id is not None):
                # NOTE(TheJulia): Unlike iSCSI with cinder, we have no need
                # to warn about multiple IQN entries, since we are able to
                # submit multiple fibre channel WWPN entries.
                if connector.type == 'wwpn':
                    wwpn_found += 1
                if connector.type == 'wwnn':
                    wwnn_found += 1
        if len(iscsi_uuids_found) > 1:
            LOG.warning("Multiple possible iSCSI connectors, "
                        "%(iscsi_uuids_found)s found, for node %(node)s. "
                        "Only the first iSCSI connector, %(iscsi_uuid)s, "
                        "will be utilized.",
                        {'node': node.uuid,
                         'iscsi_uuids_found': iscsi_uuids_found,
                         'iscsi_uuid': iscsi_uuids_found[0]})
        if wwpn_found != wwnn_found:
            msg = _("Cinder requires both wwnn and wwpn entries for FCoE "
                    "connections. There must be a wwpn entry for every wwnn "
                    "entry. There are %(wwpn)d wwpn entries and %(wwnn)s wwnn "
                    "entries.") % {'wwpn': wwpn_found, 'wwnn': wwnn_found}
            self._fail_validation(task, msg, exception.StorageError)
        return {'fc_found': wwpn_found >= 1,
                'iscsi_found': len(iscsi_uuids_found) >= 1}

    def _validate_targets(self, task, found_types, iscsi_boot, fc_boot):
        """Validate target information helper.

        Enumerates through all target objects and identifies if
        iSCSI or Fibre Channel targets are present, and matches the
        connector capability of the node.

        :param task: The task object.
        :param found_types: Dictionary containing boolean values returned
                            from the _validate_connectors helper method.
        :param iscsi_boot: Boolean value indicating if iSCSI boot operations
                           are available.
        :param fc_boot: Boolean value indicating if Fibre Channel boot
                        operations are available.
        :raises: InvalidParameterValue
        """

        for volume in task.volume_targets:
            if volume.volume_id is None:
                msg = (_("volume_id missing from target %(id)s.") %
                       {'id': volume.uuid})
                self._fail_validation(task, msg)

            # NOTE(TheJulia): We should likely consider incorporation
            # of the volume boot_index field, however it may not be
            # relevant to the checks we perform here as in the end a
            # FC volume "attached" to a node is a valid configuration
            # as well.
            # TODO(TheJulia): When we create support in nova to record
            # that a volume attachment is going to take place, we will
            # likely need to match the driver_volume_type field to
            # our generic volume_type field. NB The LVM driver appears
            # to not use that convention in cinder, as it is freeform.
            if volume.volume_type == 'fibre_channel':
                if not fc_boot and volume.boot_index == 0:
                    msg = (_("Volume target %(id)s is configured for "
                             "'fibre_channel', however the capability "
                             "'fibre_channel_boot' is not set on node.") %
                           {'id': volume.uuid})
                    self._fail_validation(task, msg)
                if not found_types['fc_found']:
                    msg = (_("Volume target %(id)s is configured for "
                             "'fibre_channel', however no Fibre Channel "
                             "WWPNs are configured for the node volume "
                             "connectors.") %
                           {'id': volume.uuid})
                    self._fail_validation(task, msg)

            elif volume.volume_type == 'iscsi':
                if not iscsi_boot and volume.boot_index == 0:
                    msg = (_("Volume target %(id)s is configured for "
                             "'iscsi', however the capability 'iscsi_boot' "
                             "is not set for the node.") %
                           {'id': volume.uuid})
                    self._fail_validation(task, msg)
                if not found_types['iscsi_found']:
                    msg = (_("Volume target %(id)s is configured for "
                             "'iscsi', however no iSCSI connectors are "
                             "configured for the node.") %
                           {'id': volume.uuid})
                    self._fail_validation(task, msg)
            else:
                # NOTE(TheJulia); The note below needs to be updated
                # whenever support for additional volume types are added.
                msg = (_("Volume target %(id)s is of an unknown type "
                         "'%(type)s'. Supported types: 'iscsi' or "
                         "'fibre_channel'") %
                       {'id': volume.uuid, 'type': volume.volume_type})
                self._fail_validation(task, msg)

    def validate(self, task):
        """Validate storage_interface configuration for Cinder usage.

        In order to provide fail fast functionality prior to nodes being
        requested to enter the active state, this method performs basic
        checks of the volume connectors, volume targets, and operator
        defined capabilities. These checks are to help ensure that we
        should have a compatible configuration prior to activating the
        node.

        :param task: The task object.
        :raises: InvalidParameterValue If a misconfiguration or mismatch
                 exists that would prevent storage the cinder storage
                 driver from initializing attachments.
        """

        found_types = self._validate_connectors(task)
        node = task.node
        iscsi_boot = strutils.bool_from_string(
            utils.get_node_capability(node, 'iscsi_boot'))
        fc_boot = strutils.bool_from_string(
            utils.get_node_capability(node, 'fibre_channel_boot'))

        # Validate capability configuration against configured volumes
        # such that we raise errors for missing connectors if the
        # boot capability is defined.
        if iscsi_boot and not found_types['iscsi_found']:
            valid_types = ', '.join(VALID_ISCSI_TYPES)
            msg = (_("In order to enable the 'iscsi_boot' capability for "
                     "the node, an associated volume_connector type "
                     "must be valid for iSCSI (%(options)s).") %
                   {'options': valid_types})
            self._fail_validation(task, msg)

        if fc_boot and not found_types['fc_found']:
            valid_types = ', '.join(VALID_FC_TYPES)
            msg = (_("In order to enable the 'fibre_channel_boot' capability "
                     "for the node, an associated volume_connector type must "
                     "be valid for Fibre Channel (%(options)s).") %
                   {'options': valid_types})
            self._fail_validation(task, msg)

        self._validate_targets(task, found_types, iscsi_boot, fc_boot)

    def attach_volumes(self, task):
        """Informs the storage subsystem to attach all volumes for the node.

        :param task: The task object.
        :raises: StorageError If an underlying exception or failure
                              is detected.
        """
        node = task.node
        targets = [target.volume_id for target in task.volume_targets]

        # If there are no targets, then we have nothing to do.
        if not targets:
            return

        connector = self._generate_connector(task)
        try:
            connected = cinder.attach_volumes(task, targets, connector)
        except exception.StorageError as e:
            with excutils.save_and_reraise_exception():
                LOG.error("Error attaching volumes for node %(node)s: "
                          "%(err)s", {'node': node.uuid, 'err': e})
                self.detach_volumes(task, connector=connector,
                                    aborting_attach=True)

        if len(targets) != len(connected):
            LOG.error("The number of volumes defined for node %(node)s does "
                      "not match the number of attached volumes. Attempting "
                      "detach and abort operation.", {'node': node.uuid})
            self.detach_volumes(task, connector=connector,
                                aborting_attach=True)
            raise exception.StorageError(("Mismatch between the number of "
                                          "configured volume targets for "
                                          "node %(uuid)s and the number of "
                                          "completed attachments.") %
                                         {'uuid': node.uuid})

        for volume in connected:
            # Volumes that were already attached are
            # skipped. Updating target volume properties
            # for these volumes is nova's responsibility.
            if not volume.get('already_attached'):
                volume_uuid = volume['data']['ironic_volume_uuid']
                targets = objects.VolumeTarget.list_by_volume_id(task.context,
                                                                 volume_uuid)

                for target in targets:
                    target.properties = volume['data']
                    target.save()

    def detach_volumes(self, task, connector=None, aborting_attach=False):
        """Informs the storage subsystem to detach all volumes for the node.

        This action is retried in case of failure.

        :param task: The task object.
        :param connector: The dictionary representing a node's connectivity
                          as defined by _generate_connector(). Generated
                          if not passed.
        :param aborting_attach: Boolean representing if this detachment
                                was requested to handle aborting a
                                failed attachment
        :raises: StorageError If an underlying exception or failure
                              is detected.
        """
        # TODO(TheJulia): Ideally we should query the cinder API and reconcile
        # or add any missing volumes and initiate detachments.
        node = task.node
        targets = [target.volume_id for target in task.volume_targets]

        # If there are no targets, then we have nothing to do.
        if not targets:
            return

        if not connector:
            connector = self._generate_connector(task)

        @retrying.retry(
            retry_on_exception=lambda e: isinstance(e, exception.StorageError),
            stop_max_attempt_number=CONF.cinder.action_retries + 1,
            wait_fixed=CONF.cinder.action_retry_interval * 1000)
        def detach_volumes():
            try:
                # NOTE(TheJulia): If the node is in ACTIVE state, we can
                # tolerate failures detaching as the node is likely being
                # powered down to cause a detachment event.
                allow_errors = (task.node.provision_state == states.ACTIVE
                                or aborting_attach and outer_args['attempt']
                                > 0)
                cinder.detach_volumes(task, targets, connector,
                                      allow_errors=allow_errors)
            except exception.StorageError as e:
                with excutils.save_and_reraise_exception():
                    # NOTE(TheJulia): In the event that the node is not in
                    # ACTIVE state, we need to fail hard as we need to ensure
                    # all attachments are removed.
                    if aborting_attach:
                        msg_format = ("Error on aborting volume detach for "
                                      "node %(node)s: %(err)s.")
                    else:
                        msg_format = ("Error detaching volume for "
                                      "node %(node)s: %(err)s.")
                    msg = (msg_format) % {'node': node.uuid,
                                          'err': e}
                    if outer_args['attempt'] < CONF.cinder.action_retries:
                        outer_args['attempt'] += 1
                        msg += " Re-attempting detachment."
                        LOG.warning(msg)
                    else:
                        LOG.error(msg)

        # NOTE(mjturek): This dict is used by detach_volumes to determine
        # if this is the last attempt. This is a dict rather than an int
        # so that it is mutable by the inner function. In python3 this is
        # possible with the 'nonlocal' keyword which is unfortunately not
        # available in python2.
        outer_args = {'attempt': 0}
        detach_volumes()

    def should_write_image(self, task):
        """Determines if deploy should perform the image write-out.

        :param task: The task object.
        :returns: True if the deployment write-out process should be
                  executed.
        """
        # NOTE(TheJulia): There is no reason to check if a root volume
        # exists here because if the validation has already been passed
        # then we know that there should be a volume. If there is an
        # image_source, then we should expect to write it out.
        instance_info = task.node.instance_info
        if 'image_source' not in instance_info:
            for volume in task.volume_targets:
                if volume['boot_index'] == 0:
                    return False
        return True

    def _generate_connector(self, task):
        """Generate cinder connector value based upon the node.

        Generates cinder compatible connector information for the purpose of
        attaching volumes. Translation: We need to tell the storage where and
        possibly how we can connect.

        Supports passing iSCSI information in the form of IP and IQN records,
        as well as Fibre Channel information in the form of WWPN addresses.
        Fibre Channel WWNN addresses are also sent, however at present in-tree
        Cinder drivers do not utilize WWNN addresses.

        If multiple connectors exist, the request will be filed with
        MultiPath IO being enabled.

        A warning is logged if an unsupported volume type is encountered.

        :params task: The task object.

        :returns: A dictionary data structure similar to:
                    {'ip': ip,
                     'initiator': iqn,
                     'multipath: True,
                     'wwpns': ['WWN1', 'WWN2']}
        :raises: StorageError upon no valid connector record being identified.
        """
        data = {}
        valid = False
        for connector in task.volume_connectors:
            if 'iqn' in connector.type and 'initiator' not in data:
                data['initiator'] = connector.connector_id
                valid = True
            elif 'ip' in connector.type and 'ip' not in data:
                data['ip'] = connector.connector_id
            # TODO(TheJulia): Translate to, or generate an IQN.
            elif 'wwpn' in connector.type:
                data.setdefault('wwpns', []).append(connector.connector_id)
                valid = True
            elif 'wwnn' in connector.type:
                data.setdefault('wwnns', []).append(connector.connector_id)
                valid = True
            else:
                # TODO(jtaryma): Add handling of type 'mac' with MAC to IP
                #                translation.
                LOG.warning('Node %(node)s has a volume_connector (%(uuid)s) '
                            'defined with an unsupported type: %(type)s.',
                            {'node': task.node.uuid,
                             'uuid': connector.uuid,
                             'type': connector.type})
        if not valid:
            valid_types = ', '.join(VALID_FC_TYPES + VALID_ISCSI_TYPES)
            msg = (_('Insufficient or incompatible volume connection '
                     'records for node %(uuid)s. Valid connector '
                     'types: %(types)s') %
                   {'uuid': task.node.uuid, 'types': valid_types})
            LOG.error(msg)
            raise exception.StorageError(msg)

        # NOTE(TheJulia): Hostname appears to only be used for logging
        # in cinder drivers, however that may not always be true, and
        # may need to change over time.
        data['host'] = task.node.uuid
        if len(task.volume_connectors) > 1 and len(data) > 1:
            data['multipath'] = True

        return data
