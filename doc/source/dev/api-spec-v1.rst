=========================
Ironic REST API v1.0 Spec
=========================

Contents
#########

- `General Concepts`_
- `Resource Definitions`_
- `Areas To Be Defined`_


General Concepts
#################

- `Links and Relationships`_
- Queries_
- `State Transitions`_
- `Vendor MIME Types`_
- Pagination_
- SubResource_
- Security_
- Versioning_
- `Updating Resources`_

Links and Relationships
------------------------

Relationships between top level resources are represented as links.  Links take
the form similar to that of the AtomPub standard and include a 'rel' and 'href'
element.  For one to many relations between resources, a link will be provided
that points to a collection of resources that satisfies the many side of the
relationship.

All collections, top level resources and sub resources have links that provide
a URL to itself and a bookmarked version of itself.  These links are defined
via "rel": "self" and "rel": "bookmark".

Queries
-------

Queries are allowed on collections that allow some filtering of the resources
returned in the collection document.

A simple example::

  /nodes/?arch=x86_64

State Transitions
------------------

Some resources have states.  A node is a typical example.  It may have various
possible states, such as ON, OFF, DEPLOYED, REBOOTING and so on.  States are
governed internally via a finite state machine.

You can change the state of a resource by updating its state SubResource_ and
setting the "current" field to one of the states codes shown in
"available_states" field.

This is often achieved in other APIs using HTTP query paramter, such as
"node/1/?actions=reboot".  This is adding behaviour to the underlying protocol
which should not be done in a REST API.
See: https://code.google.com/p/implementing-rest/wiki/RESTAPIRules

Vendor MIME Types
------------------

The initial vendor MIME types will represent format and version.  i.e. v1 and
json.  Future MIME types can be used to get better performance from the API.
For example, we could define a new MIME type vnd.openstack.ironic.min,v1 that
could be minimize document size or vnd.openstack.ironic.max,v1 that could be
used to return larger documents but minimize the number of HTTP requests need
to perform some action.

Pagination
-----------

Pagination is designed to return a subset of the larger collection
while providing a link that can be used to retrieve the next. You should
always check for the presence of a 'next' link and use it as the URI in
a subsequent HTTP GET request. You should follow this pattern until the
'next' link is no longer provided.

Collections also take query parameters that serve to filter the returned
list. It is important to note that the 'next' link will preserve any
query parameters you send in your initial request. The following list
details these query parameters:

* ``sort_key=KEY``

  Results will be ordered by the specified resource attribute
  ``KEY``. Accepted values that are present in all resources are: ``id``
  (default), ``created_at`` and ``updated_at``.

* ``sort_dir=DIR``

  Results will be sorted in the direction ``DIR``. Accepted values are
  ``asc`` (default) for ascending or ``desc`` for descending.

* ``marker=UUID``

  A resource ``UUID`` marker may be specified. When present, only items
  which occur after the identifier ``UUID`` will be listed, ie the items
  which have a `sort_key` later than that of the marker ``UUID`` in the
  `sort_dir` direction.

* ``limit=LIMIT``

  The maximum number of results returned will not exceed ``LIMIT``.

Example::

  /nodes?limit=100&marker=1cd5bef6-b2e0-4296-a88f-d98a6c5486f2

SubResource
------------

Sub Resources are resources that only exist within another top level resource.
Sub resources are not neccessarily useful on their own, but are defined so that
smaller parts of resource descriptions can be viewed and edited independently
of the resource itself.


For example, if a client wanted to change the deployment configuration for a
specific node, the client could update the deployment part of the node's
DriverConfiguration_ with the new parameters directly at:
/nodes/1/driver_configuration/deploy

Security
---------

To be Defined

Versioning
-----------

The API uses 2 ways of specifying versions through the use of either a vendor
MIME type, specified in the version resource and also through a URL that
contains the version ID.  The API has a default version as specified in the
API resource.  Failure to specify a version specific MIME type or a URL encoded
with a particular version will result the API will assume the use of the
default version.  When both URL version and MIME type are specified and
conflicting the URL version takes precedence.

