.. _rolling-upgrades-dev:

================
Rolling Upgrades
================

The ironic (ironic-api and ironic-conductor) services support rolling upgrades,
starting with a rolling upgrade from the Ocata to the Pike release. This
describes the design of rolling upgrades, followed by notes for developing new
features or modifying an IronicObject.

Design
======

Rolling upgrades between releases
---------------------------------
Ironic follows the `release-cycle-with-intermediary release model
<https://releases.openstack.org/reference/release_models.html>`_.
The releases are `semantic-versioned <http://semver.org/>`_, in the form
<major>.<minor>.<patch>.
We refer to a ``named release`` of ironic as the release associated with a
development cycle like Pike.

In addition, ironic follows the `standard deprecation policy
<https://governance.openstack.org/tc/reference/tags/assert_follows-standard-deprecation.html>`_,
which says that the deprecation period must be at least three months
and a cycle boundary. This means that there will never be anything that
is both deprecated *and* removed between two named releases.

Rolling upgrades will be supported between:

* named release N to N+1 (starting with N == Ocata)
* any named release to its latest revision, containing backported bug fixes.
  Because those bug fixes can contain improvements to the upgrade process, the
  operator should patch the system before upgrading between named releases.
* most recent named release N (and semver releases newer than N) to master.
  As with the above bullet point, there may be a bug or a feature introduced
  on a master branch, that we want to remove before publishing a named release.
  Deprecation policy allows to do this in a 3 month time frame.
  If the feature was included and removed in intermediate releases, there
  should be a release note added, with instructions on how to do a rolling
  upgrade to master from an affected release or release span. This would
  typically instruct the operator to upgrade to a particular intermediate
  release, before upgrading to master.

Rolling upgrade process
-----------------------
Ironic supports rolling upgrades as described in the
:doc:`upgrade guide <../admin/upgrade-guide>`.

The upgrade process will cause the ironic services to be running the ``FromVer``
and ``ToVer`` releases in this order:

0. Upgrade ironic code and run database schema migrations via the
   ``ironic-dbsync upgrade`` command.

1. Upgrade code and restart ironic-conductor services, one at a time.

2. Upgrade code and restart ironic-api services, one at a time.

3. Unpin API, RPC and object versions so that the services can now use the
   latest versions in ``ToVer``. This is done via updating the
   configuration option described below in `API, RPC and object version
   pinning`_ and then restarting the services.
   ironic-conductor services should be restarted
   first, followed by the ironic-api services. This is to ensure that when new
   functionality is exposed on the unpinned API service (via API micro
   version), it is available on the backend.

+------+---------------------------------+---------------------------------+
| step | ironic-api                      | ironic-conductor                |
+======+=================================+=================================+
|  0   | all FromVer                     | all FromVer                     |
+------+---------------------------------+---------------------------------+
|  1.1 | all FromVer                     | some FromVer, some ToVer-pinned |
+------+---------------------------------+---------------------------------+
|  1.2 | all FromVer                     | all ToVer-pinned                |
+------+---------------------------------+---------------------------------+
|  2.1 | some FromVer, some ToVer-pinned | all ToVer-pinned                |
+------+---------------------------------+---------------------------------+
|  2.2 | all ToVer-pinned                | all ToVer-pinned                |
+------+---------------------------------+---------------------------------+
|  3.1 | all ToVer-pinned                | some ToVer-pinned, some ToVer   |
+------+---------------------------------+---------------------------------+
|  3.2 | all ToVer-pinned                | all ToVer                       |
+------+---------------------------------+---------------------------------+
|  3.3 | some ToVer-pinned, some ToVer   | all ToVer                       |
+------+---------------------------------+---------------------------------+
|  3.4 | all ToVer                       | all ToVer                       |
+------+---------------------------------+---------------------------------+

Policy for changes to the DB model
----------------------------------

The policy for changes to the DB model is as follows:

* Adding new items to the DB model is supported.

