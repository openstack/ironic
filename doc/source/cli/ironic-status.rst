=============
ironic-status
=============

Synopsis
========

::

  ironic-status <category> <command> [<args>]

Description
===========

:program:`ironic-status` is a tool that provides routines for checking the
status of a Ironic deployment.

Options
=======

The standard pattern for executing a :program:`ironic-status` command is::

    ironic-status <category> <command> [<args>]

Run without arguments to see a list of available command categories::

    ironic-status

Categories are:

* ``upgrade``

Detailed descriptions are below.

You can also run with a category argument such as ``upgrade`` to see a list of
all commands in that category::

    ironic-status upgrade

These sections describe the available categories and arguments for
:program:`ironic-status`.

Upgrade
~~~~~~~

.. _ironic-status-checks:

``ironic-status upgrade check``
  Performs a release-specific readiness check before restarting services with
  new code. This command expects to have complete configuration and access
  to databases and services.

  **Return Codes**

  .. list-table::
     :widths: 20 80
     :header-rows: 1

     * - Return code
       - Description
     * - 0
       - All upgrade readiness checks passed successfully and there is nothing
         to do.
     * - 1
       - At least one check encountered an issue and requires further
         investigation. This is considered a warning but the upgrade may be OK.
     * - 2
       - There was an upgrade status check failure that needs to be
         investigated. This should be considered something that stops an
         upgrade.
     * - 255
       - An unexpected error occurred.

  **History of Checks**

  **12.0.0 (Stein)**

  * Adds a check for compatibility of the object versions with the release
    of ironic.

  **Wallaby**

  * Adds a check to validate the configured policy file is not JSON
    based as JSON based policies have been deprecated.
