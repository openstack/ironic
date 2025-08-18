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

import os
import signal

from oslo_config import cfg
from oslo_log import log

from ironic.conductor import rpc_service

LOG = log.getLogger(__name__)

CONF = cfg.CONF


# NOTE(TheJulia): These methods are for the parent processes to
# glue behavior expectations to conductor shutdowns.
def handle_no_deregister(signo, frame):
    LOG.info('Got signal SIGUSR1. Not deregistering on next shutdown '
             'on host %(host)s.',
             {'host': CONF.host})
    rpc_service.DEREGISTER_ON_SHUTDOWN.clear()


def handle_drain(signo, frame):
    LOG.info('Got signal SIGUSR2. Initiating a workload drain and '
             'shutdown on host %(host)s.',
             {'host': CONF.host})
    rpc_service.DRAIN.set()
    # NOTE(TheJulia): This is sort of aggressive, but it works.
    # Issue in part is we need to trigger the child process to stop, and
    # the manager shutdown method is for parent process calls, in other words
    # the application triggering a self shutdown. Utlimately this triggers the
    # application stop() method to be called.
    os.kill(0, signal.SIGTERM)


def handle_signal():
    """Add a signal handler for SIGUSR1, SIGUSR2.

    The SIGUSR1 handler ensures that the manager is not deregistered when
    it is shutdown.

    The SIGUSR2 handler starts a drain shutdown.
    """
    signal.signal(signal.SIGUSR1, handle_no_deregister)
    # In ironic, USR2 triggers a draining shutdown, we'll need to figure out
    # how to do that in this model, most likely set a flag and request the
    # manager to shutdown.
    signal.signal(signal.SIGUSR2, handle_drain)
