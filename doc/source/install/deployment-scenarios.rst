.. meta::
   :description: Common deployment scenarios for OpenStack Ironic bare metal service, including standalone, OpenStack-integrated, and full cloud configurations.
   :keywords: ironic deployment, standalone ironic, ironic with nova, bare metal deployment patterns, bifrost, metal3
   :author: OpenStack Ironic Team
   :robots: index, follow
   :audience: cloud operators, system administrators, architects

====================
Deployment Scenarios
====================

Ironic can be deployed in several different ways depending on what you need
from it. The scenarios below cover the most common patterns, though they are
not exhaustive — your environment may not map cleanly to any one of them, and
that is fine. Think of these as starting points, not a checklist.

Scenarios at a Glance
=====================

.. list-table::
   :header-rows: 1

   * - Scenario
     - Scale
     - Multi-tenancy
     - User-facing API
   * - :ref:`deploy-scenarios-standalone`
     - 1 to hundreds of nodes
     - No
     - Ironic API
   * - :ref:`deploy-scenarios-openstack-no-nova`
     - Small to large
     - Yes (owner/lessee)
     - Ironic API
   * - :ref:`deploy-scenarios-full-openstack`
     - 1 node to multiple datacenters
     - Yes (native)
     - Nova Compute API

.. note::
   The :ref:`deploy-scenarios-full-openstack` scenario comes in two variants
   depending on whether end users also get direct access to the Ironic API.
   Deployments are also free to :ref:`mix and match
   <deploy-scenarios-mix-and-match>` pieces of these scenarios.

.. _deploy-scenarios-standalone:

Standalone
==========

This is Ironic without any other OpenStack services. You manage and provision
hardware through the Ironic API directly — no Keystone, no Neutron, no Glance.
This makes sense when you need to provision machines without building out an
OpenStack cloud, or when you are writing automation that drives Ironic
directly.

The hard constraint is that there is **no multi-tenancy**. One set of
credentials controls everything. Authentication is handled either by disabling
it entirely (``noauth``) or using HTTP Basic auth. Standalone can also skip
the full message queue and use JSON-RPC instead, which removes a significant
operational dependency. See :doc:`/install/standalone/configure` for both.
For networking, a flat network is sufficient to get started. If you want
switch-level automation without Neutron, the
:doc:`ironic-networking service </install/standalone/networking>` handles
that without pulling in the rest of OpenStack.

A standalone deployment can run one or more conductors. A single conductor is
enough to get started and comfortably handles a smaller fleet; adding
conductors is how you scale out and gain high availability, rather than growing
any one of them. See :ref:`refarch-conductor-scaling` and :doc:`/admin/tuning`
for sizing and performance guidance. When multi-tenancy becomes a requirement,
the OpenStack scenarios below are the right path.

Two projects build on top of Ironic in this mode and are worth knowing about:

* :bifrost-doc:`Bifrost <>` — Ansible playbooks that automate deployment
  onto a set of known hardware. If you are already comfortable with Ansible,
  this is the fastest path to a working standalone setup. It can optionally
  deploy Keystone as well, if you want authentication without building out a
  full OpenStack cloud.

* `Metal3`_ — A Kubernetes operator that manages bare metal nodes using
  Ironic. The right choice if your workloads run on Kubernetes and you want
  bare metal nodes to participate in that model.

Both are single-tenant by nature. When you find yourself wanting to give
different teams different levels of access — or wanting to integrate with a
broader platform — that is the signal to move to the next scenario.

.. _Metal3: http://metal3.io/

.. _deploy-scenarios-openstack-no-nova:

OpenStack without Nova
======================

This is Ironic integrated with :keystone-doc:`Keystone <>`,
:glance-doc:`Glance <>`, and :neutron-doc:`Neutron <>`, but without Nova.
Users still provision nodes directly through the Ironic API, but now with
real credentials tied to Keystone projects. That opens up multi-tenancy and
gives you the full OpenStack access control model.

Multi-tenancy works through the owner and lessee model on nodes. A node can
be assigned to a project as an owner (full administrative control over that
node) or as a lessee (temporary, limited access). A system administrator sets
the owner field; the owner operates from there. See
:doc:`/admin/node-multitenancy` for how to configure this, and
:doc:`/admin/secure-rbac` for the full RBAC model.

Glance stores the images you deploy onto nodes. Neutron handles IPAM and,
with the right ML2 plugin — `networking-generic-switch`_ is a common choice
— can automate switch port configuration as part of the provisioning
lifecycle. If your environment uses OVN, see :doc:`/admin/ovn-networking`
for what is supported and the current caveats. See :doc:`/admin/networking`
for the full picture on which network interface options are available and
what each one requires.

This configuration scales from a handful of nodes up to a large deployment.
It can be installed with any standard OpenStack deployment tool —
Kolla-Ansible, OpenStack-Ansible, and OpenStack Helm all work here. See
:doc:`configure-integration` for the OpenStack service integration setup.

