=================
Deploy Interfaces
=================

A *deploy* interface plays a critical role in the provisioning process. It
orchestrates the whole deployment and defines how the image gets transferred
to the target disk.

.. _iscsi-deploy:

iSCSI deploy
============

With ``iscsi`` deploy interface (and also ``oneview-iscsi``, specific to the
``oneview`` hardware type) the deploy ramdisk publishes the node's hard drive
as an iSCSI_ share. The ironic-conductor then copies the image to this share.
See :ref:`iSCSI deploy diagram <iscsi-deploy-example>` for a detailed
explanation of how this deploy interface works.

This interface is used by default, if enabled (see
:ref:`enable-hardware-interfaces`). You can specify it explicitly
when creating or updating a node::

    openstack baremetal node create --driver ipmi --deploy-interface iscsi
    openstack baremetal node set <NODE> --deploy-interface iscsi

.. _iSCSI: https://en.wikipedia.org/wiki/ISCSI

.. _direct-deploy:

Direct deploy
=============

With ``direct`` deploy interface (and also ``oneview-direct``, specific to the
``oneview`` hardware type), the deploy ramdisk fetches the image from an
HTTP location. It can be an object storage (swift or RadosGW) temporary URL or
a user-provided HTTP URL. The deploy ramdisk then copies the image to the
target disk.  See :ref:`direct deploy diagram <direct-deploy-example>` for
a detailed explanation of how this deploy interface works.

You can specify this deploy interface when creating or updating a node::

    openstack baremetal node create --driver ipmi --deploy-interface direct
    openstack baremetal node set <NODE> --deploy-interface direct

.. note::
    For historical reasons the ``direct`` deploy interface is sometimes called
    ``agent``. This is because before the Kilo release **ironic-python-agent**
    used to only support this deploy interface.

.. _ansible-deploy:

Ansible deploy
==============

This interface is similar to ``direct`` in the sense that the image
is downloaded by the ramdisk directly from the image store
(not from ironic-conductor host), but the logic of provisioning the node
is held in a set of Ansible playbooks that are applied by the
``ironic-conductor`` service handling the node.
While somewhat more complex to set up, this deploy interface provides greater
flexibility in terms of advanced node preparation during provisioning.

This interface is supported by most but not all hardware types declared
in ironic (for example, ``oneview`` hardware type does not support it).
However this deploy interface is not enabled by default.
To enable it, add ``ansible`` to the list of enabled deploy
interfaces in ``enabled_deploy_interfaces`` option in the ``[DEFAULT]``
section of ironic's configuration file:

.. code-block:: ini

   [DEFAULT]
   ...
   enabled_deploy_interfaces = iscsi,direct,ansible
   ...

Once enabled, you can specify this deploy interface when creating or updating
a node:

.. code-block:: shell

   openstack baremetal node create --driver ipmi --deploy-interface ansible
   openstack baremetal node set <NODE> --deploy-interface ansible

For more information about this deploy interface, its features and how to use
it, see :doc:`Ansible deploy interface <../drivers/ansible>`.


.. toctree::
   :hidden:

   ../drivers/ansible

Ramdisk deploy
==============

The ramdisk interface is intended to provide a mechanism to "deploy" an
instance where the item to be deployed is in reality a ramdisk.
Most commonly this is peformed when an instance is booted via PXE or iPXE,
with the only local storage contents being those in memory. Initially this
is only supported by the ``pxe`` boot interface, but other boot interfaces
could support this funtionality in the future.

As with most non-default interfaces, it must be enabled and set for a node
to be utilized:

.. code-block:: ini

   [DEFAULT]
   ...
   enabled_deploy_interfaces = iscsi,direct,ramdisk
   ...

Once enabled and the conductor(s) have been restarted, the interface can
be set upon creation of a new node or update a pre-existing node:

.. code-block:: shell

   openstack baremetal node create --driver ipmi \
       --deploy-interface ramdisk \
       --boot-interface pxe
   openstack baremetal node set <NODE> --deploy-interface ramdisk

The intended use case is for advanced scientific and ephemeral workloads
where the step of writing an image to the local storage is not required
or desired. As such, this interface does come with several caveats:

* Configuration drives are not supported.
* Disk image contents are not written to the bare metal node.
* Users and Operators who intend to leverage this interface should
  expect to leverage a metadata service, custom ramdisk images, or the
  ``instance_info/ramdisk_kernel_arguments`` parameter to add options to
  the kernel boot command line.
* Bare metal nodes must continue to have network access to PXE and iPXE
  network resources. This is contrary to most tenant networking enabled
  configurations where this access is restricted to the provisioning and
  cleaning networks
* As with all deployment interfaces, automatic cleaning of the node will
  still occur with the contents of any local storage being wiped between
  deployments.

.. warning::
   As of the Rocky release of the BareMetal service, only the ``pxe`` boot
   interface is supported.
