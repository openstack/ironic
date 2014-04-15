.. _drivers:

=================
Pluggable Drivers
=================

The IPMITool driver provides an interface to the command-line `ipmitool`_
utility, whereas the IPMINative driver provides an interface to the newer
`pyghmi`_ python library.

The SSH driver provides an interface to control the power state of virtual
machines used in our test environments.

The SeaMicro driver provides an enhanced interface for SeaMicro hardware.

.. toctree::
    ../api/ironic.drivers.base
    ../api/ironic.drivers.pxe
    ../api/ironic.drivers.modules.ipminative
    ../api/ironic.drivers.modules.ipmitool
    ../api/ironic.drivers.modules.pxe
    ../api/ironic.drivers.modules.seamicro
    ../api/ironic.drivers.modules.ssh

.. _ipmitool: http://ipmitool.sourceforge.net/
.. _pyghmi: https://github.com/stackforge/pyghmi
