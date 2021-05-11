.. _upgrade-guide:

================================
Bare Metal Service Upgrade Guide
================================

This document outlines various steps and notes for operators to consider when
upgrading their ironic-driven clouds from previous versions of OpenStack.

The Bare Metal (ironic) service is tightly coupled with the ironic driver that
is shipped with the Compute (nova) service. Some special considerations must be
taken into account when upgrading your cloud.

Both offline and rolling upgrades are supported.

Plan your upgrade
=================

* Rolling upgrades are available starting with the Pike release; that is, when
  upgrading from Ocata. This means that it is possible to do an upgrade with
  minimal to no downtime of the Bare Metal API.

* Upgrades are only supported between two consecutive named releases.
  This means that you cannot upgrade Ocata directly into Queens; you need to
  upgrade into Pike first.

* The `release notes <https://docs.openstack.org/releasenotes/ironic/>`_
  should always be read carefully when upgrading the Bare Metal service.
  Specific upgrade steps and considerations are documented there.

* The Bare Metal service should always be upgraded before the Compute service.

  .. note::
     The ironic virt driver in nova always uses a specific version of the
     ironic REST API. This API version may be one that was introduced in the
     same development cycle, so upgrading nova first may result in nova being
     unable to use the Bare Metal API.

* Make a backup of your database. Ironic does not support downgrading of the
  database. Hence, in case of upgrade failure, restoring the database from
  a backup is the only choice.

* Before starting your upgrade, it is best to ensure that all nodes have
  reached, or are in, a stable ``provision_state``. Nodes in states with
  long running processes such as deploying or cleaning, may fail, and may
  require manual intervention to return them to the available hardware pool.
  This is most likely in cases where a timeout has occurred or a service was
  terminated abruptly. For a visual diagram detailing states and possible
  state transitions, please see :ref:`states`.

Offline upgrades
================

In an offline (or cold) upgrade, the Bare Metal service is not available
during the upgrade, because all the services have to be taken down.

When upgrading the Bare Metal service, the following steps should always be
taken in this order:

#. upgrade the ironic-python-agent image

#. update ironic code, without restarting services

#. run database schema migrations via ``ironic-dbsync upgrade``

#. restart ironic-conductor and ironic-api services

Once the above is done, do the following:

* update any applicable configuration options to stop using any deprecated
  features or options, and perform any required work to transition to
  alternatives. All the deprecated features and options will be supported for
  one release cycle, so should be removed before your next upgrade is
  performed.

* upgrade python-ironicclient along with any other services connecting
  to the Bare Metal service as a client, such as nova-compute

* run the ``ironic-dbsync online_data_migrations`` command to make sure
  that data migrations are applied. The command lets you limit
  the impact of the data migrations with the ``--max-count`` option, which
  limits the number of migrations executed in one run. You should complete
  all of the migrations as soon as possible after the upgrade.

  .. warning::
     You will not be able to start an upgrade to the release
     after this one, until this has been completed for the current
     release. For example, as part of upgrading from Ocata to Pike,
     you need to complete Pike's data migrations. If this not done,
     you will not be able to upgrade to Queens -- it will not be
     possible to execute Queens' database schema updates.


Rolling upgrades
================

To Reduce downtime, the services can be upgraded in a rolling fashion, meaning
to upgrade one or a few services at a time to minimize impact.

Rolling upgrades are available starting with the Pike release. This feature
makes it possible to upgrade between releases, such as Ocata to Pike, with
minimal to no downtime of the Bare Metal API.

Requirements
------------

To facilitate an upgrade in a rolling fashion, you need to have a
highly-available deployment consisting of at least two ironic-api
and two ironic-conductor services.
Use of a load balancer to balance requests across the ironic-api
services is recommended, as it allows for a minimal impact to end users.

Concepts
--------

There are four aspects of the rolling upgrade process to keep in mind:

* API and RPC version pinning, and versioned object backports
* online data migrations
* graceful service shutdown
* API load balancer draining

