#
# Copyright (C) 2024 Sikt
#
# This file is part of Network Administration Visualized (NAV).
#
# NAV is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 3 as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.  You should have received a copy of the GNU General Public License
# along with NAV. If not, see <http://www.gnu.org/licenses/>.
#
"""
Fetch DHCP stats from Kea DHCP servers, using the Kea API
"""

from dataclasses import dataclass
from datetime import datetime
import time
from enum import IntEnum
from itertools import chain
import json
import logging
from typing import Optional
import re


from IPy import IP
from requests import RequestException, JSONDecodeError, Session

from nav.errors import GeneralException
from nav.metrics.templates import metric_path_for_subnet_dhcp

_logger = logging.getLogger(__name__)


@dataclass(order=True, frozen=True)
class _Pool:
    """
    A Kea DHCP configured pool
    """

    id: int
    name: str
    range_start: IP
    range_end: IP

    _cidr_pattern_kea = re.compile(r"\d+\.\d+\.\d+\.\d+/\d+")

    @classmethod
    def from_kea(cls, kea_pool: dict):
        match kea_pool:
            case {"pool": str(pool_range), "id": int(pool_id)}:
                if cls._cidr_pattern_kea.fullmatch(pool_range):
                    cidr = IP(pool_range)
                    return cls(pool_id, "abc", cidr.start, cidr.end)


@dataclass(order=True, frozen=True)
class _Subnet:
    """
    A Kea DHCP configured subnet
    """

    id: int
    prefix: IP
    pools: list[_Pool]


_Metric = tuple[str, tuple[int, int]]