If you need users to provision bare metal without knowing or caring which
specific node they get, read on.

.. _networking-generic-switch: https://opendev.org/openstack/networking-generic-switch/src/branch/master/README.rst

.. _deploy-scenarios-full-openstack:

Full OpenStack
==============

This adds :nova-doc:`Nova <>` and Placement to the previous scenario. Users
request bare metal through the Nova Compute API using flavors — Nova handles
scheduling and Placement tracks resource availability. Nova flavors map to
Ironic resource classes, which Placement uses to match workloads to available
hardware. See :doc:`configure-compute` for the Nova integration and
:doc:`configure-nova-flavors` for flavor setup.

This is the right choice when you want a unified API for both virtual and
physical resources, or when Nova's scheduling model should decide which
hardware a workload lands on. The scale range is wide: a single node running
everything is a valid starting point, while at the other end multiple data
centers with distributed conductor groups managing hardware regionally is a
well-tested configuration. The same deployment tools that work for the previous
scenario — Kolla-Ansible, OpenStack-Ansible, and OpenStack Helm — support this
one as well.

Whether or not end users ever touch the Ironic API directly splits this
scenario into two distinct patterns.

Nova as the sole (hidden) Ironic client
---------------------------------------

Here Ironic is treated as a *system* (infrastructure) API. Nova is the only
client of the Ironic API: it authenticates as a single ``ironic`` service user
in the ``service`` project (see :doc:`configure-compute`) and drives the
hardware on behalf of end users, who only ever see the Compute API. A tenant's
identity reaches Ironic only as the ``project_id`` that Nova stamps onto each
node it deploys.

Because tenants never reach the Ironic API, owner- and lessee-based
self-service is not the point in this mode. Multi-tenancy is enforced entirely
by Nova's project model, so there is nothing extra to configure for it beyond
what you already set up for Keystone. ``conductor.automatic_lessee_source`` can
be left at its default, but it has little bearing on access here.

Nova alongside a public Ironic API
----------------------------------

Here Nova provisions some workloads, but projects *also* get direct,
authenticated access to the Ironic API. This enables self-service
administration **and** multitenancy alongside Nova: a project can manage the
nodes it owns through Ironic directly while still consuming hardware through the
Compute API.

Access is granted through the node ``owner`` and ``lessee`` fields. With
``conductor.automatic_lessee_source`` set to ``instance`` (the default), Ironic
derives a node's lessee from the ``project_id`` in ``instance_info`` that Nova
sets at deploy time; setting a node ``owner`` grants a project fuller
administrative control over its hardware. See :doc:`/admin/secure-rbac` and
:doc:`/admin/node-multitenancy` for the full access model.

For a concrete example of this configuration at small scale, see
:doc:`refarch/small-cloud-trusted-tenants`.

.. _deploy-scenarios-mix-and-match:

Mixing and Matching
===================

Real deployments are rarely pure. The scenarios above are starting points, and
most of the pieces can be combined — the following hybrids are common and fully
supported.

**Mixed fronting.** A single deployment can front some projects through Nova
while others drive Ironic directly. Nodes that Nova deploys carry the tenant's
``project_id`` in ``instance_info`` — which becomes the node ``lessee`` under
the default ``conductor.automatic_lessee_source`` of ``instance`` — while nodes
managed directly can have their ``owner`` and ``lessee`` set explicitly with
``baremetal node set``. Because ``automatic_lessee_source`` is a single
conductor-wide setting, mixed operation relies on Nova stamping the project onto
its own nodes and on explicit owner and lessee assignment everywhere else.

**Mixed networking.** The ``network_interface`` is a per-node setting, so nodes
using different network models can coexist in the same deployment: some on a
``flat`` provider network, some on tenant networks via ``neutron``, and some
using the standalone ``ironic-networking`` service. Each interface you intend to
use must be listed in ``enabled_network_interfaces``. See :doc:`/admin/networking`
and its :ref:`network-interfaces` overview for the available options, and
:doc:`/install/standalone/networking` for the ``ironic-networking`` service.

User Personas
=============

Who interacts with Ironic depends on which scenario you are running. In
standalone mode there is effectively one role. In OpenStack deployments the
RBAC model creates meaningful distinctions between people who manage hardware,
people who own or lease specific nodes, and people who provision and consume
them. See :doc:`/admin/secure-rbac` for the full role and scope model — in
particular the :ref:`trust model <secure-rbac-trust-model>` — and
:doc:`/admin/node-multitenancy` for the ``owner`` and ``lessee`` fields.

The personas below are illustrative, not prescriptive. There are no hard rules
about where one role ends and the next begins — the boundaries, and how each
role is configured, are up to whoever deploys Ironic. Treat these as a starting
set of ideas to adapt to your own organization, and expect them to overlap.

