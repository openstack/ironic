.. _configure-trait-based-networking:


Configure Trait Based Networking to Plan Networking Related Operations at vif Attach
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ironic has a feature called Trait Based Networking (or TBN) that allows
operators to configure how a node's network will be built and attached.

TBN applies to OpenStack installations utilizing Ironic, Neutron, and Nova
that want dynamic port scheduling based on networks and flavors chosen by the
instance creator.

In order to use this feature, a few steps must be completed.

#. Enable Trait Based Networking in the ironic-conductor service configuration:

   .. code-block:: ini

       [conductor]

       # Enables Trait Based Networking, defaults to False
       enable_trait_based_networking=True

#. Place a TBN configuration file in the configured location. The default
   location is: ``/etc/ironic/trait_based_networking.yaml``.

   For discussion of the syntax and format of the configuration file refer to
   :doc:`/references/trait-based-networking/tbn-config-file`.

   The default configuration which ships with Ironic is reproduced below:

    .. include:: ../../../etc/ironic/trait_based_networks.yaml.sample
        :code: yaml

#. Set desired TBN traits on a node's ``instance_info.traits``. Trait names
   must match exactly for a TBN trait to be applied.


Then, when ``vif_attach`` is called, TBN will plan networking operations based
on the node's ``instance_info.traits`` and supplied configured traits. If
planning succeeds, then each network operation will be applied.
