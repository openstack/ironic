# Copyright 2016 Hewlett Packard Enterprise Development LP.
# Copyright 2016 Universidade Federal de Campina Grande
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
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _, _LE, _LI, _LW
from ironic.common import states
from ironic.drivers.modules.oneview import common

LOG = logging.getLogger(__name__)

oneview_exception = importutils.try_import('oneview_client.exceptions')
oneview_utils = importutils.try_import('oneview_client.utils')


def get_properties():
    return common.COMMON_PROPERTIES


def prepare(task):
    """Applies Server Profile and update the node when preparing.

    This method is responsible for applying a Server Profile to the Server
    Hardware and add the uri of the applied Server Profile in the node's
    'applied_server_profile_uri' field on properties/capabilities.

    :param task: A TaskManager object
    :raises InstanceDeployFailure: If the node doesn't have the needed OneView
            informations, if Server Hardware is in use by an OneView user, or
            if the Server Profile can't be applied.

    """
    if task.node.provision_state == states.DEPLOYING:
        try:
            instance_display_name = task.node.instance_info.get('display_name')
            instance_uuid = task.node.instance_uuid
            server_profile_name = (
                "%(instance_name)s [%(instance_uuid)s]" %
                {"instance_name": instance_display_name,
                 "instance_uuid": instance_uuid}
            )
            _allocate_server_hardware_to_ironic(task.node, server_profile_name)
        except exception.OneViewError as e:
            raise exception.InstanceDeployFailure(node=task.node.uuid,
                                                  reason=e)


def tear_down(task):
    """Remove Server profile and update the node when tear down.

    This method is responsible for power a Server Hardware off, remove a Server
    Profile from the Server Hardware and remove the uri of the applied Server
    Profile from the node's 'applied_server_profile_uri' in
    properties/capabilities.

    :param task: A TaskManager object
    :raises InstanceDeployFailure: If node has no uri of applied Server
            Profile, or if some error occur while deleting Server Profile.

    """
    try:
        _deallocate_server_hardware_from_ironic(task.node)
    except exception.OneViewError as e:
        raise exception.InstanceDeployFailure(node=task.node.uuid, reason=e)


def prepare_cleaning(task):
    """Applies Server Profile and update the node when preparing cleaning.

    This method is responsible for applying a Server Profile to the Server
    Hardware and add the uri of the applied Server Profile in the node's
    'applied_server_profile_uri' field on properties/capabilities.

    :param task: A TaskManager object
    :raises NodeCleaningFailure: If the node doesn't have the needed OneView
            informations, if Server Hardware is in use by an OneView user, or
            if the Server Profile can't be applied.

    """
    try:
        server_profile_name = "Ironic Cleaning [%s]" % task.node.uuid
        _allocate_server_hardware_to_ironic(task.node, server_profile_name)
    except exception.OneViewError as e:
        oneview_error = common.SERVER_HARDWARE_ALLOCATION_ERROR
        driver_internal_info = task.node.driver_internal_info
        driver_internal_info['oneview_error'] = oneview_error
        task.node.driver_internal_info = driver_internal_info
        task.node.save()
        raise exception.NodeCleaningFailure(node=task.node.uuid,
                                            reason=e)


def tear_down_cleaning(task):
    """Remove Server profile and update the node when tear down cleaning.

    This method is responsible for power a Server Hardware off, remove a Server
    Profile from the Server Hardware and remove the uri of the applied Server
    Profile from the node's 'applied_server_profile_uri' in
    properties/capabilities.

    :param task: A TaskManager object
    :raises NodeCleaningFailure: If node has no uri of applied Server Profile,
            or if some error occur while deleting Server Profile.

    """
    try:
        _deallocate_server_hardware_from_ironic(task.node)
    except exception.OneViewError as e:
        raise exception.NodeCleaningFailure(node=task.node.uuid, reason=e)


def is_node_in_use_by_oneview(node):
    """Check if node is in use by OneView user.

    :param node: an ironic node object
    :returns: Boolean value. True if node is in use by OneView,
              False otherwise.
    :raises OneViewError: if not possible to get OneView's informations
             for the given node, if not possible to retrieve Server Hardware
             from OneView.

    """
    oneview_info = common.get_oneview_info(node)

    oneview_client = common.get_oneview_client()

    sh_uuid = oneview_utils.get_uuid_from_uri(
        oneview_info.get("server_hardware_uri")
    )

    try:
        server_hardware = oneview_client.get_server_hardware_by_uuid(
            sh_uuid
        )
    except oneview_exception.OneViewResourceNotFoundError as e:
        msg = (_("Error while obtaining Server Hardware from node "
                 "%(node_uuid)s. Error: %(error)s") %
               {'node_uuid': node.uuid, 'error': e})
        raise exception.OneViewError(error=msg)

    applied_sp_uri = (
        node.driver_info.get('applied_server_profile_uri')
    )

    # Check if Profile exists in Oneview and it is different of the one
    # applied by ironic
    if (server_hardware.server_profile_uri not in (None, '') and
            applied_sp_uri != server_hardware.server_profile_uri):

        LOG.warning(_LW("Node %s is already in use by OneView."),
                    node.uuid)

        return True

    else:
        LOG.debug(_(
            "Hardware %(hardware_uri)s is free for use by "
            "ironic on node %(node_uuid)s."),
            {"hardware_uri": server_hardware.uri,
             "node_uuid": node.uuid})

        return False


