===========
Secure RBAC
===========

Suggested Reading
=================

It is likely an understatement to say that policy enforcement is a complex
subject. It requires operational context to craft custom policy to meet
general use needs. Part of this is why the Secure RBAC effort was started,
to provide consistency and a "good" starting place for most users who need
a higher level of granularity.

That being said, it would likely help anyone working to implement
customization of these policies to consult some reference material
in hopes of understanding the context.

* `Keystone Adminstrator Guide - Service API Protection <https://docs.openstack.org/keystone/latest/admin/service-api-protection.html>`_
* `Ironic Scoped Role Based Access Control Specification <https://specs.openstack.org/openstack/ironic-specs/specs/not-implemented/secure-rbac.html>`_

Historical Context - How we reached our access model
----------------------------------------------------

Ironic has reached the access model through an evolution the API and the data
stored. Along with the data stored, the enforcement of policy based upon data
stored in these fields.

* `Ownership Information Storage <https://specs.openstack.org/openstack/ironic-specs/specs/12.1/ownership-field.html>`_
* `Allow Node owners to Administer <https://specs.openstack.org/openstack/ironic-specs/specs/14.0/node-owner-policy.html>`_
* `Allow Leasable Nodes <https://specs.openstack.org/openstack/ironic-specs/specs/15.0/node-lessee.html>`_

System Scoped
=============

.. todo: Need to be filled out in an earlier patch most likely.

Project Scoped
==============

Project scoped authentication is when a request token and associated records
indicate an associated ``project_id`` value.

Legacy Behavior
---------------

The legacy behavior of API service is that all requests are treated as
project scoped requests where access is governed using an "admin project".
This behavior is *deprecated*. The new behavior is a delineation of
access through ``system`` scoped and ``project`` scoped requests.

In essence, what would have served as an "admin project", is now ``system``
scoped usage.

Previously, Ironic API, by default, responded with access denied or permitted
based upon the admin project and associated role. These responses would
generate an HTTP 403 if the project was incorrect or if a user role.

.. NOTE:: While Ironic has had the concept of an ``owner`` and a
          ``lessee``, they are *NOT* used by default. They require
          custom policy configuration files to be used in the legacy
          operating mode.

Supported Endpoints
-------------------

* /nodes
* /nodes/<uuid>/ports
* /nodes/<uuid>/portgroups
* /nodes/<uuid>/volume/connectors
* /nodes/<uuid>/volume/targets
* /ports
* /portgroups
* /volume/connectors
* /volume/targets

How Project Scoped Works
------------------------

Ironic has two project use models where access is generally more delagative
to an ``owner`` where access to a ``lessee`` is generally more utilitarian.

The purpose of an owner, is more to enable the System Operator to delegate
much of the administrative activity of a Node to the owner.
This may be because they physically own the hardware, or they are in charge
of the node. Regardless of the use model that the fields and mechanics
support, these fields are to support humans, and possibly services where
applicable.

The purpose of a lessee is more for a *tenant* in their *project* to
be able to have access to perform basic actions with the API. In some cases
that may be to reprovision or rebuild a node. Ultimately that is the lessee's
progative, but by default there are actions and field updates that cannot
be performed by default. This is also governed by access level within
a project.

These policies are applied in the way data is viewed and how data can be
updated. Generally, an inability to view a node is an access permission issue
in term of the project ID being correct for owner/lessee.

The ironic project has attempted to generally codify what we believe is
reasonable, however operators may wish to override these policy settings.
For details general policy setting details, please see
:doc:`/configuration/policy`.

Field value visibility restrictions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ironic's API, by default has a concept of filtering node values to prevent
sensitive data from being leaked. System scoped users are subjected to basic
restrictions, where as project scoped users are, by default, examined further
and against additional policies. This threshold is controlled with the
``baremetal:node:get:filter_threshold``.

By default, the following fields are masked on Nodes and are controlled by the
associated policies. By default, owner's are able to see insight into the
infrastucture, where as lessee users *CANNOT* view these fields by default.

* ``last_error`` - ``baremetal:node:get:last_error``
* ``reservation`` - ``baremetal:node:get:reservation``
* ``driver_internal_info`` - ``baremetal:node:get:driver_internal_info``
* ``driver_info`` - ``baremetal:node:get:driver_info``

Field update restrictions
~~~~~~~~~~~~~~~~~~~~~~~~~

Some of the fields in this list are restricted to System scoped users,
or even only System Administrators. Some of these default restrictions
are likely obvious. Owners can't change the owner. Lessee's can't
change the owner.

* ``driver_info`` - ``baremetal:node:update:driver_info``
* ``properties`` - ``baremetal:node:update:properties``
* ``chassis_uuid`` - ``baremetal:node:update:chassis_uuid``
* ``instance_uuid`` - ``baremetal:node:update:instance_uuid``
* ``lessee`` - ``baremetal:node:update:lessee``
* ``owner`` - ``baremetal:node:update:owner``
* ``driver`` - ``baremetal:node:update:driver_interfaces``
* ``*_interface`` - ``baremetal:node:update:driver_interfaces``
* ``network_data`` - ``baremetal:node:update:network_data``
* ``conductor_group`` - ``baremetal:node:update:conductor_group``
* ``name`` - ``baremetal:node:update:name``
* ``retired`` - ``baremetal:node:update:driver_info``
* ``retired_reason`` - ``baremetal:node:update:retired``

.. WARNING:: The ``chassis_uuid`` field is a write-once-only field. As such
             it is restricted to system scoped administrators.

More information is available on these fields in :doc:`/configuration/policy`.

Pratical differences
--------------------

Most users, upon implementing the use of ``system`` scoped authentication
should not notice a difference as long as their authentication token is
properly scoped to ``system`` and with the appropriate role for their
access level. For most users who used a ``baremetal`` project,
or other custom project via a custom policy file, along with a custom
role name such as ``baremetal_admin``, this will require changing
the user to be a ``system`` scoped user with ``admin`` privilges.

The most noticeable difference for API consumers is the HTTP 403 access
code is now mainly a HTTP 404 access code. The access concept has changed
from "Does the user user broadly has access to the API?" to
"Does user have access to the node, and then do they have access
to the specific resource?".

How do I assign an owner?
-------------------------

.. todo: need to add information on the owner assignment
   and also cover what this generally means... maybe?

How do I assign a lessee?
-------------------------

.. todo: Need to cover how to assign a lessee.
