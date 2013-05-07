#!/usr/bin/env python
# -*- encoding: utf-8 -*-
#
# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

"""
The Ironic Service API 
"""

import sys

from oslo.config import cfg
from wsgiref import simple_server

from ironic.api import app
from ironic.common.service import prepare_service
from ironic.openstack.common import service
from ironic.openstack.common.rpc import service as rpc_service

CONF = cfg.CONF


def main():
    # Pase config file and command line options, then start logging
    prepare_service(sys.argv)

    # Build and start the WSGI app
    host = CONF.ironic_api_bind_ip
    port = CONF.ironic_api_port
    wsgi = simple_server.make_server(
            host, port,
            app.VersionSelectorApplication())

    print "Serving on http://%s:%s" % (host, port)

    try:
        wsgi.serve_forever()
    except KeyboardInterrupt:
        pass
