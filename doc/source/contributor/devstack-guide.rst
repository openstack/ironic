.. _`deploy_devstack`:

==============================
Deploying Ironic with DevStack
==============================

DevStack may be configured to deploy Ironic, setup Nova to use the Ironic
driver and provide hardware resources (network, baremetal compute nodes)
using a combination of OpenVSwitch and libvirt.  It is highly recommended
to deploy on an expendable virtual machine and not on your personal work
station.

.. seealso::

    https://docs.openstack.org/devstack/latest/

.. note::
    The devstack "demo" tenant has read-only access to Ironic's API. This is
    sufficient for all the examples below. Should you want to create or modify
    bare metal resources directly (ie. through Ironic rather than through Nova)
    you will need to use the devstack "admin" tenant.

Basic process
=============

Create a stack user with proper permissions using script from devstack::

    git clone https://opendev.org/openstack/devstack.git devstack
    sudo ./devstack/tools/create-stack-user.sh


Switch to the stack user and clone DevStack::

    sudo su - stack
    git clone https://opendev.org/openstack/devstack.git devstack


From the :ref:`Configurations` section below, create a ``local.conf`` file.

Once you have the configuration in place and ready to go, you can deploy
devstack with::

    ./stack.sh


.. note::
  Devstack configurations change frequently. If you are having trouble getting
  one of the below configs to work, please file a bug against Ironic or ask on
  #openstack-ironic in OFTC.

.. _configurations:

Configurations
==============

Ironic
------

Create devstack/local.conf with minimal settings required to enable Ironic.
This does not configure Nova to operate with Ironic.

An example local.conf that enables the ``direct``
:doc:`deploy interface </admin/interfaces/deploy>` and uses the ``ipmi``
hardware type by default::

    cd devstack
    cat >local.conf <<END
    [[local|localrc]]
    # Enable only minimal services
    disable_all_services
    enable_service g-api
    enable_service key
    enable_service memory_tracker
    enable_service mysql
    enable_service q-agt
    enable_service q-dhcp
    enable_service q-l3
    enable_service q-meta
    enable_service q-metering
    enable_service q-svc
    enable_service rabbit

    # Credentials
    ADMIN_PASSWORD=password
    DATABASE_PASSWORD=password
    RABBIT_PASSWORD=password
    SERVICE_PASSWORD=password
    SERVICE_TOKEN=password

    # Set glance's default limit to be baremetal image friendly
    GLANCE_LIMIT_IMAGE_SIZE_TOTAL=5000

    # Enable Ironic plugin
    enable_plugin ironic https://opendev.org/openstack/ironic

    # Create 3 virtual machines to pose as Ironic's baremetal nodes.
    IRONIC_VM_COUNT=3
    IRONIC_BAREMETAL_BASIC_OPS=True
    DEFAULT_INSTANCE_TYPE=baremetal

    IRONIC_RPC_TRANSPORT=json-rpc
    IRONIC_RAMDISK_TYPE=tinyipa

    # Enable additional hardware types, if needed.
    #IRONIC_ENABLED_HARDWARE_TYPES=ipmi,fake-hardware
    # Don't forget that many hardware types require enabling of additional
    # interfaces, most often power and management:
    #IRONIC_ENABLED_MANAGEMENT_INTERFACES=ipmitool,fake
    #IRONIC_ENABLED_POWER_INTERFACES=ipmitool,fake
    #IRONIC_DEFAULT_DEPLOY_INTERFACE=direct

    # Change this to alter the default driver for nodes created by devstack.
    # This driver should be in the enabled list above.
    IRONIC_DEPLOY_DRIVER="ipmi"

    # The parameters below represent the minimum possible values to create
    # functional nodes.
    IRONIC_VM_SPECS_RAM=1024
    IRONIC_VM_SPECS_DISK=3

    # Size of the ephemeral partition in GB. Use 0 for no ephemeral partition.
    IRONIC_VM_EPHEMERAL_DISK=0

    # To build your own IPA ramdisk from source, set this to True
    IRONIC_BUILD_DEPLOY_RAMDISK=False

    INSTALL_TEMPEST=False
    VIRT_DRIVER=ironic

    # By default, DevStack creates a 10.0.0.0/24 network for instances.
    # If this overlaps with the hosts network, you may adjust with the
    # following.
    IP_VERSION=4
    FIXED_RANGE=10.1.0.0/20
    IPV4_ADDRS_SAFE_TO_USE=10.1.0.0/20
    NETWORK_GATEWAY=10.1.0.1

    Q_AGENT=openvswitch
    Q_ML2_PLUGIN_MECHANISM_DRIVERS=openvswitch
    Q_ML2_TENANT_NETWORK_TYPE=vxlan

    # Log all output to files
    LOGFILE=/opt/stack/devstack.log
    LOGDIR=/opt/stack/logs
    IRONIC_VM_LOG_DIR=/opt/stack/ironic-bm-logs

    END

