==================
Node Multi-Tenancy
==================

This guide explains the steps needed to enable node multi-tenancy. This
feature enables non-admins to perform API actions on nodes, limited by
policy configuration. The Bare Metal service supports two kinds of
non-admin users:

* Owner: owns specific nodes and performs administrative actions on them
* Lessee: receives temporary and limited access to a node

Setting the Owner and Lessee
============================

Non-administrative access to a node is controlled through a node's ``owner``
or ``lessee`` attribute::

  baremetal node set --owner 080925ee2f464a2c9dce91ee6ea354e2  node-7
  baremetal node set --lessee 2a210e5ff114c8f2b6e994218f51a904  node-10

Ironic's API automatically grants visibility and access to these nodes
when a user request comes in with a "project" scope, i.e. credentials
which indicate the user is in a user within a project.

In older versions of Ironic, this functionality had to be manually configured
and then set via custom policies, but now it is automatically available
in modern versions of Ironic.
