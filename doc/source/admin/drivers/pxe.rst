.. pxe:

==============================
Configuring PXE boot interface
==============================

Enable persistent boot device for deploy/clean operation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ironic uses non-persistent boot for cleaning/deploying phases as default,
in PXE interface. For some drivers, a persistent change is far more
costly than a non-persistent one, so this can bring performance improvements.

Enable persistent boot device on node
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Set the flag ``force_persistent_boot_device`` to ``True`` in the node's ``driver_info``::

    $ openstack baremetal node set --driver-info force_persistent_boot_device=True <node>

   .. note::
      It's recommended to check if the node's state has not changed as there
      is no way of locking the node between these commands.

Once the flag is present, the next cleaning and deploy steps will be done
with persistent boot for that node.
