=============
VNC Container
=============

Overview
--------

This allows a container image to be built which supports Ironic's graphical
console functionality.

For each node with an enabled graphical console, the service ironic-novncproxy
(or nova-novncproxy) will connect to a VNC server exposed by a container
running this image.

Building and using
------------------

To build the container image for local use, install ``buildah`` and run the
following as the user which runs ironic-conductor::

    buildah bud -f ./Containerfile.ubuntu -t localhost/ironic-vnc-container

The ``systemd`` container provider (or an external provider) can then be configured
to use this image in ``ironic.conf``:

.. code-block:: ini

      [vnc]
      enabled = True
      container_provider=systemd
      console_image=localhost/ironic-vnc-container


Implementation
--------------

When the container is started the following occurs:

1. x11vnc is run, which exposes a VNC server port

When a VNC connection is established, the following occurs:

1. Xvfb is run, which starts a virtual X11 session
2. A firefox browser is started in kiosk mode
3. A firefox extension automates loading the requested console app
4. For the ``fake`` app, display drivers/fake/index.html
5. For the ``redfish-graphical`` app, detect the vendor by looking at the
   ``Oem`` value in a ``/redfish/v1`` response
6. Runs vendor specific scripts to display an HTML5 based console

Multiple VNC connections can share a single instance. When the last VNC
connection is closed, the running Firefox is closed.

Vendor specific implementations are as follows.

Dell iDRAC
~~~~~~~~~~

One-time console credentials are created with a call to
``/Managers/<manager>/Oem/Dell/DelliDRACCardService/Actions/DelliDRACCardService.GetKVMSession``
and the browser loads a console URL using those credentials.

HPE iLO
~~~~~~~

The ``/irc.html`` URL is loaded. For iLO 6 the inline login form is populated
with credentials and submitted, showing the console. For iLO 5 the main login
page is loaded, and when the login is submitted ``irc.html`` is loaded again.

Supermicro (Experimental)
~~~~~~~~~~~~~~~~~~~~~~~~~

A simulated user logs in, waits for the console preview image to load, then
clicks on it.

