.. _deploy-ramdisk:

Building or downloading a deploy ramdisk image
==============================================

Ironic depends on having an image with the ironic-python-agent_ (IPA)
service running on it for controlling and deploying bare metal nodes.

You can download a pre-built version of the deploy ramdisk built with
the `CoreOS tools`_ at:

* `CoreOS deploy kernel <http://tarballs.openstack.org/ironic-python-agent/coreos/files/coreos_production_pxe-stable-newton.vmlinuz>`_
* `CoreOS deploy ramdisk <http://tarballs.openstack.org/ironic-python-agent/coreos/files/coreos_production_pxe_image-oem-stable-newton.cpio.gz>`_

.. _ironic-python-agent: http://docs.openstack.org/developer/ironic-python-agent/newton/

Building from source
--------------------

There are two known methods for creating the deployment image with the
IPA service:

.. _BuildingCoreOSDeployRamdisk:

CoreOS tools
~~~~~~~~~~~~

#. Clone the ironic-python-agent_ project::

    git clone https://git.openstack.org/openstack/ironic-python-agent

#. Install the requirements::

    Fedora 21/RHEL7/CentOS7:
        sudo yum install docker gzip util-linux cpio findutils grep gpg

    Fedora 22 or higher:
        sudo dnf install docker gzip util-linux cpio findutils grep gpg

    Ubuntu 14.04 (trusty) or higher:
        sudo apt-get install docker.io gzip uuid-runtime cpio findutils grep gnupg

#. Change directory to ``imagebuild/coreos``::

    cd ironic-python-agent/imagebuild/coreos

#. Start the docker daemon::

    Fedora/RHEL7/CentOS7:
        sudo systemctl start docker

    Ubuntu:
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

.. _`diskimage-builder documentation`: http://docs.openstack.org/developer/diskimage-builder
.. _`diskimage-builder installation documentation`: http://docs.openstack.org/developer/diskimage-builder/user_guide/installation.html