API & RPC version pinning and versioned object backports
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Through careful RPC versioning, newer services are able to talk to older
services (and vice-versa). The ``[DEFAULT]/pin_release_version`` configuration
option is used for this. It should be set (pinned) to the release version
that the older services are using. The newer services will backport RPC calls
and objects to their appropriate versions from the pinned release. If the
``IncompatibleObjectVersion`` exception occurs, it is most likely due to an
incorrect or unspecified ``[DEFAULT]/pin_release_version`` configuration value.
For example, when ``[DEFAULT]/pin_release_version`` is not set to the older
release version, no conversion will happen during the upgrade.

For the ironic-api service, the API version is pinned via the same
``[DEFAULT]/pin_release_version`` configuration option as above. When pinned,
the new ironic-api services will not service any API requests with Bare Metal
API versions that are higher than what the old ironic-api services support.
HTTP status code 406 is returned for such requests. This prevents new features
(available in new API versions) from being used until after the upgrade
has been completed.

Online data migrations
~~~~~~~~~~~~~~~~~~~~~~

To make database schema migrations less painful to execute, we have
implemented process changes to facilitate upgrades.

* All data migrations are banned from schema migration scripts.
* Schema migration scripts only update the database schema.
* Data migrations must be done at the end of the rolling upgrade process,
  after the schema migration and after the services have been upgraded to
  the latest release.

All data migrations are performed using the
``ironic-dbsync online_data_migrations`` command. It can be run as
a background process so that it does not interrupt running services;
however it must be run to completion for a cold upgrade if the intent
is to make use of new features immediately.

(You would also execute the same command with services turned off if
you are doing a cold upgrade).

This data migration must be completed. If not, you will not be able to
upgrade to future releases. For example, if you had upgraded from Ocata to
Pike but did not do the data migrations, you will not be able to upgrade from
Pike to Queens. (More precisely, you will not be able to apply Queens' schema
migrations.)

Graceful conductor service shutdown
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ironic-conductor service is a Python process listening for messages on a
message queue. When the operator sends the SIGTERM signal to the process, the
service stops consuming messages from the queue, so that no additional work is
picked up. It completes any outstanding work and then terminates. During this
process, messages can be left on the queue and will be processed after the
Python process starts back up. This gives us a way to shutdown a service using
older code, and start up a service using newer code with minimal impact.

.. note::
   This was tested with RabbitMQ messaging backend and may vary with other
   backends.

Nodes that are being acted upon by an ironic-conductor process, which are
not in a stable state, may encounter failures. Node failures that occur
during an upgrade are likely due to timeouts, resulting from delays
involving messages being processed and acted upon by a conductor
during long running, multi-step processes such as deployment or cleaning.

API load balancer draining
~~~~~~~~~~~~~~~~~~~~~~~~~~

If you are using a load balancer for the ironic-api services, we recommend that
you redirect requests to the new API services and drain off of the ironic-api
services that have not yet been upgraded.

Rolling upgrade process
-----------------------

Before maintenance window
~~~~~~~~~~~~~~~~~~~~~~~~~

* Upgrade the ironic-python-agent image

* Using the new release (ironic code), execute the required database schema
  updates by running the database upgrade command: ``ironic-dbsync upgrade``.
  These schema change operations should have minimal or no effect on
  performance, and should not cause any operations to fail (but please check
  the release notes). You can:

  * install the new release on an existing system
  * install the new release in a new virtualenv or a container

  At this point, new columns and tables may exist in the database. These
  database schema changes are done in a way that both the old and new (N and
  N+1) releases can perform operations against the same schema.

.. note::
   Ironic bases its API, RPC and object storage format versions on the
   ``[DEFAULT]/pin_release_version`` configuration option. It is
   advisable to automate the deployment of changes in configuration
   files to make the process less error prone and repeatable.

During maintenance window
~~~~~~~~~~~~~~~~~~~~~~~~~

