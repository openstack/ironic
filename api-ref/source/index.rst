:tocdepth: 2

================
 Bare Metal API
================

This documentation describes the REST API for the Ironic service, beginning with the
5.1.0 (Mitaka) release.

Version negotiation is implemented in the server. When the negotiated version
is not the current maximum version, both request and response may not match what
is presented in this document. Significant changes may be noted inline.


.. rest_expand_all::

.. include:: baremetal-api-versions.inc
.. include:: baremetal-api-v1-nodes.inc
.. include:: baremetal-api-v1-node-management.inc
.. include:: baremetal-api-v1-node-passthru.inc
.. include:: baremetal-api-v1-ports.inc
.. include:: baremetal-api-v1-nodes-ports.inc
.. include:: baremetal-api-v1-drivers.inc
.. include:: baremetal-api-v1-driver-passthru.inc
.. include:: baremetal-api-v1-chassis.inc

