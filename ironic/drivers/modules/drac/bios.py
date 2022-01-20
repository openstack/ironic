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
DRAC BIOS configuration specific methods
"""

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils
from oslo_utils import timeutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.conductor import periodics
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job
from ironic.drivers.modules.redfish import bios as redfish_bios
from ironic import objects

drac_client = importutils.try_import('dracclient.client')
drac_exceptions = importutils.try_import('dracclient.exceptions')
drac_uris = importutils.try_import('dracclient.resources.uris')
drac_utils = importutils.try_import('dracclient.utils')

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


class DracRedfishBIOS(redfish_bios.RedfishBIOS):
    """iDRAC Redfish interface for BIOS settings-related actions.

    Presently, this class entirely defers to its base class, a generic,
    vendor-independent Redfish interface. Future resolution of Dell EMC-
    specific incompatibilities and introduction of vendor value added
    should be implemented by this class.
    """


class DracWSManBIOS(base.BIOSInterface):
    """BIOSInterface Implementation for iDRAC."""

    # argsinfo dict for BIOS clean/deploy steps
    _args_info = {
        "settings": {
            "description": "List of BIOS settings to apply",
            "required": True
        }
    }

    def __init__(self):
        super(DracWSManBIOS, self).__init__()
        if drac_exceptions is None:
            raise exception.DriverLoadError(
                driver='idrac',
                reason=_("Unable to import dracclient.exceptions library"))

    @METRICS.timer('DracWSManBIOS.apply_configuration')
    @base.clean_step(priority=0, argsinfo=_args_info, requires_ramdisk=False)
    @base.deploy_step(priority=0, argsinfo=_args_info)
    def apply_configuration(self, task, settings):
        """Apply the BIOS configuration to the node

        :param task: a TaskManager instance containing the node to act on
        :param settings: List of BIOS settings to apply
        :raises: DRACOperationError upon an error from python-dracclient

        :returns: states.CLEANWAIT (cleaning) or states.DEPLOYWAIT (deployment)
                  if configuration is in progress asynchronously or None if it
                  is completed.
        """

        LOG.debug("Configuring node %(node_uuid)s with BIOS settings:"
                  " %(settings)s", {"node_uuid": task.node.uuid,
                                    "settings": settings})
        node = task.node
        # convert ironic settings list to DRAC kwsettings
        kwsettings = {s['name']: s['value'] for s in settings}
        drac_job.validate_job_queue(node)
        client = drac_common.get_drac_client(node)
        try:
            #  Argument validation is done by the dracclient method
            #  set_bios_settings. No need to do it here.
            set_result = client.set_bios_settings(kwsettings)
        except drac_exceptions.BaseClientException as exc:
            LOG.error("Failed to apply BIOS config on node %(node_uuid)s."
                      " Error %(error)s", {"node_uuid": task.node.uuid,
                                           "error": exc})
            raise exception.DracOperationError(error=exc)

        # If no commit is required, we're done
        if not set_result['is_commit_required']:
            LOG.info("Completed BIOS configuration on node %(node_uuid)s"
                     " with BIOS settings: %(settings)s",
                     {
                         "node_uuid": task.node.uuid,
                         "settings": settings
                     })
            return

        # Otherwise, need to reboot the node as well to commit configuration
        else:
            LOG.debug("Rebooting node %(node_uuid)s to apply BIOS settings",
                      {"node_uuid": task.node.uuid})
            reboot_needed = set_result['is_reboot_required']
            try:
                commit_result = client.commit_pending_bios_changes(
                    reboot=reboot_needed)
            except drac_exceptions.BaseClientException as exc:
                LOG.error("Failed to commit BIOS changes on node %(node_uuid)s"
                          ". Error %(error)s", {"node_uuid": task.node.uuid,
                                                "error": exc})
                raise exception.DracOperationError(error=exc)

            # Store JobID for the async job handler _check_node_bios_jobs
            bios_config_job_ids = node.driver_internal_info.get(
                'bios_config_job_ids', [])
            bios_config_job_ids.append(commit_result)
            node.set_driver_internal_info('bios_config_job_ids',
                                          bios_config_job_ids)

            # This method calls node.save(), bios_config_job_ids will then be
            # saved.
            # These flags are for the conductor to manage the asynchronous
            # jobs that have been initiated by this method
            deploy_utils.set_async_step_flags(
                node,
                reboot=reboot_needed,
                skip_current_step=True,
                polling=True)
            # Return the clean/deploy state string
            return deploy_utils.get_async_step_return_state(node)

    @METRICS.timer('DracWSManBIOS._query_bios_config_job_status')
    # TODO(noor): Consider patch of CONF to add an entry for BIOS query
    # spacing since BIOS jobs could be comparatively shorter in time than
    # RAID ones currently using the raid spacing to avoid errors
    # spacing parameter for periodic method
    @periodics.node_periodic(
        purpose='checking async bios configuration jobs',
        spacing=CONF.drac.query_raid_config_job_status_interval,
        filters={'reserved': False, 'maintenance': False},
        predicate_extra_fields=['driver_internal_info'],
        predicate=lambda n: (
            n.driver_internal_info.get('bios_config_job_ids')
            or n.driver_internal_info.get('factory_reset_time_before_reboot')),
    )
    def _query_bios_config_job_status(self, task, manager, context):
        """Periodic task to check the progress of running BIOS config jobs.

        :param manager: an instance of Ironic Conductor Manager with
                        the node list to act on
        :param context: context of the request, needed when acquiring
                        a lock on a node. For access control.
        """
        # check bios_config_job_id exist & checks job is completed
        if task.node.driver_internal_info.get("bios_config_job_ids"):
            self._check_node_bios_jobs(task)

        if task.node.driver_internal_info.get(
                "factory_reset_time_before_reboot"):
            self._check_last_system_inventory_changed(task)

    def _check_last_system_inventory_changed(self, task):
        """Check the progress of last system inventory time of a node.

        This handles jobs for BIOS factory reset. Handle means,
        it checks for job status to not only signify completed jobs but
        also handle failures by invoking the 'fail' event, allowing the
        conductor to put the node into clean/deploy FAIL state.

        :param task: a TaskManager instance with the node to act on
        """
        node = task.node
        client = drac_common.get_drac_client(node)
        # Get the last system inventory time from node before reboot
        factory_reset_time_before_reboot = node.driver_internal_info.get(
            'factory_reset_time_before_reboot')

        # Get the factory reset start time
        factory_reset_time = node.driver_internal_info.get(
            'factory_reset_time')
        LOG.debug("Factory resetting node %(node_uuid)s factory reset time "
                  " %(factory_reset_time)s", {"node_uuid": task.node.uuid,
                                              "factory_reset_time":
                                              factory_reset_time})
        # local variable to track difference between current time and factory
        # reset start time
        time_difference = 0
        # Get the last system inventory time after reboot
        factory_reset_time_endof_reboot = (client.get_system()
                                           .last_system_inventory_time)

        LOG.debug("Factory resetting node %(node_uuid)s "
                  "last inventory reboot time after factory reset "
                  "%(factory_reset_time_endof_reboot)s",
                  {"node_uuid": task.node.uuid,
                   "factory_reset_time_endof_reboot":
                   factory_reset_time_endof_reboot})

        if factory_reset_time_before_reboot != factory_reset_time_endof_reboot:
            # from the database cleanup with factory reset time
            self._delete_cached_reboot_time(node)
            # Cache the new BIOS settings,
            self.cache_bios_settings(task)
            self._resume_current_operation(task)
        else:
            # Calculate difference between current time and factory reset
            # start time if it is more than configured timeout then set
            # the node to fail state
            time = timeutils.utcnow(with_timezone=True
                                    ) - timeutils.parse_isotime(str(
                                        factory_reset_time))
            time_difference = time.total_seconds()
            LOG.debug("Factory resetting node %(node_uuid)s "
                      "time difference %(time_difference)s ",
                      {"node_uuid": task.node.uuid, "time_difference":
                       time_difference})

            if time_difference > CONF.drac.bios_factory_reset_timeout:
                task.upgrade_lock()
                self._delete_cached_reboot_time(node)
                error_message = ("BIOS factory reset was not completed within "
                                 "{} seconds, unable to cache updated bios "
                                 "setting").format(
                                     CONF.drac.bios_factory_reset_timeout)
                self._set_failed(task, error_message)
            else:
                LOG.debug("Factory reset for a node %(node)s is not done "
                          "will check again later", {'node': task.node.uuid})

    def _check_node_bios_jobs(self, task):
        """Check the progress of running BIOS config jobs of a node.

        This handles jobs for BIOS set and reset. Handle means,
        it checks for job status to not only signify completed jobs but
        also handle failures by invoking the 'fail' event, allowing the
        conductor to put the node into clean/deploy FAIL state.

        :param task: a TaskManager instance with the node to act on
        """
        node = task.node
        bios_config_job_ids = node.driver_internal_info['bios_config_job_ids']
        finished_job_ids = []
        # local variable to track job failures
        job_failed = False

        for config_job_id in bios_config_job_ids:
            config_job = drac_job.get_job(node, job_id=config_job_id)

            if config_job is None or config_job.status == 'Completed':
                finished_job_ids.append(config_job_id)
            elif (config_job.status == 'Failed'
                    or config_job.status == 'Completed with Errors'):
                finished_job_ids.append(config_job_id)
                job_failed = True

        # If no job has finished, return
        if not finished_job_ids:
            return

        # The finished jobs will require a node reboot, need to update the
        # node lock to exclusive, allowing a destructive reboot operation
        task.upgrade_lock()
        # Cleanup the database with finished jobs, they're no longer needed
        self._delete_cached_config_job_ids(node, finished_job_ids)

        if not job_failed:
            # Cache the new BIOS settings, caching needs to happen here
            # since the config steps are async. Decorator won't work.
            self.cache_bios_settings(task)
            # if no failure, continue with clean/deploy
            self._resume_current_operation(task)
        else:
            # invoke 'fail' event to allow conductor to put the node in
            # a clean/deploy fail state
            error_message = ("Failed config job: {}. Message: '{}'.".format(
                config_job.id, config_job.message))
            self._set_failed(task, error_message)

    def _delete_cached_config_job_ids(self, node, finished_job_ids=None):
        """Remove Job IDs from the driver_internal_info table in database.

        :param node: an ironic node object
        :param finished_job_ids: a list of finished Job ID strings to remove
        """
        if finished_job_ids is None:
            finished_job_ids = []
        # take out the unfinished job ids from all the jobs
        unfinished_job_ids = [
            job_id for job_id
            in node.driver_internal_info['bios_config_job_ids']
            if job_id not in finished_job_ids]
        # assign the unfinished job ids back to the total list
        # this will clear the finished jobs from the list
        node.set_driver_internal_info('bios_config_job_ids',
                                      unfinished_job_ids)
        node.save()

    def _delete_cached_reboot_time(self, node):
        """Remove factory time from the driver_internal_info table in database.

         :param node: an ironic node object
         """
        # Remove the last reboot time and factory reset time
        node.del_driver_internal_info('factory_reset_time_before_reboot')
        node.del_driver_internal_info('factory_reset_time')
        node.save()

    def _set_failed(self, task, error_message):
        """Set the node in failed state by invoking 'fail' event.

        :param task: a TaskManager instance with node to act on
        :param error_message: Error message
        """
        log_msg = ("BIOS configuration failed for node %(node)s. %(error)s " %
                   {'node': task.node.uuid,
                    'error': error_message})
        if task.node.clean_step:
            manager_utils.cleaning_error_handler(task, log_msg, error_message)
        else:
            manager_utils.deploying_error_handler(task, log_msg, error_message)

    def _resume_current_operation(self, task):
        """Continue cleaning/deployment of the node.

        For asynchronous operations, it is necessary to notify the
        conductor manager to continue the cleaning/deployment operation
        after a job has finished. This is done through an RPC call. The
        notify_conductor_resume_* wrapper methods provide that.

        :param task: a TaskManager instance with node to act on
        """
        if task.node.clean_step:
            manager_utils.notify_conductor_resume_clean(task)
        else:
            manager_utils.notify_conductor_resume_deploy(task)

    @METRICS.timer('DracWSManBIOS.factory_reset')
    @base.clean_step(priority=0, requires_ramdisk=False)
    @base.deploy_step(priority=0)
    def factory_reset(self, task):
        """Reset the BIOS settings of the node to the factory default.

        This uses the Lifecycle Controller configuration to perform
        BIOS configuration reset. Leveraging the python-dracclient
        methods already available.

        :param task: a TaskManager instance containing the node to act on
        :raises: DracOperationError on an error from python-dracclient
        :returns: states.CLEANWAIT (cleaning) or states.DEPLOYWAIT
                  (deployment) if reset is in progress asynchronously or None
                  if it is completed.
        """
        node = task.node
        drac_job.validate_job_queue(node)
        client = drac_common.get_drac_client(node)
        lc_bios_reset_attrib = {
            "BIOS Reset To Defaults Requested": "True"
        }
        try:
            set_result = client.set_lifecycle_settings(lc_bios_reset_attrib)
        except drac_exceptions.BaseClientException as exc:
            LOG.error('Failed to reset BIOS on the node %(node_uuid)s.'
                      ' Reason: %(error)s.', {'node_uuid': node.uuid,
                                              'error': exc})
            raise exception.DracOperationError(error=exc)
        if not set_result['is_commit_required']:
            LOG.info("BIOS reset successful on the node "
                     "%(node_uuid)s", {"node_uuid": node.uuid})
            return
        else:
            # Rebooting the Node is compulsory, LC call returns
            # reboot_required=False/Optional, which is not desired
            reboot_needed = True
            try:
                factory_reset_time_before_reboot =\
                    client.get_system().last_system_inventory_time

                LOG.debug("Factory resetting node %(node_uuid)s "
                          "last inventory reboot time before factory reset "
                          "%(factory_reset_time_before_reboot)s",
                          {"node_uuid": task.node.uuid,
                           "factory_reset_time_before_reboot":
                           factory_reset_time_before_reboot})

                commit_job_id = client.commit_pending_lifecycle_changes(
                    reboot=reboot_needed)
                LOG.info("Commit job id of a node %(node_uuid)s."
                         "%(commit_job_id)s", {'node_uuid': node.uuid,
                                               "commit_job_id": commit_job_id})
            except drac_exceptions.BaseClientException as exc:
                LOG.error('Failed to commit BIOS reset on node '
                          '%(node_uuid)s. Reason: %(error)s.', {
                              'node_uuid': node.uuid,
                              'error': exc})
                raise exception.DracOperationError(error=exc)
            # Store the last inventory time on reboot for async job handler
            # _check_last_system_inventory_changed
            node.set_driver_internal_info('factory_reset_time_before_reboot',
                                          factory_reset_time_before_reboot)
            # Store the current time to later check if factory reset times out
            node.timestamp_driver_internal_info('factory_reset_time')

            # rebooting the server to apply factory reset value
            task.driver.power.reboot(task)

            # This method calls node.save(), bios_config_job_id will be
            # saved automatically
            # These flags are for the conductor to manage the asynchronous
            # jobs that have been initiated by this method
            deploy_utils.set_async_step_flags(
                node,
                reboot=reboot_needed,
                skip_current_step=True,
                polling=True)

            return deploy_utils.get_async_step_return_state(task.node)

    def cache_bios_settings(self, task):
        """Store or update the current BIOS settings for the node.

        Get the current BIOS settings and store them in the bios_settings
        database table.

        :param task: a TaskManager instance containing the node to act on.
        :raises: DracOperationError on an error from python-dracclient
        """
        node = task.node
        node_id = node.id
        node_uuid = node.uuid

        client = drac_common.get_drac_client(node)

        try:
            kwsettings = client.list_bios_settings()
        except drac_exceptions.BaseClientException as exc:
            LOG.error('DRAC driver failed to get the BIOS settings for node '
                      '%(node_uuid)s. Reason: %(error)s.',
                      {'node_uuid': node.uuid,
                       'error': exc})
            raise exception.DracOperationError(error=exc)

        # convert dracclient BIOS settings into ironic settings list
        settings = [{"name": name, "value": attrib.current_value}
                    for name, attrib in kwsettings.items()]

        # Store them in the database table
        LOG.debug('Caching BIOS settings for node %(node_uuid)s', {
                  'node_uuid': node_uuid})
        create_list, update_list, delete_list, nochange_list = (
            objects.BIOSSettingList.sync_node_setting(
                task.context, node_id, settings))

        if create_list:
            objects.BIOSSettingList.create(
                task.context, node_id, create_list)
        if update_list:
            objects.BIOSSettingList.save(
                task.context, node_id, update_list)
        if delete_list:
            delete_names = [d['name'] for d in delete_list]
            objects.BIOSSettingList.delete(
                task.context, node_id, delete_names)

    # BaseInterface methods implementation
    def get_properties(self):
        """Return the properties of the BIOS Interface

        :returns: dictionary of <property name>: <property description> entries
        """
        return drac_common.COMMON_PROPERTIES

    def validate(self, task):
        """Validates the driver-specific information used by the idrac BMC

        :param task: a TaskManager instance containing the node to act on
        :raises: InvalidParameterValue if some mandatory information
                 is missing on the node or on invalid inputs
        """
        drac_common.parse_driver_info(task.node)


def get_config(node):
    """Get the BIOS configuration.

    The BIOS settings look like::

        {'EnumAttrib': {'name': 'EnumAttrib',
                        'current_value': 'Value',
                        'pending_value': 'New Value', # could also be None
                        'read_only': False,
                        'possible_values': ['Value', 'New Value', 'None']},
         'StringAttrib': {'name': 'StringAttrib',
                          'current_value': 'Information',
                          'pending_value': None,
                          'read_only': False,
                          'min_length': 0,
                          'max_length': 255,
                          'pcre_regex': '^[0-9A-Za-z]{0,255}$'},
         'IntegerAttrib': {'name': 'IntegerAttrib',
                           'current_value': 0,
                           'pending_value': None,
                           'read_only': True,
                           'lower_bound': 0,
                           'upper_bound': 65535}}

    :param node: an ironic node object.
    :raises: DracOperationError on an error from python-dracclient.
    :returns: a dictionary containing BIOS settings

    The above values are only examples, of course.  BIOS attributes exposed via
    this API will always be either an enumerated attribute, a string attribute,
    or an integer attribute.  All attributes have the following parameters:

    :param name: is the name of the BIOS attribute.
    :param current_value: is the current value of the attribute.
                          It will always be either an integer or a string.
    :param pending_value: is the new value that we want the attribute to have.
                          None means that there is no pending value.
    :param read_only: indicates whether this attribute can be changed.
                      Trying to change a read-only value will result in
                      an error. The read-only flag can change depending
                      on other attributes.
                      A future version of this call may expose the
                      dependencies that indicate when that may happen.

    Enumerable attributes also have the following parameters:

    :param possible_values: is an array of values it is permissible to set
                            the attribute to.

    String attributes also have the following parameters:

    :param min_length: is the minimum length of the string.
    :param max_length: is the maximum length of the string.
    :param pcre_regex: is a PCRE compatible regular expression that the string
                       must match.  It may be None if the string is read only
                       or if the string does not have to match any particular
                       regular expression.

    Integer attributes also have the following parameters:

    :param lower_bound: is the minimum value the attribute can have.
    :param upper_bound: is the maximum value the attribute can have.
    """

    client = drac_common.get_drac_client(node)

    try:
        return client.list_bios_settings()
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to get the BIOS settings for node '
                  '%(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)


def set_config(task, **kwargs):
    """Sets the pending_value parameter for each of the values passed in.

    :param task: a TaskManager instance containing the node to act on.
    :param kwargs: a dictionary of {'AttributeName': 'NewValue'}
    :raises: DracOperationError on an error from python-dracclient.
    :returns: A dictionary containing the 'is_commit_required' key with a
              boolean value indicating whether commit_config() needs to be
              called to make the changes, and the 'is_reboot_required' key
              which has a value of 'true' or 'false'.  This key is used to
              indicate to the commit_config() call if a reboot should be
              performed.
    """
    node = task.node
    drac_job.validate_job_queue(node)

    client = drac_common.get_drac_client(node)
    if 'http_method' in kwargs:
        del kwargs['http_method']

    try:
        return client.set_bios_settings(kwargs)
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to set the BIOS settings for node '
                  '%(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)


def commit_config(task, reboot=False):
    """Commits pending changes added by set_config

    :param task: a TaskManager instance containing the node to act on.
    :param reboot: indicates whether a reboot job should be automatically
                   created with the config job.
    :raises: DracOperationError on an error from python-dracclient.
    :returns: the job_id key with the id of the newly created config job.
    """
    node = task.node
    drac_job.validate_job_queue(node)

    client = drac_common.get_drac_client(node)

    try:
        return client.commit_pending_bios_changes(reboot)
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to commit the pending BIOS changes '
                  'for node %(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)


def abandon_config(task):
    """Abandons uncommitted changes added by set_config

    :param task: a TaskManager instance containing the node to act on.
    :raises: DracOperationError on an error from python-dracclient.
    """
    node = task.node
    client = drac_common.get_drac_client(node)

    try:
        client.abandon_pending_bios_changes()
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to delete the pending BIOS '
                  'settings for node %(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)
