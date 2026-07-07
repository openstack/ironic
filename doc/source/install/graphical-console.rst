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

When Ironic itself is deployed in Docker or Podman containers, the
``container`` provider can manage console containers directly through the
same container engine. Other deployment architectures may require writing an
external custom container provider.

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

Docker/Podman container provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``container`` provider manages containers directly through a Docker
compatible container engine (Docker or Podman) by invoking its CLI. It is
intended for deployments which run the Ironic services themselves in Docker
or Podman containers, where neither the ``systemd`` nor the ``kubernetes``
provider is usable: the container engine already running ironic-conductor is
the natural place to run the console containers.

A minimal configuration:

.. code-block:: ini

   [vnc]
   enabled = True
   container_provider = container
   console_image = localhost/ironic-vnc-container

The provider invokes the CLI named by ``[vnc]container_executable`` (default
``docker``, Docker CLI 20.10 or later required) with an argument vector, no
shell and no privilege escalation. Access to the engine is governed entirely
by socket permissions, which the deployment controls: when ironic-conductor
itself runs in a container, mount the engine socket into its container and
ensure the conductor's image includes the CLI. Registry authentication for
pulling ``console_image`` uses the CLI's standard credential store (``docker
login``, ``REGISTRY_AUTH_FILE``) in the conductor's environment.

When ``[vnc]container_host`` is set it is exported to the CLI as both
``DOCKER_HOST`` and ``CONTAINER_HOST``; when unset the CLI's default socket
resolution applies (typically ``unix:///var/run/docker.sock``). The engine is
assumed to run on the conductor host: the default publish binding and the
unspecified-address substitution are only correct for a local engine, so a
remote ``container_host`` requires ``[vnc]container_publish_port`` to bind an
address which is valid and routable on the engine host.

The VNC endpoint of each container is published according to
``[vnc]container_publish_port`` (default ``$my_ip::5900``): bind to
``$my_ip`` and let the engine allocate a random high host port. An IPv6 bind
address must be bracketed (for example ``[2001:db8::1]::5900``), so
deployments where ``my_ip`` is IPv6 must set this option explicitly.

``[vnc]container_command_template`` points to the Jinja2 template which
renders the arguments of the container run command. Operators may edit it for
deployment-specific needs, such as the ``--pull`` policy, ``--network``,
resource limits (``--memory``/``--cpus``), log rotation (``--log-opt``),
extra labels, or removing ``--rm`` to keep crashed containers for
inspection. A custom template must keep, as rendered by the default template:
the container ``--name`` and the ``org.openstack.ironic.*`` labels (per-node
stop, bulk cleanup and the prune commands below find containers by them),
``--detach``, the publish of container port 5900 and the value-less ``--env
APP_INFO`` entry (the credentials are supplied through the CLI's process
environment). Note that with the default ``--pull missing`` (or ``always``) a
console start may include an image pull of unbounded duration; pre-pull
``console_image`` (or set ``--pull never``) to keep console start times
predictable.

Podman compatibility
^^^^^^^^^^^^^^^^^^^^

Podman provides a Docker compatible CLI and a Docker compatible API service
(``podman system service``), so the same provider is expected to work against
Podman by setting ``container_executable = podman`` (Podman 4.0 or later
recommended) or by pointing ``container_host`` at a Podman socket with the
``docker`` CLI or ``podman-docker`` shim. The Podman CLI honours
``CONTAINER_HOST`` (which also enables remote mode) and ignores
``DOCKER_HOST``. Podman support through the compatibility interface is
best-effort; podman-on-the-host deployments are already served by the
``systemd`` provider.

Security considerations
^^^^^^^^^^^^^^^^^^^^^^^

Access to a rootful container engine socket is root-equivalent on the host:
anyone who can talk to the engine can start privileged containers and mount
host paths. Mounting such a socket into the ironic-conductor container
therefore extends a conductor compromise to host root. This is a deliberate
deployment trade-off. Where possible use a dedicated engine or a rootless
Podman socket (a rootless socket grants only the owning user's privileges),
and consider engine authorization plugins.

The node's BMC addresses and credentials are passed to the container as the
``APP_INFO`` environment variable, where they are visible via ``docker
inspect`` and the container's process environment to anyone with socket
access. This matches the exposure of the ``systemd`` provider (environment in
a quadlet unit file) and the ``kubernetes`` provider (Secret consumed as an
environment variable). The value is supplied through the CLI's process
environment, never on a command line, so it does not leak through
``/proc/<pid>/cmdline`` or debug-logged command lines.

As with all providers, the VNC server in the console container is
unauthenticated and unencrypted. Do not bind the publish specification to
``0.0.0.0``; published ports must be reachable only from networks hosting
ironic-novncproxy or nova-novncproxy.

If ``container_host`` points at a TCP endpoint, it must be protected with
TLS, configured through the standard Docker client mechanisms
(``DOCKER_TLS_VERIFY``, ``DOCKER_CERT_PATH``) in the conductor's
environment. These apply to the ``docker`` CLI only: the Podman CLI's remote
transport has no TLS option, so with Podman use a Unix socket or an
``ssh://`` endpoint. Unix sockets are the recommended deployment.

Disk usage
^^^^^^^^^^

Ironic never removes images, so every pull of an updated ``console_image``
(for instance a weekly rebuild with security updates) leaves the superseded
image behind, and over a long conductor uptime these add up to real disk
consumption. Bounding it is an operator task with existing engine tooling
such as ``docker image prune``.

The default template runs containers with ``--rm``, so a container that exits
for any reason removes itself and exited containers cannot accumulate
writable layers and logs. The provider captures ``docker logs`` at debug
level before the removals it performs on stop and on failure; what ``--rm``
gives up is the post-mortem of a container that exited on its own. When debugging such exits,
remove ``--rm`` from the template: exited containers are then cleaned up by
the provider's explicit removals and at conductor startup, and can
additionally be purged on a TTL with the engine's own tooling::

    docker container prune --filter until=24h \
        --filter label=org.openstack.ironic.console=true

Docker's default ``json-file`` log driver does not rotate logs, so
deployments expecting long-lived, heavily used consoles should set
``--log-opt max-size`` in the template or configure log rotation engine-wide.
That, not ``--rm``, is what bounds log growth while a container is still
running.

Containers belonging to a conductor which died without running its shutdown
cleanup persist until that conductor restarts. The
``org.openstack.ironic.console`` label locates such orphans::

    docker ps --all --filter label=org.openstack.ironic.console=true

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

For the ``systemd`` and ``container`` providers the VNC server will be
published on a random high port number. For the ``kubernetes`` pod the VNC
server is running on port ``5900`` on the pod's ``hostIP``.

Console containers need access to the management network to access the BMC web
interface. If driver_info ``redfish_verify_ca=False`` then web requests will
not be verified by the browser. Setting ``redfish_verify_ca`` to a certificate
path is not yet supported by the ``systemd`` container provider as the
certificate is not bind-mounted into the container. This can be supported
locally by building a container which includes the expected certificate files.
