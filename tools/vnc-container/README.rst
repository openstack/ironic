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

    buildah bud -f ./Containerfile -t localhost/ironic-vnc-container

The ``systemd`` container provider (or an external provider) can then be configured
to use this image in ``ironic.conf``:

.. code-block:: ini

      [vnc]
      container_provider=systemd
      console_image=localhost/ironic-vnc-container


Implementation
--------------

When the container is started the following occurs:

1. Xvfb is run, which starts a virtual X11 session
2. x11vnc is run, which exposes a VNC server port

When a VNC connection is established a Selenium python script is started
which:

1. Starts a Chromium browser
2. For the ``fake`` app displays drivers/fake/index.html
3. For the ``redfish`` app detects the vendor by looking at the ``Oem``
   value in a ``/redfish/v1`` response
4. Runs vendor specific code to display an HTML5 based console

When the VNC connection is terminated, the Selenium script and Chromium is
also terminated.

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

