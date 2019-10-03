========================
Ansible deploy interface
========================

`Ansible`_ is a mature and popular automation tool, written in Python
and requiring no agents running on the node being configured.
All communications with the node are by default performed over secure SSH
transport.

The ``ansible`` deploy interface uses Ansible playbooks to define the
deployment logic. It is not based on
:ironic-python-agent-doc:`Ironic Python Agent (IPA) <>`
and does not generally need IPA to be running in the deploy ramdisk.

Overview
========

The main advantage of this deploy interface is extended flexibility in
regards to changing and adapting node deployment logic for specific
use cases, via Ansible tooling that is already familiar to operators.

It can be used to shorten the usual feature development cycle of

* implementing logic in ironic,
* implementing logic in IPA,
* rebuilding deploy ramdisk,
* uploading deploy ramdisk to Glance/HTTP storage,
* reassigning deploy ramdisk to nodes,
* restarting ironic-conductor service(s) and
* running a test deployment

by using a "stable" deploy ramdisk and not requiring
ironic-conductor restarts (see `Extending playbooks`_).

The main disadvantage of this deploy interface is the synchronous manner
of performing deployment/cleaning tasks.
A separate ``ansible-playbook`` process is spawned for each node being
provisioned or cleaned, which consumes one thread from the thread pool
available to the ``ironic-conductor`` process and blocks this thread until
the node provisioning or cleaning step is finished or fails.
This has to be taken into account when planning an ironic deployment
that enables this deploy interface.

Each action (deploy, clean) is described by a single playbook with roles,
which is run whole during deployment, or tag-wise during cleaning.
Control of cleaning steps is through tags and auxiliary clean steps file.
The playbooks for actions can be set per-node, as can the clean steps
file.

Features
--------

Similar to deploy interfaces relying on
:ironic-python-agent-doc:`Ironic Python Agent (IPA) <>`, this deploy
interface also depends on the deploy ramdisk calling back to ironic API's
``heartbeat`` endpoint.

However, the driver is currently synchronous, so only the first heartbeat is
processed and is used as a signal to start ``ansible-playbook`` process.

User images
~~~~~~~~~~~

Supports whole-disk images and partition images:

- compressed images are downloaded to RAM and converted to disk device;
- raw images are streamed to disk directly.

For partition images the driver will create root partition, and,
if requested, ephemeral and swap partitions as set in node's
``instance_info`` by the Compute service or operator.
The create partition table will be of ``msdos`` type by default,
the node's ``disk_label`` capability is honored if set in node's
``instance_info`` (see also :ref:`choosing_the_disk_label`).

Configdrive partition
~~~~~~~~~~~~~~~~~~~~~

Creating a configdrive partition is supported for both whole disk
and partition images, on both ``msdos`` and ``GPT`` labeled disks.

Root device hints
~~~~~~~~~~~~~~~~~

Root device hints are currently supported in their basic form only,
with exact matches (see :ref:`root-device-hints` for more details).
If no root device hint is provided for the node, the first device returned as
part of ``ansible_devices`` fact is used as root device to create partitions
on or write the whole disk image to.

Node cleaning
~~~~~~~~~~~~~

Cleaning is supported, both automated and manual.
The driver has two default clean steps:

- wiping device metadata
- disk shredding

Their priority can be overridden via
``[deploy]\erase_devices_metadata_priority`` and
``[deploy]\erase_devices_priority`` options, respectively, in the ironic
configuration file.

As in the case of this driver all cleaning steps are known to the
ironic-conductor service, booting the deploy ramdisk is completely skipped
when there are no cleaning steps to perform.

.. note::

   Aborting cleaning steps is not supported.

Logging
~~~~~~~

Logging is implemented as custom Ansible callback module,
that makes use of ``oslo.log`` and ``oslo.config`` libraries
and can re-use logging configuration defined in the main ironic configuration
file to set logging for Ansible events, or use a separate file for this purpose.

It works best when ``journald`` support for logging is enabled.


Requirements
============

Ansible
    Tested with, and targets, Ansible 2.4.x

Bootstrap image requirements
----------------------------

