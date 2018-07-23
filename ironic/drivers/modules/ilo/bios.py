# Copyright 2018 Hewlett-Packard Development Company, L.P.
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
iLO BIOS Interface
"""

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers.modules.ilo import common as ilo_common
from ironic import objects

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

ilo_error = importutils.try_import('proliantutils.exception')


class IloBIOS(base.BIOSInterface):

    def get_properties(self):
        return ilo_common.REQUIRED_PROPERTIES

    @METRICS.timer('IloBIOS.validate')
    def validate(self, task):
        """Check that 'driver_info' contains required ILO credentials.

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required credentials information.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue if required iLO parameters
                 are not valid.
        :raises: MissingParameterValue if a required parameter is missing.
        """
        ilo_common.parse_driver_info(task.node)

    @METRICS.timer('IloBIOS.apply_configuration')
    @base.clean_step(priority=0, abortable=False, argsinfo={
        'settings': {
            'description': "Dictionary with current BIOS configuration.",
            'required': True
        }
    })
    def apply_configuration(self, task, settings):
        """Applies the provided configuration on the node.

        :param task: a TaskManager instance.
        :param settings: Settings intended to be applied on the node.
        :raises: NodeCleaningFailure when applying the configuration on
                 the node fails.

        """
        data = {}
        for setting in settings:
            data.update({setting['name']: setting['value']})

        node = task.node

        errmsg = _("Clean step \"apply_configuration\" failed "
                   "on node %(node)s with error: %(err)s")

        try:
            ilo_object = ilo_common.get_ilo_object(node)
            ilo_object.set_bios_settings(data)
        except (exception.MissingParameterValue,
                exception.InvalidParameterValue,
                ilo_error.IloError,
                ilo_error.IloCommandNotSupportedError) as ir_exception:
            raise exception.NodeCleaningFailure(
                errmsg % {'node': node.uuid, 'err': ir_exception})

    @METRICS.timer('IloBIOS.factory_reset')
    @base.clean_step(priority=0, abortable=False)
    def factory_reset(self, task):
        """Reset the BIOS settings to factory configuration.

        :param task: a TaskManager instance.
        :raises: NodeCleaningFailure when IloError or any other exception
                 is caught.

        """
        node = task.node

        errmsg = _("Clean step \"factory_reset\" failed "
                   "on node %(node)s with error: %(err)s")

        try:
            ilo_object = ilo_common.get_ilo_object(node)
            ilo_object.reset_bios_to_default()
        except (exception.MissingParameterValue,
                exception.InvalidParameterValue,
                ilo_error.IloError,
                ilo_error.IloCommandNotSupportedError) as ir_exception:
            raise exception.NodeCleaningFailure(
                errmsg % {'node': node.uuid, 'err': ir_exception})

    @METRICS.timer('IloBIOS.cache_bios_settings')
    def cache_bios_settings(self, task):
        """Store the BIOS settings in the database.

        :param task: a TaskManager instance.
        :raises: NodeCleaningFailure when IloError or any other exception
                 is caught.

        """
        node = task.node
        nodeid = node.id

        errmsg = _("Caching BIOS settings failed "
                   "on node %(node)s with error: %(err)s")
        try:
            ilo_object = ilo_common.get_ilo_object(node)
            bios_settings = ilo_object.get_pending_bios_settings()

        except (exception.MissingParameterValue,
                exception.InvalidParameterValue,
                ilo_error.IloError,
                ilo_error.IloCommandNotSupportedError) as ir_exception:
            raise exception.NodeCleaningFailure(
                errmsg % {'node': node.uuid, 'err': ir_exception})

        fmt_bios_settings = []

        for setting in bios_settings:
            fmt_bios_settings.append({"name": setting,
                                      "value": bios_settings[setting]})

        create_list, update_list, delete_list, nochange_list = (
            objects.BIOSSettingList.sync_node_setting(task.context,
                                                      nodeid,
                                                      fmt_bios_settings))
        if len(create_list) > 0:
            objects.BIOSSettingList.create(task.context, nodeid, create_list)
        if len(update_list) > 0:
            objects.BIOSSettingList.save(task.context, nodeid, update_list)
        if len(delete_list) > 0:
            delete_name_list = [delete_name.get(
                "name") for delete_name in delete_list]
            objects.BIOSSettingList.delete(
                task.context, nodeid, delete_name_list)
