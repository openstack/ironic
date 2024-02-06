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

import os
import time

import eventlet
from eventlet import event
from ironic_lib import metrics_utils
from oslo_log import log

from ironic.common.i18n import _
from ironic.common import states
from ironic.conf import CONF
from ironic.db import api as dbapi
from ironic.pxe_filter import dnsmasq

LOG = log.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)

_START_DELAY = 1.0


class PXEFilterManager:
    topic = 'ironic.pxe_filter'

    def __init__(self, host):
        self.host = host or CONF.host
        self._started = False

    def prepare_host(self):
        if not CONF.pxe_filter.dhcp_hostsdir:
            raise RuntimeError(_('The [pxe_filter]dhcp_hostsdir option '
                                 'is required'))
        if not os.path.isdir(CONF.pxe_filter.dhcp_hostsdir):
            # FIXME(dtantsur): should we try to create it? The permissions will
            # most likely be wrong.
            raise RuntimeError(_('The path in [pxe_filter]dhcp_hostsdir '
                                 'does not exist'))

    def init_host(self, admin_context):
        if self._started:
            raise RuntimeError(_('Attempt to start an already running '
                                 'PXE filter manager'))

        self._shutdown = event.Event()
        self._thread = eventlet.spawn_after(_START_DELAY, self._periodic_sync)
        self._started = True

    def del_host(self):
        self._shutdown.send(True)
        eventlet.sleep(0)
        self._thread.wait()
        self._started = False

    def _periodic_sync(self):
        db = dbapi.get_instance()
        self._try_sync(db)
        while not self._shutdown.wait(timeout=CONF.pxe_filter.sync_period):
            self._try_sync(db)

    def _try_sync(self, db):
        try:
            return self._sync(db)
        except Exception:
            LOG.exception('Sync failed, will retry')

    @METRICS.timer('PXEFilterManager._sync')
    def _sync(self, db):
        LOG.debug('Starting periodic sync of the filter')
        ts = time.time()

        nodeinfo_list = db.get_nodeinfo_list(
            columns=['id', 'inspect_interface'],
            filters={
                'provision_state_in': [states.INSPECTWAIT, states.INSPECTING],
            })
        nodes_on_inspection = {
            node[0] for node in nodeinfo_list
            if node[1] in CONF.pxe_filter.supported_inspect_interfaces
        }
        all_ports = db.get_port_list()
        LOG.debug("Found %d nodes on inspection, handling %d ports",
                  len(nodes_on_inspection), len(all_ports))

        allow = [port.address for port in all_ports
                 if port.node_id in nodes_on_inspection]
        deny = [port.address for port in all_ports
                if port.node_id not in nodes_on_inspection]
        allow_unknown = (CONF.auto_discovery.enabled
                         or bool(nodes_on_inspection))

        dnsmasq.sync(allow, deny, allow_unknown)
        LOG.info('Finished periodic sync of the filter, took %.2f seconds',
                 time.time() - ts)