Hardware Technician (read-only)
-------------------------------

This person works hands-on with the physical hardware: racking and cabling
machines, swapping failed components, attaching a crash cart, and verifying a
node's configuration, firmware, and physical state. With read-only access to
Ironic they can look up a node's state and correlate it with the
machine in front of them, but any action on the node is left to someone with
write access. In RBAC terms this is a system-scoped ``reader`` role (equivalent
to the legacy ``baremetal_observer``).

Hardware Technician (read-write)
--------------------------------

This person does everything the read-only technician does, but also has the
access to act on nodes through Ironic — for example applying a firmware update
to resolve an issue, re-running hardware inspection after replacing a component,
placing a node into maintenance, or driving a reprovision. They may be
physically present at the hardware, or they may be operating the fleet remotely.
A remote technician is often the first line of triage, resolving what they can
through the API before dispatching someone to physically visit the machine.

This access can be a system-scoped ``member`` (or ``admin``) role. It also
overlaps with the Self-Service Project Ownership role below — a technician
responsible for a subset of hardware might instead be made the ``owner`` of just
those nodes, rather than given access across the whole fleet. To hand structured
operational tasks to people who lack deep Ironic knowledge, see
:doc:`/admin/runbooks`, which provide a controlled way to execute predefined
cleaning and servicing processes.

The split between the read-only and read-write technician is organizational,
not technical: they may be different people with different job responsibilities,
or there may be no distinction at all with only one of the two in use.

Cloud Administrator
-------------------

This person manages the Ironic service itself — policies, conductor groups, and
service-level configuration — rather than individual nodes. In OpenStack
deployments they hold a system-scoped ``admin`` role (equivalent to the legacy
``baremetal_admin``). In standalone mode, this is whoever holds the API
credentials. In larger deployments the distinction between this role and the
technician roles above is meaningful; in smaller ones a single person often
wears all of these hats.

Self-Service Project Ownership
------------------------------

This role exists in the OpenStack scenarios only. In organizations where
separate internal groups manage or onboard their own hardware, a project
administrator may be able to add nodes and then provision, deprovision, and
configure the nodes their project owns. Nodes are associated with a Keystone
project through the ``owner`` field: a system administrator can set it, or it is
populated automatically when a project administrator enrolls their own nodes,
and the owning project operates from there. See :doc:`/admin/node-multitenancy`.

Cloud User
----------

This is the person who ultimately consumes the bare metal. What "consuming"
means — and how much they can do — depends entirely on the deployment scenario,
ranging from near-total control to a narrow, policy-bounded slice of a single
node.

* **Standalone** — there is effectively no separation between the cloud user and
  the operator. One set of credentials controls everything, so the consumer has
  near-total control of the hardware.

* **OpenStack without Nova** — the user is project-scoped and drives Ironic
  directly with their own Keystone credentials. Depending on how nodes are
  assigned, they may act as an owner (administering their project's nodes) or a
  lessee (using them within limits).

* **Nova (hidden Ironic API)** — the user only ever touches the Compute API and
  may not know they are getting physical hardware at all. They never reach
  Ironic; Nova provisions on their behalf.

* **Nova (public Ironic API)** — alongside the Compute API, the user gets direct
  but limited Ironic access as a node **lessee**. They cannot provision nodes,
  but can interact with the nodes leased to them in whatever ways policy allows
  — controlling power, adjusting boot settings, or attaching virtual media —
  while sensitive fields like ``driver_info`` stay hidden by default.

In the OpenStack scenarios, access is scoped through the node ``owner`` and
``lessee`` fields: a system administrator or a node's owner can set them, or the
lessee is populated automatically at deployment time (see
``conductor.automatic_lessee_source``). :doc:`/admin/runbooks` are a good fit
for giving these users a controlled, predefined way to run permitted operations
without broad Ironic knowledge or access. See :doc:`/admin/node-multitenancy`
and :doc:`/admin/secure-rbac` for the full model.

Choosing Your Path
==================

* **No OpenStack:** Standalone. Consider :bifrost-doc:`Bifrost <>` for
  Ansible-based automation or `Metal3`_ if you are running Kubernetes.

* **Need multi-tenancy or OpenStack integration, want direct control over
  which node is used:** OpenStack without Nova. You get the full OpenStack
  access model while keeping explicit control over node selection.

* **Users expect a VM-like experience or you need a unified API for virtual
  and physical resources:** Full OpenStack. Nova handles scheduling and users
  work through the familiar Compute API — optionally alongside direct Ironic
  API access for projects that need it.

* **Not sure:** Start with OpenStack without Nova. Nova can be added later
  without rebuilding the Ironic deployment, and you can always
  :ref:`mix and match <deploy-scenarios-mix-and-match>` as your needs evolve.
