.. _oci_container_registry:

================================
Use of an OCI Container Registry
================================

What is an OCI Container Registry?
----------------------------------

An OCI Container registry is an evolution of a docker container registry
where layers which make up containers can be housed as individual data
files, and then be retrieved to be reconstructed into a running container.
OCI is short for "Open Container Initiative", and you can learn more about
about OCI at `opencontainers.org <https://opencontainers.org>`_.

Container registries are evolving to support housing other data files, and
the focus in this context is the evolution to support those additional files
to be housed in and served by a container registry.

.. WARNING::
   This feature should be considered experimental.

Overview
--------

A recent addition to Ironic is the ability to retrieve artifacts from an
OCI Container Registry. This support is modeled such that it can be used
by an Ironic deployment for both disk images, and underlying artifacts used
for deployment, such as kernels and ramdisks. Different rules apply and
as such, please review the next several sections carefully.

At present, this functionality is only available for users who are directly
interacting with Ironic. Nova's data model is *only* compatible with usage
Glance at this present time, but that may change in the future.

How it works
------------

An OCI registry has a layered data model which can be divided into three
conceptual layers.

- Artifact Index - Higher level list which points to manifests and contains
  information like annotations, platform, architecture.
- Manifest - The intermediate structural location which contains the lower
  level details related to the blob (Binary Large OBject) data as well as
  the information where to find the blob data. When a container image is
  being referenced, this Manifest contains information on multiple "layers"
  which comprise a container.
- Blob data - The actual artifact, which can only be retrieved using the
  data provided in the manifest.

Ironic has a separate image service client which translates an an OCI
style container URL in an ``image_source`` value, formatted such as
``oci://host/user/container:tag``. When just a tag has been defined,
which can be thought of as specific "tagged" view containing many
artifacts, which Ironic will search through to find the best match.

Matching is performed with an attempt to weigh preference to file type
based upon the configured ``image_download_source``, where as with a ``local``
value, ``qcow2`` disk images are preferred. Otherwise ``raw`` is preferred.
This uses the ``disktype`` annotation where ``qcow2`` and ``qemu`` are
considered QCOW2 format images. A ``disktype`` annotation on the manifests
of ``raw`` or ``applehv``, are considered raw disk images.
Once file types have been appropriately weighted, the code attempts to match
the baremetal node's CPU architecture to the listed platform ``architecture``
in the remote registry. Once the file identification process has been
completed, Ironic automatically updates the ``image_source`` value to the
matching artifact in the remote container registry.

.. NOTE::
   The code automatically attempts to handle differences in architecture
   naming which has been observed, where ``x86_64`` is sometimes referred to
   as ``amd64``, and ``aarch64`` is sometimes referred to as ``arm64``.

.. WARNING:: An ``image_download_source`` of ``swift`` is incompatible
   with this image service. Only ``local`` and ``http`` are supported.

When a URL is specific and pointing to a specific manifest, for example
``oci://host/user/container@sha256:f00b...``, Ironic is only able to
retrieve that specific file from the the container registry. Due to the
data model, we also cannot learn additional details about that image
such as annotations, as annotations are part of the structural data
which points to manifests in the first place.

An added advantage to the use of container registries, is that the
checksum *is confirmed* in transit based upon the supplied metadata
from the container registry. For example, when you use a manifest URL,
the digest portion of the URL is used to checksum the returned contents,
and that manifests then contains the digest values for artifacts which
also supplies sufficient information to identify the URL where to download
the artifacts from.

Authentication
--------------

Authentication is an important topic for users of an OCI Image Registry.

While some public registries are fairly friendly to providing download access,
other registries may have aggressive quotas in place which require users to
be authenticated to download artifacts. Furthermore, private image registries
may require authentication for any access.

As such, there are three available paths for providing configuration:

* A node ``instance_info`` value of ``image_pull_secret``. This value may be
  utilized to retrieve an image artifact, but is not intended for pulling
  other artifacts like kernels or ramdisks used as part of a deployment
  process. As with all other ``instance_info`` field values, this value
  is deleted once the node has been unprovisioned. The way this field is
  used, is by supplying the pre-shared secret token value. This is the same
  value which you would normally have in your Docker ``config.json`` file
  ``auth`` field for the top level domain your accessing.
* A node ``driver_info`` value of ``image_pull_secret``. This setting is
  similar to the ``instance_info`` setting, but may be utilized by an
  administrator of a baremetal node to define the specific registry
  credential to utilize for the node.