Updating Resources
-------------------

The PATCH HTTP method is used to update a resource in the API. PATCH
allows clients to do partial updates to a resource, sending only the
attributes requiring modification. Operations supported are "remove",
"add" and "replace", multiple operations can be combined in a single
request.

The request body must conform to the 'application/json-patch+json'
media type (RFC 6902) and response body will represent the updated
resource entity.

Example::

    PATCH /chassis/4505e16b-47d6-424c-ae78-e0ef1b600700

    [
     {"path": "/description", "value": "new description", "op": "replace"},
     {"path": "/extra/foo", "value": "bar", "op": "add"},
     {"path": "/extra/noop", "op": "remove"}
    ]

Different types of attributes that exists in the resource will be either
removed, added or replaced according to the following rules:

Singular attributes
^^^^^^^^^^^^^^^^^^^^

An "add" or "replace" operation replaces the value of an existing
attribute with a new value. Adding new attributes to the root document
of the resource is not allowed.

The "remove" operation resets the target attribute to its default value.

Example, replacing an attribute::

    PATCH /chassis/4505e16b-47d6-424c-ae78-e0ef1b600700

    [
     {"path": "/description", "value": "new description", "op": "replace"}
    ]


Example, removing an attribute::

    PATCH /chassis/4505e16b-47d6-424c-ae78-e0ef1b600700

    [
     {"path": "/description", "op": "remove"}
    ]

*Note: This operation will not remove the description attribute from
the document but instead will reset it to its default value.*

Multi-valued attributes
^^^^^^^^^^^^^^^^^^^^^^^^

In case of an "add" operation the attribute is added to the collection
if the it does not exist and merged if a matching attribute is present.

The "remove" operation removes the target attribute from the collection.

The "replace" operation replaces the value at the target attribute with
a new value.

Example, adding an attribute to the collection::

    PATCH /chassis/4505e16b-47d6-424c-ae78-e0ef1b600700

    [
     {"path": "/extra/foo", "value": "bar", "op": "add"}
    ]


Example, removing an attribute from the collection::

    PATCH /chassis/4505e16b-47d6-424c-ae78-e0ef1b600700

    [
     {"path": "/extra/foo", "op": "remove"}
    ]


Example, removing **all** attributes from the collection::

    PATCH /chassis/4505e16b-47d6-424c-ae78-e0ef1b600700

    [
     {"path": "/extra", "op": "remove"}
    ]


Resource Definitions
#####################

Top Level Resources
--------------------

- API_
- Version_
- Node_
- Chassis_
- Port_
- Driver_
- Image_

Sub Resources
---------------

- DriverConfiguration_
- MetaData_
- State_

API
----

An API resource is returned at the root URL (or entry point) to the API.  From
here all versions and subsequent resources are discoverable.

Usage
^^^^^^

=======  =============  =====================
Verb     Path           Response
=======  =============  =====================
GET      /              Get the API resource
=======  =============  =====================


Fields
^^^^^^^

type
    The type of this resource, i.e. api
name
    The name of the API, e,g, openstack.ironic.api
description
    Some information about this API
versions
    A link to all the versions available in this API
default_version
    A link to the default version used when no version is specified in the URL
    or in the content-type

Example
^^^^^^^^

JSON structure of an API::

  {
    "type": "api",
    "name": "openstack ironic API",
    "description": "foobar",
    "versions": {
      "links": [{
          "rel": "self",
          "href": "http://localhost:8080/api/versions/"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/api/versions"
        }
      ]
    },
    "default_version": {
      "id": "1.0",
      "type": "version",
      "links": [{
          "rel": "self",
          "href": "http://localhost:8080/api/versions/1.0/"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/api/versions/1.0/"
        }
      ]
    }
  }

Version
--------

A version is essentially an API version and contains information on how to use
this version as well as links to documentation, schemas and the available
content-types that are supported.

Usage
^^^^^^

=======  ===============  =====================
Verb     Path             Response
=======  ===============  =====================
GET      /versions        Returns a list of versions
GET      /versions/<id>   Receive a specific version
=======  ===============  =====================

