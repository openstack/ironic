=================================
Redfish Interoperability Profile
=================================

Overview
--------

The Redfish Interoperability Profile is a JSON document written in a
particular format that serves two purposes.

*  It enables the creation of a human-readable document that merges the
   profile requirements with the Redfish schema into a single document
   for developers or users.
*  It allows a conformance test utility to test a Redfish Service
   implementation for conformance with the profile.

The JSON document structure is intended to align easily with JSON payloads
retrieved from Redfish Service implementations, to allow for easy comparisons
and conformance testing. Many of the properties defined within this structure
have assumed default values that correspond with the most common use case, so
that those properties can be omitted from the document for brevity.

Validation of Profiles using DMTF tool
---------------------------------------

An open source utility has been created by the Redfish Forum to verify that
a Redfish Service implementation conforms to the requirements included in a
Redfish Interoperability Profile. The Redfish Interop Validator is available
for download from the DMTF's organization on Github at
https://github.com/DMTF/Redfish-Interop-Validator. Refer to instructions in
README on how to configure and run validation.


Reference
---------

https://github.com/DMTF/Redfish-Interop-Validator