* The :oslo.config:option:`oci.authentication_config` which allows for
  a conductor process wide pre-shared secret configuration. This configuration
  value can be set to a file which parses the common auth configuration
  format used for container tooling in regards to the secret to utilize
  for container registry authentication. This value is only consulted
  *if* a specific secret has not been defined to utilize, and is intended
  to be compaitble with the the format used by docker ``config.json`` to
  store authentication detail.

An example of the configuration file looks something like the following
example.

.. code-block:: json

  {
    "auths": {
      "quay.io": {
        "auth": "<pull_secret_here>"
      },
      "private-registry.tld": {
        "auth": "<pull_secret_here>"
      }
    }
  }


.. NOTE::
   The ``image_pull_secret`` values are not visible in the API surface
   due Ironic's secret value santiization, which prevents sensitive
   values from being visible, and are instead returned as '******'.

.. NOTE::
   If you need to extract the pull secret from a config.json file,
   you may want to explore using the ``jq`` command with a syntax
   along the lines of `jq '.auths."domain.tld".auth' config.json`
   which will return the quoted string you can then populate. Other
   command line oriented ways exist for users to retrieve such a value
   once a login has completed to a container platform, meaning you can
   use that same token value if desired.

Available URL Formats
---------------------

The following URL formats are available for use to download a disk image
artifact. When a non-precise manifest URL is supplied, Ironic will attempt
to identify and match the artifact. URLs for artifacts which are not disk
images are required to be specific and point to a specific manifest.

.. NOTE::
   If no tag is defined, the tag ``latest`` will be attempted,
   however, if that is not found in the *list* of available tags returned
   by the container registry, an ImageNotFound error will be raised in
   Ironic.

* oci://host/path/container - Ironic assumes 'latest' is the desired tag
  in this case.
* oci://host/path/container:tag - Ironic discoveres artifacts based upon
  the view provided by the defined tag.
* oci://host/path/container@sha256:f00f - This is a URL which defines a
  specific manifest. Should this be a container, this would be a manifest
  file with many layers to make a container, but for an artifact only a
  single file is represented by this manifest, and we retrieve this
  specific file.

.. WARNING::
   The use of tag values to access an artifact, for example, ``deploy_kernel``
   or ``deploy_ramdisk``, is not possible. This is an intentional limitation
   which may addressed in a future version of Ironic.

Known Limitations
-----------------

* For usage with disk images, only whole-disk images are supported.
  Ironic does not intend to support Partition images with this image service.

* IPA is unaware of remote container registries, as well as authentication
  to a remote registry. This is expected to be addressed in a future release
  of Ironic.

* Some artifacts may be compressed using Zstandard. Only disk images or
  artifacts which transit through the conductor may be appropriately
  decompressed. Unfortunately IPA won't be able to decompress such artifacts
  dynamically while streaming content.

* Authentication to container image registries is *only* available through
  the use of pre-shared token secrets.

* Use of tags may not be viable on some OCI Compliant image registries.
  This may result as an ImageNotFound error being raised when attempting
  to resolve a tag.

* User authentication is presently limited to use of a bearer token,
  under the model only supporting a "pull secret" style of authentication.
  If Basic authentication is required, please file a bug in
  `Ironic Launchpad <https://bugs.launchpad.net/ironic>`_.

How do I upload files to my own registry?
-----------------------------------------

While there are several different ways to do this, the easiest path is to
leverage a tool called ``ORAS``. You can learn more about ORAS at
`https://oras.land <https://oras.land/>`_

The ORAS utility is able to upload arbitrary artifacts to a Container
Registry along with the required manifest *and* then associates a tag
for easy human reference. While the OCI data model *does* happily
support a model of one tag in front of many manifests, ORAS does not.
In the ORAS model, one tag is associated with one artifact.

In the examples below, you can see how this is achieved. Please be careful
that these examples are *not* commands you can just cut and paste, but are
intended to demonstrate the required step and share the concept of how
to construct the URL for the artifact.

.. NOTE::
   These examples command lines may differ slightly based upon your remote
   registry, and underlying configuration, and as such leave out credential
   settings.

As a first step, we will demonstrate uploading an IPA Ramdisk kernel.