Fields
^^^^^^^

id
    The ID of the version, also acts as the release number
type
    The type of this resource, i.e. version
media_types
    An array of supported media types for this version
description
    Some information about this API
links
    Contains links that point to a specific URL for this version (as an
    alternate to using MIME types) as well as links to documentation and
    schemas

The version also contains links to all of the top level resources available in
this version of the API.  Example below shows chassis, ports, drivers and
nodes.  Different versions may have more or less resources.

Example
^^^^^^^^

JSON structure of a Version::

  {
    "id": "1",
    "type": "version",
    "media_types": [{
        "base": "application/json",
        "type": "application/vnd.openstack.ironic.v1+json"
      }
    ],
    "links": [{
        "rel": "self",
        "href": "http://localhost:8080/v1/"
      }, {
        "rel": "describedby",
        "type": "application/pdf",
        "href": "http://docs.openstack.ironic.com/api/v1.pdf"
      }, {
        "rel": "describedby",
        "type": "application/vnd.sun.wadl+xml",
        "href": "http://docs.openstack.ironic.com/api/v1/application.wadl"
      }
    ],
    "chassis": {
      "links": [{
          "rel": "self",
          "href": "http://localhost:8080/v1.0/chassis"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/chassis"
        }
      ]
    },
    "ports": {
      "links": [{
          "rel": "self",
          "href": "http://localhost:8080/v1.0/ports"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/ports"
        }
      ]
    },
    "drivers": {
      "links": [{
          "rel": "self",
          "href": "http://localhost:8080/v1.0/drivers"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/drivers"
        }
      ]
    }
    "nodes": {
      "links": [{
          "rel": "self",
          "href": "http://localhost:8080/v1.0/nodes"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/nodes"
        }
      ]
    }
  }

Node
-----

Usage
^^^^^^

=======  =============  ==========
Verb     Path           Response
=======  =============  ==========
GET      /nodes         List nodes
GET      /nodes/detail  Lists all details for all nodes
GET      /nodes/<id>    Retrieve a specific node
POST     /nodes         Create a new node
PATCH    /nodes/<id>    Update a node
DELETE   /nodes/<id>    Delete node and all associated ports
=======  =============  ==========


Fields
^^^^^^^

id
    Unique ID for this node
type
    The type of this resource, i.e. node
arch
    The node CPU architecture
cpus
    The number of available CPUs
disk
    The amount of available storage space in GB
ram
    The amount of available RAM  in MB
meta_data
    This node's meta data see: MetaData_
image
    A reference to this node's current image see: Image_
state
    This node's state, see State_
chassis
    The chassis this node belongs to see: Chassis_
ports
    A list of available ports for this node see: Port_
driver_configuration
    This node's driver configuration see: DriverConfiguration_

Example
^^^^^^^^
JSON structure of a node::


  {
    "id": "fake-node-id",
    "type": "node",
    "arch": "x86_64",
    "cpus": 8,
    "disk": 1024,
    "ram": 4096,
    "meta_data": {
      "data_centre": "us.east.1",
      "function": "high_speed_cpu",
      "links": [{
          "rel": "self",
          "href": "http://localhost:8080/v1.0/nodes/1/meta-data"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/nodes/1/meta-data"
        }
      ]
    },
    "image": {
      "id": "fake-image-id",
      "links": [{
          "rel": "self",
          "href": "http://localhost:8080/images/1"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/images/1"
        }, {
          "rel": "alternate",
          "href": "http://glance.api..."
        }
      ]
    },
    "state": {
      "current": "OFF",
      "available_states": ["DEPLOYED"],
      "started": "2013 - 05 - 20 12: 34: 56",
      "links ": [{
          "rel ": "self ",
          "href ": "http: //localhost:8080/v1/nodes/1/state"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/ndoes/1/state"
        }
      ]
    },
    "ports": {
      "links": [{
          "rel": "self",
          "href": "http://localhost:8080/v1/nodes/1/ports"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/nodes/1/ports"
        }
      ]
    },
    "driver_configuration": {
      "type": "driver_configuration",
      "driver": {
        "links": [{
            "rel": "self",
            "href": "http://localhost:8080/v1/drivers/1"
          }, {
            "rel": "bookmark",
            "href": "http://localhost:8080/drivers/1"
          }
        ]
      },
      "parameters": {
        "ipmi_username": "admin",
        "ipmi_password": "password",
        "image_source": "glance://image-uuid",
        "deploy_image_source": "glance://deploy-image-uuid",
        "links": [{
            "rel": "self",
            "href": "http://localhost:8080/v1.0/nodes/1/driver_configuration/parameters"
          }, {
            "rel": "bookmark",
            "href": "http://localhost:8080/nodes/1/driver_configuration/control/parameters"
          }
        ]
      }
    }
  }

