==========================================
Ironic multitenant networking and DevStack
==========================================

This guide will walk you through using OpenStack Ironic/Neutron with the ML2
``networking-generic-switch`` plugin.


Using VMs as baremetal servers
==============================

This scenario shows how to setup Devstack to use Ironic/Neutron integration
with VMs as baremetal servers and ML2 ``networking-generic-switch``
that interacts with OVS.


DevStack Configuration
----------------------
The following is ``local.conf`` that will setup Devstack with 3 VMs that are
registered in ironic. ``networking-generic-switch`` driver will be installed and
configured in Neutron.

::

    [[local|localrc]]

    # Configure ironic from ironic devstack plugin.
    enable_plugin ironic https://opendev.org/openstack/ironic

    # Install networking-generic-switch Neutron ML2 driver that interacts with OVS
    enable_plugin networking-generic-switch https://opendev.org/openstack/networking-generic-switch

    # Add link local info when registering Ironic node
    IRONIC_USE_LINK_LOCAL=True

    IRONIC_ENABLED_NETWORK_INTERFACES=flat,neutron
    IRONIC_NETWORK_INTERFACE=neutron

    #Networking configuration
    OVS_PHYSICAL_BRIDGE=brbm
    PHYSICAL_NETWORK=mynetwork
    IRONIC_PROVISION_NETWORK_NAME=ironic-provision
    IRONIC_PROVISION_SUBNET_PREFIX=10.0.5.0/24
    IRONIC_PROVISION_SUBNET_GATEWAY=10.0.5.1

    Q_PLUGIN=ml2
    ENABLE_TENANT_VLANS=True
    Q_ML2_TENANT_NETWORK_TYPE=vlan
    TENANT_VLAN_RANGE=100:150

    # Credentials
    ADMIN_PASSWORD=password
    RABBIT_PASSWORD=password
    DATABASE_PASSWORD=password
    SERVICE_PASSWORD=password
    SERVICE_TOKEN=password
    SWIFT_HASH=password
    SWIFT_TEMPURL_KEY=password

    # Enable Ironic API and Ironic Conductor
    enable_service ironic
    enable_service ir-api
    enable_service ir-cond

    # Disable nova novnc service, ironic does not support it anyway.
    disable_service n-novnc

    # Enable Swift for the direct deploy interface.
    enable_service s-proxy
    enable_service s-object
    enable_service s-container
    enable_service s-account

    # Disable Horizon
    disable_service horizon

    # Disable Cinder
    disable_service cinder c-sch c-api c-vol

    # Disable Tempest
    disable_service tempest

    # Swift temp URL's are required for the direct deploy interface.
    SWIFT_ENABLE_TEMPURLS=True

    # Create 3 virtual machines to pose as Ironic's baremetal nodes.
    IRONIC_VM_COUNT=3
    IRONIC_BAREMETAL_BASIC_OPS=True

    # Enable additional hardware types, if needed.
    #IRONIC_ENABLED_HARDWARE_TYPES=ipmi,fake-hardware
    # Don't forget that many hardware types require enabling of additional
    # interfaces, most often power and management:
    #IRONIC_ENABLED_MANAGEMENT_INTERFACES=ipmitool,fake
    #IRONIC_ENABLED_POWER_INTERFACES=ipmitool,fake
    #IRONIC_DEFAULT_DEPLOY_INTERFACE=direct

    # Change this to alter the default driver for nodes created by devstack.
    # This driver should be in the enabled list above.
    IRONIC_DEPLOY_DRIVER=ipmi

    # The parameters below represent the minimum possible values to create
    # functional nodes.
    IRONIC_VM_SPECS_RAM=1024
    IRONIC_VM_SPECS_DISK=10

    # Size of the ephemeral partition in GB. Use 0 for no ephemeral partition.
    IRONIC_VM_EPHEMERAL_DISK=0

    # To build your own IPA ramdisk from source, set this to True
    IRONIC_BUILD_DEPLOY_RAMDISK=False

    VIRT_DRIVER=ironic

    # By default, DevStack creates a 10.0.0.0/24 network for instances.
    # If this overlaps with the hosts network, you may adjust with the
    # following.
    NETWORK_GATEWAY=10.1.0.1
    FIXED_RANGE=10.1.0.0/24
    FIXED_NETWORK_SIZE=256

    # Log all output to files
    LOGFILE=$HOME/devstack.log
    LOGDIR=$HOME/logs
    IRONIC_VM_LOG_DIR=$HOME/ironic-bm-logs
