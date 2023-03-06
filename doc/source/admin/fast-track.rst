=====================
Fast-Track Deployment
=====================

*Fast track* is a mode of operation where the Bare Metal service keeps a
machine powered on with the agent running between provisioning operations.
It is first booted during in-band inspection or cleaning (whatever happens
first) and is only shut down before rebooting into the final instance.
Depending on the configuration, this mode can save several reboots and is
particularly useful for scenarios where nodes are enrolled, prepared and
provisioned within a short period of time.

.. warning::
   Fast track deployment targets standalone use cases and is only tested with
   the ``noop`` networking. The case where inspection, cleaning and
   provisioning networks are different is not supported.

.. note::
   Fast track mode is very sensitive to long-running processes on the conductor
   side that may prevent agent heartbeats from being registered.

   For example, converting a large image to the raw format may take long enough
   to reach the fast track timeout. In this case, you can either :ref:`use raw
   images <stream_raw_images>` or move the conversion to the agent side with:

   .. code-block:: ini

    [DEFAULT]
    force_raw_images = False

Enabling
========

Fast track is off by default and should be enabled in the configuration:

.. code-block:: ini

   [deploy]
   fast_track = true

Starting with the Yoga release series, it can also be enabled or disabled per
node:

.. code-block:: console

   baremetal node set <node> --driver-info fast_track=true

Inspection
----------

If using :ref:`in-band inspection`, you need to tell ironic-inspector not to
power off nodes afterwards. Depending on the inspection mode (managed or
unmanaged), you need to configure two places. In ``ironic.conf``:

.. code-block:: ini

   [inspector]
   power_off = false

And in ``inspector.conf``:

.. code-block:: ini

   [processing]
   power_off = false

Finally, you need to update the :ironic-inspector-doc:`inspection PXE
configuration <install/index.html#configuration>` to include the
``ipa-api-url`` kernel parameter, pointing at the **ironic** endpoint, in
addition to the existing ``ipa-inspection-callback-url``.
