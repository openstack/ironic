==================
In-Band Inspection
==================

In-band inspection involves booting a ramdisk on the target node and fetching
information directly from it. This process is more fragile and time-consuming
than the out-of-band inspection, but it is not vendor-specific and works
across a wide range of hardware.

In the 2023.2 "Bobcat" release series, Ironic received an experimental
implementation of in-band inspection that does not require the separate
ironic-inspector_ service.

.. note::
   The implementation described in this document is not 100% compatible with
   the previous one (based on ironic-inspector_). Check the documentation and
   the release notes for which features are currently available.

   Use :doc:`inspector` for production deployments of Ironic 2023.2 or earlier
   releases.

.. _ironic-inspector: https://pypi.org/project/ironic-inspector

.. toctree::

   managed
   data
   hooks
   discovery

Configuration
-------------

In-band inspection is supported by all hardware types. The ``agent``
*inspect* interface has to be enabled to use it:

.. code-block:: ini

    [DEFAULT]
    enabled_inspect_interfaces = agent,no-inspect

You can make it the default if you want all nodes to use it automatically:

.. code-block:: ini

    [DEFAULT]
    default_inspect_interface = agent

Of course, you can configure it per node:

.. code-block:: console

   $ baremetal node set --inspect-interface agent <NODE>
