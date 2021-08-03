=============
Tuning Ironic
=============

Memory Utilization
==================

Memory utilization is a difficult thing to tune in Ironic as largely we may
be asked by API consumers to perform work for which the underlying tools
require large amounts of memory.

The biggest example of this is image conversion. Images not in a raw format
need to be written out to disk (local files or remote in iscsi deploy) which
requires the conversion process to generate an in-memory map to re-assemble
the image contents into a coherent stream of data. This entire process also
stresses the kernel buffers and cache.

This ultimately comes down to a trade-off of Memory versus Performance,
similar to the trade-off of Performance versus Cost.

On a plus side, an idle Ironic deployment does not need much in the way
of memory. On the down side, a highly bursty environment where a large
number of concurrent deployments may be requested should consider two
aspects:

* How is the ironic-api service/process set up? Will more
  processes be launched automatically?
* Are images prioritized for storage size on disk? Or are they compressed and
  require format conversion?

API
===

Ironic's API should have a fairly stable memory footprint with activity,
however depending on how the webserver is running the API, additional
processes can be launched.

Under normal conditions, as of Ironic 15.1, the ``ironic-api`` service/process
consumes approximately 270MB of memory per worker. Depending on how the
process is being launched, the number of workers and maximum request threads
per worker may differ. Naturally there are configuration and performance
trade-offs.

* Directly as a native python process, i.e. execute ``ironic-api``
  processes. Each single worker allows for multiple requests to be handled
  and threaded at the same time which can allow high levels of request
  concurrency. As of the Victoria cycle, a direct invocation of the
  ``ironic-api`` program will only launch a maximum of four workers.
* Launched via a wrapper such as Apache+uWSGI may allow for multiple distinct
  worker processes, but these workers typically limit the number of request
  processing threads that are permitted to execute. This means requests can
  stack up in the front-end webserver and be released to the ``ironic-api``
  as prior requests complete. In environments with long running synchronous
  calls, such as use of the vendor passthru interface, this can be very
  problematic.

When the webserver is launched by the API process directly, the default is
based upon the number of CPU sockets in your machine.

When launching using uwsgi, this will entirely vary upon your configuration,
but balancing workers/threads based upon your load and needs is highly
advisable. Each worker process is unique and consumes far more memory than
a comparable number of worker threads. At the same time, the scheduler will
focus on worker processes as the threads are greenthreads.

.. note::
   Host operating systems featuring in-memory de-duplication should see
   an improvement in the overall memory footprint with multiple processes,
   but this is not something the development team has measured and will vary
   based upon multiple factors.

One important item to note: each Ironic API service/process *does* keep a
copy of the hash ring as generated from the database *in-memory*. This is
done to help allocate load across a cluster in-line with how individual nodes
and their responsible conductors are allocated across the cluster.
In other words, your amount of memory WILL increase corresponding to
the number of nodes managed by each ironic conductor. It is important
to understand that features such as `conductor groups <./conductor-groups.rst>`_
means that only matching portions of nodes will be considered for the
hash ring if needed.

Conductor
=========

A conductor process will launch a number of other processes, as required,
in order to complete the requested work. Ultimately this means it can quickly
consume large amounts of memory because it was asked to complete a substantial
amount of work all at once.

The ``ironic-conductor`` from ironic 15.1 consumes by default about 340MB of
RAM in an idle configuration. This process, by default, operates as a single
process. Additional processes can be launched, but they must have unique
resolvable hostnames and addresses for JSON-RPC or use a central
oslo.messaging supported message bus in order for Webserver API to Conductor
API communication to be functional.

Typically, the most memory intensive operation that can be triggered is a
image conversion for deployment, which is limited to 1GB of RAM per conversion
process.

Most deployments, by default, do have a concurrency limit depending on their
Compute (See `nova.conf <https://docs.openstack.org/nova/latest/configuration/sample-config.html>`_
setting ``max_concurrent_builds``) configuration. However, this is only per
``nova-compute`` worker, so naturally this concurrency will scale with
additional workers.

Stand-alone users can easily request deployments exceeding the Compute service
default maximum concurrent builds. As such, if your environment is used this
way, you may wish to carefully consider your deployment architecture.

With a single nova-compute process talking to a single conductor, asked to
perform ten concurrent deployments of images requiring conversion, the memory
needed may exceed 10GB. This does however, entirely depend upon image block
structure and layout, and what deploy interface is being used.