.. code-block:: shell

 $ export HOST=my-container-host.domain.tld
 $ export CONTAINER=my-project/my-container
 $ oras push ${HOST}/${CONTAINER}:ipa_kernel tinyipa-master.vmlinuz
 ✓ Exists    tinyipa-master.vmlinuz                         5.65/5.65 MB 100.00%     0s
   └─ sha256:15ed5220a397e6960a9ac6f770a07e3cc209c6870c42cbf8f388aa409d11ea71
 ✓ Exists    application/vnd.oci.empty.v1+json                    2/2  B 100.00%     0s
   └─ sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a
 ✓ Uploaded  application/vnd.oci.image.manifest.v1+json       606/606  B 100.00%     0s
   └─ sha256:2d408348dd6ff2e26efc1de03616ca91d76936a27028061bc314289cecdc895f
 Pushed [registry] my-container-host.domain.tld/my-project/my-container:ipa_kernel
 ArtifactType: application/vnd.unknown.artifact.v1
 Digest: sha256:2d408348dd6ff2e26efc1de03616ca91d76936a27028061bc314289cecdc895f
 $
 $ export MY_IPA_KERNEL=oci://${HOST}/${CONTAINER}:@sha256:2d408348dd6ff2e26efc1de03616ca91d76936a27028061bc314289cecdc895f

As you can see from this example, we've executed the command, and uploaded the file.
The important aspect to highlight is the digest reported at the end. This is the
manifest digest which you can utilize to generate your URL.

.. WARNING::
   When constructing environment variables for your own use, specifically with
   digest values, please be mindful that you will need to utilize the digest
   value from your own upload, and not from the example.

.. code-block:: shell

 $ oras push ${HOST}/${CONTAINER}:ipa_ramdisk tinyipa-master.gz
 ✓ Exists    tinyipa-master.gz                              91.9/91.9 MB 100.00%     0s
   └─ sha256:0d92eeb98483f06111a352b673d588b1aab3efc03690c1553ef8fd8acdde15fc
 ✓ Exists    application/vnd.oci.empty.v1+json                    2/2  B 100.00%     0s
   └─ sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a
 ✓ Uploaded  application/vnd.oci.image.manifest.v1+json       602/602  B 100.00%     0s
   └─ sha256:b17e53ff83539dd6d49e714b09eeb3bd0a9bb7eee2ba8716f6819f2f6ceaad13
 Pushed [registry] my-container-host.domain.tld/my-project/my-container:ipa_ramdisk
 ArtifactType: application/vnd.unknown.artifact.v1
 Digest: sha256:b17e53ff83539dd6d49e714b09eeb3bd0a9bb7eee2ba8716f6819f2f6ceaad13
 $
 $ export MY_IPA_RAMDISK=oci://${HOST}/${CONTAINER}:@sha256:b17e53ff83539dd6d49e714b09eeb3bd0a9bb7eee2ba8716f6819f2f6ceaad13

As a reminder, please remember to utilize *different* tags with ORAS.

For example, you can view the current tags in the remote registry by existing the following command.

.. code-block:: shell

 $ oras repo tags --insecure $HOST/project/container
 ipa_kernel
 ipa_ramdisk
 unrelated_item
 $

Now that you have successfully uploaded an IPA kernel and ramdisk, the only
item remaining is a disk image. In this example below, we're generating a
container tag based URL as well as direct manifest digest URL.

.. NOTE::
   The example below sets a manifest annotation of ``disktype`` and
   artifact platform. While not explicitly required, these are recommended
   should you allow Ironic to resolve the disk image utilizing the container
   tag as opposed to a digest URL.

.. code-block:: shell

 $ oras push -a disktype=qcow2 --artifact-platform linux/x86_64 $HOST/$CONTAINER:cirros-0.6.3 ./cirros-0.6.3-x86_64-disk.img
 ✓ Exists    cirros-0.6.3-x86_64-disk.img                   20.7/20.7 MB 100.00%     0s
   └─ sha256:7d6355852aeb6dbcd191bcda7cd74f1536cfe5cbf8a10495a7283a8396e4b75b
 ✓ Uploaded  application/vnd.oci.image.config.v1+json           38/38  B 100.00%   43ms
   └─ sha256:369358945e345b86304b802b704a7809f98ccbda56b0a459a269077169a0ac5a
 ✓ Uploaded  application/vnd.oci.image.manifest.v1+json       626/626  B 100.00%     0s
   └─ sha256:0a175cf13c651f44750d6a5cf0cf2f75d933bd591315d77e19105e5446b73a86
 Pushed [registry] my-container-host.domain.tld/my-project/my-container:cirros-0.6.3
 ArtifactType: application/vnd.unknown.artifact.v1
 Digest: sha256:0a175cf13c651f44750d6a5cf0cf2f75d933bd591315d77e19105e5446b73a86
 $ export MY_DISK_IMAGE_TAG_URL=oci://${HOST}/${CONTAINER}:cirros-0.6.3
 $ export MY_DISK_IMAGE_DIGEST_URL=oci://${HOST}/${CONTAINER}@sha256:0a175cf13c651f44750d6a5cf0cf2f75d933bd591315d77e19105e5446b73a86
