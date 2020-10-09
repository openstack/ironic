.. _bios:

==================
BIOS Configuration
==================

Overview
========

The Bare Metal service supports BIOS configuration for bare metal nodes.
It allows administrators to retrieve and apply the desired BIOS settings
via CLI or REST API. The desired BIOS settings are applied during manual
cleaning.

Prerequisites
=============

Bare metal servers must be configured by the administrator to be managed
via ironic hardware type that supports BIOS configuration.

Enabling hardware types
-----------------------

Enable a specific hardware type that supports BIOS configuration.
Refer to :doc:`/install/enabling-drivers` for how to enable a hardware type.

Enabling hardware interface
---------------------------

To enable the bios interface:

.. code-block:: ini

    [DEFAULT]
    enabled_bios_interfaces = no-bios

Append the actual bios interface name supported by the enabled hardware type
to ``enabled_bios_interfaces`` with comma separated values in ``ironic.conf``.

All available in-tree bios interfaces are listed in setup.cfg file in the
source code tree, for example:

.. code-block:: ini

    ironic.hardware.interfaces.bios =
        fake = ironic.drivers.modules.fake:FakeBIOS
        no-bios = ironic.drivers.modules.noop:NoBIOS

Retrieve BIOS settings
======================

To retrieve the cached BIOS configuration from a specified node::

    $ baremetal node bios setting list <node>

BIOS settings are cached on each node cleaning operation or when settings
have been applied successfully via BIOS cleaning steps. The return of above
command is a table of last cached BIOS settings from specified node.
If ``-f json`` is added as suffix to above command, it returns BIOS settings
as following::

    [
      {
        "setting name":
          {
            "name": "setting name",
            "value": "value"
          }
      },
      {
        "setting name":
          {
            "name": "setting name",
            "value": "value"
          }
      },
      ...
    ]

To get a specified BIOS setting for a node::

    $ baremetal node bios setting show <node> <setting-name>

If ``-f json`` is added as suffix to above command, it returns BIOS settings
as following::

    {
      "setting name":
        {
          "name": "setting name",
          "value": "value"
        }
    }

Configure BIOS settings
=======================

Two :ref:`manual_cleaning` steps are available for managing nodes'
BIOS settings:

Factory reset
-------------

This cleaning step resets all BIOS settings to factory default for a given
node::

    {
      "target":"clean",
      "clean_steps": [
        {
          "interface": "bios",
          "step": "factory_reset"
        }
      ]
    }

The ``factory_reset`` cleaning step does not require any arguments, as it
resets all BIOS settings to factory defaults.

Apply BIOS configuration
------------------------

This cleaning step applies a set of BIOS settings for a node::

    {
      "target":"clean",
      "clean_steps": [
        {
          "interface": "bios",
          "step": "apply_configuration",
          "args": {
            "settings": [
              {
                "name": "name",
                "value": "value"
              },
              {
                "name": "name",
                "value": "value"
              }
            ]
          }
        }
      ]
    }

The representation of ``apply_configuration`` cleaning step follows the same
format of :ref:`manual_cleaning`. The desired BIOS settings can be provided
via the ``settings`` argument which contains a list of BIOS options to be
applied, each BIOS option is a dictionary with ``name`` and ``value`` keys.

To check whether the desired BIOS configuration is set properly, use the
command mentioned in the `Retrieve BIOS settings`_ section.

.. note::
   When applying BIOS settings to a node, vendor-specific driver may take
   the given BIOS settings from the argument and compare them with the
   current BIOS settings on the node and only apply when there is a
   difference.