.. _itp:

Ironic with Nova
----------------
With this config, Nova will be configured to use Ironic's virt driver. Ironic
will have the ``direct`` :doc:`deploy interface </admin/interfaces/deploy>`
enabled and use the ``ipmi`` hardware type with this config::

    cd devstack
    cat >local.conf <<END
    [[local|localrc]]
    # Credentials
    ADMIN_PASSWORD=password
    DATABASE_PASSWORD=password
    RABBIT_PASSWORD=password
    SERVICE_PASSWORD=password
    SERVICE_TOKEN=password
    SWIFT_HASH=password
    SWIFT_TEMPURL_KEY=password

    # Set glance's default limit to be baremetal image friendly
    GLANCE_LIMIT_IMAGE_SIZE_TOTAL=5000

    # Enable Ironic plugin
    enable_plugin ironic https://opendev.org/openstack/ironic

    # Disable nova novnc service, ironic does not support it anyway.
    disable_service n-novnc

    # Enable Swift for the direct deploy interface.
    enable_service s-proxy s-object s-container s-account

    # Disable Horizon
    disable_service horizon

    # Disable Cinder
    disable_service cinder c-sch c-api c-vol

    # Configure networking by disabling OVN and enabling Neutron w/OVS.
    disable_service ovn-controller ovn-northd q-ovn-metadata-agent
    disable_service ovn-northd
    enable_service q-agt q-dhcp q-l3 q-svc q-meta
    Q_AGENT=openvswitch
    Q_ML2_PLUGIN_MECHANISM_DRIVERS="openvswitch"
    Q_ML2_TENANT_NETWORK_TYPE="vxlan"
    Q_USE_SECGROUP="False"

    # By default, devstack assumes you have IPv4 and IPv6 access. If you are on
    # a v4-only network, set the value below.
    # IP_VERSION=4

    # Swift temp URL's are required for the direct deploy interface
    SWIFT_ENABLE_TEMPURLS=True

    # Support via emulated BMC exists for the following hardware types, and
    # VMs to back them will be created by default unless IRONIC_IS_HARDWARE is
    # True.
    #  - ipmi (VirtualBMC)
    #  - redfish (sushy-tools)
    #
    # If you wish to change the default driver for nodes created by devstack,
    # you can do so by setting IRONIC_DEPLOY_DRIVER to the name of the driver
    # you wish used by default, and ensuring that driver (along with others) is
    # enabled.
    IRONIC_DEPLOY_DRIVER=ipmi

    # Example: Uncommenting these will configure redfish by default
    #IRONIC_ENABLED_HARDWARE_TYPES=redfish,ipmi,fake-hardware
    #IRONIC_DEPLOY_DRIVER=redfish
    # Don't forget that many hardware types require enabling of additional
    # interfaces, most often power and management:
    #IRONIC_ENABLED_MANAGEMENT_INTERFACES=redfish,ipmitool,fake
    #IRONIC_ENABLED_POWER_INTERFACES=redfish,ipmitool,fake

    IRONIC_VM_COUNT=3
    IRONIC_BAREMETAL_BASIC_OPS=True
    DEFAULT_INSTANCE_TYPE=baremetal

    # You can also change the default deploy interface used.
    #IRONIC_DEFAULT_DEPLOY_INTERFACE=direct

    # The parameters below represent the minimum possible values to create
    # functional nodes.
    IRONIC_VM_SPECS_RAM=2048
    IRONIC_VM_SPECS_DISK=10

    # Size of the ephemeral partition in GB. Use 0 for no ephemeral partition.
    IRONIC_VM_EPHEMERAL_DISK=0

    # To build your own IPA ramdisk from source, set this to True
    IRONIC_BUILD_DEPLOY_RAMDISK=False

    VIRT_DRIVER=ironic

    # By default, DevStack creates a 10.0.0.0/24 network for instances.
    # If this overlaps with the hosts network, you may adjust with the
    # following.
    # NETWORK_GATEWAY=10.1.0.1
    # FIXED_RANGE=10.1.0.0/24
    # FIXED_NETWORK_SIZE=256

    # Log all output to files
    LOGFILE=$HOME/devstack.log
    LOGDIR=$HOME/logs
    IRONIC_VM_LOG_DIR=$HOME/ironic-bm-logs

    END


