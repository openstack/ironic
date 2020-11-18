========
Policies
========

.. warning::
   JSON formatted policy files were deprecated in the Wallaby development
   cycle due to the Victoria deprecation by the ``olso.policy`` library.
   Use the `oslopolicy-convert-json-to-yaml`__ tool
   to convert the existing JSON to YAML formatted policy file in backward
   compatible way.

.. __: https://docs.openstack.org/oslo.policy/latest/cli/oslopolicy-convert-json-to-yaml.html


The following is an overview of all available policies in Ironic.  For
a sample configuration file, refer to :doc:`sample-policy`.

.. show-policy::
   :config-file: tools/policy/ironic-policy-generator.conf
