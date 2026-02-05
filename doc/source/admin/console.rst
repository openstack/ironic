.. _console:

====================
Configuring Consoles
====================

Overview
--------

There are two types of consoles which are available in Bare Metal service:

* (`Node graphical console`_) for a graphical console from a NoVNC web browser
* (`Node serial console`_) for serial console support

Node graphical console
----------------------

Graphical console drivers require a configured and running ``ironic-novncproxy``
service. Each supported driver is described below.

redfish-graphical
~~~~~~~~~~~~~~~~~

A driver for a subset of Redfish hosts. Starting the console will start a
container which exposes a VNC server for ``ironic-novncproxy`` to attach to.
When attached, a browser will start which displays an HTML5 based console on
the following supported hosts:

* Dell iDRAC
* HPE iLO
* Supermicro

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = redfish
    enabled_console_interfaces = redfish-graphical,no-console

fake-graphical
~~~~~~~~~~~~~~~~~

A driver for demonstrating working graphical console infrastructure. Starting
the console will start a container which exposes a VNC server for
``ironic-novncproxy`` to attach to. When attached, a browser will start which
displays an animation.

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = fake-hardware
    enabled_console_interfaces = fake-graphical,no-console

Node serial console
-------------------

Serial consoles for nodes are implemented using `socat`_. It is supported by
the ``ipmi``, ``irmc``, and ``redfish`` hardware types.

.. NOTE::
   The use of the ``ipmitool-socat`` console interface on any hardware type
   requires the ipmi connection parameters to be set into the ``driver_info``
   filed on the node.

Serial consoles can be configured in the Bare Metal service as follows:

* Install socat on the ironic conductor node. Also, ``socat`` needs to be in
  the $PATH environment variable that the ironic-conductor service uses.

  Installation example:

  Ubuntu::

      sudo apt-get install socat

  RHEL/CentOS/Fedora::

      sudo dnf install socat

* Append console parameters for bare metal PXE boot in the Bare Metal
  service configuration file. See the reference on how to configure them in
  :ref:`kernel-boot-parameters`.

* Enable the ``ipmitool-socat`` console interface, for example:

  .. code-block:: ini

    [DEFAULT]
    enabled_console_interfaces = ipmitool-socat,no-console

* Configure node console.

  If the node uses a hardware type, for example ``ipmi``, set the node's
  console interface to ``ipmitool-socat``::

    baremetal node set <node> --console-interface ipmitool-socat

  Enable the serial console, for example::

   baremetal node set <node> --driver-info ipmi_terminal_port=<port>
   baremetal node console enable <node>

  Check whether the serial console is enabled, for example::

   baremetal node validate <node>

  Disable the serial console, for example::

   baremetal node console disable  <node>
   baremetal node unset <node> --driver-info <ipmi_terminal_port>

Serial console information is available from the Bare Metal service.  Get
serial console information for a node from the Bare Metal service as follows::

 baremetal node console show <node>
 +-----------------+----------------------------------------------------------------------+
 | Property        | Value                                                                |
 +-----------------+----------------------------------------------------------------------+
 | console_enabled | True                                                                 |
 | console_info    | {u'url': u'tcp://<host>:<port>', u'type': u'socat'}                  |
 +-----------------+----------------------------------------------------------------------+

If ``console_enabled`` is ``false`` or ``console_info`` is ``None`` then
the serial console is disabled. If you want to launch serial console, see the
``Configure node console``.

The node serial console of the Bare Metal service is compatible with the
serial console of the Compute service. Hence, serial consoles to
Bare Metal nodes can be seen and interacted with via the Dashboard service.
In order to achieve that, you need to follow the documentation for
:nova-doc:`Serial Console <admin/remote-console-access.html#serial>`
from the Compute service.

Configuring HA
~~~~~~~~~~~~~~

When using Bare Metal serial console under High Availability (HA)
configuration, you may consider some settings below.

* If you use HAProxy, you may need to set the timeout for both client
  and server sides with appropriate values. Here is an example of the
  configuration for the timeout parameter.

  ::

    frontend nova_serial_console
      bind 192.168.20.30:6083
      timeout client 10m  # This parameter is necessary
      use_backend nova_serial_console if <...>

    backend nova_serial_console
      balance source
      timeout server 10m  # This parameter is necessary
      option  tcpka
      option  tcplog
      server  controller01 192.168.30.11:6083 check inter 2000 rise 2 fall 5
      server  controller02 192.168.30.12:6083 check inter 2000 rise 2 fall 5

* The Compute service's caching feature may need to be enabled in order
  to make the Bare Metal serial console work under a HA configuration.
  Here is an example of a caching configuration in ``nova.conf``.

  .. code-block:: ini

    [cache]
    enabled = true
    backend = dogpile.cache.memcached
    memcache_servers = memcache01:11211,memcache02:11211,memcache03:11211

.. _`socat`: http://www.dest-unreach.org/socat
