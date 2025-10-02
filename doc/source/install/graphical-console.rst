.. _graphical-console:

Graphical console support
=========================

The Bare Metal service supports displaying graphical consoles from a number of
hardware vendors.

The following preconditions are required for a node's graphical console to be
viewable:

* Service ironic-conductor has a configured console container provider
  appropriate for the environment

* Service ironic-novncproxy is configured and running

* The node's ``console_interface`` is set to a graphical driver such as
  ``redfish-graphical``

When enabled and configured, the following sequence occurs when a graphical
console is accessed when interacting with Bare Metal service directly:

* A REST API call is made to enable the console, for example via the CLI
  command ``baremetal node console enable``

* ironic-conductor creates and stores a time-limited token with the node

* ironic-conductor triggers starting a container which runs a virtual X11
  display, starts a web browser, and exposes a VNC server

* Once enabled, a REST API call is made to fetch the console URL, for example
  via the CLI command ``baremetal node console show``

* The user accesses the console URL with a web browser

* ironic-novncproxy serves the NoVNC web assets to the browser

* A websocket is initiated with ironic-novncproxy, which looks up the node and
  validates the token

* ironic-novncproxy makes a VNC connection with the console container and
  proxies VNC traffic between the container and the browser

* The container initiates a connection with the node's BMC Redfish endpoint
  and determines which vendor script to run

* The container makes Redfish calls and simulates a browser user to display
  an HTML5 console, which the end user can now view

Building a console container
----------------------------

The `tools/vnc-container
<https://opendev.org/openstack/ironic/src/branch/master/tools/vnc-container>`_
directory contains the files and instructions to build a console container.
This directory will be where further development occurs, and currently only a
CentOS Stream based image can be built.

Container providers
-------------------

ironic-conductor must be configured with a container provider so that it can
trigger starting and stopping console containers based on node's console
enabled state. Given the variety of deployment architectures for Ironic, an
appropriate container provider needs to be configured.

In many cases this will require writing an external custom container provider,
especially when Ironic itself is deployed in a containerized environment.

Systemd container provider
~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``systemd`` provider manages containers as Systemd Quadlet containers.
This provider is appropriate to use when the Ironic services themselves are
not containerised, and is also a good match when ironic-conductor itself is
managed as a Systemd unit.

To start a container, this provider writes ``.container`` files to
``/etc/containers/systemd/users/{uid}/containers/systemd`` then calls
``systemctl --user daemon-reload`` to generate a unit file which is then
started with ``systemctl --user start {unit name}``.

Kubernetes container provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``kubernetes`` provider manages containers as kubernetes pods and allows
associated resources to also be managed. The provider requires the ``kubectl``
command, and valid kubernetes credentials be available to the running
ironic-conductor. The current assumption with this driver is that
ironic-conductor, ironic-novncproxy, and the console containers are all
running in the same kubernetes cluster. Therefore, the credentials will be
provided by the service account mechanism supplied to the ironic-conductor
pod.

``ironic.conf`` ``[vnc]kubernetes_container_template`` points to a template
file which defines the kubernetes resources including the pod running the
console container. The default template creates one Secret to store the app
info (including BMC credentials) and one Pod to run the actual console
container. This default template ``ironic-console-pod.yaml.template`` is
functional but will likely need to be replaced with a variant that
customises:

* The namespace the resources are deployed to
* The labels to match the conventions of the deployment

When ironic-conductor starts and stops it will stop any existing console
container associated with that ironic-conductor. For this delete-all
operation, the labels in the template are transformed into a kubectl selector,
so this needs to be a consideration when choosing the labels in the template.

When ironic-conductor is using cluster service account credentials, a
RoleBinding to a Role which allows appropriate resource management is
required. For example, the default template would require at minimum the
following role rules::

    apiVersion: rbac.authorization.k8s.io/v1
    kind: Role
    metadata:
      # ...
    rules:
    - apiGroups:
      - ""
      resources:
      - pods
      verbs:
      - create
      - delete
    - apiGroups:
      - ""
      resources:
      - secrets
      verbs:
      - create
      - delete

The provider assumes that ironic-novnc is running in the cluster, and can
connect a VNC server using the console container's ``hostIP``.

Creating an external container provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

An external python library can contribute its own container provider by
subclassing ``ironic.console.container.base.BaseConsoleContainer`` then adding
it to the library's ``setup.cfg`` ``[entry_points]ironic.console.container``.

The ``start_container`` method must return the IP and port of the resulting
running VNC server, which in most scenarios would mean blocking until the
container is running.

Networking requirements
-----------------------

ironic-novncproxy
~~~~~~~~~~~~~~~~~

Like ironic-api, ironic-novncproxy presents a public endpoint. However unlike
ironic-api, node console URLs are coupled to the ironic-conductor managing
that node, so load balancing across all ironic-novncproxy instances is not
appropriate.

A TLS enabled reverse proxy needs to support WebSockets, otherwise TLS can be
enabled in the ``ironic.conf`` ``[vnc]`` section.

ironic-novncproxy needs to be able to connect to the VNC servers exposed by
the console containers.

Console containers
~~~~~~~~~~~~~~~~~~

The VNC servers exposed by console containers are unencrypted and
unauthenticated, so public access *must* be restricted via another network
configuration mechanism. The ironic-novncproxy service needs to access the VNC
server exposed by these containers, and so does nova-novncproxy when Nova is
using the Ironic driver.

For the ``systemd`` container the VNC server will be published on a random
high port number. For the ``kubernetes`` pod the VNC server is running on
port ``5900`` on the pod's ``hostIP``.

Console containers need access to the management network to access the BMC web
interface. If driver_info ``redfish_verify_ca=False`` then web requests will
not be verified by the browser. Setting ``redfish_verify_ca`` to a certificate
path is not yet supported by the ``systemd`` container provider as the
certificate is not bind-mounted into the container. This can be supported
locally by building a container which includes the expected certificate files.
