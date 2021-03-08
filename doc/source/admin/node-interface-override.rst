=======================
Node Interface Override
=======================

Non-admins with temporary access to a node, may wish to specify different
node interfaces. However, allowing them to set these interface values is
problematic, as there is no automated way to ensure that the original
interface values are restored.

This guide details a method for temporarily overriding a node interface
value.

Overriding a Node Interface
===========================

In order to temporarily override a node interface, simply set the
appropriate value in `instance_info`. For example, if you'd like to
override a node's storage interface, run the following::

  baremetal node set --instance-info storage_interface=cinder node-1

`instance_info` values persist until after a node is cleaned.
