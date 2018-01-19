=============
ironic-dbsync
=============

The :command:`ironic-dbsync` utility is used to create the database schema
tables that the ironic services will use for storage. It can also be used to
upgrade existing database tables when migrating between
different versions of ironic.

The `Alembic library <http://alembic.readthedocs.org>`_ is used to perform
the database migrations.

Options
=======

This is a partial list of the most useful options. To see the full list,
run the following::

  ironic-dbsync --help

.. program:: ironic-dbsync

.. option:: -h, --help

  Show help message and exit.

.. option:: --config-dir <DIR>

  Path to a config directory with configuration files.

.. option:: --config-file <PATH>

  Path to a configuration file to use.

.. option:: -d, --debug

  Print debugging output.

.. option:: --version

  Show the program's version number and exit.

.. option:: upgrade, stamp, revision, version, create_schema,
            online_data_migrations

  The :ref:`command <dbsync_cmds>` to run.

Usage
=====

Options for the various :ref:`commands <dbsync_cmds>` for
:command:`ironic-dbsync` are listed when the :option:`-h` or :option:`--help`
option is used after the command.

For example::

  ironic-dbsync create_schema --help

Information about the database is read from the ironic configuration file
used by the API server and conductor services. This file must be specified
with the :option:`--config-file` option::

  ironic-dbsync --config-file /path/to/ironic.conf create_schema

The configuration file defines the database backend to use with the
*connection* database option::

  [database]
  connection=mysql+pymysql://root@localhost/ironic

If no configuration file is specified with the :option:`--config-file` option,
:command:`ironic-dbsync` assumes an SQLite database.

.. _dbsync_cmds:

Command Options
===============

:command:`ironic-dbsync` is given a command that tells the utility what actions
to perform. These commands can take arguments. Several commands are available:

.. _create_schema:

create_schema
-------------

.. program:: create_schema

.. option:: -h, --help

  Show help for create_schema and exit.

This command will create database tables based on the most current version.
It assumes that there are no existing tables.

An example of creating database tables with the most recent version::

  ironic-dbsync --config-file=/etc/ironic/ironic.conf create_schema

online_data_migrations
----------------------

.. program:: online_data_migrations

.. option:: -h, --help

  Show help for online_data_migrations and exit.

.. option:: --max-count <NUMBER>

  The maximum number of objects (a positive value) to migrate. Optional.
  If not specified, all the objects will be migrated (in batches of 50 to
  avoid locking the database for long periods of time).

.. option:: --option <MIGRATION.KEY=VALUE>

  If a migration accepts additional parameters, they can be passed via this
  argument. It can be specified several times.

This command will migrate objects in the database to their most recent versions.
This command must be successfully run (return code 0) before upgrading to a
future release.

It returns:

* 1 (not completed) if there are still pending objects to be migrated.
  Before upgrading to a newer release, this command must be run until
  0 is returned.

* 0 (success) after migrations are finished or there are no data to migrate

* 127 (error) if max-count is not a positive value or an option is invalid

* 2 (error) if the database is not compatible with this release. This command
  needs to be run using the previous release of ironic, before upgrading and
  running it with this release.

revision
--------

.. program:: revision

.. option:: -h, --help

  Show help for revision and exit.

.. option:: -m <MESSAGE>, --message <MESSAGE>

  The message to use with the revision file.

.. option:: --autogenerate

  Compares table metadata in the application with the status of the database
  and generates migrations based on this comparison.

This command will create a new revision file. You can use the
:option:`--message` option to comment the revision.

This is really only useful for ironic developers making changes that require
database changes. This revision file is used during database migration and
will specify the changes that need to be made to the database tables. Further
discussion is beyond the scope of this document.

stamp
-----

.. program:: stamp

.. option:: -h, --help

  Show help for stamp and exit.

.. option:: --revision <REVISION>

  The revision number.

This command will 'stamp' the revision table with the version specified with
the :option:`--revision` option. It will not run any migrations.

upgrade
-------

.. program:: upgrade

.. option:: -h, --help

  Show help for upgrade and exit.

.. option:: --revision <REVISION>

  The revision number to upgrade to.

This command will upgrade existing database tables to the most recent version,
or to the version specified with the :option:`--revision` option.

Before this ``upgrade`` is invoked, the command
:command:`ironic-dbsync online_data_migrations` must have been successfully run
using the previous version of ironic (if you are doing an upgrade as opposed to
a new installation of ironic). If it wasn't run, the database will not be
compatible with this recent version of ironic, and this command will return
2 (error).

If there are no existing tables, then new tables are created, beginning
with the oldest known version, and successively upgraded using all of the
database migration files, until they are at the specified version. Note
that this behavior is different from the :ref:`create_schema` command
that creates the tables based on the most recent version.

An example of upgrading to the most recent table versions::

  ironic-dbsync --config-file=/etc/ironic/ironic.conf upgrade

.. note::

  This command is the default if no command is given to
  :command:`ironic-dbsync`.

.. warning::

  The upgrade command is not compatible with SQLite databases since it uses
  ALTER TABLE commands to upgrade the database tables. SQLite supports only
  a limited subset of ALTER TABLE.

version
-------

.. program:: version

.. option:: -h, --help

  Show help for version and exit.

This command will output the current database version.
