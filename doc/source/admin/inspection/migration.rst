Migrating from ironic-inspector
===============================

This document outlines the process of migrating from a separate
ironic-inspector_ service to the built-in :doc:`in-band inspection <index>`.

.. note::
   This is a live document that is updated as more ironic-inspector features
   are supported in ironic. If you're upgrading to a branch other than
   ``master``, use the version of this document from the target branch.

.. _ironic-inspector: https://docs.openstack.org/ironic-inspector/

Understand the feature differences
----------------------------------

Removed
~~~~~~~

Some rarely used or controversial features have not been migrated to ironic.
This list currently includes:

* `Retrieving unprocesses inspection data
  <https://docs.openstack.org/api-ref/baremetal-introspection/#get-unprocessed-introspection-data>`_
* `Reapplying the processing pipeline on new data
  <https://docs.openstack.org/api-ref/baremetal-introspection/#reapply-introspection-on-data>`_
* :doc:`discovery` is no longer based on plug-ins.
* Introspection of nodes in the ``active`` provision state.
* PXE filters based on ``iptables``.
* Certain client commands are not available in ironicclient_, for example, the
  ones that `display the network interface information from the LLDP data
  <https://docs.openstack.org/python-ironic-inspector-client/latest/cli/index.html#list-interface-data>`_.

:ironic-inspector-doc:`Inspection rules <user/usage.html#introspection-rules>`
are also currently not implemented but are planned for the 2024.2 release or
later.

New defaults
~~~~~~~~~~~~

* The database :oslo.config:option:`data storage backend
  <inventory.data_backend>` is used by default.
* The list of :oslo.config:option:`default hooks <inspector.default_hooks>` is
  limited to only most commonly used ones (see also `Built-in hooks`_).

Built-in hooks
~~~~~~~~~~~~~~

Most of the :ironic-inspector-doc:`introspection hooks
<user/usage.html#plugins>` have been :doc:`migrated to ironic <hooks>`,
although many have been migrated for clarity and consistency.

.. list-table:: Hooks mapping
   :header-rows: 1

   * - Inspector
     - ironic
     - ``default_hooks``?
     - Notes
   * - ``accelerators``
     - ``accelerators``
     - No
     -
   * - ``capabilities``
     - ``boot-mode``, ``cpu-capabilities``
     - No
     - Split into two logical parts.
   * - ``extra_hardware``
     - ``extra-hardware``
     - No
     - python-hardware_ is not actively maintained any more.
   * - ``lldp_basic``
     - ``parse-lldp``
     - No
     -
   * - ``local_link_connection``
     - ``local-link-connection``
     - No
     -
   * - ``pci_devices``
     - ``pci-devices``
     - No
     -
   * - ``physnet_cidr_map``
     - ``physical-network``
     - No
     -
   * - ``raid_device``
     - ``raid-device``
     - No
     -
   * - ``root_device``
     - ``root-device``
     - No
     -
   * - ``ramdisk_error``
     - ``ramdisk-error``
     - **Yes**
     -
   * - ``scheduler``
     - ``architecture``, ``memory``
     - Only ``architecture``
     - Split, dropped ``local_gb`` and ``vcpus`` support.
   * - ``validate_interfaces``
     - ``validate-interfaces``, ``ports``
     - **Yes**
     - Split into two logical parts.

.. _python-hardware: https://github.com/redhat-cip/hardware

Custom hooks
~~~~~~~~~~~~

A custom hook (called *processing hook* in ironic-inspector) has to be
derived from the base class :py:class:`InspectionHook
<ironic.drivers.modules.inspector.hooks.base.InspectionHook>`. It differs
from the older :ironic-inspector-doc:`ProcessingHook
<contributor/api/ironic_inspector.plugins.base.html#ironic_inspector.plugins.base.ProcessingHook>`
in a few important ways, requiring custom hooks to be adapted for ironic:

* Hooks operate on the regular :py:class:`task
  <ironic.conductor.task_manager.TaskManager>` instead of the
  inspector-specific ``NodeInfo`` object.
* Since changes to nodes and ports no longer require an API call, hooks are
  expected to commit their changes immediately rather than letting them
  accumulate on the task object.
* The hook methods have been renamed: ``before_processing`` is called
  ``preprocess``, the ``__call__`` method is used instead of
  ``before_update``.
* *Introspection data* has been split into its *inventory* part and *plugin
  data*. Hooks should not update the inventory.
* New hooks use the entry point ``ironic.inspection.hooks`` instead of
  ``ironic_inspector.hooks.processing``.

Other concerns
~~~~~~~~~~~~~~

* There is no way to migrate the inspection data automatically. You need to
  repeat inspections or copy the data over manually.

Migration process
-----------------

1. Make sure you're running at ironic 2024.1 or newer.
2. Enable the new inspection implementation as described in :doc:`index`.
3. Carefully research options in the :oslo.config:group:`inventory` and
   :oslo.config:group:`inspector` sections. Update options to match similar
   ones in the ironic-inspector configuration.
4. Enable the required `Built-in hooks`_, taking into the account the new names
   and composition.
5. If using network boot and *unmanaged* inspection or auto-discovery,
   :ref:`configure unmanaged boot <configure-unmanaged-inspection>`.
6. If using the OpenStack Networking, consider configuring (but not starting
   yet) the :doc:`pxe_filter`.
7. Make sure no inspection are running.
8. Stop ironic-inspector or at least disable its PXE filter (it may conflict
   with the one used here).
9. Start :doc:`pxe_filter` if needed. Restart the Bare Metal service.
10. Change all nodes to use the new inspection interface, for example:

    .. code-block:: bash

        baremetal node list --fields uuid inspect_interface -f value | while read uuid iface; do
            if [ "$iface" = "inspector" ]; then
                baremetal node set --inspect-interface agent "$uuid"
            fi
        done

11. Make sure your scripts use ironicclient_ and the Bare Metal API in
    OpenStackSDK instead of the client API that is specific to
    ironic-inspector.

.. _ironicclient: https://docs.openstack.org/python-ironicclient/latest/