* The dropping of columns or tables and corresponding objects' fields is
  subject to ironic's `deprecation policy
  <https://governance.openstack.org/tc/reference/tags/assert_follows-standard-deprecation.html>`_.
  But its alembic script has to wait one more deprecation period, otherwise
  an ``unknown column`` exception will be thrown when ``FromVer`` services
  access the DB. This is because :command:`ironic-dbsync upgrade` upgrades the
  DB schema but ``FromVer`` services still contain the dropped field in their
  SQLAlchemy DB model.

* An ``alembic.op.alter_column()`` to rename or resize a column is not allowed.
  Instead, split it into multiple operations, with one operation per release
  cycle (to maintain compatibility with an old SQLAlchemy model). For example,
  to rename a column, add the new column in release N, then remove the old
  column in release N+1.

* Some implementations of SQL's ``ALTER TABLE``, such as adding foreign keys in
  PostgreSQL, may impose table locks and cause downtime. If the change cannot
  be avoided and the impact is significant (e.g. the table can be frequently
  accessed and/or store a large dataset), these cases must be mentioned in the
  release notes.

API, RPC and object version pinning
-----------------------------------

For the ironic services to be running old and new releases at the same time
during a rolling upgrade, the services need to be able to handle different API,
RPC and object versions.

This versioning is handled via the configuration option:
``[DEFAULT]/pin_release_version``. It is used to pin the API, RPC and
IronicObject (e.g., Node, Conductor, Chassis, Port, and Portgroup) versions for
all the ironic services.

The default value of empty indicates that ironic-api and ironic-conductor
will use the latest versions of API, RPC and IronicObjects. Its possible values
are releases, named (e.g. ``ocata``) or sem-versioned (e.g. ``7.0``).

Internally, in `common/release_mappings.py
<https://opendev.org/openstack/ironic/src/branch/master/ironic/common/release_mappings.py>`_,
ironic maintains a mapping that indicates the API, RPC and
IronicObject versions associated with each release. This mapping is
maintained manually.

During a rolling upgrade, the services using the new release will set the
configuration option value to be the name (or version) of the old release.
This will indicate to the services running the new release, which API, RPC and
object versions that they should be compatible with, in order to communicate
with the services using the old release.

Handling API versions
---------------------

When the (newer) service is pinned, the maximum API version it supports
will be the pinned version -- which the older service supports (as described
above at `API, RPC and object version pinning`_). The ironic-api
service returns HTTP status code 406 for any requests with API versions that
are higher than this maximum version.

Handling RPC versions
---------------------

`ConductorAPI.__init__()
<https://opendev.org/openstack/ironic/src/commit/338fdb94fc3b031e8d91bc7131cb4cadf05d7b92/ironic/conductor/rpcapi.py#L111>`_
sets the ``version_cap`` variable to the desired (latest or pinned) RPC API
version and passes it to the ``RPCClient`` as an initialization parameter. This
variable is then used to determine the maximum requested message version that
the ``RPCClient`` can send.

Each RPC call can customize the request according to this ``version_cap``.
The `Ironic RPC versions`_ section below has more details about this.

Handling IronicObject versions
------------------------------

Internally, ironic services deal with IronicObjects in their latest versions.
Only at these boundaries, when the IronicObject enters or leaves the service,
do we deal with object versioning:

* getting objects from the database: convert to latest version
* saving objects to the database: if pinned, save in pinned version; else
  save in latest version
* serializing objects (to send over RPC): if pinned, send pinned version;
  else send latest version
* deserializing objects (receiving objects from RPC): convert to latest
  version

The ironic-api service also has to handle API requests/responses
based on whether or how a feature is supported by the API version and object
versions. For example, when the ironic-api service is pinned, it can only
allow actions that are available to the object's pinned version, and cannot
allow actions that are only available for the latest version of that object.

To support this:

* All the database tables (SQLAlchemy models) of the IronicObjects have a
  column named ``version``. The value is the version of the object that
  is saved in the database.

* The method ``IronicObject.get_target_version()`` returns the target version.
  If pinned, the pinned version is returned. Otherwise, the latest version is
  returned.

* The method ``IronicObject.convert_to_version()`` converts the object into the
  target version. The target version may be a newer or older version than the
  existing version of the object. The bulk of the work is done in the helper
  method ``IronicObject._convert_to_version()``. Subclasses that have new
  versions redefine this to perform the actual conversions.

