.. _console:

=================================
Configuring Web or Serial Console
=================================

Overview
--------

There are two types of console which are available in Bare Metal service,
one is web console (`Node web console`_) which is available directly from web
browser, another is serial console (`Node serial console`_).

Node web console
----------------

The web console can be configured in Bare Metal service in the following way:

* Install shellinabox in ironic conductor node. For RHEL/CentOS, shellinabox package
  is not present in base repositories, user must enable EPEL repository, you can find
  more from `FedoraProject page`_.

  Installation example::

    Ubuntu:
        sudo apt-get install shellinabox

    Fedora 21/RHEL7/CentOS7:
        sudo yum install shellinabox

    Fedora 22 or higher:
         sudo dnf install shellinabox

  You can find more about shellinabox on the `shellinabox page`_.

  You can optionally use the SSL certificate in shellinabox. If you want to use the SSL
  certificate in shellinabox, you should install openssl and generate the SSL certificate.

  1. Install openssl, for example::

        Ubuntu:
             sudo apt-get install openssl

        Fedora 21/RHEL7/CentOS7:
             sudo yum install openssl

        Fedora 22 or higher:
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
  for example::

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

* Configure node web console.

  Enable the web console, for example::

   ironic node-update <node-uuid> add driver_info/<terminal_port>=<customized_port>
   ironic node-set-console-mode <node-uuid> true

  Check whether the console is enabled, for example::

   ironic node-validate <node-uuid>

  Disable the web console, for example::

   ironic node-set-console-mode <node-uuid> false
   ironic node-update <node-uuid> remove driver_info/<terminal_port>

  The ``<terminal_port>`` is driver dependent. The actual name of this field can be
  checked in driver properties, for example::

   ironic driver-properties <driver>

  For ``*_ipmitool`` and ``*_ipminative`` drivers, this option is ``ipmi_terminal_port``.
  Give a customized port number to ``<customized_port>``,
  for example ``8023``, this customized port is used in web console url.

  Get web console information for a node as follows::

   ironic node-get-console <node-uuid>
   +-----------------+----------------------------------------------------------------------+
   | Property        | Value                                                                |
   +-----------------+----------------------------------------------------------------------+
   | console_enabled | True                                                                 |
   | console_info    | {u'url': u'http://<url>:<customized_port>', u'type': u'shellinabox'} |
   +-----------------+----------------------------------------------------------------------+

  You can open web console using above ``url`` through web browser. If ``console_enabled`` is
  ``false``, ``console_info`` is ``None``, web console is disabled. If you want to launch web
  console, see the ``Configure node web console`` part.

.. _`shellinabox page`: https://code.google.com/p/shellinabox/
.. _`openssl page`: https://www.openssl.org/
.. _`FedoraProject page`: https://fedoraproject.org/wiki/Infrastructure/Mirroring


Node serial console
-------------------

Serial consoles for nodes are implemented using `socat`_.
In Newton, the following drivers support socat consoles for nodes:

* agent_ipmitool_socat
* pxe_ipmitool_socat

Serial consoles can be configured in the Bare Metal service as follows:

* Install socat on the ironic conductor node. Also, ``socat`` needs to be in
  the $PATH environment variable that the ironic-conductor service uses.

  Installation example::

    Ubuntu:
        sudo apt-get install socat

    Fedora 21/RHEL7/CentOS7:
        sudo yum install socat

    Fedora 22 or higher:
        sudo dnf install socat

* Append console parameters for bare metal PXE boot in the Bare Metal
  service configuration file. See the reference on how to configure them in
  :ref:`kernel-boot-parameters`.

* Configure node console.

  Enable the serial console, for example::

   ironic node-update <node-uuid> add driver_info/ipmi_terminal_port=<port>
   ironic node-set-console-mode <node-uuid> true

  Check whether the serial console is enabled, for example::

   ironic node-validate <node-uuid>

  Disable the serial console, for example::

   ironic node-set-console-mode <node-uuid> false
   ironic node-update <node-uuid> remove driver_info/ipmi_terminal_port

Serial console information is available from the Bare Metal service.  Get
serial console information for a node from the Bare Metal service as follows::

 ironic node-get-console <node-uuid>
 +-----------------+----------------------------------------------------------------------+
 | Property        | Value                                                                |
 +-----------------+----------------------------------------------------------------------+
 | console_enabled | True                                                                 |
 | console_info    | {u'url': u'tcp://<host>:<port>', u'type': u'socat'}                  |
 +-----------------+----------------------------------------------------------------------+

If ``console_enabled`` is ``false`` or ``console_info`` is ``None`` then
the serial console is disabled. If you want to launch serial console, see the
``Configure node console``.

.. _`socat`: http://www.dest-unreach.org/socat