Database
========

Query load upon the database is one of the biggest potential bottlenecks which
can cascade across a deployment and ultimately degrade service to an Ironic
user.

Often, depending on load, query patterns, periodic tasks, and so on and so
forth, additional indexes may be needed to help provide hints to the database
so it can most efficently attempt to reduce the number of rows which need to
be examined in order to return a result set.

Adding indexes
--------------

This example below is specific to MariaDB/MySQL, but the syntax should be
easy to modify for operators using PostgreSQL.

.. code-block:: sql

   use ironic;
   create index owner_idx on nodes (owner) LOCK = SHARED;
   create index lessee_idx on nodes (lessee) LOCK = SHARED;
   create index driver_idx on nodes (driver) LOCK = SHARED;
   create index provision_state_idx on nodes (provision_state) LOCK = SHARED;
   create index reservation_idx on nodes (reservation) LOCK = SHARED;
   create index conductor_group_idx on nodes (conductor_group) LOCK = SHARED;
   create index resource_class_idx on nodes (resource_class) LOCK = SHARED;

.. note:: The indexes noted have been added automatically by Xena versions of
   Ironic and later. They are provided here as an example and operators can
   add them manually prior with versions of Ironic. The database upgrade for
   the Xena release of Ironic which adds these indexes are only aware of being
   able to skip index creation if it already exists on MySQL/MariaDB.

.. note:: It may be possible to use "LOCK = NONE". Basic testing indicates
   this takes a little bit longer, but shouldn't result in the database
   table becoming write locked during the index creation. If the database
   engine cannot support this, then the index creation will fail.

Database platforms also have a concept of what is called a "compound index"
where the index is aligned with the exact query pattern being submitted to
the database. The database is able to use this compound index to attempt to
drastically reduce the result set generation time for the remainder of the
query. As of the composition of this document, we do not ship compound
indexes in Ironic as we feel the most general benefit is single column
indexes, and depending on data present, an operator may wish to explore
compound indexes with their database administrator, as comound indexes
can also have negative performance impacts if improperly constructed.

.. code-block:: sql

   use ironic;
   create index my_custom_app_query_index on nodes (reservation, provision_state, driver);

The risk, and *WHY* you should engage a Database Administrator, is depending on
your configuration, the actual index may need to include one or more additional
fields such as owner or lessee which may be added on to the index. At the same
time, queries with less field matches, or in different orders will exhibit
different performance as the compound index may not be able to be consulted.

Indexes will not fix everything
-------------------------------

Indexes are not a magical cure-all for all API or database performance issues,
but they are an increadibly important part depending on data access and query
patterns.

The underlying object layer and data conversions including record pagination
do add a substantial amount of overhead to what may otherwise return as a
result set on a manual database query. In Ironic's case, due to the object
model and the need to extract multiple pieces of data at varying levels
of the data model to handle cases such as upgrades, the entire result set
is downloaded and transformed which is an overhead you do not experience with
a command line database client.

What can I do?
==============

Previously in this document, we've already suggested some architectural
constraints and limitations, but there are some things that can be done
to maximize performance. Again, this will vary greatly depending on your
use.

* Use the ``direct`` deploy interface. This offloads any final image
  conversion to the host running the ``ironic-python-agent``. Additionally,
  if Swift or other object storage such as RadosGW is used, downloads can
  be completely separated from the host running the ``ironic-conductor``.
* Use small/compact "raw" images. Qcow2 files are generally compressed
  and require substantial amounts of memory to decompress and stream.
* Tune the internal memory limit for the conductor using the
  ``[DEFAULT]memory_required_minimum`` setting. This will help the conductor
  throttle back memory intensive operations. The default should prevent
  Out-of-Memory operations, but under extreme memory pressure this may
  still be sub-optimal. Before changing this setting, it is highly advised
  to consult with your resident "Unix wizard" or even the Ironic
  development team in upstream IRC. This feature was added in the Wallaby
  development cycle.
* If network bandwidth is the problem you are seeking to solve for, you may
  wish to explore a mix of the ``direct`` deploy interface and caching
  proxies. Such a configuration can be highly beneficial in wide area
  deployments. See :ref:`Using proxies for image download <ipa-proxies>`.