In the following,

* The old release is ``FromVer``; it uses version 1.14 of a Node object.
* The new release is ``ToVer``. It uses version 1.15 of a Node object --
  this has a deprecated ``extra`` field and a new ``meta`` field that replaces
  ``extra``.
* db_obj['meta'] and db_obj['extra'] are the database representations of those
  node fields.

Getting objects from the database (API/conductor <-- DB)
::::::::::::::::::::::::::::::::::::::::::::::::::::::::

Both ironic-api and ironic-conductor services read values from the database.
These values are converted to IronicObjects via the method
``IronicObject._from_db_object()``. This method always returns the IronicObject
in its latest version, even if it was in an older version in the database.
This is done regardless of the service being pinned or not.

Note that if an object is converted to a later version, that IronicObject will
retain any changes (in its ``_changed_fields`` field) resulting from that
conversion. This is needed in case the object gets saved later, in the latest
version.

For example, if the node in the database is in version 1.14 and has
db_obj['extra'] set:

* a ``FromVer`` service will get a Node with node.extra = db_obj['extra']
  (and no knowledge of node.meta since it doesn't exist)

* a ``ToVer`` service (pinned or unpinned), will get a Node with:

  * node.meta = db_obj['extra']
  * node.extra = None
  * node._changed_fields = ['meta', 'extra']

Saving objects to the database (API/conductor --> DB)
:::::::::::::::::::::::::::::::::::::::::::::::::::::

The version used for saving IronicObjects to the database is determined as
follows:

* For an unpinned service, the object is saved in its latest version. Since
  objects are always in their latest version, no conversions are needed.
* For a pinned service, the object is saved in its pinned version. Since
  objects are always in their latest version, the object needs to be converted
  to the pinned version before being saved.

The method ``IronicObject.do_version_changes_for_db()`` handles this logic,
returning a dictionary of changed fields and their new values (similar to the
existing ``oslo.versionedobjects.VersionedObject.obj_get_changes()``).
Since we do not keep track internally, of the database version of an object,
the object's ``version`` field will always be part of these changes.

The `Rolling upgrade process`_  (at step 3.1) ensures that by the time an
object can be saved in its latest version, all services are running the newer
release (although some may still be pinned) and can handle the latest object
versions.

An interesting situation can occur when the services are as described in step
3.1. It is possible for an IronicObject to be saved in a newer version and
subsequently get saved in an older version. For example, a ``ToVer`` unpinned
conductor might save a node in version 1.5. A subsequent request may cause a
``ToVer`` pinned conductor to replace and save the same node in version 1.4!

Sending objects via RPC (API/conductor -> RPC)
::::::::::::::::::::::::::::::::::::::::::::::

When a service makes an RPC request, any IronicObjects that are sent as
part of that request are serialized into entities or primitives via
``IronicObjectSerializer.serialize_entity()``. The version used for objects
being serialized is as follows:

* For an unpinned service, the object is serialized to its latest version.
  Since objects are always in their latest version, no conversions are needed.
* For a pinned service, the object is serialized to its pinned version.
  Since objects are always in their latest version, the object is converted to
  the pinned version before being serialized. The converted object includes
  changes that resulted from the conversion; this is needed so that the service
  at the other end of the RPC request has the necessary information if that
  object will be saved to the database.

Receiving objects via RPC (API/conductor <- RPC)
::::::::::::::::::::::::::::::::::::::::::::::::

When a service receives an RPC request, any entities that are part of the
request need to be deserialized (via
``oslo.versionedobjects.VersionedObjectSerializer.deserialize_entity()``).
For entities that represent IronicObjects, we want the deserialization process
(via ``IronicObjectSerializer._process_object()``) to result in IronicObjects
that are in their latest version, regardless of the version they were sent in
and regardless of whether the receiving service is pinned or not. Again, any
objects that are converted will retain the changes that resulted from the
conversion, useful if that object is later saved to the database.

For example, a ``FromVer`` ironic-api could issue an ``update_node()`` RPC
request with a node in version 1.4, where node.extra was changed (so
node._changed_fields = ['extra']). This node will be serialized in version 1.4.
The receiving ``ToVer`` pinned ironic-conductor deserializes it and converts
it to version 1.5. The resulting node will have node.meta set (to the changed
value from node.extra in v1.4), node.extra = None, and node._changed_fields =
['meta', 'extra'].


When developing a new feature or modifying an IronicObject
==========================================================

When adding a new feature or changing an IronicObject, they need to be coded so
that things work during a rolling upgrade.

The following describe areas where the code may need to be changed, as well as
some points to keep in mind when developing code.

ironic-api
----------

During a rolling upgrade, the new, pinned ironic-api is talking to a new
conductor that might also be pinned. There may also be old ironic-api services.
So the new, pinned ironic-api service needs to act like it was the older
service:

* New features should not be made available, unless they are somehow totally
  supported in the old and new releases. Pinning the API version is in place
  to handle this.

  * If, for whatever reason, the API version pinning doesn't prevent a request
    from being handled that cannot or should not be handled, it should be
    coded so that the response has HTTP status code 406 (Not Acceptable).
    This is the same response to requests that have an incorrect (old) version
    specified.

Ironic RPC versions
-------------------
When the signature (arguments) of an RPC method is changed or new methods are
added, the following needs to be considered:

- The RPC version must be incremented and be the same value for both the
  client (``ironic/conductor/rpcapi.py``, used by ironic-api) and the server
  (``ironic/conductor/manager.py``, used by ironic-conductor). It should also
  be updated in ``ironic/common/release_mappings.py``.
- Until there is a major version bump, new arguments of an RPC method can only
  be added as optional. Existing arguments cannot be removed or changed in
  incompatible ways with the method in older RPC versions.
- ironic-api (client-side) sets a version cap (by passing the version cap to
  the constructor of oslo_messaging.RPCClient). This "pinning" is in place
  during a rolling upgrade when the ``[DEFAULT]/pin_release_version``
  configuration option is set.
- New RPC methods are not available when the service is pinned to the older
  release version. In this case, the corresponding REST API function should
  return a server error or implement alternative behaviours.
- Methods which change arguments should run
  ``client.can_send_version()`` to see if the version of the request is
  compatible with the version cap of the RPC Client. Otherwise the request
  needs to be created to work with a previous version that is supported.
- ironic-conductor (server-side) should tolerate older versions of requests in
  order to keep working during the rolling upgrade process. The behaviour of
  ironic-conductor will depend on the input parameters passed from the
  client-side.
- Old methods can be removed only after they are no longer used by a previous
  named release.

Object versions
---------------
When subclasses of ``ironic.objects.base.IronicObject`` are modified, the
following needs to be considered:

- Any change of fields or change in signature of remotable methods needs a bump
  of the object version. The object versions are also maintained in
  ``ironic/common/release_mappings.py``.
- New objects must be added to ``ironic/common/release_mappings.py``. Also for
  the first releases they should be excluded from the version check by adding
  their class names to the ``NEW_MODELS`` list in ``ironic/cmd/dbsync.py``.
- The arguments of remotable methods (methods which are remoted to the
  conductor via RPC) can only be added as optional. They cannot be removed or
  changed in an incompatible way (to the previous release).
- Field types cannot be changed. Instead, create a new field and deprecate
  the old one.
- There is a `unit test
  <https://opendev.org/openstack/ironic/src/commit/e9318c75748c87a318b4ff35d9385b4d09e79da6/ironic/tests/unit/objects/test_objects.py#L721>`_
  that generates the hash of an object using its fields and the
  signatures of its remotable methods. Objects that have a version bump need
  to be updated in the
  `expected_object_fingerprints
  <https://opendev.org/openstack/ironic/src/commit/e9318c75748c87a318b4ff35d9385b4d09e79da6/ironic/tests/unit/objects/test_objects.py#L682>`_
  dictionary; otherwise this test will fail. A failed test can also indicate to
  the developer that their change(s) to an object require a version bump.
- When new version objects communicate with old version objects and when
  reading or writing to the database,
  ``ironic.objects.base.IronicObject._convert_to_version()`` will be called to
  convert objects to the target version. Objects should implement their own
  ._convert_to_version() to remove or alter fields which were added or changed
  after the target version::

    def _convert_to_version(self, target_version,
                            remove_unavailable_fields=True):
        """Convert to the target version.

        Subclasses should redefine this method, to do the conversion of the
        object to the target version.

        Convert the object to the target version. The target version may be
        the same, older, or newer than the version of the object. This is
        used for DB interactions as well as for serialization/deserialization.

        The remove_unavailable_fields flag is used to distinguish these two
        cases:

        1) For serialization/deserialization, we need to remove the unavailable
           fields, because the service receiving the object may not know about
           these fields. remove_unavailable_fields is set to True in this case.

        2) For DB interactions, we need to set the unavailable fields to their
           appropriate values so that these fields are saved in the DB. (If
           they are not set, the VersionedObject magic will not know to
           save/update them to the DB.) remove_unavailable_fields is set to
           False in this case.

        :param target_version: the desired version of the object
        :param remove_unavailable_fields: True to remove fields that are
            unavailable in the target version; set this to True when
            (de)serializing. False to set the unavailable fields to appropriate
            values; set this to False for DB interactions.

  This method must handle:

  * converting from an older version to a newer version
  * converting from a newer version to an older version
  * making sure, when converting, that you take into consideration other
    object fields that may have been affected by a field (value) only available
    in a newer version. For example, if field 'new' is only available in Node
    version 1.5 and Node.affected = Node.new+3, when converting to 1.4 (an
    older version), you may need to change the value of Node.affected too.

Online data migrations
----------------------
The ``ironic-dbsync online_data_migrations`` command will perform online
data migrations.

Keep in mind the `Policy for changes to the DB model`_.
Future incompatible changes in SQLAlchemy models, like removing or renaming
columns and tables can break rolling upgrades (when ironic services are run
with different release versions simultaneously). It is forbidden to remove these
database resources when they may still be used by the previous named release.

When `creating new Alembic migrations <faq>`_ which modify existing models,
make sure that any new columns default to NULL. Test the migration out on a
non-empty database to make sure that any new constraints don't cause the
database to be locked out for normal operations.

You can find an overview on what DDL operations may cause downtime in
https://dev.mysql.com/doc/refman/5.7/en/innodb-create-index-overview.html.
(You should also check older, widely deployed InnoDB versions for issues.)
In the case of PostgreSQL, adding a foreign key may lock a whole table for
writes.

Make sure to add a release note if there are any downtime-related concerns.

Backfilling default values, and migrating data between columns or between tables
must be implemented inside an online migration script. A script is a database
API method (added to ``ironic/db/api.py`` and ``ironic/db/sqlalchemy/api.py``)
which takes two arguments:

- context: an admin context
- max_count: this is used to limit the query. It is the maximum number of
  objects to migrate; >= 0. If zero, all the objects will be migrated.

It returns a two-tuple:

- the total number of objects that need to be migrated, at the start of
  the method, and
- the number of migrated objects.

In this method, the version column can be used to select and update old
objects.

The method name should be added to the list of ``ONLINE_MIGRATIONS`` in
``ironic/cmd/dbsync.py``.

The method should be removed in the next named release after this one.

After online data migrations are completed and the SQLAlchemy models no longer
contain old fields, old columns can be removed from the database. This takes
at least 3 releases, since we have to wait until the previous named release no
longer contains references to the old schema. Before removing any resources
from the database by modifying the schema, make sure that your implementation
checks that all objects in the affected tables have been migrated. This check
can be implemented using the version column.

"ironic-dbsync upgrade" command
-------------------------------
The ``ironic-dbsync upgrade`` command first checks that the versions of the
objects are compatible with the (new) release of ironic, before it will make
any DB schema changes. If one or more objects are not compatible, the upgrade
will not be performed.

This check is done by comparing the objects' ``version`` field in the database
with the expected (or supported) versions of these objects. The supported
versions are the versions specified in
``ironic.common.release_mappings.RELEASE_MAPPING``.
The newly created tables cannot pass this check and thus have to be excluded by
adding their object class names (e.g. ``Node``) to
``ironic.cmd.dbsync.NEW_MODELS``.
