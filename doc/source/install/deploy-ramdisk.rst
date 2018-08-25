.. _deploy-ramdisk:

Building or downloading a deploy ramdisk image
==============================================

Ironic depends on having an image with the ironic-python-agent_ (IPA)
service running on it for controlling and deploying bare metal nodes.

You can download a pre-built version of the deploy ramdisk built with
the `CoreOS tools`_ at:

* `CoreOS deploy kernel <https://tarballs.openstack.org/ironic-python-agent/coreos/files/coreos_production_pxe.vmlinuz>`_
* `CoreOS deploy ramdisk <https://tarballs.openstack.org/ironic-python-agent/coreos/files/coreos_production_pxe_image-oem.cpio.gz>`_

.. _ironic-python-agent: https://docs.openstack.org/ironic-python-agent/latest/

Building from source
--------------------

There are two known methods for creating the deployment image with the
IPA service:

.. _BuildingCoreOSDeployRamdisk:

CoreOS tools
~~~~~~~~~~~~

#. Clone the ironic-python-agent_ project::

    git clone https://git.openstack.org/openstack/ironic-python-agent

#. Install the requirements:

   RHEL7/CentOS7::

       sudo yum install docker gzip util-linux cpio findutils grep gpg

   Fedora::

       sudo dnf install docker gzip util-linux cpio findutils grep gpg

   Ubuntu 14.04 (trusty) or higher::

       sudo apt-get install docker.io gzip uuid-runtime cpio findutils grep gnupg cgroup-lite

   SUSE::

       sudo zypper install docker gzip util-linux cpio findutils grep gpg2

#. Change directory to ``imagebuild/coreos``::

    cd ironic-python-agent/imagebuild/coreos

#. Start the docker daemon:

   Fedora/RHEL7/CentOS7/SUSE::

       sudo systemctl start docker

   Ubuntu::

       sudo service docker start

#. Create the image::

    sudo make

#. Or, create an ISO image to boot with virtual media::

    sudo make iso


.. note::
   Once built the deploy ramdisk and kernel will appear inside of a
   directory called ``UPLOAD``.


.. _BuildingDibBasedDeployRamdisk:

disk-image-builder
~~~~~~~~~~~~~~~~~~

#. Follow `diskimage-builder installation documentation`_ to install
   diskimage-builder.

#. Create the image::

    disk-image-create ironic-agent fedora -o ironic-deploy

   The above command creates the deploy ramdisk and kernel named
   ``ironic-deploy.vmlinuz`` and ``ironic-deploy.initramfs`` in your
   current directory.

#. Or, create an ISO image to boot with virtual media::

    disk-image-create ironic-agent fedora iso -o ironic-deploy

   The above command creates the deploy ISO named ``ironic-deploy.iso``
   in your current directory.

.. note::
   Fedora was used as an example for the base operational system. Please
   check the `diskimage-builder documentation`_ for other supported
   operational systems.

.. _`diskimage-builder documentation`: https://docs.openstack.org/diskimage-builder/latest/
.. _`diskimage-builder installation documentation`: https://docs.openstack.org/diskimage-builder/latest/user_guide/installation.html
