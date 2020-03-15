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

import configparser
import os

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import strutils
import pbr.version


CONF = cfg.CONF
DOMAIN = 'ironic'
VERSION = pbr.version.VersionInfo(DOMAIN).release_string()


# find and parse callback config file
def parse_callback_config():
    basename = os.path.splitext(__file__)[0]
    config = configparser.ConfigParser()
    callback_config = {'ironic_config': None,
                       'ironic_log_file': None,
                       'use_journal': True,
                       'use_syslog': False}
    try:
        config.read_file(open(basename + ".ini"))
        if config.has_option('ironic', 'config_file'):
            callback_config['ironic_config'] = config.get(
                'ironic', 'config_file')
        if config.has_option('ironic', 'log_file'):
            callback_config['ironic_log_file'] = config.get(
                'ironic', 'log_file')
        if config.has_option('ironic', 'use_journal'):
            callback_config['use_journal'] = strutils.bool_from_string(
                config.get('ironic', 'use_journal'))
        if config.has_option('ironic', 'use_syslog'):
            callback_config['use_syslog'] = strutils.bool_from_string(
                config.get('ironic', 'use_syslog'))
    except Exception:
        pass
    return callback_config


def setup_log():

    logging.register_options(CONF)

    conf_kwargs = dict(args=[], project=DOMAIN, version=VERSION)
    callback_config = parse_callback_config()

    if callback_config['ironic_config']:
        conf_kwargs['default_config_files'] = [
            callback_config['ironic_config']]
    CONF(**conf_kwargs)

    if callback_config['use_journal']:
        CONF.set_override('use_journal', True)
    if callback_config['use_syslog']:
        CONF.set_override('use_syslog', True)
    if callback_config['ironic_log_file']:
        CONF.set_override("log_file", callback_config['ironic_log_file'])

    logging.setup(CONF, DOMAIN)


class CallbackModule(object):

    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'ironic_log'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self, display=None):
        setup_log()
        self.log = logging.getLogger(__name__)
        self.node = None
        self._plugin_options = {}

    # NOTE(pas-ha) this method is required for Ansible>=2.4
    # TODO(pas-ha) rewrite to support defining callback plugin options
    # in ansible.cfg after we require Ansible >=2.4
    def set_options(self, option=None, option_value=None):
        if option:
            if option_value:
                self._plugin_options[option] = option_value
            else:
                self._plugin_options = option

    def runner_msg_dict(self, result):
        self.node = result._host.get_name()
        name = result._task.get_name()
        res = str(result._result)
        return dict(node=self.node, name=name, res=res)

    def v2_playbook_on_task_start(self, task, is_conditional):
        # NOTE(pas-ha) I do not know (yet) how to obtain a ref to host
        # until first task is processed
        node = self.node or "Node"
        name = task.get_name()
        if name == 'setup':
            self.log.debug("Processing task %(name)s.", dict(name=name))
        else:
            self.log.debug("Processing task %(name)s on node %(node)s.",
                           dict(name=name, node=node))

    def v2_runner_on_failed(self, result, *args, **kwargs):
        self.log.error(
            "Ansible task %(name)s failed on node %(node)s: %(res)s",
            self.runner_msg_dict(result))

    def v2_runner_on_ok(self, result):
        msg_dict = self.runner_msg_dict(result)
        if msg_dict['name'] == 'setup':
            self.log.info("Ansible task 'setup' complete on node %(node)s",
                          msg_dict)
        else:
            self.log.info("Ansible task %(name)s complete on node %(node)s: "
                          "%(res)s", msg_dict)

    def v2_runner_on_unreachable(self, result):
        self.log.error(
            "Node %(node)s was unreachable for Ansible task %(name)s: %(res)s",
            self.runner_msg_dict(result))

    def v2_runner_on_async_poll(self, result):
        self.log.debug("Polled ansible task %(name)s for complete "
                       "on node %(node)s: %(res)s",
                       self.runner_msg_dict(result))

    def v2_runner_on_async_ok(self, result):
        self.log.info("Async Ansible task %(name)s complete on node %(node)s: "
                      "%(res)s", self.runner_msg_dict(result))

    def v2_runner_on_async_failed(self, result):
        self.log.error("Async Ansible task %(name)s failed on node %(node)s: "
                       "%(res)s", self.runner_msg_dict(result))

    def v2_runner_on_skipped(self, result):
        self.log.debug(
            "Ansible task %(name)s skipped on node %(node)s: %(res)s",
            self.runner_msg_dict(result))