#. All ironic-conductor services should be upgraded first. Ensure that at
   least one ironic-conductor service is running at all times. For every
   ironic-conductor, either one by one or a few at a time:

   * shut down the service. Messages from the ironic-api services to the
     conductors are load-balanced by the message queue and a hash-ring,
     so the only thing you need to worry about is to shut the service down
     gracefully (using ``SIGTERM`` signal) to make sure it will finish all the
     requests being processed before shutting down.
   * upgrade the installed version of ironic and dependencies
   * set the ``[DEFAULT]/pin_release_version`` configuration option value to
     the version you are upgrading from (that is, the old version). Based on
     this setting, the new ironic-conductor services will downgrade any
     RPC communication and data objects to conform to the old service.
     For example, if you are upgrading from Ocata to Pike, set this value to
     ``ocata``.
   * start the service

#. The next service to upgrade is ironic-api. Ensure that at least one
   ironic-api service is running at all times. You may want to start another
   temporary instance of the older ironic-api to handle the load while you are
   upgrading the original ironic-api services. For every ironic-api service,
   either one by one or a few at a time:

   * in HA deployment you are typically running them behind a load balancer
     (for example HAProxy), so you need to take the service instance out of the
     balancer
   * shut it down
   * upgrade the installed version of ironic and dependencies
   * set the ``[DEFAULT]/pin_release_version`` configuration option value to
     the version you are upgrading from (that is, the old version). Based on
     this setting, the new ironic-api services will downgrade any RPC
     communication and data objects to conform to the old service. In addition,
     the new services will return HTTP status code 406 for any requests with
     newer API versions that the old services did not support. This prevents
     new features (available in new API versions) from being used until after
     the upgrade has been completed.
     For example, if you are upgrading from Ocata to Pike, set this value to
     ``ocata``.
   * restart the service
   * add it back into the load balancer

   After upgrading all the ironic-api services, the Bare Metal service is
   running in the new version but with downgraded RPC communication and
   database object storage formats. New features (in new API versions) are
   not supported, because they could fail when objects are in the
   downgraded object formats and some internal RPC API functions may still
   not be available.

#. For all the ironic-conductor services, one at a time:

   * remove the ``[DEFAULT]/pin_release_version`` configuration option setting
   * restart the ironic-conductor service

#. For all the ironic-api services, one at a time:

   * remove the ``[DEFAULT]/pin_release_version`` configuration option setting
   * restart the ironic-api service

After maintenance window
~~~~~~~~~~~~~~~~~~~~~~~~

Now that all the services are upgraded, the system is able to use the latest
version of the RPC protocol and able to access all the features of the new
release.

* Update any applicable configuration options to stop using any deprecated
  features or options, and perform any required work to transition to
  alternatives. All the deprecated features and options will be supported for
  one release cycle, so should be removed before your next upgrade is
  performed.

* Upgrade ``python-ironicclient`` along with other services connecting
  to the Bare Metal service as a client, such as ``nova-compute``.

  .. warning::
    A ``nova-compute`` instance tries to attach VIFs to all active instances
    on start up. Make sure that for all active nodes there is at least one
    running ``ironic-conductor`` process to manage them. Otherwise the
    instances will be moved to the ``ERROR`` state on the ``nova-compute``
    start up.

* Run the ``ironic-dbsync online_data_migrations`` command to make sure
  that data migrations are applied. The command lets you limit
  the impact of the data migrations with the ``--max-count`` option, which
  limits the number of migrations executed in one run. You should complete
  all of the migrations as soon as possible after the upgrade.

  .. warning::
     Note that you will not be able to start an upgrade to the next release after
     this one, until this has been completed for the current release. For example,
     as part of upgrading from Ocata to Pike, you need to complete Pike's data
     migrations. If this not done, you will not be able to upgrade to Queens --
     it will not be possible to execute Queens' database schema updates.

.. toctree::
  :hidden:

  upgrade-to-hardware-types.rst
