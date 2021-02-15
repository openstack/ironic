===================================
Role Based Access Control - Testing
===================================

.. todo: This entire file is being added in to provide context for
   reviewers so we can keep in-line comments to the necessary points
   in the yaml files. It *IS* written with a forward awareness of the
   later patches, but it is also broad in nature attempting to provide
   context to aid in review.

The Role Based Access control testing is a minor departure from the Ironic
standard pattern of entirely python based unit testing. In part this was done
for purposes of speed and to keep the declaration of the test context.

This also lended itself to be very useful due to the nature of A/B testing
which is requried to properly migrate the Ironic project from a project
scoped universe where an ``admin project`` is utilized as the authenticating
factor coupled with two custom roles, ``baremetal_admin``, and
``baremetal_observer``.

As a contributor looking back after getting a over a thousand additional tests
in place using this method, it definitely helped the speed at which these
were created, and then ported to support additional.

How these tests work
====================

These tests execute API calls through the API layer, using the appropriate
verb and header, which settings to prevent the ``keystonemiddleware`` from
intercepting and replacing the headers we're passing. Ultimately this is a
feature, and it helps quite a bit.

The second aspect of how this works is we're mocking the conductor RPC
``get_topic_for`` and ``get_random_topic_for`` methods. These calls raise
Temporary Unavailable, since trying to execute the entire interaction into
the conductor is moderately pointless because all policy enforement is
located with-in the API layer.

At the same time wiring everything up to go from API to conductor code and
back would have been a heavier lift. As such, the tests largely look for
one of the following error codes.

* 200 - Got the item from the API - This is an database driven interaction.
* 201 - Created - This is databaes driven interaction. These are rare.
* 204 - Accepted - This is a database driven interaction. These are rare.
* 403 - Forbidden - This tells us the policy worked as expected where
        access was denied.
* 404 - NotFound - This is typically when objects were not found. Before
        Ironic becomes scope aware, these are generally only in the drivers
        API endpoint's behavior. In System scope aware Project scoped
        configuration, i.e. later RBAC tests, this will become the dominant
        response for project scoped users as responding with a 403 if they
        could be an owner or lessee would provide insight into the existence
        of a node.
* 503 - Service Unavailable - In the context of our tests, we expect this
        when a request *has* been successfully authenticated and would have
        been sent along to the conductor.

How to make changes or review these tests?
==========================================

The tests cycle through the various endpoints, and repeating patterns
are clearly visible. Typically this means a given endpoint is cycled
through with the same basic test using slightly different parameters
such as different authentication parameters. When it comes to system
scope aware tests supporting node ``owners`` and ``lessee``, these
tests will cycle a little more with slightly different attributes
as the operation is not general against a shared common node, but
different nodes.

Some tests will test body contents, or attributes. some will validate
the number of records returned. This is important later with ``owner``
and ``lessee`` having slightly different views of the universe.

Some general rules apply

* Admins can do things, at least as far as their scope or rights apply.
  Remember: owner and lessee admins are closer to System scoped Admin Members.
* Members can do some things, but not everything
* Readers can always read, but as we get into sensitive data later on
  such as fields containing infrastucture internal addresses, these values
  will become hidden and additional tests will examine this.
* Third party, or external/other Admins will find nothing but sadness
  in empty lists, 403, 404, or even 500 errors.

What is/will be tested?
=======================

The idea is to in essence test as much as possible, however as these
tests Role Based Access Control related capabilities will come in a
series of phases, styles vary a little.

The first phase is ``"legacy"``. In essence these are partially
programatically generated and then human reviewed and values populated
with expected values.

The second phase is remarkably similar to ``legacy``. It is the safety net
where we execute the ``legacy`` tests with the updated ``oslo.policy``
configuration to help enforce scopes. These tests will intentionally begin to
fail in phase three.

The third phase is the implementation of System scope awareness for the
API. In this process, as various portions of the API are made system scope
aware. The ``legacy`` tests are marked as ``deprecated`` which signals to
the second phase test sequences that they are **expected** to fail. New
``system scoped`` tests are also implemented which are matched up by name
to the ``legacy`` tests. The major difference being some header values,
and a user with a ``member`` role in the ``system`` scope now has some
rights.

The forth phase, is implementaiton of ``owner`` and ``lessee`` aware
project scoping. The testing approach is similar, however it is much more of
a "shotgun" approach. We test what we know should work, and what know should
not work, but we do not have redundant testing for each role as ``admin``
users are also ``members``, and since the policy rules are designed around
thresholds of access, it just made no sense to run the same test for admin
and members, where member was the threshold. These thresholds will vary with
the proposed default policy. The forth scope also tests a third party external
admin as a negative test to ensure that we are also denying access to
resources appropriately.