- password-less sudo permissions for the user used by Ansible
- python 2.7.x
- openssh-server
- GNU coreutils
- utils-linux
- parted
- gdisk
- qemu-utils
- python-requests (for ironic callback and streaming image download)
- python-netifaces (for ironic callback)

A set of scripts to build a suitable deploy ramdisk based on TinyCore Linux
and ``tinyipa`` ramdisk, and an element for ``diskimage-builder`` can be found
in ironic-staging-drivers_ project but will be eventually migrated to the new
ironic-python-agent-builder_ project.

Setting up your environment
===========================

#. Install ironic (either as part of OpenStack or standalone)

   - If using ironic as part of OpenStack, ensure that the Image service is
     configured to use the Object Storage service as backend,
     and the Bare Metal service is configured accordingly, see
     :doc:`Configure the Image service for temporary URLs <../../install/configure-glance-swift>`.

#. Install Ansible version as specified in ``ironic/driver-requirements.txt``
   file
#. Edit ironic configuration file

   A. Add ``ansible`` to the list of deploy interfaces defined in
      ``[DEFAULT]\enabled_deploy_interfaces`` option.
   B. Ensure that a hardware type supporting ``ansible`` deploy interface
      is enabled in ``[DEFAULT]\enabled_hardware_types`` option.
   C. Modify options in the ``[ansible]`` section of ironic's configuration
      file if needed (see `Configuration file`_).

#. (Re)start ironic-conductor service
#. Build suitable deploy kernel and ramdisk images
#. Upload them to Glance or put in your HTTP storage
#. Create new or update existing nodes to use the enabled driver
   of your choice and populate `Driver properties for the Node`_ when
   different from defaults.
#. Deploy the node as usual.

Ansible-deploy options
----------------------

Configuration file
~~~~~~~~~~~~~~~~~~~

Driver options are configured in ``[ansible]`` section of ironic
configuration file, for their descriptions and default values please see
`configuration file sample  <../../configuration/config.html#ansible>`_.

Driver properties for the Node
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Set them per-node via ``openstack baremetal node set`` command,
for example:

.. code-block:: shell

   openstack baremetal node set <node> \
       --deploy-interface ansible \
       --driver-info ansible_username=stack \
       --driver-info ansible_key_file=/etc/ironic/id_rsa


ansible_username
    User name to use for Ansible to access the node.
    Default is taken from ``[ansible]/default_username`` option of the
    ironic configuration file (defaults to ``ansible``).

ansible_key_file
    Private SSH key used to access the node.
    Default is taken from ``[ansible]/default_key_file`` option of the
    ironic configuration file.
    If neither is set, the default private SSH keys of the user running
    the ``ironic-conductor`` process will be used.

ansible_deploy_playbook
    Playbook to use when deploying this node.
    Default is taken from ``[ansible]/default_deploy_playbook`` option of the
    ironic configuration file (defaults to ``deploy.yaml``).

ansible_shutdown_playbook
    Playbook to use to gracefully shutdown the node in-band.
    Default is taken from ``[ansible]/default_shutdown_playbook`` option of the
    ironic configuration file (defaults to ``shutdown.yaml``).

ansible_clean_playbook
    Playbook to use when cleaning the node.
    Default is taken from ``[ansible]/default_clean_playbook`` option of the
    ironic configuration file (defaults to ``clean.yaml``).

ansible_clean_steps_config
    Auxiliary YAML file that holds description of cleaning steps
    used by this node, and defines playbook tags in
    ``ansible_clean_playbook`` file corresponding to each cleaning step.
    Default is taken from ``[ansible]/default_clean_steps_config`` option of the
    ironic configuration file (defaults to ``clean_steps.yaml``).

ansible_python_interpreter
    Absolute path to the python interpreter on the managed machine.
    Default is taken from ``[ansible]/default_python_interpreter`` option of
    the ironic configuration file.
    Ansible uses ``/usr/bin/python`` by default.



Customizing the deployment logic
================================


Expected playbooks directory layout
-----------------------------------

The ``[ansible]\playbooks_path`` option in the ironic configuration file
is expected to have a standard layout for an Ansible project with
some additions::

    <playbooks_path>
    |
    \_ inventory
    \_ add-ironic-nodes.yaml
    \_ roles
     \_ role1
     \_ role2
     \_ ...
    |
    \_callback_plugins
     \_ ...
    |
    \_ library
     \_ ...


