# Copyright 2016 OpenStack Foundation
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

from oslo_config import cfg

from ironic.conf import agent
from ironic.conf import anaconda
from ironic.conf import ansible
from ironic.conf import api
from ironic.conf import audit
from ironic.conf import cinder
from ironic.conf import conductor
from ironic.conf import console
from ironic.conf import database
from ironic.conf import default
from ironic.conf import deploy
from ironic.conf import dhcp
from ironic.conf import drac
from ironic.conf import glance
from ironic.conf import healthcheck
from ironic.conf import ibmc
from ironic.conf import ilo
from ironic.conf import inspector
from ironic.conf import ipmi
from ironic.conf import irmc
from ironic.conf import metrics
from ironic.conf import metrics_statsd
from ironic.conf import molds
from ironic.conf import neutron
from ironic.conf import nova
from ironic.conf import pxe
from ironic.conf import redfish
from ironic.conf import service_catalog
from ironic.conf import snmp
from ironic.conf import swift
from ironic.conf import xclarity
from ironic.conf import watcher

CONF = cfg.CONF

agent.register_opts(CONF)
anaconda.register_opts(CONF)
ansible.register_opts(CONF)
api.register_opts(CONF)
audit.register_opts(CONF)
cinder.register_opts(CONF)
conductor.register_opts(CONF)
console.register_opts(CONF)
database.register_opts(CONF)
default.register_opts(CONF)
deploy.register_opts(CONF)
drac.register_opts(CONF)
dhcp.register_opts(CONF)
glance.register_opts(CONF)
healthcheck.register_opts(CONF)
ibmc.register_opts(CONF)
ilo.register_opts(CONF)
inspector.register_opts(CONF)
ipmi.register_opts(CONF)
irmc.register_opts(CONF)
metrics.register_opts(CONF)
metrics_statsd.register_opts(CONF)
molds.register_opts(CONF)
neutron.register_opts(CONF)
nova.register_opts(CONF)
pxe.register_opts(CONF)
redfish.register_opts(CONF)
service_catalog.register_opts(CONF)
snmp.register_opts(CONF)
swift.register_opts(CONF)
xclarity.register_opts(CONF)
watcher.register_opts(CONF)
