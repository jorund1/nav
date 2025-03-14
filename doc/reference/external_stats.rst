=========================
External stats (Kea DHCP)
=========================

In some cases, it is desireable to retrieve stats from endpoints that isn't necessarily
part of the network managed by NAV and send it to Graphite so that it
nevertheless can be used in graphs and reports in NAV. A typical example is data
fetched from an external API server.

The `externalstats` cron job periodically reads the `externalstats.conf` file
for endpoints and attempts to fetch stats from these endpoints. All endpoints
must have configured a type and a url. Other options that can be configured for
an endpoint depend on its type.

The kind of stats that are are fetched, how they are fetched from the endpoint, how
they are stored in Graphite, and how these stats are viewed in NAV, depends
on the configured type and thus varies among endpoints .


The Configuration File
======================


.. code-block:: ini
   :caption: externalstats.conf

   [endpoint_myname1]
   type=foo
   url=https://example.org/
   type_dependent_option_1=bar
   type_dependent_option_2=baz



One section in `externalstats.conf` (e.g. ``[endpoint_myname1]`` above) configures one specific endpoint, given that the
section name (in brackets) starts with 'endpoint\_'. Each endpoint section must
contain the 'type' option and the 'url' option.  Other options are
type-dependent.


Kea DHCPv4 Endpoints
====================

For each endpoint configured with type `kea-dhcp4`, the following stats are fetched.

* Per subnet total amount of DHCP-managed IPv4 addresses. Stored in Graphite as ``nav.dhcp.subnet.<subnetprefix>.total``.

* Per subnet total amount of DHCP-assigned IPv4 addresses. Stored in Graphite as ``nav.dhcp.subnet.<subnetprefix>.assigned``.

* Per subnet total amount of expired DHCP-assigned IPv4 addresses not yet reclaimed ("declined" addresses). Stored in graphite as ``nav.dhcp.subnet.<subnetprefix>.declined``.


These stats will be displayed in a VLAN's page if that VLAN contains one or more subnets that
stats exist for.

For NAV to be able to fetch these stats, A Kea API endpoint for
the Kea DHCPv4 server must set have been up. A plain `Kea Control Agent
<https://kea.readthedocs.io/en/kea-2.7.6/arm/agent.html>`_ will suffice (no
additional Kea API "hook libraries" are required).

.. note::

   NAV doesn't make use of API services supplied by the optional `libdhcp_stat_cmds Kea hook library
   <https://kea.readthedocs.io/en/kea-2.7.6/arm/hooks.html#libdhcp-stat-cmds-so-statistics-commands-for-supplemental-lease-statistics>`_.
   This library is recommended for consistent stats
   when multiple Kea DHCPv4 servers share the same lease database. A future NAV
   release may add support for utilizing API services from this library if the
   API has the library configured.


Below is an example of a kea-dhcp4 endpoint configuration. All
available options are specified.

.. code-block:: ini
   :caption: externalstats.conf

   [endpoint_myname2]
   type=kea-dhcp4
   url=https://example.org:8080/
   http_basic_username=nav
   http_basic_password=nav
   client_cert_path=/etc/client.cert
   client_cert_key_path=/etc/client.key

* ``[endpoint_example_2]`` specifies that this is an endpoint with name 'myname2'.
* ``type=kea-dhcp4`` specifies that the type of the endpoint is kea-dhcp4.
* ``url=https://example.org:8080/`` specifies that the url of the Kea API
  is ``https://example.org:8080/``.
* ``http_basic_username=nav`` and ``http_basic_password=nav``
  are optional options. When both of these options are set they specify that HTTP
  Basic Authentication should be used with the given username and password.
* ``client_cert_path`` gives the path to a client TLS certificate, and ``client_cert_key_path`` gives the path to the certificate's private key. These are optional options.
  When only ``client_cert_path`` is set, the certificate is assumed to have been combined with its private key into a single file.
  When both ``client_cert_path`` and ``client_cert_key_path`` is set, it is assumed that the private key exists in its own file specified by ``client_cert_key_path``. In both
  cases, NAV will use the certificate to authenticate itself with Kea.