The extra files relied by this driver are:

inventory
    Ansible inventory file containing a single entry of
    ``conductor ansible_connection=local``.
    This basically defines an alias to ``localhost``.
    Its purpose is to make logging for tasks performed by Ansible locally and
    referencing the localhost in playbooks more intuitive.
    This also suppresses warnings produced by Ansible about ``hosts`` file
    being empty.

add-ironic-nodes.yaml
    This file contains an Ansible play that populates in-memory Ansible
    inventory with access information received from the ansible-deploy
    interface, as well as some per-node variables.
    Include it in all your custom playbooks as the first play.

The default ``deploy.yaml`` playbook is using several smaller roles that
correspond to particular stages of deployment process:

- ``discover`` - e.g. set root device and image target
- ``prepare`` - if needed, prepare system, for example create partitions
- ``deploy`` - download/convert/write user image and configdrive
- ``configure`` - post-deployment steps, e.g. installing the bootloader

Some more included roles are:

- ``shutdown`` - used to gracefully power the node off in-band
- ``clean`` - defines cleaning procedure, with each clean step defined
  as separate playbook tag.

Extending playbooks
-------------------

Most probably you'd start experimenting like this:

#. Create a copy of ``deploy.yaml`` playbook *in the same folder*,
   name it distinctively.
#. Create Ansible roles with your customized logic in ``roles`` folder.

   A. In your custom deploy playbook, replace the ``prepare`` role
      with your own one that defines steps to be run
      *before* image download/writing.
      This is a good place to set facts overriding those provided/omitted
      by the driver, like ``ironic_partitions`` or ``ironic_root_device``,
      and create custom partitions or (software) RAIDs.
   B. In your custom deploy playbook, replace the ``configure`` role
      with your own one that defines steps to be run
      *after* image is written to disk.
      This is a good place for example to configure the bootloader and
      add kernel options to avoid additional reboots.
   C. Use those new roles in your new playbook.

#. Assign the custom deploy playbook you've created to the node's
   ``driver_info/ansible_deploy_playbook`` field.
#. Run deployment.

   A. No ironic-conductor restart is necessary.
   B. A new deploy ramdisk must be built and assigned to nodes only when
      you want to use a command/script/package not present in the current
      deploy ramdisk and you can not or do not want to install those
      at runtime.

Variables you have access to
----------------------------

This driver will pass the single JSON-ified extra var argument to
Ansible (as in ``ansible-playbook -e ..``).
Those values are then accessible in your plays as well
(some of them are optional and might not be defined):

.. code-block:: yaml


   ironic:
     nodes:
     - ip: "<IPADDRESS>"
       name: "<NODE_UUID>"
       user: "<USER ANSIBLE WILL USE>"
       extra: "<COPY OF NODE's EXTRA FIELD>"
     image:
       url: "<URL TO FETCH THE USER IMAGE FROM>"
       disk_format: "<qcow2|raw|...>"
       container_format: "<bare|...>"
       checksum: "<hash-algo:hashstring>"
       mem_req: "<REQUIRED FREE MEMORY TO DOWNLOAD IMAGE TO RAM>"
       tags: "<LIST OF IMAGE TAGS AS DEFINED IN GLANCE>"
       properties: "<DICT OF IMAGE PROPERTIES AS DEFINED IN GLANCE>"
     configdrive:
       type: "<url|file>"
       location: "<URL OR PATH ON CONDUCTOR>"
     partition_info:
       label: "<msdos|gpt>"
       preserve_ephemeral: "<bool>"
       ephemeral_format: "<FILESYSTEM TO CREATE ON EPHEMERAL PARTITION>"
       partitions: "<LIST OF PARTITIONS IN FORMAT EXPECTED BY PARTED MODULE>"
     raid_config: "<COPY OF NODE's TARGET_RAID_CONFIG FIELD>"


``ironic.nodes``
    List of dictionaries (currently of only one element) that will be used by
    ``add-ironic-nodes.yaml`` play to populate in-memory inventory.
    It also contains a copy of node's ``extra`` field so you can access it in
    the playbooks. The Ansible's host is set to node's UUID.