.. note::
  For adding :ref:`tempest` support to this configuration, see the
  :ref:`tempest` section of this document.

Other Devstack Configurations
-----------------------------
There are additional devstack configurations in other parts of contributor
documentation:

* :ref:`Ironic Boot from Volume <BFVDevstack>`
* :ref:`Ironic w/Multitenant Networking <DevstackMTNetwork>`

Deploying to Ironic node using Nova
===================================

This section assumes you already have a working, deployed Ironic with Nova
configured as laid out above.

We need to gather two more pieces of information before performing the
deploy, we need to determine what image to use, and what network to use.

Determine the network::

    net_id=$(openstack network list | egrep "$PRIVATE_NETWORK_NAME"'[^-]' | awk '{ print $2 }')


We also need to choose an image to deploy. Devstack has both cirros partition
and whole disk images by default. For this example, we'll use the whole disk
image::

    image=$(openstack image list | grep -- '-disk' | awk '{ print $2 }')

Source credentials and create a key, and spawn an instance as the ``demo``
user::

    . ~/devstack/openrc demo

    # create keypair
    ssh-keygen
    openstack keypair create --public-key ~/.ssh/id_rsa.pub default

Now you're ready to build::

    openstack server create --flavor baremetal --nic net-id=$net_id --image $image --key-name default testing

You should now see a Nova instance building::

    openstack server list --long
    +----------+---------+--------+------------+-------------+----------+------------+----------+-------------------+------+------------+
    | ID       | Name    | Status | Task State | Power State | Networks | Image Name | Image ID | Availability Zone | Host | Properties |
    +----------+---------+--------+------------+-------------+----------+------------+----------+-------------------+------+------------+
    | a2c7f812 | testing | BUILD  | spawning   | NOSTATE     |          | cirros-0.3 | 44d4092a | nova              |      |            |
    | -e386-4a |         |        |            |             |          | .5-x86_64- | -51ac-47 |                   |      |            |
    | 22-b393- |         |        |            |             |          | disk       | 51-9c50- |                   |      |            |
    | fe1802ab |         |        |            |             |          |            | fd6e2050 |                   |      |            |
    | d56e     |         |        |            |             |          |            | faa1     |                   |      |            |
    +----------+---------+--------+------------+-------------+----------+------------+----------+-------------------+------+------------+

Nova will be interfacing with Ironic conductor to spawn the node.  On the
Ironic side, you should see an Ironic node associated with this Nova instance.
It should be powered on and in a 'wait call-back' provisioning state::

    baremetal node list
    +--------------------------------------+--------+--------------------------------------+-------------+--------------------+-------------+
    | UUID                                 | Name   | Instance UUID                        | Power State | Provisioning State | Maintenance |
    +--------------------------------------+--------+--------------------------------------+-------------+--------------------+-------------+
    | 9e592cbe-e492-4e4f-bf8f-4c9e0ad1868f | node-0 | None                                 | power off   | None               | False       |
    | ec0c6384-cc3a-4edf-b7db-abde1998be96 | node-1 | None                                 | power off   | None               | False       |
    | 4099e31c-576c-48f8-b460-75e1b14e497f | node-2 | a2c7f812-e386-4a22-b393-fe1802abd56e | power on    | wait call-back     | False       |
    +--------------------------------------+--------+--------------------------------------+-------------+--------------------+-------------+

At this point, Ironic conductor has called to libvirt (via virtualbmc) to
power on a virtual machine, which will PXE + TFTP boot from the conductor node and
progress through the Ironic provisioning workflow.  One libvirt domain should
be active now::

    sudo virsh list --all
     Id    Name                           State
    ----------------------------------------------------
     2     node-2                         running
     -     node-0                         shut off
     -     node-1                         shut off

This provisioning process may take some time depending on the performance of
the host system, but Ironic should eventually show the node as having an
'active' provisioning state::

    baremetal node list
    +--------------------------------------+--------+--------------------------------------+-------------+--------------------+-------------+
    | UUID                                 | Name   | Instance UUID                        | Power State | Provisioning State | Maintenance |
    +--------------------------------------+--------+--------------------------------------+-------------+--------------------+-------------+
    | 9e592cbe-e492-4e4f-bf8f-4c9e0ad1868f | node-0 | None                                 | power off   | None               | False       |
    | ec0c6384-cc3a-4edf-b7db-abde1998be96 | node-1 | None                                 | power off   | None               | False       |
    | 4099e31c-576c-48f8-b460-75e1b14e497f | node-2 | a2c7f812-e386-4a22-b393-fe1802abd56e | power on    | active             | False       |
    +--------------------------------------+--------+--------------------------------------+-------------+--------------------+-------------+