Chassis
--------

Usage
^^^^^^

=======    ===============  ==========
Verb       Path             Response
=======    ===============  ==========
GET        /chassis         List chassis
GET        /chassis/detail  Lists all details for all chassis
GET        /chassis/<id>    Retrieve a specific chassis
POST       /chassis         Create a new chassis
PATCH      /chassis/<id>    Update a chassis
DELETE     /chassis/<id>    Delete chassis and remove all associations between
                            nodes
=======    ===============  ==========


Fields
^^^^^^^

uuid
    Unique UUID for this chassis
description
    A user defined description
extra
    This chassis's meta data see: MetaData_
nodes
    A link to a collection of nodes associated with this chassis see: Node_
links
    A list containing a self link and associated chassis links see: `Links and Relationships`_

Example
^^^^^^^^

JSON structure of a chassis::

  {
      "uuid": "64ec49cf-8881-4ceb-ba9e-cf9d67b63e70",
      "description": "chassis1-datacenter1",
      "extra": {
          "foo": "bar",
      },
      "links": [
          {
              "href": "http://0.0.0.0:6385/v1/chassis/64ec49cf-8881-4ceb-ba9e-cf9d67b63e70",
              "rel": "self"
          },
          {
              "href": "http://0.0.0.0:6385/v1/chassis/64ec49cf-8881-4ceb-ba9e-cf9d67b63e70",
              "rel": "bookmark"
          }
      ],
      "nodes": [
          {
              "href": "http://0.0.0.0:6385/v1/chassis/64ec49cf-8881-4ceb-ba9e-cf9d67b63e70/nodes",
              "rel": "self"
          },
          {
              "href": "http://0.0.0.0:6385/chassis/64ec49cf-8881-4ceb-ba9e-cf9d67b63e70/nodes",
              "rel": "bookmark"
          }
      ],
  }

Port
-----

Usage
^^^^^^

=======  =============  ==========
Verb     Path           Response
=======  =============  ==========
GET      /ports         List ports
GET      /ports/detail  Lists all details for all ports
GET      /ports/<id>    Retrieve a specific port
POST     /ports         Create a new port
PATCH    /ports/<id>    Update a port
DELETE   /ports/<id>    Delete port and remove all associations between nodes
=======  =============  ==========


Fields
^^^^^^^

id
    Unique ID for this port
type
    The type of this resource, i.e. port
address
    MAC Address for this port
meta_data
    This port's meta data see: MetaData_
nodes
    A link to the node this port belongs to see: Node_

Example
^^^^^^^^

JSON structure of a port::

  {
    "id": "fake-port-uuid",
    "type": "port",
    "address": "01:23:45:67:89:0A",
    "meta-data": {
      "foo": "bar",
      "links": [{
          "rel": "self",
          "href": "http://localhost:8080/v1.0/ports/1/meta-data"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/ports/1/meta-data"
        }
      ]
    },
    "node": {
      "links": [{
          "rel": "self",
          "href": "http://localhost:8080/v1.0/ports/1/node"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/ports/1/node"
        }
      ]
    }
  }


Driver
-------

Usage
^^^^^^

=======  =============  ==========
Verb     Path           Response
=======  =============  ==========
GET      /drivers       List drivers
GET      /drivers/<id>  Retrieve a specific driver
=======  =============  ==========

Fields
^^^^^^^

id
    Unique ID for this driver
