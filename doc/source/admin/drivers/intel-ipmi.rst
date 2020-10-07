=================
Intel IPMI driver
=================

Overview
========

The ``intel-ipmi``  hardware type is same as the :doc:`ipmitool` hardware
type except for the support of Intel Speed Select Performance Profile
(Intel SST-PP_) feature. Intel SST-PP allows a server to run different
workloads by configuring the CPU to run at 3 distinct operating points
or profiles.

Intel SST-PP supports three configuration levels:

* 0 - Intel SST-PP Base Config
* 1 - Intel SST-PP Config 1
* 2 - Intel SST-PP Config 2

The following table shows the list of active cores and their base frequency at
different SST-PP config levels:

 ============== ========= ===================
    Config       Cores      Base Freq (GHz)
 ============== ========= ===================
     Base         24             2.4
   Config 1       20             2.5
   Config 2       16             2.7
 ============== ========= ===================

This configuration is managed by the management interface ``intel-ipmitool``
for IntelIPMI hardware.

IntelIPMI manages nodes by using IPMI_ (Intelligent Platform
Management Interface) protocol versions 2.0 or 1.5. It uses the IPMItool_
utility which is an open-source command-line interface (CLI) for controlling
IPMI-enabled devices.

Glossary
========

* IPMI - Intelligent Platform Management Interface.
* Intel SST-PP - Intel Speed Select Performance Profile.

Enabling the IntelIPMI hardware type
====================================

Please see :doc:`/install/configure-ipmi` for the required dependencies.

#. To enable ``intel-ipmi`` hardware, add the following configuration to your
   ``ironic.conf``:

   .. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = intel-ipmi
    enabled_management_interfaces = intel-ipmitool

#. Restart the Ironic conductor service::

    sudo service ironic-conductor restart

    # Or, for RDO:
    sudo systemctl restart openstack-ironic-conductor

Registering a node with the IntelIPMI driver
============================================

Nodes configured to use the IntelIPMI drivers should have the
``driver`` field set to ``intel-ipmi``.

All the configuration value required for IntelIPMI is the same as the IPMI
hardware type except the management interface which is ``intel-ipmitool``.
Refer :doc:`ipmitool` for details.

The ``baremetal node create`` command can be used to enroll a node
with an IntelIPMI driver. For example::

    baremetal node create --driver intel-ipmi \
        --driver-info ipmi_address=<address> \
        --driver-info ipmi_username=<username> \
        --driver-info ipmi_password=<password>


Features of the ``intel-ipmi`` hardware type
============================================

Intel SST-PP
^^^^^^^^^^^^^

A node with Intel SST-PP can be configured to use it via
``configure_intel_speedselect`` deploy step. This deploy accepts:

* ``intel_speedselect_config``:
  Hexadecimal code of Intel SST-PP configuration. Accepted values are
  '0x00', '0x01', '0x02'. These values correspond to
  `Intel SST-PP Config Base`, `Intel SST-PP Config 1`,
  `Intel SST-PP Config 2` respectively. The input value must be a string.

* ``socket_count``:
  Number of sockets in the node. The input value must be a positive
  integer (1 by default).

The deploy step issues an IPMI command with the raw code for each socket in
the node to set the requested configuration. A reboot is required to reflect
the changes.

Each configuration profile is mapped to traits that Ironic understands.
Please note that these names are used for example purpose only. Any name can
be used. Only the parameter value should match the deploy step
``configure_intel_speedselect``.

* 0 - ``CUSTOM_INTEL_SPEED_SELECT_CONFIG_BASE``
* 1 - ``CUSTOM_INTEL_SPEED_SELECT_CONFIG_1``
* 2 - ``CUSTOM_INTEL_SPEED_SELECT_CONFIG_2``

Now to configure a node with Intel SST-PP while provisioning, create deploy
templates for each profiles in Ironic.

.. code-block:: console

   baremetal deploy template create \
      CUSTOM_INTEL_SPEED_SELECT_CONFIG_BASE \
      --steps '[{"interface": "management", "step": "configure_intel_speedselect", "args": {"intel_speedselect_config": "0x00", "socket_count": 2}, "priority": 150}]'

   baremetal deploy template create \
       CUSTOM_INTEL_SPEED_SELECT_CONFIG_1 \
       --steps '[{"interface": "management", "step": "configure_intel_speedselect", "args": {"intel_speedselect_config": "0x01", "socket_count": 2}, "priority": 150}]'

   baremetal deploy template create \
      CUSTOM_INTEL_SPEED_SELECT_CONFIG_2 \
      --steps '[{"interface": "management", "step": "configure_intel_speedselect", "args": {"intel_speedselect_config": "0x02", "socket_count": 2}, "priority": 150}]'


All Intel SST-PP capable nodes should have these traits associated.

.. code-block:: console

   baremetal node add trait node-0 \
      CUSTOM_INTEL_SPEED_SELECT_CONFIG_BASE \
      CUSTOM_INTEL_SPEED_SELECT_CONFIG_1 \
      CUSTOM_INTEL_SPEED_SELECT_CONFIG_2

To trigger the Intel SST-PP configuration during node provisioning, one of the traits
can be added to the flavor.


.. code-block:: console

   openstack flavor set baremetal --property trait:CUSTOM_INTEL_SPEED_SELECT_CONFIG_1=required

Finally create a server with ``baremetal`` flavor to provision a baremetal node
with Intel SST-PP profile *Config 1*.

.. _IPMI: https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface
.. _IPMItool: https://sourceforge.net/projects/ipmitool/
.. _SST-PP: https://www.intel.com/content/www/us/en/architecture-and-technology/speed-select-technology-article.html
