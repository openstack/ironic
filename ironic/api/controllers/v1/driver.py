#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Red Hat, Inc.
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

import pecan
from pecan import rest

from wsme import types as wtypes
import wsmeext.pecan as wsme_pecan

from ironic.api.controllers.v1 import base
from ironic.openstack.common import log
from oslo.config import cfg

CONF = cfg.CONF
CONF.import_opt('heartbeat_timeout', 'ironic.conductor.manager',
        group='conductor')

LOG = log.getLogger(__name__)


class Driver(base.APIBase):
    """API representation of a driver."""

    name = wtypes.text

    @classmethod
    def convert(cls, name):
        driver = Driver()
        driver.name = name
        return driver


class DriverList(base.APIBase):
    """API representation of a list of drivers."""

    drivers = [Driver]
    "A list containing drivers objects"

    @classmethod
    def convert(cls, drivers):
        collection = DriverList()
        collection.drivers = [Driver.convert(driver) for driver in drivers]
        return collection


class DriversController(rest.RestController):
    """REST controller for Drivers."""

    @wsme_pecan.wsexpose(DriverList)
    def get_all(self):
        """Retrieve a list of drivers."""
        drivers = pecan.request.dbapi.list_active_conductor_drivers(
                                     interval=CONF.conductor.heartbeat_timeout)
        return DriverList.convert(drivers)
