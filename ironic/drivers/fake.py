# vim: tabstop=4 shiftwidth=4 softtabstop=4
# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
"""
Fake drivers used in testing.
"""

from ironic.drivers import base


class FakeDeployDriver(base.DeployDriver):
    def __init__(self):
        pass

    def activate_bootloader(self, task, node):
        pass

    def deactivate_bootloader(self, task, node):
        pass

    def activate_node(self, task, node):
        pass

    def deactivate_node(self, task, node):
        pass


class FakeControlDriver(base.ControlDriver):
    def __init__(self):
        pass

    def start_console(self, task, node):
        pass

    def stop_console(self, task, node):
        pass

    def attach_console(self, task, node):
        pass

    def get_power_state(self, task, node):
        pass

    def set_power_state(self, task, node):
        pass

    def reboot(self, task, node):
        pass
