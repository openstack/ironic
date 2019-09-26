.. _deploy-ramdisk:

Building or downloading a deploy ramdisk image
==============================================

Ironic depends on having an image with the ironic-python-agent_ (IPA)
service running on it for controlling and deploying bare metal nodes.

Two kinds of images are published on every commit from every branch of
ironic-python-agent_:

* DIB_ images are suitable for production usage and can be downloaded from
  https://tarballs.openstack.org/ironic-python-agent/dib/files/.
* TinyIPA_ images are suitable for CI and testing environments and can be
  downloaded from
  https://tarballs.openstack.org/ironic-python-agent/tinyipa/files/.

Building from source
--------------------

Check the ironic-python-agent-builder_ project for information on how to build
ironic-python-agent ramdisks.

.. _ironic-python-agent: https://docs.openstack.org/ironic-python-agent/latest/
.. _DIB: https://docs.openstack.org/ironic-python-agent-builder/latest/admin/dib.html
.. _TinyIPA: https://docs.openstack.org/ironic-python-agent-builder/latest/admin/tinyipa.html
.. _ironic-python-agent-builder: https://docs.openstack.org/ironic-python-agent-builder/latest/