type
    The type of this resource, i.e. driver
name
    Name of this driver
function
    The function this driver performs, see: DriverFunctions_
meta_data
    This driver's meta data see: MetaData_
required_fields
    An array containing the required fields for this driver
optional_fields
    An array containing optional fields for this driver

Example Driver
^^^^^^^^^^^^^^^

JSON structure of a driver::

  {
    "id": "ipmi_pxe",
    "type": "driver",
    "name": "ipmi_pxe",
    "description": "Uses pxe for booting and impi for power management",
    "meta-data": {
      "foo": "bar",
      "links": [{
          "rel": "self",
          "href": "http://localhost:8080/v1.0/ports/1/meta-data"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/ports/1/meta-data"
        }
      ]
    },
    "required_fields": [
      "ipmi_address",
      "ipmi_password",
      "ipmi_username",
      "image_source",
      "deploy_image_source",
    ],
    "optional_fields": [
      "ipmi_terminal_port",
    ],
    "links": [{
        "rel": "self",
        "href": "http://localhost:8080/v1/drivers/"
      }, {
        "rel": "bookmark",
        "href": "http://localhost:8080/drivers/1"
      }
    ]
  }

Image
-------

An Image resource.  This represents a disk image used for booting a Node_.
Images are not stored within Ironic, instead images are stored in glance and
can be accessed via this API.

Usage
^^^^^^

=======  =============  ==========
Verb     Path           Response
=======  =============  ==========
GET      /images        List images
GET      /images/<id>   Retrieve a specific image
=======  =============  ==========

Fields
^^^^^^^

id
    Unique ID for this port
type
    The type of this resource, i.e. image
name
    Name of this image
status
    Status of the image
visibility
    Whether or not this is publicly visible
size
    Size of this image in MB
Checksum
    MD5 Checksum of the image
Tags
    Tags associated with this image

Example
^^^^^^^^

JSON structure of an image::

  {
    "id": "da3b75d9-3f4a-40e7-8a2c-bfab23927dea",
    "type": "image"
    "name": "cirros-0.3.0-x86_64-uec-ramdisk",
    "status": "active",
    "visibility": "public",
    "size": 2254249,
    "checksum": "2cec138d7dae2aa59038ef8c9aec2390",
    "tags": ["ping", "pong"],
    "created_at": "2012-08-10T19:23:50Z",
    "updated_at": "2012-08-10T19:23:50Z",
    "links": [{
        "rel": "self",
        "href": "http://localhost:8080/v1/images/"
      }, {
        "rel": "bookmark",
        "href": "http://localhost:8080/images/1"
      }, {
        "rel": "alternate",
        "href": "http://openstack.glance.org/v2/images/da3b75d9-3f4a-40e7-8a2c-bfab23927dea"
      }, {
        "rel": "file",
        "href": "http://openstack.glance.org/v2/images/da3b75d9-3f4a-40e7-8a2c-bfab23927dea/file"
      }
    ]
  }

DriverConfiguration
------------------------

The Configuration is a sub resource (see: SubResource_) that
contains information about how to manage a particular node.
This resource makes up part of the node resource description and can only be
accessed from within a node URL structure.  For example:
/nodes/1/driver_configuration.  The DriverConfiguration essentially
defines the driver setup.

An empty driver configuration resource will be created upon node creation.
Therefore only PUT and GET are defined on DriverConfiguration resources.

The Parameters resource is not introspected by Ironic; they are passed directly
to the respective drivers. Each driver defines a set of Required and Optional
fields, which are validated when the resource is set to a non-empty value.
Supplying partial or invalid data will result in an error and no data will be
saved. PUT an empty resource, such as '{}' to /nodes/1/driver_configuration
to erase the existing data.


driver configuration Usage:
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

=======  ==================================  ================================
Verb     Path                                Response
=======  ==================================  ================================
GET      /nodes/1/driver_configuration       Retrieve a node's driver
                                             configuration
PUT      /nodes/1/driver_configuration       Update a node's driver
                                             configuration
=======  ==================================  ================================

driver configuration / Parameters Usage:
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

