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


import time

from tempest.lib.common.utils import misc as misc_utils
from tempest.lib import exceptions as lib_exc


def wait_for_bm_node_status(client, node_id, attr, status, timeout=None,
                            interval=None):
    """Waits for a baremetal node attribute to reach given status.

    :param client: an instance of tempest plugin BaremetalClient.
    :param node_id: identifier of the node.
    :param attr: node's API-visible attribute to check status of.
    :param status: desired status.
    :param timeout: the timeout after which the check is considered as failed.
        Defaults to client.build_timeout.
    :param interval: an interval between show_node calls for status check.
        Defaults to client.build_interval.

    The client should have a show_node(node_id) method to get the node.
    """
    if timeout is None:
        timeout = client.build_timeout
    if interval is None:
        interval = client.build_interval
    if timeout < 0 or interval < 0:
        raise lib_exc.InvalidConfiguration(
            'timeout and interval should be >= 0 or None, current values are: '
            '%(timeout)s, %(interval)s respectively.' % dict(timeout=timeout,
                                                             interval=interval)
        )

    start = int(time.time())
    _, node = client.show_node(node_id)

    while node[attr] != status:
        status_curr = node[attr]
        if status_curr == status:
            return

        if int(time.time()) - start >= timeout:
            message = ('Node %(node_id)s failed to reach %(attr)s=%(status)s '
                       'within the required time (%(timeout)s s).' %
                       {'node_id': node_id,
                        'attr': attr,
                        'status': status,
                        'timeout': client.build_timeout})
            message += ' Current state of %s: %s.' % (attr, status_curr)
            caller = misc_utils.find_test_caller()
            if caller:
                message = '(%s) %s' % (caller, message)
            raise lib_exc.TimeoutException(message)

        time.sleep(interval)
        _, node = client.show_node(node_id)
