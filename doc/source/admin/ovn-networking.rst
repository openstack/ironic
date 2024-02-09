=====================
Use of OVN Networking
=====================

Overview
========

OVN is largely considered an evolution of OVS. While it is recommended that
operators continue to utilize OVS with Ironic, OVN has an attractive a
superset of capabilities and shifts some of the configuration of networking
away from configuration files, towards a service modeled at serving a more
scalable software defined networking experience. However, as with all newer
technologies, there are caveats and issues. The purpose of this documentation
is to help convey OVN's state, capabilities, and provide operators with
the context required to navigate their path forward.

.. Warning:: OVN is under quite a bit of active development, and this
             information may grow out of date quickly. We've provided links
             to help spread the information and enable operators to learn
             the current status.

Challenges
==========

DHCP
----

Historically, while OVN has included a DHCP server, this DHCP server has not
had the capability to handle clients needing custom attributes such as those
used by PXE and iPXE to enable network boot operations.

Typically, this has resulted in operators who use OVN with Bare Metal to
continue to operate the ``neutron-dhcp-agent`` service, along with setting
OVN configuration appropriate to disable OVN from responding to DHCP requests
for baremetal ports. Please see
:neutron-doc:`routed networks <configuration/ovn.html#ovn.disable_ovn_dhcp_for_baremetal_ports>`
for more information on this setting.

As of the 2023.2 Release of Ironic, The Ironic project *can* confirm that
OVN's DHCP server does work for PXE and iPXE operations when using **IPv4**,
OVS version **3.11**, and OVN version **23.06.0**.

Support for IPv6 is presently pending changes to Neutron, as IPv6 requires
additional configuration options and a different pattern of behavior, and
thus has not been tested. Your advised to continue to us the
``neutron-dhcp-agent`` if you need IPv6 at this time. Currently this support
is being worked in Neutron
`change 890683 <https://review.opendev.org/c/openstack/neutron/+/890683>`_ and
`bug 20305201 <https://bugs.launchpad.net/neutron/+bug/20305201>`_.

.. warning::
   Use of OVN with HTTPBoot interfaces has not been explicitly tested by the
   Ironic project, and is unlikely to take place until after integrated IPv6
   support with Neutron is ready for use. The project does not expect any
   specific issues, but the OVN DHCP server is an entirely different server
   than the interfaces were tested upon.

Maximum Transmission Units
--------------------------

OVN's handling of MTUs has been identified by OVN as being incomplete.
The reality is that it assumes the MTU is not further constrained beyond
the gateway, which sort of works in some caess for virtual machines, but
might not be applicable with baremetal because your traffic may pass
through lower, or higher MTUs.

Ideally, your environment should have consistent MTUs. If you cannot have
consistent MTUs, we recommend clamping the MTU and Maximum Segment Size
(MSS) using your front end router to ensure igress traffic is sized and
fragmented appropriately. Egress traffic should inherent it's MTU size
based upon the DHCP service configuration.

A items you can keep track of regarding MTU handling:

* Bug `2032817 <https://bugs.launchpad.net/neutron/+bug/2032817>`_
* OVN `TODO document <https://github.com/ovn-org/ovn/blob/main/TODO.rst>`_

To clamp the MTU and MSS on a linux based router, you can utilize the
following command::

  ip route add $network via $OVN_ROUTER advmss $MAX_SEGMENT_SIZE mtu lock $MTU

NAT of TFTP
-----------

Because the NAT and Connection Tracking layer gets applied differently with
OVN, as the router doesn't appear as a namespace or to the local OS kernel,
you will not be able to enable NAT translation for Bare Metal Networks
under the direct management of OVN, that is if you don't have a separate
TFTP service running from with-in that network.

This is a result of the kernel of the OVN gateway being unable to associate
and handle return packet directly as part of the connection tracking layer.
No direct work around for this is known, but generally Ironic encourages the
use of Virtual Media where possible to sidestep this sort of issue and ensure
a higher operational security posture for the deployment. Users of the
``redfish`` hardware type can learn about
:ref:`redfish-virtual-media` in our Redfish documentation.

.. Warning::
   Creation of FIPs, such as those which may be used grant SSH access to
   a internal node on a network, for example which may be used by Tempest,
   establishes a 1:1 NAT rule. When this is the case, TFTP packets
   *cannot* transit OVN and network boot operations will fail.

Rescue
------

Due to the aforementioned NAT issues, we know Rescue operations may not work.

This is being tracked as `bug 2033083 <https://bugs.launchpad.net/ironic/+bug/2033083>`_.

PXE boot of GRUB
----------------

Initial testing has revelaed that EFI booting Grub2 via OVN does not appear
to work with OVN. For some reason, Grub2 believes the network mask is
incorrect based upon the DHCP interaction, and results in a belief
that the TFTP server is locally attached.

For example, if a client is assigned ``10.1.0.13/28``, with a default
gateway of ``10.1.0.1``, and a tftp-sever of ``10.203.101.230``,
then grub2 believes it's default route is 10.0.0.0/8.

This is being tracked as `bug 2033430 <https://bugs.launchpad.net/ironic/+bug/2033430>`_
until we're better able to understand the root cause and file a bug with the
appropriate project.

Required Configuration
======================

OVN is designed to provide packet handling in a distributed fashion for a
each compute hypervisor in a cloud of virtual machines. However with Bare
Metal instances, you will likely need to have a pool of dedicated
"network nodes" to handle OVN traffic.

Chassis as Gateway
------------------

The networking node chassis must be configured to operate as a gateway.

This can be configured manually, but *should* (as far as Ironic is aware) be
configured by Neutron and set on interfaces matching the bridge mappings. At
least, it works that way in Devstack.

ML2 Plugins
-----------

The ``ovn-router`` and ``trunk`` ml2 plugins as supplied with Neutron
*must* be enabled.

If you need to attach to the network...
---------------------------------------

For example if you need to bind something into a network for baremetal,
above and beyond a dedicated interface, you will need to make the attachment
on the ``br-ex`` integration bridge, as opposed to ``br-int`` as one would
have done with OVS.

VTEP Switch Support
===================

Alpha-quality support was added to Ironic for OVN VTEP switches in API version
1.90. When the keys ``vtep-logical-switch``, ``vtep-physical-switch``, and
``port_id`` are set in ``port.local_link_connection``, Ironic will pass them on
to Neutron to be included in the binding profile to enable OVN support.

There `are reports of this approach working <https://bugs.launchpad.net/ironic/+bug/2034953>`_,
but Ironic developers do not have access to physical hardware to fully test
this feature. If you have any feedback for this feature, please reach out
to the Ironic community.

Unknowns
========

It is presently unknown if it is possible for OVN to perform and enable VXLAN
attachments to physical ports on integrated devices, thus operators are advised
to continue to use ``vlan`` networking with their hosts with existing ML2
integrations.
