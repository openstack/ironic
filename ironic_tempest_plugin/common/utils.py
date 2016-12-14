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


def get_node(client, node_id=None, instance_uuid=None):
    """Get a node by its identifier or instance UUID.

    If both node_id and instance_uuid specified, node_id will be used.

    :param client: an instance of tempest plugin BaremetalClient.
    :param node_id: identifier (UUID or name) of the node.
    :param instance_uuid: UUID of the instance.
    :returns: the requested node.
    :raises: AssertionError, if neither node_id nor instance_uuid was provided
    """
    assert node_id or instance_uuid, ('Either node or instance identifier '
                                      'has to be provided.')
    if node_id:
        _, body = client.show_node(node_id)
        return body
    elif instance_uuid:
        _, body = client.show_node_by_instance_uuid(instance_uuid)
        if body['nodes']:
            return body['nodes'][0]