class Client:
    """
    Fetches DHCP stats for each subnet managed by some Kea DHCP server by using
    the Kea API

    TODO: This client assumes no hooks have been installed. The lease-stats hook
          is required for reliable stats when multiple servers share the same lease
          database because the standard commands issue the cache, not the DB.
    """

    def __init__(
        self,
        url: str,
        dhcp_version: int = 4,
        http_basic_username: str = "",
        http_basic_password: str = "",
        client_cert_path: str = "",
        client_cert_key_path: str = "",
        timeout: int = 10,
    ):
        self._url: str = url
        self._dhcp_version: int = dhcp_version
        self._http_basic_user: str = http_basic_username
        self._http_basic_password: str = http_basic_password
        self._client_cert_path: str = client_cert_path
        self._client_key_path: str = client_cert_key_path
        self._timeout: int = timeout

        self._dhcp_config: Optional[dict] = None
        self._session: Optional[Session] = None

        if dhcp_version == 4:
            self._api_namings = (
                ("total", "total-addresses"),
                ("assigned", "assigned-addresses"),
                ("declined", "declined-addresses"),
            )
        else:
            raise ValueError(f"DHCPv{dhcp_version} is not supported")

    def fetch_stats(self) -> list[_Metric]:
        """
        Fetches and returns a list containing the most recent DHCP stats for
        each subnet + stat name combination.

        If the Kea API responds with an empty response to one or more of the
        requests for some stat(s), these stats will be missing in the returned
        list, but a list is still succesfully returned. Other errors while
        requesting stats will cause a fitting subclass of KeaException to be
        raised:

        * Communication errors (HTTP errors, JSON errors, access control errors,
          unexpected responses) causes KeaException to be raised.

        * A Kea API that doesn't support the bare-minimum set of commands this
          client needs for fetching stats, causes KeaUnsupported to be raised.
        """
        self._session = self._create_session()
        start_time = time.time()
        local_tz_offset = datetime.now().astimezone().utcoffset().total_seconds()
        start_time = start_time + local_tz_offset

        # config = self._fetch_config()
        # subnets = self._subnets_of_config(config)
        subnets = self._fetch_subnets()

        stats = []
        for subnet in subnets:
            for stat_name, api_naming in self._api_namings:
                value = self._fetch_stat_value(subnet, api_naming)
                if value is None:
                    continue
                path = metric_path_for_subnet_dhcp(subnet.prefix, stat_name)
                stats.append((path, (int(start_time), value)))

        # maybe_updated_config = self._fetch_config()
        # maybe_updated_subnets = self._subnets_of_config(maybe_updated_config)
        maybe_updated_subnets = self._fetch_subnets()
        if sorted(subnets) != sorted(maybe_updated_subnets):
            _logger.warning(
                "Server's subnet configuration was modified during fetching of DHCP "
                "stats. This may cause stats collected this run to be associated with "
                "wrong subnet."
            )

        self._session.close()
        self._session = None
        end_time = time.time()
        local_tz_offset = datetime.now().astimezone().utcoffset().total_seconds()
        end_time = end_time + local_tz_offset
        _logger.info(
            "Fetched %d stats(s) for %d subnet(s) in %.2f seconds from %s",
            len(stats),
            len(subnets),
            end_time - start_time,
            self._url,
        )
        return stats

    def _fetch_stat_value(self, subnet: _Subnet, api_stat_name: str) -> Optional[int]:
        """
        Return the most recent stat value recorded by the Kea DHCP server for
        the given subnet and stat name.
        """
        full_name = f"subnet[{subnet.id}].{api_stat_name}"
        try:
            response = self._send_query("statistic-get", name=full_name)
        except KeaEmpty:
            # This may occur if the subnet we query have been removed from the
            # DHCP server's configuration at time of request
            response = {}

        samples = response.get("arguments", {}).get(full_name, [])

        if len(samples) == 0:
            _logger.info(
                "No samples found when querying for '%s' in subnet '%s'",
                api_stat_name,
                subnet.prefix,
            )
            return None

        # The reference API consumer assumes the first sample is the most recent
        # See https://gitlab.isc.org/isc-projects/stork/-/blob/4193375c01e3ec0b3d862166e2329d76e686d16d/backend/server/apps/kea/rps.go#L223-227
        value, timestring = samples[0]
        return value

    def _fetch_config(self) -> dict:
        """
        Returns the current config of the Kea DHCP server that the Kea
        API serves.
        """
        if (
            self._dhcp_config is None
            or (dhcp_confighash := self._dhcp_config.get("hash", None)) is None
            or self._fetch_config_hash() != dhcp_confighash
        ):
            response = self._send_query("config-get")
            try:
                self._dhcp_config = response["arguments"][f"Dhcp{self._dhcp_version}"]
            except KeyError as err:
                raise KeaException(
                    "Unrecognizable response to a 'config-get' request"
                ) from err
        return self._dhcp_config or {}

    def _fetch_config_hash(self) -> Optional[str]:
        """
        Returns the hash of the current config of the Kea DHCP server
        that the Kea API serves.
        """
        try:
            return (
                self._send_query("config-hash-get")
                .get("arguments", {})
                .get("hash", None)
            )
        except KeaUnsupported as err:
            _logger.debug(str(err))
            return None

    def _send_query(self, command: str, **kwargs) -> dict:
        """
        Returns the API response from the Kea API to the
        query with command `command` instructed towards the Kea DHCP server.
        Additional keyword arguments to this function will be passed as
        arguments to the command.

        Communication errors (HTTP errors, JSON errors, access control errors,
        unrecognized json response formats) causes a KeaException to be
        raised. If possible, it is reraised from a more descriptive error such
        as an HTTPError.

        Valid Kea API responses that indicate a failure on the
        server-end causes a descriptive subclass of KeaException to be raised.
        """
        session = self._session or self._create_session()

        _logger.debug("Sending command '%s' to Kea API at %s", command, self._url)

        post_data = json.dumps(
            {
                "command": command,
                "arguments": {**kwargs},
                "service": [f"dhcp{self._dhcp_version}"],
            }
        )

        try:
            responses = session.post(
                self._url,
                data=post_data,
                timeout=self._timeout,
                headers={"Content-Type": "application/json"},
            )
            _logger.debug(
                "%s responded with 'HTTP %s: %s' to command '%s'",
                self._url,
                responses.status_code,
                responses.reason,
                command,
            )
            responses.raise_for_status()
            responses = responses.json()
        except JSONDecodeError as err:
            raise KeaException(
                "%s does not look like a Kea API endpoint; "
                "response to command '%s' was not valid JSON",
                self._url,
                command,
            ) from err
        except RequestException as err:
            raise KeaException(err.strerror) from err

        # Any valid response from Kea is a JSON list with one entry corresponding to the
        # response from either the dhcp4 or dhcp6 service we queried
        if not (
            isinstance(responses, list)
            and len(responses) == 1
            and isinstance(responses[0], dict)
            and "result" in responses[0]
        ):
            if (
                isinstance(responses, dict)
                and "result" in responses
                and "text" in responses
            ):
                # If the response is a JSON object it's a specific error message
                # See https://kea.readthedocs.io/en/kea-2.6.0/arm/ctrl-channel.html#control-agent-command-response-format
                raise KeaException(f"{responses['result']}: {responses['text']}")
            raise KeaException(
                "%s does not look like a Kea API; "
                "response JSON structured in an unknown way",
                self._url,
            )

        response = responses[0]
        status = response["result"]
        description = response.get("text", "(no description)")

        _logger.debug(
            "Response from %s to command '%s' was '%s: %s'",
            self._url,
            command,
            status,
            description,
        )

        if status == _KeaStatus.SUCCESS:
            return response
        elif status == _KeaStatus.UNSUPPORTED:
            raise KeaUnsupported
        elif status == _KeaStatus.EMPTY:
            raise KeaEmpty
        elif status == _KeaStatus.ERROR:
            raise KeaError
        elif status == _KeaStatus.CONFLICT:
            raise KeaConflict
        raise KeaException("Unkown response status")

    def _create_session(self) -> Session:
        """
        Creates and returns a HTTP session for use with recurring HTTP requests
        in the requests package
        """
        _logger.debug("Creating new HTTP session for use with Kea API at %s", self._url)

        session = Session()

        https = self._url.startswith("https://")

        if self._http_basic_user and self._http_basic_password:
            _logger.debug("Using HTTP Basic Authentication")
            if not https:
                _logger.warning("Using HTTP Basic Authentication without HTTPS")
            session.auth = (self._http_basic_user, self._http_basic_password)
        else:
            _logger.debug("Not using HTTP Basic Authentication")

        if self._client_cert_path:
            _logger.debug("Using client certificate authentication")
            _logger.debug("Certificate path: '%s'", self._client_cert_path)
            if not https:
                raise ValueError("HTTPS is required to use client certificates")
            if self._client_key_path:
                _logger.debug("Certificate key path: '%s'", self._client_key_path)
                session.cert = (self._client_cert_path, self._client_key_path)
            else:
                session.cert = self._client_cert_path
        else:
            _logger.debug("Not using client certificate authentication")

        return session

    def _fetch_subnets(self) -> list[_Subnet]:
        """
        Returns a list containing one _Subnet(subnet-id, subnet-prefix) instance
        per subnet listed in the Kea DHCP configuration `config`.
        """
        subnets: list[_Subnet] = []
        subnetkey = f"subnet{self._dhcp_version}"

        config = self._fetch_config()

        for subnet in chain.from_iterable(
            [config.get(subnetkey, [])]
            + [
                network.get(subnetkey, [])
                for network in config.get("shared-networks", [])
            ]
        ):
            subnet_id = subnet.get("id", None)
            netprefix = subnet.get("subnet", None)
            if subnet_id is None or netprefix is None:
                _logger.warning(
                    "id and/or prefix missing from a subnet's configuration"
                )
                continue
            subnets.append(
                _Subnet(subnet_id, IP(netprefix), list(self._iter_pools(subnet)))
            )

        return subnets

    def _iter_pools(self, subnet: dict):
        subnet_pools = subnet.get("pools", [])
        for pool in subnet_pools:
            yield _Pool.from_kea(pool)


class KeaException(GeneralException):
    """An unexpected error occurred when communicating with Kea"""


class KeaError(KeaException):
    """Kea failed during command processing"""


class KeaUnsupported(KeaException):
    """Unsupported command"""


class KeaEmpty(KeaException):
    """Requested resource not found"""


class KeaConflict(KeaException):
    """Kea failed to apply requested changes due to conflicts with its server state"""


class _KeaStatus(IntEnum):
    """Status of a response sent from a Kea API"""

    SUCCESS = 0
    ERROR = 1
    UNSUPPORTED = 2
    EMPTY = 3
    CONFLICT = 4
