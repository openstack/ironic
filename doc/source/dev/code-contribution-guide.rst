.. _code-contribution-guide:

=======================
Code Contribution Guide
=======================

This document provides some necessary points for developers to consider when
writing and reviewing Ironic code. The checklist will help developers get things
right.

Live Upgrade Related Concerns
=============================
Ironic implements upgrade with the same methodology of Nova:
    http://docs.openstack.org/developer/nova/upgrade.html

Ironic API RPC Versions
-----------------------

*  When the signature(arguments) of an RPC method is changed, the following things
   need to be considered:

 - The RPC version must be incremented and be the same value for both the client
   (conductor/rpcapi.py, used by ironic-api) and the server (conductor/manager.py,
   used by ironic-conductor).
 - New arguments of the method can only be added as optional. Existing arguments cannot be
   removed or changed in incompatible ways (with the method in older RPC versions).
 - Client-side can pin a version cap by passing ``version_cap`` to the constructor
   of oslo_messaging.RPCClient. Methods which change arguments should run
   client.can_send_version() to see if the version of the request is compatible with the
   version cap of RPC Client, otherwise the request needs to be created to work with a
   previous version that is supported.
 - Server-side should tolerate the older version of requests in order to keep
   working during the progress of live upgrade. The behavior of server-side should
   depend on the input parameters passed from the client-side.

Object Versions
---------------
* When Object classes (subclasses of ironic.objects.base.IronicObject) are modified, the
  following things need to be considered:

 - The change of fields and the signature of remotable method needs a bump of object
   version.
 - The arguments of methods can only be added as optional, they cannot be
   removed or changed in an incompatible way.
 - Fields types cannot be changed. If it is a must, create a new field and
   deprecate the old one.
 - When new version objects communicate with old version objects,
   obj_make_compatible() will be called to convert objects to the target version during
   serialization. So objects should implement their own obj_make_compatible() to
   remove/alter attributes which was added/changed after the target version.
 - There is a test (object/test_objects.py) to generate the hash of object fields and the
   signtures of remotable methods, which helps developers to check if the change of
   objects need a version bump. The object fingerprint should only be updated with a
   version bump.
