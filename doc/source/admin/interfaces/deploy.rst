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

The ``iscsi`` deploy interface is also used in all of the *classic drivers*
with names starting with ``pxe_`` (except for ``pxe_agent_cimc``)
and ``iscsi_``.

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

The ``direct`` deploy interface is also used in all *classic drivers*
whose names include ``agent``.

.. note::
    For historical reasons the ``direct`` deploy interface is sometimes called
    ``agent``, and some *classic drivers* using it are called ``agent_*``.
    This is because before the Kilo release **ironic-python-agent** used to
    only support this deploy interface.