def _add_applied_server_profile_uri_field(node, applied_profile):
    """Adds the applied Server Profile uri to a node.

    :param node: an ironic node object

    """
    driver_info = node.driver_info
    driver_info['applied_server_profile_uri'] = applied_profile.uri
    node.driver_info = driver_info
    node.save()


def _del_applied_server_profile_uri_field(node):
    """Delete the applied Server Profile uri from a node if it exists.

    :param node: an ironic node object

    """
    driver_info = node.driver_info
    driver_info.pop('applied_server_profile_uri', None)
    node.driver_info = driver_info
    node.save()


def _allocate_server_hardware_to_ironic(node, server_profile_name):
    """Allocate Server Hardware to ironic.

    :param node: an ironic node object
    :param server_profile_name: a formatted string with the Server Profile
           name
    :raises OneViewError: if an error occurs while allocating the Server
            Hardware to ironic

    """
    node_in_use_by_oneview = is_node_in_use_by_oneview(node)

    if not node_in_use_by_oneview:

        oneview_info = common.get_oneview_info(node)

        applied_sp_uri = node.driver_info.get('applied_server_profile_uri')

        sh_uuid = oneview_utils.get_uuid_from_uri(
            oneview_info.get("server_hardware_uri")
        )
        spt_uuid = oneview_utils.get_uuid_from_uri(
            oneview_info.get("server_profile_template_uri")
        )
        oneview_client = common.get_oneview_client()
        server_hardware = oneview_client.get_server_hardware_by_uuid(sh_uuid)

        # Don't have Server Profile on OneView but has
        # `applied_server_profile_uri` on driver_info
        if (server_hardware.server_profile_uri in (None, '') and
                applied_sp_uri is not (None, '')):

            _del_applied_server_profile_uri_field(node)
            LOG.info(_LI(
                "Inconsistent 'applied_server_profile_uri' parameter "
                "value in driver_info. There is no Server Profile "
                "applied to node %(node_uuid)s. Value deleted."),
                {"node_uuid": node.uuid}
            )

        # applied_server_profile_uri exists and is equal to Server profile
        # applied on Hardware. Do not apply again.
        if (applied_sp_uri and server_hardware.server_profile_uri and
            server_hardware.server_profile_uri == applied_sp_uri):
            LOG.info(_LI(
                "The Server Profile %(applied_sp_uri)s was already applied "
                "by ironic on node %(node_uuid)s. Reusing."),
                {"node_uuid": node.uuid, "applied_sp_uri": applied_sp_uri}
            )
            return

        try:
            applied_profile = oneview_client.clone_template_and_apply(
                server_profile_name, sh_uuid, spt_uuid
            )
            _add_applied_server_profile_uri_field(node, applied_profile)

            LOG.info(
                _LI("Server Profile %(server_profile_uuid)s was successfully"
                    " applied to node %(node_uuid)s."),
                {"node_uuid": node.uuid,
                 "server_profile_uuid": applied_profile.uri}
            )

        except oneview_exception.OneViewServerProfileAssignmentError as e:
            LOG.error(_LE("An error occurred during allocating server "
                          "hardware to ironic during prepare: %s"), e)
            raise exception.OneViewError(error=e)
    else:
        msg = (_("Node %s is already in use by OneView.") %
               node.uuid)

        raise exception.OneViewError(error=msg)


def _deallocate_server_hardware_from_ironic(node):
    """Deallocate Server Hardware from ironic.

    :param node: an ironic node object
    :raises OneViewError: if an error occurs while deallocating the Server
            Hardware to ironic

    """
    oneview_info = common.get_oneview_info(node)

    oneview_client = common.get_oneview_client()
    oneview_client.power_off(oneview_info)

    applied_sp_uuid = oneview_utils.get_uuid_from_uri(
        oneview_info.get('applied_server_profile_uri')
    )

    try:
        oneview_client.delete_server_profile(applied_sp_uuid)
        _del_applied_server_profile_uri_field(node)

        LOG.info(
            _LI("Server Profile %(server_profile_uuid)s was successfully"
                " deleted from node %(node_uuid)s."
                ),
            {"node_uuid": node.uuid, "server_profile_uuid": applied_sp_uuid}
        )
    except oneview_exception.OneViewException as e:

        msg = (_("Error while deleting applied Server Profile from node "
                 "%(node_uuid)s. Error: %(error)s") %
               {'node_uuid': node.uuid, 'error': e})

        raise exception.OneViewError(
            node=node.uuid, reason=msg
        )
