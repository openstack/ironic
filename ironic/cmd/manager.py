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
The Ironic Management Service
"""

import sys

from oslo.config import cfg
from wsgiref import simple_server

from ironic.manager import manager
from ironic.common.service import prepare_service
from ironic.openstack.common import service
from ironic.openstack.common.rpc import service as rpc_service

CONF = cfg.CONF


def main():
    # Pase config file and command line options, then start logging
    prepare_service(sys.argv)

    topic = 'ironic.manager'
    mgr = manager.ManagerService(CONF.host, topic)
    launcher = service.launch(mgr)
    launcher.wait()