This should also be reflected in the Nova instance state, which at this point
should be ACTIVE, Running and an associated private IP::

    openstack server list --long
    +----------+---------+--------+------------+-------------+---------------+------------+----------+-------------------+------+------------+
    | ID       | Name    | Status | Task State | Power State | Networks      | Image Name | Image ID | Availability Zone | Host | Properties |
    +----------+---------+--------+------------+-------------+---------------+------------+----------+-------------------+------+------------+
    | a2c7f812 | testing | ACTIVE | none       | Running     | private=10.1. | cirros-0.3 | 44d4092a | nova              |      |            |
    | -e386-4a |         |        |            |             | 0.4, fd7d:1f3 | .5-x86_64- | -51ac-47 |                   |      |            |
    | 22-b393- |         |        |            |             | c:4bf1:0:f816 | disk       | 51-9c50- |                   |      |            |
    | fe1802ab |         |        |            |             | :3eff:f39d:6d |            | fd6e2050 |                   |      |            |
    | d56e     |         |        |            |             | 94            |            | faa1     |                   |      |            |
    +----------+---------+--------+------------+-------------+---------------+------------+----------+-------------------+------+------------+

The server should now be accessible via SSH::

    ssh cirros@10.1.0.4
    $

Testing Ironic with Tempest
===========================

.. _tempest:

Add Ironic Tempest Plugin
-------------------------

Using the stack user, clone the ironic-tempest-plugin repository in the same
directory you cloned DevStack::

    git clone https://opendev.org/openstack/ironic-tempest-plugin.git

Then, add the following configuration to a working Ironic with Nova
devstack configuration::

    TEMPEST_PLUGINS=/opt/stack/ironic-tempest-plugin

Running tests
-------------
.. note::
    Some tests may be skipped depending on the configuration of your
    environment, they may be reliant on a driver or a capability that you
    did not configure.

After deploying devstack including Ironic with the
ironic-tempest-plugin enabled, one might want to run integration
tests against the running cloud. The Tempest project is the project
that offers an integration test suite for OpenStack.

First, navigate to Tempest directory::

  cd /opt/stack/tempest

To run all tests from the `Ironic plugin
<https://opendev.org/openstack/ironic-tempest-plugin/src/branch/master/>`_,
execute the following command::

  tox -e all -- ironic

To limit the amount of tests that you would like to run, you can use
a regex. For instance, to limit the run to a single test file, the
following command can be used::

  tox -e all -- ironic_tempest_plugin.tests.scenario.test_baremetal_basic_ops


Debugging tests
---------------

It is sometimes useful to step through the test code, line by line,
especially when the error output is vague. This can be done by
running the tests in debug mode and using a debugger such as `pdb
<https://docs.python.org/2/library/pdb.html>`_.

For example, after editing the *test_baremetal_basic_ops* file and
setting up the pdb traces you can invoke the ``run_tempest.sh`` script
in the Tempest directory with the following parameters::

  ./run_tempest.sh -N -d ironic_tempest_plugin.tests.scenario.test_baremetal_basic_ops

* The *-N* parameter tells the script to run the tests in the local
  environment (without a virtualenv) so it can find the Ironic tempest
  plugin.

* The *-d* parameter enables the debug mode, allowing it to be used
  with pdb.

For more information about the supported parameters see::

  ./run_tempest.sh --help

.. note::
   Always be careful when running debuggers in time sensitive code,
   they may cause timeout errors that weren't there before.


FAQ/Tips for development using devstack
=======================================

VM logs are missing
-------------------
When running QEMU as non-root user (e.g. ``qemu`` on Fedora or ``libvirt-qemu`` on Ubuntu),
make sure ``IRONIC_VM_LOG_DIR`` points to a directory where QEMU will be able to write.
You can verify this with, for example::

      # on Fedora
      sudo -u qemu touch $HOME/ironic-bm-logs/test.log
      # on Ubuntu
      sudo -u libvirt-qemu touch $HOME/ironic-bm-logs/test.log

Downloading an unmerged patch when stacking
-------------------------------------------
To check out an in-progress patch for testing, you can add a Git ref to the
``enable_plugin`` line. For instance::

      enable_plugin ironic https://opendev.org/openstack/ironic refs/changes/46/295946/15

For a patch in review, you can find the ref to use by clicking the
"Download" button in Gerrit. You can also specify a different git repo, or
a branch or tag::

      enable_plugin ironic https://github.com/openstack/ironic stable/kilo

For more details, see the
`devstack plugin interface documentation
<https://docs.openstack.org/devstack/latest/plugins.html#plugin-interface>`_.
