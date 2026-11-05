=============
ironic-manage
=============

The :command:`ironic-manage` utility assists operators in managing and
exploring an ironic installation. It is organized into sub-commands, listed
below.

Options
=======

This is a partial list of the most useful options. To see the full list,
run the following::

  ironic-manage --help

.. program:: ironic-manage

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

.. option:: drivers, inspection-rules

  The :ref:`command <manage_cmds>` to run.

Usage
=====

Options for the various :ref:`commands <manage_cmds>` for
:command:`ironic-manage` are listed when the :option:`-h` or :option:`--help`
option is used after the command.

.. _manage_cmds:

Command Options
===============

:command:`ironic-manage` is given a command that tells the utility what
actions to perform. These commands can take arguments. The following
commands are supported.

drivers hardware-types
----------------------

.. program:: drivers hardware-types

Lists the hardware types installed on this system, discovered via the
``ironic.hardware.types`` Python entry points. These names are the valid
values for the ``[DEFAULT]enabled_hardware_types`` configuration option.
For each hardware type, the implementing class and the Python package
providing it are shown, along with a note when the hardware type is
deprecated or cannot be loaded (for example, because a required vendor
library is not installed)::

  ironic-manage drivers hardware-types

drivers interfaces
------------------

.. program:: drivers interfaces

Lists the hardware interfaces installed on this system, discovered via the
``ironic.hardware.interfaces.<interface type>`` Python entry points. These
names are the valid values for the various
``[DEFAULT]enabled_<interface type>_interfaces`` configuration options.
The output follows the same format as ``drivers hardware-types``.

By default, all interface types are listed. One or more interface types
(such as ``bios``, ``boot``, ``console``, ``deploy``, ``inspect``,
``management``, ``network``, ``power``, ``raid`` or ``storage``) can be
passed as arguments to only list those types::

  ironic-manage drivers interfaces
  ironic-manage drivers interfaces deploy network

inspection-rules check
----------------------

.. program:: inspection-rules check

Evaluates :doc:`inspection rules </admin/inspection/rules>` against captured
hardware data to show which rules match and what actions would be executed,
without touching any real node. This helps test and debug inspection rules
before deploying them to a production environment.

The rules file is always required and is given with :option:`--rules`. The
hardware data to evaluate the rules against is given either as a single
node/inventory file pair, or as a directory tree of test cases.

For a single set of files, the node and inventory data can be captured from
a real node::

  openstack baremetal node show <node> -f json > node.json
  openstack baremetal node inventory save --file inventory.json <node>
  ironic-manage inspection-rules check --rules rules.yaml \
      --node node.json --inventory inventory.json

Alternatively, a whole directory tree of test cases can be checked at once.
Each subdirectory of the given directory is one test case and must contain a
node file (``node.yaml`` or ``node.json``) and an inventory file
(``inventory.yaml`` or ``inventory.json``)::

  ironic-manage inspection-rules check --rules rules.yaml \
      --data-dir <directory>

.. option:: --rules <rules file>

  YAML file with the inspection rules to evaluate. Required.

.. option:: --node <node file>

  JSON or YAML file with node data. Requires :option:`--inventory`.

.. option:: --inventory <inventory file>

  JSON or YAML file with hardware inventory and plugin data. Requires
  :option:`--node`.

.. option:: --data-dir <directory>

  Directory containing test case subdirectories to check. Cannot be
  combined with :option:`--node` and :option:`--inventory`.

For each rule, the command prints whether it matched (``[MATCH]``) or was
skipped (``[SKIP]``), the result of each condition, and the arguments of each
action after variable interpolation. Rules are evaluated in priority order,
highest first. No changes are made to any node: the actions are only
reported, never executed. A summary line gives the number of rules matched
and any errors encountered. With :option:`--data-dir`, each test case is
reported as ``PASS`` or ``FAIL``, followed by a total.

The command exits with status 0 on success, 1 if any rule fails to load or
evaluate (or, with :option:`--data-dir`, if any test case fails), and 2 if
the options are invalid. This makes it suitable for use in CI jobs.

.. seealso::

   :ref:`inspection-rules-testing` in the inspection rules guide.
