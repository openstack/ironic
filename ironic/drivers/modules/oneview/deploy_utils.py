# Copyright (2015-2017) Hewlett Packard Enterprise Development LP
# Copyright (2015-2017) Universidade Federal de Campina Grande
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

import operator

from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.drivers.modules.oneview import common

LOG = logging.getLogger(__name__)

client_exception = importutils.try_import('hpOneView.exceptions')


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
            allocate_server_hardware_to_ironic(task.node, server_profile_name)
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
        deallocate_server_hardware_from_ironic(task)
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
        allocate_server_hardware_to_ironic(task.node, server_profile_name)
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
        deallocate_server_hardware_from_ironic(task)
    except exception.OneViewError as e:
        raise exception.NodeCleaningFailure(node=task.node.uuid, reason=e)


def _create_profile_from_template(
        oneview_client, server_profile_name,
        server_hardware_uri, server_profile_template):
    """Create a server profile from a server profile template.

    :param oneview_client: an HPE OneView Client instance
    :param server_profile_name: the name of the new server profile
    :param server_hardware_uri: the server_hardware assigned to server profile
    :param server_profile_template: the server profile template id or uri
    :returns: The new server profile generated with the name and server
              hardware passed on parameters
    :raises OneViewError: if the communication with OneView fails

    """
    server_profile = oneview_client.server_profile_templates.get_new_profile(
        server_profile_template
    )
    server_profile['name'] = server_profile_name
    server_profile['serverHardwareUri'] = server_hardware_uri
    server_profile['serverProfileTemplateUri'] = ""
    try:
        return oneview_client.server_profiles.create(server_profile)
    except client_exception.HPOneViewException as e:
        msg = (_("Error while creating a Server Profile for Server Hardware: "
                 "%(sh_uri)s. Error: %(error)s") %
               {'sh_uri': server_hardware_uri, 'error': e})
        raise exception.OneViewError(error=msg)


def _is_node_in_use(server_hardware, applied_sp_uri, by_oneview=False):
    """Check if node is in use by ironic or by OneView.

    :param server_hardware: Server Hardware object.
    :param applied_sp_uri: Server Profile URI applied in the node.
    :param by_oneview: Boolean value. True when want to verify if node is in
                       use by OneView. False to verify if node is in use by
                       ironic.
    :returns: Boolean value. True if by_oneview param is also True and node is
              in use by OneView, False otherwise. True if by_oneview param is
              False and node is in use by ironic, False otherwise.
    """
    operation = operator.ne if by_oneview else operator.eq
    server_profile_uri = server_hardware.get('serverProfileUri')
    return (server_profile_uri
            and operation(applied_sp_uri, server_profile_uri))


def is_node_in_use_by_oneview(node):
    """Check if node is in use by OneView user.

    :param node: an ironic node object.
    :returns: Boolean value. True if node is in use by OneView,
              False otherwise.
    :raises OneViewError: if not possible to get OneView's informations
            for the given node, if not possible to retrieve Server Hardware
            from OneView.
    """
    oneview_client = common.get_hponeview_client()
    positive = _("Node '%s' is in use by OneView.") % node.uuid
    negative = _("Node '%s' is not in use by OneView.") % node.uuid

    def predicate(server_hardware, applied_sp_uri):
        # Check if Profile exists in Oneview and it is different of the one
        # applied by ironic
        return _is_node_in_use(server_hardware, applied_sp_uri,
                               by_oneview=True)

    return _check_applied_server_profile(oneview_client, node,
                                         predicate, positive, negative)


def is_node_in_use_by_ironic(node):
    """Check if node is in use by ironic in OneView.

    :param node: an ironic node object.
    :returns: Boolean value. True if node is in use by ironic,
              False otherwise.
    :raises OneViewError: if not possible to get OneView's information
            for the given node, if not possible to retrieve Server Hardware
            from OneView.
    """
    oneview_client = common.get_hponeview_client()
    positive = _("Node '%s' is in use by Ironic.") % node.uuid
    negative = _("Node '%s' is not in use by Ironic.") % node.uuid

    def predicate(server_hardware, applied_sp_uri):
        # Check if Profile exists in Oneview and it is equals of the one
        # applied by ironic
        return _is_node_in_use(server_hardware, applied_sp_uri,
                               by_oneview=False)

    return _check_applied_server_profile(oneview_client, node,
                                         predicate, positive, negative)


