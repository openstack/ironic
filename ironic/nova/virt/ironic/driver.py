# coding=utf-8
#
# Copyright 2014 Red Hat, Inc.
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
A driver wrapping the Ironic API, such that Nova may provision
bare metal resources.
"""

from ironicclient import client as ironic_client
from ironicclient import exc as ironic_exception
from oslo.config import cfg

from ironic.nova.virt.ironic import ironic_states
from nova.compute import power_state
from nova import exception
from nova.objects import flavor as flavor_obj
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import loopingcall
from nova.virt import driver as virt_driver
from nova.virt import firewall

LOG = logging.getLogger(__name__)

opts = [
    cfg.IntOpt('api_version',
               default=1,
               help='Version of Ironic API service endpoint.'),
    cfg.StrOpt('api_endpoint',
               help='URL for Ironic API endpoint.'),
    cfg.StrOpt('admin_username',
               help='Ironic keystone admin name'),
    cfg.StrOpt('admin_password',
               help='Ironic keystone admin password.'),
    cfg.StrOpt('admin_auth_token',
               help='Ironic keystone auth token.'),
    cfg.StrOpt('admin_url',
               help='Ironic public api endpoint.'),
    cfg.StrOpt('pxe_bootfile_name',
               help='This gets passed to Neutron as the bootfile dhcp '
               'parameter when the dhcp_options_enabled is set.',
               default='pxelinux.0'),
    cfg.StrOpt('admin_tenant_name',
               help='Ironic keystone tenant name.'),
    cfg.ListOpt('instance_type_extra_specs',
                default=[],
                help='A list of additional capabilities corresponding to '
                'instance_type_extra_specs for this compute '
                'host to advertise. Valid entries are name=value, pairs '
                'For example, "key1:val1, key2:val2"'),
    cfg.IntOpt('api_max_retries',
               default=5,
               help=('How many retries when a request does conflict.')),
    cfg.IntOpt('api_retry_interval',
               default=2,
               help=('How often to retry in seconds when a request '
                     'does conflict')),
    ]

ironic_group = cfg.OptGroup(name='ironic',
                            title='Ironic Options')

CONF = cfg.CONF
CONF.register_group(ironic_group)
CONF.register_opts(opts, ironic_group)

_FIREWALL_DRIVER = "%s.%s" % (firewall.__name__,
                              firewall.NoopFirewallDriver.__name__)

_POWER_STATE_MAP = {
    ironic_states.POWER_ON: power_state.RUNNING,
    ironic_states.NOSTATE: power_state.NOSTATE,
    ironic_states.POWER_OFF: power_state.SHUTDOWN,
}


class MaximumRetriesReached(exception.NovaException):
    msg_fmt = _("Maximum number of retries reached.")


def map_power_state(state):
    try:
        return _POWER_STATE_MAP[state]
    except KeyError:
        LOG.warning(_("Power state %s not found.") % state)
        return power_state.NOSTATE


def validate_instance_and_node(icli, instance):
    """Get and validate a node's uuid out of a manager instance dict.

    The compute manager is meant to know the node uuid, so missing uuid
    a significant issue - it may mean we've been passed someone elses data.

    Check with the Ironic service that this node is still associated with
    this instance. This catches situations where Nova's instance dict
    contains stale data (eg, a delete on an instance that's already gone).

    """
    try:
        return icli.node.get_by_instance_uuid(instance['uuid'])
    except ironic_exception.HTTPNotFound:
        raise exception.InstanceNotFound(instance_id=instance['uuid'])


def _get_required_value(key, value):
    """Return the requested value."""
    if '/' in value:
        # we need to split the value
        split_value = value.split('/')
        eval_string = 'key'
        for value in split_value:
            eval_string = "%s['%s']" % (eval_string, value)
        return eval(eval_string)
    else:
        return key[value]


def _get_nodes_supported_instances(cpu_arch=''):
    """Return supported instances for a node."""
    return [(cpu_arch, 'baremetal', 'baremetal')]


class IronicDriver(virt_driver.ComputeDriver):
    """Hypervisor driver for Ironic - bare metal provisioning."""

    capabilities = {"has_imagecache": False}

    def __init__(self, virtapi, read_only=False):
        super(IronicDriver, self).__init__(virtapi)

        self.firewall_driver = firewall.load_driver(default=_FIREWALL_DRIVER)
        # TODO(deva): sort out extra_specs and nova-scheduler interaction
        extra_specs = {}
        extra_specs["ironic_driver"] = \
                "ironic.nova.virt.ironic.driver.IronicDriver"
        # cpu_arch set per node.
        extra_specs['cpu_arch'] = ''
        for pair in CONF.ironic.instance_type_extra_specs:
            keyval = pair.split(':', 1)
            keyval[0] = keyval[0].strip()
            keyval[1] = keyval[1].strip()
            extra_specs[keyval[0]] = keyval[1]

        self.extra_specs = extra_specs

    def _retry_if_service_is_unavailable(self, func, *args):
        """Rety the request if the API returns 409 (Conflict)."""
        def _request_api():
            try:
                func(*args)
                raise loopingcall.LoopingCallDone()
            except ironic_exception.HTTPServiceUnavailable:
                pass

            if self.tries >= CONF.ironic.api_max_retries:
                raise MaximumRetriesReached()
            else:
                self.tries += 1

        self.tries = 0
        timer = loopingcall.FixedIntervalLoopingCall(_request_api)
        timer.start(interval=CONF.ironic.api_retry_interval).wait()

    def _get_client(self):
        # TODO(deva): save and reuse existing client & auth token
        #             until it expires or is no longer valid
        auth_token = CONF.ironic.admin_auth_token
        if auth_token is None:
            kwargs = {'os_username': CONF.ironic.admin_username,
                      'os_password': CONF.ironic.admin_password,
                      'os_auth_url': CONF.ironic.admin_url,
                      'os_tenant_name': CONF.ironic.admin_tenant_name,
                      'os_service_type': 'baremetal',
                      'os_endpoint_type': 'public'}
        else:
            kwargs = {'os_auth_token': auth_token,
                      'ironic_url': CONF.ironic.api_endpoint}
        return ironic_client.get_client(CONF.ironic.api_version, **kwargs)

    def _node_resource(self, node):
        # TODO(deva): refactor this to match ironic node datastruct
        vcpus_used = 0
        memory_mb_used = 0
        local_gb_used = 0

        vcpus = int(node.properties.get('cpus', 0))
        memory_mb = int(node.properties.get('memory_mb', 0))
        local_gb = int(node.properties.get('local_gb', 0))
        cpu_arch = str(node.properties.get('cpu_arch', 'NotFound'))
        nodes_extra_specs = self.extra_specs
        nodes_extra_specs['cpu_arch'] = cpu_arch

        if node.instance_uuid:
            vcpus_used = vcpus
            memory_mb_used = memory_mb
            local_gb_used = local_gb

        dic = {'vcpus': vcpus,
               'memory_mb': memory_mb,
               'local_gb': local_gb,
               'vcpus_used': vcpus_used,
               'memory_mb_used': memory_mb_used,
               'local_gb_used': local_gb_used,
               'hypervisor_type': self.get_hypervisor_type(),
               'hypervisor_version': self.get_hypervisor_version(),
               'hypervisor_hostname': str(node.uuid),
               'cpu_info': 'baremetal cpu',
               'supported_instances': jsonutils.dumps(
                                     _get_nodes_supported_instances(cpu_arch)),
               'stats': jsonutils.dumps(nodes_extra_specs)
               }
        return dic

    def _start_firewall(self, instance, network_info):
        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance, network_info)
        self.firewall_driver.apply_instance_filter(instance, network_info)

    def _stop_firewall(self, instance, network_info):
        self.firewall_driver.unfilter_instance(instance, network_info)

    def _add_driver_fields(self, node, instance, image_meta, flavor=None):
        icli = self._get_client()
        if 'pxe' in node.driver:
            # add required fields
            pxe_fields = importutils.import_class(
                'ironic.nova.virt.ironic.ironic_driver_fields.PXE')

            patch = []
            for field in pxe_fields.required:
                path_to_add = "%s/%s" % (field['ironic_path'],
                                         field['ironic_variable'])
                patch = [{'op': 'add',
                         'path': path_to_add,
                         'value': unicode(_get_required_value(
                                          eval(field['nova_object']),
                                               field['object_field']))}]
                try:
                    self._retry_if_service_is_unavailable(icli.node.update,
                                                          node.uuid, patch)
                except MaximumRetriesReached:
                    msg = (_("Adding the parameter %(param)s on node %(node)s "
                             "failed after %(retries)d retries")
                           % {'param': path_to_add, 'node': node.uuid,
                              'retries': CONF.ironic.api_max_retries})
                    LOG.error(msg)
                    raise exception.NovaException(msg)

    def _cleanup_deploy(self, node, instance, network_info):
        icli = self._get_client()

        # remove the instance uuid
        if node.instance_uuid and node.instance_uuid == instance['uuid']:
            try:
                patch = [{'op': 'remove', 'path': '/instance_uuid'}]
                self._retry_if_service_is_unavailable(icli.node.update,
                                                      node.uuid, patch)
            except MaximumRetriesReached:
                LOG.warning(_("Failed to unassociate the instance "
                              "%(instance)s with node %(node)s") %
                             {'instance': instance['uuid'], 'node': node.uuid})
            except ironic_exception.HTTPBadRequest:
                pass

        if 'pxe' in node.driver:
            # add required fields
            pxe_fields = importutils.import_class(
                'ironic.nova.virt.ironic.ironic_driver_fields.PXE')

            patch = []
            for field in pxe_fields.required:
                path_to_remove = "%s/%s" % (field['ironic_path'],
                                            field['ironic_variable'])
                patch = [{'op': 'remove', 'path': path_to_remove}]

                try:
                    self._retry_if_service_is_unavailable(icli.node.update,
                                                          node.uuid, patch)
                except MaximumRetriesReached:
                    LOG.warning(_("Removing the parameter %(param)s on node "
                                  "%(node)s failed after %(retries)d retries")
                                % {'param': path_to_remove, 'node': node.uuid,
                                   'retries': CONF.ironic.api_max_retries})
                except ironic_exception.HTTPBadRequest:
                    pass

        self._unplug_vifs(node, instance, network_info)
        self._stop_firewall(instance, network_info)

    @classmethod
    def instance(cls):
        if not hasattr(cls, '_instance'):
            cls._instance = cls()
        return cls._instance

    def init_host(self, host):
        return

    def get_hypervisor_type(self):
        return 'ironic'

    def get_hypervisor_version(self):
        return CONF.ironic.api_version

    def list_instances(self):
        try:
            icli = self._get_client()
        except ironic_exception.Unauthorized:
            LOG.error(_("Unable to authenticate Ironic client."))
            return []

        instances = [i for i in icli.node.list() if i.instance_uuid]
        return instances

    def get_available_nodes(self, refresh=False):
        nodes = []
        icli = self._get_client()
        node_list = icli.node.list()

        for n in node_list:
            # for now we'll use the nodes power state. if power_state is None
            # we'll assume it is not ready to be presented to Nova.
            if n.power_state:
                nodes.append(n.uuid)

        LOG.debug("Returning Nodes: %s" % nodes)
        return nodes

    def get_available_resource(self, node):
        """Retrieve resource information.

        This method is called when nova-compute launches, and
        as part of a periodic task that records the results in the DB.

        :param node: the uuid of the node
        :returns: dictionary describing resources

        """
        icli = self._get_client()
        node = icli.node.get(node)
        return self._node_resource(node)

    def get_info(self, instance):

        icli = self._get_client()
        try:
            node = icli.node.get_by_instance_uuid(instance['uuid'])
        except ironic_exception.HTTPNotFound:
            return {'state': map_power_state(ironic_states.NOSTATE),
                    'max_mem': 0,
                    'mem': 0,
                    'num_cpu': 0,
                    'cpu_time': 0
                    }

        return {'state': map_power_state(node.power_state),
                'max_mem': node.properties.get('memory_mb'),
                'mem': node.properties.get('memory_mb'),
                'num_cpu': node.properties.get('cpus'),
                'cpu_time': 0
                }

    def macs_for_instance(self, instance):
        icli = self._get_client()
        try:
            node = icli.node.get(instance['node'])
        except ironic_exception.HTTPNotFound:
            return []
        ports = icli.node.list_ports(node.uuid)
        return [p.address for p in ports]

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        # The compute manager is meant to know the node uuid, so missing uuid
        # is a significant issue. It may mean we've been passed the wrong data.
        node_uuid = instance.get('node')
        if not node_uuid:
            raise exception.NovaException(_("Ironic node uuid not supplied to "
                    "driver for instance %s.") % instance['uuid'])
        icli = self._get_client()
        node = icli.node.get(node_uuid)

        # Associate the node to this instance
        try:
            # NOTE(deva): this may raise a NodeAlreadyAssociated exception
            #             which we allow to propagate up to the scheduler,
            #             so it retries on another node.
            patch = [{'op': 'replace',
                      'path': '/instance_uuid',
                      'value': instance['uuid']}]
            self._retry_if_service_is_unavailable(icli.node.update,
                                                  node_uuid, patch)
        except (ironic_exception.HTTPBadRequest, MaximumRetriesReached):
            msg = _("Unable to set instance UUID for node %s") % node_uuid
            LOG.error(msg)
            raise exception.NovaException(msg)

        # Set image id, and other driver info so we can pass it down to Ironic
        # use the ironic_driver_fields file to import
        flavor = flavor_obj.Flavor.get_by_id(context,
                                             instance['instance_type_id'])
        self._add_driver_fields(node, instance, image_meta, flavor)

        #validate we ready to do the deploy
        validate_chk = icli.node.validate(node_uuid)
        if not validate_chk.deploy or not validate_chk.power:
            # something is wrong. undo we we have done
            self._cleanup_deploy(node, instance, network_info)
            raise exception.ValidationError(_(
                "Ironic node: %(id)s failed to validate."
                " (deploy: %(deploy)s, power: %(power)s)")
                % {'id': node.uuid,
                   'deploy': validate_chk.deploy,
                   'power': validate_chk.power})

        # prepare for the deploy
        try:
            self._plug_vifs(node, instance, network_info)
            self._start_firewall(instance, network_info)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_("Error preparing deploy for instance %(instance)s "
                            "on baremetal node %(node)s.") %
                          {'instance': instance['uuid'],
                           'node': node_uuid})
                self._cleanup_deploy(node, instance, network_info)

        # trigger the node deploy
        try:
            self._retry_if_service_is_unavailable(
                            icli.node.set_provision_state, node_uuid, 'active')
        except MaximumRetriesReached:
            msg = (_("Error triggering the node %s to start the deployment")
                   % node_uuid)
            LOG.error(msg)
            self._cleanup_deploy(node, instance, network_info)
            raise exception.NovaException(msg)
        except (ironic_exception.HTTPInternalServerError,  # Validations
                ironic_exception.HTTPBadRequest) as e:     # Maintenance
            msg = (_("Failed to request Ironic to provision instance "
                     "%(inst)s: %(reason)s") % {'inst': instance['uuid'],
                                                'reason': str(e)})
            LOG.error(msg)
            self._cleanup_deploy(node, instance, network_info)
            raise exception.InstanceDeployFailure(msg)

        # wait for the node to be marked as ACTIVE in Ironic
        def _wait_for_active():
            try:
                node = icli.node.get_by_instance_uuid(instance['uuid'])
            except ironic_exception.HTTPNotFound:
                raise exception.InstanceNotFound(instance_id=instance['uuid'])

            if node.provision_state == ironic_states.ACTIVE:
                # job is done
                raise loopingcall.LoopingCallDone()

            if node.target_provision_state == ironic_states.DELETED:
                # ironic is trying to delete it now
                raise exception.InstanceNotFound(instance_id=instance['uuid'])

            if node.provision_state == ironic_states.NOSTATE:
                # ironic already deleted it
                raise exception.InstanceNotFound(instance_id=instance['uuid'])

            if node.provision_state == ironic_states.DEPLOYFAIL:
                # ironic failed to deploy
                msg = (_("Failed to provision instance %(inst)s: %(reason)s")
                       % {'inst': instance['uuid'], 'reason': node.last_error})
                LOG.error(msg)
                raise exception.InstanceDeployFailure(msg)

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_active)
        # TODO(lucasagomes): Make the time configurable
        timer.start(interval=10).wait()

    def _unprovision(self, icli, instance, node):
        """This method is called from destroy() to unprovision
        already provisioned node after required checks.
        """
        try:
            self._retry_if_service_is_unavailable(
                icli.node.set_provision_state, node.uuid, 'deleted')
        except MaximumRetriesReached:
            msg = (_("Error triggering the unprovisioning of the node %s")
                   % node.uuid)
            LOG.error(msg)
            raise exception.NovaException(msg)
        except Exception as e:
            # if the node is already in a deprovisioned state, continue
            # This should be fixed in Ironic.
            # TODO(deva): This exception should be added to
            #             python-ironicclient and matched directly,
            #             rather than via __name__.
            if getattr(e, '__name__', None) == 'InstanceDeployFailure':
                pass
            else:
                raise

        def _wait_for_provision_state():
            try:
                node = icli.node.get_by_instance_uuid(instance['uuid'])
            except ironic_exception.HTTPNotFound:
                raise exception.InstanceNotFound(instance_id=instance['uuid'])

            if not node.provision_state:
                raise loopingcall.LoopingCallDone()

            if self.tries >= CONF.ironic.api_max_retries:
                msg = (_("Error destroying the instance on node %(node)s. "
                         "Provision state still '%(state)s'.")
                       % {'state': node.provision_state,
                          'node': node.uuid})
                LOG.error(msg)
                raise exception.NovaException(msg)
            else:
                self.tries += 1

        # wait for the state transition to finish
        self.tries = 0
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_provision_state)
        timer.start(interval=CONF.ironic.api_retry_interval).wait()

    def destroy(self, context, instance, network_info,
                block_device_info=None):
        icli = self._get_client()
        try:
            node = validate_instance_and_node(icli, instance)
        except exception.InstanceNotFound:
            LOG.debug(_("Destroy called on non-existing instance %s.")
                        % instance['uuid'])
            # NOTE(deva): if nova.compute.ComputeManager._delete_instance()
            #             is called on a non-existing instance, the only way
            #             to delete it is to return from this method
            #             without raising any exceptions.
            return

        if node.provision_state in (ironic_states.ACTIVE,
                                    ironic_states.DEPLOYFAIL,
                                    ironic_states.ERROR,
                                    ironic_states.DEPLOYWAIT):
            self._unprovision(icli, instance, node)

        self._cleanup_deploy(node, instance, network_info)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        pass

    def power_off(self, instance, node=None):
        # TODO(nobodycam): check the current power state first.
        icli = self._get_client()
        node = validate_instance_and_node(icli, instance)
        icli.node.set_power_state(node.uuid, 'off')

    def power_on(self, context, instance, network_info, block_device_info=None,
                 node=None):
        # TODO(nobodycam): check the current power state first.
        icli = self._get_client()
        node = validate_instance_and_node(icli, instance)
        icli.node.set_power_state(node.uuid, 'on')

    def get_host_stats(self, refresh=False):
        caps = []
        icli = self._get_client()

        for node in icli.node.list():
            res = self._node_resource(node)
            nodename = str(node.uuid)
            cpu_arch = str(node.properties.get('cpu_arch', 'NotFound'))

            nodes_extra_specs = self.extra_specs
            nodes_extra_specs['cpu_arch'] = cpu_arch
            data = {}
            data['vcpus'] = res['vcpus']
            data['vcpus_used'] = res['vcpus_used']
            data['cpu_info'] = res['cpu_info']
            data['disk_total'] = res['local_gb']
            data['disk_used'] = res['local_gb_used']
            data['disk_available'] = res['local_gb'] - res['local_gb_used']
            data['host_memory_total'] = res['memory_mb']
            data['host_memory_free'] = res['memory_mb'] - res['memory_mb_used']
            data['hypervisor_type'] = res['hypervisor_type']
            data['hypervisor_version'] = res['hypervisor_version']
            data['supported_instances'] = _get_nodes_supported_instances(
                                                                    cpu_arch)
            data.update(nodes_extra_specs)
            data['host'] = CONF.host
            data['hypervisor_hostname'] = nodename
            data['node'] = nodename
            caps.append(data)
        return caps

    def manage_image_cache(self, context, all_instances):
        pass

    def get_console_output(self, instance):
        raise NotImplementedError()

    def refresh_security_group_rules(self, security_group_id):
        pass

    def refresh_security_group_members(self, security_group_id):
        pass

    def refresh_provider_fw_rules(self):
        pass

    def refresh_instance_security_rules(self, instance):
        pass

    def ensure_filtering_rules_for_instance(self, instance_ref, network_info):
        pass

    def unfilter_instance(self, instance_ref, network_info):
        pass

    def _plug_vifs(self, node, instance, network_info):
        LOG.debug(_("plug: instance_uuid=%(uuid)s vif=%(network_info)s")
                  % {'uuid': instance['uuid'], 'network_info': network_info})
        # start by ensuring the ports are clear
        self._unplug_vifs(node, instance, network_info)

        icli = self._get_client()
        ports = icli.node.list_ports(node.uuid)

        if len(network_info) > len(ports):
            raise exception.NovaException(_(
                "Ironic node: %(id)s virtual to physical interface count"
                "  missmatch"
                " (Vif count: %(vif_count)d, Pif count: %(pif_count)d)")
                % {'id': node.uuid,
                   'vif_count': len(network_info),
                   'pif_count': len(ports)})

        if len(network_info) > 0:
            # not needed if no vif are defined
            for vif, pif in zip(network_info, ports):
                # attach what neutron needs directly to the port
                port_id = unicode(vif['id'])
                patch = [{'op': 'add',
                          'path': '/extra/vif_port_id',
                          'value': port_id}]
                try:
                    self._retry_if_service_is_unavailable(icli.port.update,
                                                          pif.uuid, patch)
                except MaximumRetriesReached:
                    msg = (_("Failed to set the VIF networking for port %s")
                           % pif.uuid)
                    raise exception.NovaException(msg)

    def _unplug_vifs(self, node, instance, network_info):
        LOG.debug(_("unplug: instance_uuid=%(uuid)s vif=%(network_info)s")
                  % {'uuid': instance['uuid'], 'network_info': network_info})
        if network_info and len(network_info) > 0:
            icli = self._get_client()
            ports = icli.node.list_ports(node.uuid)

            # not needed if no vif are defined
            for vif, pif in zip(network_info, ports):
                # we can not attach a dict directly
                patch = [{'op': 'remove', 'path': '/extra/vif_port_id'}]
                try:
                    self._retry_if_service_is_unavailable(icli.port.update,
                                                          pif.uuid, patch)
                except MaximumRetriesReached:
                    msg = (_("Failed to remove the VIF networking for port %s")
                           % pif.uuid)
                    LOG.warning(msg)
                except ironic_exception.HTTPBadRequest:
                    pass

    def plug_vifs(self, instance, network_info):
        icli = self._get_client()
        node = icli.node.get(instance['node'])
        self._plug_vifs(node, instance, network_info)

    def unplug_vifs(self, instance, network_info):
        icli = self._get_client()
        node = icli.node.get(instance['node'])
        self._unplug_vifs(node, instance, network_info)
