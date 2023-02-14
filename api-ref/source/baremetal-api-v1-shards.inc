.. -*- rst -*-

======
Shards
======

This section describes an API endpoint returning the population of shards
among nodes in the Bare Metal Service. Shards are a way to group nodes in the
Bare Metal service. They are used by API clients to separate nodes into groups,
allowing horizontal scaling.

Shards are not directly added and removed from the Bare Metal service. Instead,
operators can configure a node into a given shard by setting the ``shard`` key
to any unique string value representing the shard.

.. note::
    The Bare Metal Service does not use shards directly. It instead relies on
    API clients and external services to use shards to group nodes into smaller
    areas of responsibility.


Shards
======

.. rest_method:: GET /v1/shards

.. versionadded:: 1.82

The ``/v1/shards`` endpoint exists to allow querying the distribution of nodes
between all defined shards.

Normal response codes: 200

Error response codes: 400 403 404

Request
-------

No request parameters are accepted by this endpoint.

Response
--------

Returns a list of shards and the count of nodes assigned to each. The
list is sorted by descending count.

.. rest_parameters:: parameters.yaml

    - name: shard_name
    - count: shard_count

Response Example
----------------

.. literalinclude:: samples/shards-list-response.json
   :language: javascript