def _check_applied_server_profile(oneview_client, node,
                                  predicate, positive, negative):
    """Check if node is in use by ironic in OneView.

    :param oneview_client: an instance of the OneView client
    :param node: an ironic node object
    :returns: Boolean value. True if node is in use by ironic,
              False otherwise.
    :raises OneViewError: if not possible to get OneView's information
             for the given node, if not possible to retrieve Server Hardware
             from OneView.

    """
    oneview_info = common.get_oneview_info(node)
    try:
        server_hardware = oneview_client.server_hardware.get(
            oneview_info.get('server_hardware_uri')
        )
    except client_exception.HPOneViewResourceNotFound as e:
        msg = (_("Error while obtaining Server Hardware from node "
                 "%(node_uuid)s. Error: %(error)s") %
               {'node_uuid': node.uuid, 'error': e})
        raise exception.OneViewError(error=msg)

    applied_sp_uri = node.driver_info.get('applied_server_profile_uri')
    result = predicate(server_hardware, applied_sp_uri)

    if result:
        LOG.debug(positive)
    else:
        LOG.debug(negative)

    return result


def _add_applied_server_profile_uri_field(node, applied_profile):
    """Adds the applied Server Profile uri to a node.

    :param node: an ironic node object
    :param applied_profile: the server_profile that will be applied to node
    """
    driver_info = node.driver_info
    driver_info['applied_server_profile_uri'] = applied_profile.get('uri')
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


def allocate_server_hardware_to_ironic(node, server_profile_name):
    """Allocate Server Hardware to ironic.

    :param node: an ironic node object.
    :param server_profile_name: a formatted string with the Server Profile
           name.
    :raises OneViewError: if an error occurs while allocating the Server
            Hardware to ironic or the node is already in use by OneView.
    """
    oneview_client = common.get_hponeview_client()
    node_in_use_by_oneview = is_node_in_use_by_oneview(node)

    if not node_in_use_by_oneview:

        oneview_info = common.get_oneview_info(node)

        applied_sp_uri = node.driver_info.get('applied_server_profile_uri')
        sh_uri = oneview_info.get("server_hardware_uri")
        spt_uri = oneview_info.get("server_profile_template_uri")
        server_hardware = oneview_client.server_hardware.get(sh_uri)

        if not server_hardware:
            msg = _("An error occurred during allocating server hardware to "
                    "ironic. Server hardware: %s not found.") % sh_uri
            raise exception.OneViewError(error=msg)

        # Don't have Server Profile on OneView but has
        # `applied_server_profile_uri` on driver_info
        if not server_hardware.get('serverProfileUri') and applied_sp_uri:

            _del_applied_server_profile_uri_field(node)
            LOG.info(
                "Inconsistent 'applied_server_profile_uri' parameter "
                "value in driver_info. There is no Server Profile "
                "applied to node %(node_uuid)s. Value deleted.",
                {"node_uuid": node.uuid}
            )

        # applied_server_profile_uri exists and is equal to Server profile
        # applied on Hardware. Do not apply again.
        if (applied_sp_uri and server_hardware.get(
                'serverProfileUri') == applied_sp_uri):
            LOG.info(
                "The Server Profile %(applied_sp_uri)s was already applied "
                "by ironic on node %(node_uuid)s. Reusing.",
                {"node_uuid": node.uuid, "applied_sp_uri": applied_sp_uri}
            )
            return

        try:
            applied_profile = _create_profile_from_template(
                oneview_client, server_profile_name, sh_uri, spt_uri
            )
            _add_applied_server_profile_uri_field(node, applied_profile)

            LOG.info(
                "Server Profile %(server_profile_uuid)s was successfully"
                " applied to node %(node_uuid)s.",
                {"node_uuid": node.uuid,
                 "server_profile_uuid": applied_profile.get('uri')}
            )

        except client_exception.HPOneViewInvalidResource as e:
            LOG.error("An error occurred during allocating server "
                      "hardware to ironic during prepare: %s", e)
            raise exception.OneViewError(error=e)
    else:
        msg = _("Node %s is already in use by OneView.") % node.uuid
        raise exception.OneViewError(error=msg)


def deallocate_server_hardware_from_ironic(task):
    """Deallocate Server Hardware from ironic.

    :param task: a TaskManager object
    :raises OneViewError: if an error occurs while deallocating the Server
            Hardware to ironic

    """
    node = task.node
    oneview_client = common.get_hponeview_client()

    if is_node_in_use_by_ironic(node):
        oneview_info = common.get_oneview_info(node)
        server_profile_uri = oneview_info.get('applied_server_profile_uri')

        try:
            task.driver.power.set_power_state(task, states.POWER_OFF)
            oneview_client.server_profiles.delete(server_profile_uri)
            _del_applied_server_profile_uri_field(node)
            LOG.info("Server Profile %(server_profile_uri)s was deleted "
                     "from node %(node_uuid)s in OneView.",
                     {'server_profile_uri': server_profile_uri,
                      'node_uuid': node.uuid})
        except client_exception.HPOneViewException as e:
            msg = (_("Error while deleting applied Server Profile from node "
                     "%(node_uuid)s. Error: %(error)s") %
                   {'node_uuid': node.uuid, 'error': e})
            raise exception.OneViewError(error=msg)

    else:
        LOG.warning("Cannot deallocate node %(node_uuid)s "
                    "in OneView because it is not in use by "
                    "ironic.", {'node_uuid': node.uuid})
