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

.. option:: drivers

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
