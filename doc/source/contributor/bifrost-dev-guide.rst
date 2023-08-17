=====================================
Bifrost Development Environment Guide
=====================================

Bifrost is a project that deploys and operates Ironic using ansible. It is
generally used standalone, without many other services running alongside. This
makes it a good choice for a quick development environment for Ironic features
that may not interact with other OpenStack services, even if you aren't
developing against bifrost directly

Bifrost maintains it's own documentation on
`building a test environment with bifrost <https://docs.openstack.org/bifrost/latest/contributor/testenv.html>`_.

The testenv provided is ideal for quickly testing API changes in Ironic or
features for client libraries. It is not the best choice for changes that
interact with one or more OpenStack services or which require tempest testing.
