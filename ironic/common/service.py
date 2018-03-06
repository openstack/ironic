# -*- encoding: utf-8 -*-
#
# Copyright © 2012 eNovance <licensing@enovance.com>
#
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

from oslo_log import log
from oslo_service import service

from ironic.common import config
from ironic.conf import CONF
from ironic.conf import opts
from ironic import objects


def prepare_service(argv=None):
    argv = [] if argv is None else argv
    log.register_options(CONF)
    opts.update_opt_defaults()
    config.parse_args(argv)
    # NOTE(vdrok): We need to setup logging after argv was parsed, otherwise
    # it does not properly parse the options from config file and uses defaults
    # from oslo_log
    log.setup(CONF, 'ironic')
    objects.register_all()


def process_launcher():
    return service.ProcessLauncher(CONF, restart_method='mutate')