======  =============================================  ==================
Verb     Path                                          Response
======  =============================================  ==================
GET     /nodes/1/driver_configuration/parameters       Retrieve a node's
                                                       driver parameters
PUT     /nodes/1/driver_configuration/parameters       Update a node's
                                                       driver parameters
======  =============================================  ==================


Fields
^^^^^^^

type
    The type of this resource, i.e. driver_configuration, deployment,
    control, parameters
driver
    Link to the driver resource for a deployment or control sub resource
paramters
    The parameters sub resource responsible for setting the driver paramters.
    The required and optional parameters are specified on the driver resource.
    see: Driver_

Example
^^^^^^^^

JSON structure of a driver_configuration::

  {
    "type": "driver_configuration",
    "driver": {
      "links": [{
          "rel": "self",
          "href": "http://localhost:8080/v1/drivers/1"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/drivers/1"
        }
      ]
    },
    "parameters": {
      "ipmi_username": "admin",
      "ipmi_password": "password",
      "image_source": "glance://image-uuid",
      "deploy_image_source": "glance://deploy-image-uuid",
      "links": [{
          "rel": "self",
          "href": "http://localhost:8080/v1.0/nodes/1/driver_configuration/parameters"
        }, {
          "rel": "bookmark",
          "href": "http://localhost:8080/nodes/1/driver_configuration/control/parameters"
        }
      ]
    }
  }

State
------

States are sub resources (see: SubResource_) that represents the state of
either a node.  The state of the node is governed by an internal state machine.
You can get the next available state code from the "available_states" array.
To change the state of the node simply set the "current" field to one of the
available states.

For example::

  PUT
  {
    ...
    "current": "DEPLOYED"
    ...
  }


Usage:
^^^^^^

=======  ==================================  ===========================
Verb     Path                                Response
=======  ==================================  ===========================
GET      /nodes/1/state                      Retrieve a node's state
PUT      /nodes/1/state                      Update a node's state
=======  ==================================  ===========================

Fields
^^^^^^^

current
    The current state (code) that this resource resides in
available_states
    An array of available states this parent resource is able to transition to
    from the current state
started
    The time and date the resource entered the current state

Example
^^^^^^^^

JSON structure of a state::

  {
    "current": "OFF",
    "available_states": ["DEPLOYED"],
    "started": "2013 - 05 - 20 12: 34: 56",
    "links ": [{
        "rel ": "self ",
        "href ": "http: //localhost:8080/v1/nodes/1/state"
      }, {
        "rel": "bookmark",
        "href": "http://localhost:8080/nodes/1/state"
      }
    ]
  }

MetaData
---------

MetaData is an arbitrary set of key value pairs that a client can set on a
resource which can be retrieved later. Ironic will not introspect the metadata
and does not support querying on individual keys.

Usage:
^^^^^^

=======  ===================  ==========
Verb     Path                  Response
=======  ===================  ==========
GET      /nodes/1/meta_data   Retrieve a node's meta data
PUT      /nodes/1/meta_data   Update a node's meta data
=======  ===================  ==========

Fields
^^^^^^^

Fields for this resource are arbitrary.

Example
^^^^^^^^

JSON structure of a meta_data::

  {
    "foo": "bar"
      "bar": "foo"
  }

VendorPassthru
---------

VendorPassthru allow vendors to expose a custom functionality in
the Ironic API. Ironic will merely relay the message from here to the
appropriate driver (see: Driver_), no introspection will be made in the
message body.

Usage:
^^^^^^

=======  ==================================  ==========================
Verb     Path                                Response
=======  ==================================  ==========================
POST      /nodes/1/vendor_passthru/<method>  Invoke a specific <method>
=======  ==================================  ==========================

Example
^^^^^^^^

Invoking "custom_method"::

  POST /nodes/1/vendor_passthru/custom_method
  {
    ...
    "foo": "bar",
    ...
  }

Areas To Be Defined
####################

- Discoverability of Driver State Change Parameters
- State Change in Drivers
- Advanced Queries
- Support for parallel driver actions
- Error Codes
- Security
