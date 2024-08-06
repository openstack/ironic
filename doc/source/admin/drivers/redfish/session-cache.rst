Internal Session Cache
======================

The ``redfish`` hardware type, and derived interfaces, utilizes a built-in
session cache which prevents Ironic from re-authenticating every time
Ironic attempts to connect to the BMC for any reason.

This consists of cached connectors objects which are used and tracked by
a unique consideration of ``redfish_username``, ``redfish_password``,
``redfish_verify_ca``, and finally ``redfish_address``. Changing any one
of those values will trigger a new session to be created.
The ``redfish_system_id`` value is explicitly not considered as Redfish
has a model of use of one BMC to many systems, which is also a model
Ironic supports.

The session cache default size is ``1000`` sessions per conductor.
If you are operating a deployment with a larger number of Redfish
BMCs, it is advised that you do appropriately tune that number.
This can be tuned via the API service configuration file,
:oslo.config:option:`redfish.connection_cache_size`.

Session Cache Expiration
~~~~~~~~~~~~~~~~~~~~~~~~

By default, sessions remain cached for as long as possible in
memory, as long as they have not experienced an authentication,
connection, or other unexplained error.

Under normal circumstances, the sessions will only be rolled out
of the cache in order of oldest first when the cache becomes full.
There is no time based expiration to entries in the session cache.

Of course, the cache is only in memory, and restarting the
``ironic-conductor`` will also cause the cache to be rebuilt
from scratch. If this is due to any persistent connectivity issue,
this may be sign of an unexpected condition, and please consider
contacting the Ironic developer community for assistance.

