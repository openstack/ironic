# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""The Ironic Service API."""

import sys

from oslo_config import cfg
from oslo_log import log

from ironic.common import service as ironic_service
from ironic.common import wsgi_service

CONF = cfg.CONF

LOG = log.getLogger(__name__)


def _error_about_sqlite_usage():
    if 'sqlite' in CONF.database.connection.lower():
        # TODO(TheJulia): Make this a hard error in C*
        LOG.error('We have detected the API is being launched with a SQLite '
                  'database backend. This is unsupported, and will be a hard '
                  'error in the future. This is because multi-process use of '
                  'a single SQLite database is problematic in terms of '
                  'locking. A single process ironic model exists for use with '
                  'SQLite.')


def main():
    # Parse config file and command line options, then start logging
    ironic_service.prepare_service('ironic_api', sys.argv)
    ironic_service.ensure_rpc_transport()

    # Build and start the WSGI app
    launcher = ironic_service.process_launcher()
    server = wsgi_service.WSGIService('ironic_api', CONF.api.enable_ssl_api)
    launcher.launch_service(server, workers=server.workers)
    sys.exit(launcher.wait())


if __name__ == '__main__':
    _error_about_sqlite_usage()
    sys.exit(main())
