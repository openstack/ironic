.. _console:

====================
Configuring Consoles
====================

Overview
--------

There are three types of consoles which are available in Bare Metal service:

* (`Node graphical console`_) for a graphical console from a NoVNC web browser
* (`Node web console`_) a terminal available from a web browser
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

Node web console
----------------

The web console can be configured in Bare Metal service in the following way:

* Install shellinabox in ironic conductor node. For RHEL/CentOS, shellinabox package
  is not present in base repositories, the user must enable EPEL repository, you can
  find more from `FedoraProject page`_.

  .. warning::

     Shell In A Box is considered abandoned by the Ironic community. The
     original maintainer stopped maintaining the project and the project
     was thus forked. The resulting
     `fork <https://github.com/shellinabox/shellinabox>`_ has not received
     updates in a number of years and is considered abandoned.
     As such, shellinabox support has been deprecated by the Ironic community.

  Installation example:

  Ubuntu::

      sudo apt-get install shellinabox

  RHEL/CentOS/Fedora::

       sudo dnf install shellinabox

  You can find more about shellinabox on the `shellinabox page`_.

  You can optionally use the SSL certificate in shellinabox. If you want to use the SSL
  certificate in shellinabox, you should install openssl and generate the SSL certificate.

  1. Install openssl, for example:

     Ubuntu::

         sudo apt-get install openssl

     RHEL/CentOS/Fedora::

         sudo dnf install openssl

  2. Generate the SSL certificate, here is an example, you can find more about openssl on
     the `openssl page`_::

        cd /tmp/ca
        openssl genrsa -des3 -out my.key 1024
        openssl req -new -key my.key  -out my.csr
        cp my.key my.key.org
        openssl rsa -in my.key.org -out my.key
        openssl x509 -req -days 3650 -in my.csr -signkey my.key -out my.crt
        cat my.crt my.key > certificate.pem

* Customize the console section in the Bare Metal service configuration
  file (/etc/ironic/ironic.conf), if you want to use SSL certificate in
  shellinabox, you should specify ``terminal_cert_dir``.
  For example::

   [console]

   #
   # Options defined in ironic.drivers.modules.console_utils
   #

   # Path to serial console terminal program. Used only by Shell
   # In A Box console. (string value)
   #terminal=shellinaboxd

   # Directory containing the terminal SSL cert (PEM) for serial
   # console access. Used only by Shell In A Box console. (string
   # value)
   terminal_cert_dir=/tmp/ca

   # Directory for holding terminal pid files. If not specified,
   # the temporary directory will be used. (string value)
   #terminal_pid_dir=<None>

   # Time interval (in seconds) for checking the status of
   # console subprocess. (integer value)
   #subprocess_checking_interval=1

   # Time (in seconds) to wait for the console subprocess to
   # start. (integer value)
   #subprocess_timeout=10

* Append console parameters for bare metal PXE boot in the Bare Metal service
  configuration file (/etc/ironic/ironic.conf). See the reference for
  configuration in :ref:`kernel-boot-parameters`.

* Enable the ``ipmitool-shellinabox`` console interface, for example:

  .. code-block:: ini

    [DEFAULT]
    enabled_console_interfaces = ipmitool-shellinabox,no-console

* Configure node web console.

  If the node uses a hardware type, for example ``ipmi``, set the node's
  console interface to ``ipmitool-shellinabox``::

    baremetal node set <node> --console-interface ipmitool-shellinabox

  Enable the web console, for example::

   baremetal node set <node> \
       --driver-info <terminal_port>=<customized_port>
   baremetal node console enable <node>

  Check whether the console is enabled, for example::

   baremetal node validate <node>

  Disable the web console, for example::

   baremetal node console disable  <node>
   baremetal node unset <node> --driver-info <terminal_port>

  The ``<terminal_port>`` is driver dependent. The actual name of this field can be
  checked in driver properties, for example::

   baremetal driver property list <driver>

  For the ``ipmi`` hardware type, this option is ``ipmi_terminal_port``.
  Give a customized port number to ``<customized_port>``,
  for example ``8023``, this customized port is used in web console url.

  Get web console information for a node as follows::

   baremetal node console show <node>
   +-----------------+----------------------------------------------------------------------+
   | Property        | Value                                                                |
   +-----------------+----------------------------------------------------------------------+
   | console_enabled | True                                                                 |
   | console_info    | {u'url': u'http://<url>:<customized_port>', u'type': u'shellinabox'} |
   +-----------------+----------------------------------------------------------------------+

  You can open the web console using the above ``url`` through web browser. If
  ``console_enabled`` is ``false``, ``console_info`` is ``None``, web console is disabled.
  If you want to launch the web console, see the ``Configure node web console`` part.

  .. note::

     An error message you may encounter when enabling the console can read
     ``Console subprocess failed to start. Timeout or error while waiting for
     console subprocess to start for node`` along with
     ``[server] Failed to find any available port!``. This error is coming from
     shellinabox itself, not from the communication with the BMC. One potential
     cause for this issue is that there are already shellinabox daemons running
     which block the configured port (remove them if appropriate and retry to
     enable the console).

.. _`shellinabox page`: https://code.google.com/archive/p/shellinabox/
.. _`openssl page`: https://www.openssl.org/
.. _`FedoraProject page`: https://fedoraproject.org/wiki/Infrastructure/Mirroring


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
