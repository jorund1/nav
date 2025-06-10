======================================
Usage and notes for isc_dhcpd_graphite
======================================

This script needs python3.

For arguments, try::

        isc_dhcpd_graphite.py --help

The script runs ``dhcpd_pool`` (full path given with -C) with the flag
``-f j`` to make it emit json.

Building the prefix
===================

The dotted-path that graphite uses to store data for each pool is controlled by
the prefix argument to the script (-p), the server-name argument to the script
(-sn) and the name of the pool; if the pool is configured within a
shared-network in the dhcpd-pools config-file, the name of the pool is the same
as the name of the shared-network. Otherwise, the name of the pool is a
concatenation of its start-address, a hyphen, and its end-address.

* The prefix (-p) defaults to "nav".
* The server-name (-sn) defaults to the hostname of the machine running this script.

If ``-p`` is "nav", ``-sn`` is not set and a pool is configured within a
shared-network called "foo" in the dhcpd-pools config-file, the resulting
graphite path that specifies the the pool's amount of assigned (leased-out)
addresses is
``nav.dhcp.pools.<local-hostname>.foo.<pool-start>.<pool-end>.assigned``.

If the pool above were to be configured outside any shared-network in the
dhcpd-pools config-file, the resulting graphite path would instead have been
``nav.dhcp.pools.<local-hostname>.<pool-start>-<pool-end>.<pool-start>.<pool-end>.assigned``.