``ironic.image``
    All fields of node's ``instance_info`` that start with ``image_`` are
    passed inside this variable. Some extra notes and fields:

    - ``mem_req`` is calculated from image size (if available) and config
      option ``[ansible]extra_memory``.
    - if ``checksum`` is not in the form ``<hash-algo>:<hash-sum>``, hashing
      algorithm is assumed to be ``md5`` (default in Glance).
    - ``validate_certs`` - boolean (``yes/no``) flag that turns validating
      image store SSL certificate on or off (default is 'yes').
      Governed by ``[ansible]image_store_insecure`` option
      in ironic configuration file.
    - ``cafile`` - custom CA bundle to use for validating image store
      SSL certificate.
      Takes value of ``[ansible]image_store_cafile`` if that is defined.
      Currently is not used by default playbooks, as Ansible has no way to
      specify the custom CA bundle to use for single HTTPS actions,
      however you can use this value in your custom playbooks to for example
      upload and register this CA in the ramdisk at deploy time.
    - ``client_cert`` - cert file for client-side SSL authentication.
      Takes value of ``[ansible]image_store_certfile`` option if defined.
      Currently is not used by default playbooks,
      however you can use this value in your custom playbooks.
    - ``client_key`` - private key file for client-side SSL authentication.
      Takes value of ``[ansible]image_store_keyfile`` option if defined.
      Currently is not used by default playbooks,
      however you can use this value in your custom playbooks.

``ironic.partition_info.partitions``
    Optional. List of dictionaries defining partitions to create on the node
    in the form:

    .. code-block:: yaml

       partitions:
       - name: "<NAME OF PARTITION>"
         unit: "<UNITS FOR SIZE>"
         size: "<SIZE OF THE PARTITION>"
         type: "<primary|extended|logical>"
         align: "<ONE OF PARTED_SUPPORTED OPTIONS>"
         format: "<PARTITION TYPE TO SET>"
         flags:
           flag_name: "<bool>"

    The driver will populate this list from ``root_gb``, ``swap_mb`` and
    ``ephemeral_gb`` fields of ``instance_info``.
    The driver will also prepend the ``bios_grub``-labeled partition
    when deploying on GPT-labeled disk,
    and pre-create a 64 MiB partition for configdrive if it is set in
    ``instance_info``.

    Please read the documentation included in the ``ironic_parted`` module's
    source for more info on the module and its arguments.

``ironic.partition_info.ephemeral_format``
    Optional. Taken from ``instance_info``, it defines file system to be
    created on the ephemeral partition.
    Defaults to the value of ``[pxe]\default_ephemeral_format`` option
    in ironic configuration file.

``ironic.partition_info.preserve_ephemeral``
    Optional. Taken from the ``instance_info``, it specifies if the ephemeral
    partition must be preserved or rebuilt. Defaults to ``no``.

``ironic.raid_config``
    Taken from the ``target_raid_config`` if not empty, it specifies the RAID
    configuration to apply.

As usual for Ansible playbooks, you also have access to standard
Ansible facts discovered by ``setup`` module.

Included custom Ansible modules
-------------------------------

The provided ``playbooks_path/library`` folder includes several custom
Ansible modules used by default implementation of ``deploy`` and
``prepare`` roles.
You can use these modules in your playbooks as well.

``stream_url``
    Streaming download from HTTP(S) source to the disk device directly,
    tries to be compatible with Ansible's ``get_url`` module in terms of
    module arguments.
    Due to the low level of such operation it is not idempotent.

``ironic_parted``
    creates partition tables and partitions with ``parted`` utility.
    Due to the low level of such operation it is not idempotent.
    Please read the documentation included in the module's source
    for more information about this module and its arguments.
    The name is chosen so that the ``parted`` module included in Ansible
    is not shadowed.

.. _Ansible: https://docs.ansible.com/ansible/latest/index.html
.. _ironic-staging-drivers: https://opendev.org/x/ironic-staging-drivers/src/branch/stable/pike/imagebuild
.. _ironic-python-agent-builder: https://opendev.org/openstack/ironic-python-agent-builder
