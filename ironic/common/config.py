# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2012 Red Hat, Inc.
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

import os

from oslo_config import cfg
import osprofiler.opts as profiler_opts

from ironic.common import rpc
from ironic import version


def parse_args(argv, default_config_files=None):
    # NOTE(amorin) allow wsgi app to start with custom config file/dir
    conf_file_from_env = os.environ.get('IRONIC_CONFIG_FILE')
    if conf_file_from_env and not default_config_files:
        default_config_files = [conf_file_from_env]
    conf_dir_from_env = os.environ.get('IRONIC_CONFIG_DIR')
    if conf_dir_from_env:
        default_config_dirs = [conf_dir_from_env]
    else:
        default_config_dirs = None

    rpc.set_defaults(control_exchange='ironic')
    cfg.CONF(argv[1:],
             project='ironic',
             version=version.version_info.release_string(),
             default_config_files=default_config_files,
             default_config_dirs=default_config_dirs)
    rpc.init(cfg.CONF)
    profiler_opts.set_defaults(cfg.CONF)
