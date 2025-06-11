#
# Copyright (C) 2025 Sikt
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
from enum import IntEnum
from itertools import chain
import json
import logging
import time
from typing import Optional, Iterator, NewType

from IPy import IP
from requests import RequestException, JSONDecodeError, Session
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from nav.errors import CommunicationError, ConfigurationError
from nav.metrics.templates import metric_path_for_dhcp_pool


_logger = logging.getLogger(__name__)


@dataclass(order=True, frozen=True, kw_only=True)
class Pool:
    """A Kea DHCP configured address pool"""
    name: str
    range_start: IP
    range_end: IP
    subnet_id: int
    pool_id: int


GraphiteMetric = tuple[str, tuple[float, int]]


class Client:
    """
    Fetches DHCP stats for each address pool managed by some Kea DHCP server by using
    the Kea API. See 'Client.fetch_stats()'.

    Note: This client assumes no hooks have been installed into the Kea DHCP
          server. The 'lease-stats' hook is required for reliable stats when
          multiple servers share the same lease database because the standard
          commands issue the cache, not the DB. This client does not support the
          hook.
    """

    def __init__(
        self,
        name: str,
        url: str,
        dhcp_version: int = 4,
        http_basic_username: str = "",
        http_basic_password: str = "",
        client_cert_path: str = "",
        client_cert_key_path: str = "",
        user_context_poolname_key: str = "name",
        timeout: int = 5,
    ):
        self._name: str = name
        self._url: str = url
        self._dhcp_version: int = dhcp_version
        self._http_basic_user: str = http_basic_username
        self._http_basic_password: str = http_basic_password
        self._client_cert_path: str = client_cert_path
        self._client_key_path: str = client_cert_key_path
        self._user_context_poolname_key: str = user_context_poolname_key
        self._timeout: float = timeout

        self._dhcp_config: Optional[dict] = None
        self._session: Optional[Session] = None
        self._start_time: float = time.time()

        if dhcp_version == 4:
            self._api_namings = (
                ("total", "total-addresses"),
                ("assigned", "assigned-addresses"),
                ("declined", "declined-addresses"),
            )
        else:
            raise ValueError(f"DHCPv{dhcp_version} is not supported")


    def fetch_stats(self) -> list[GraphiteMetric]:
        """
        Fetches and returns a list containing the most recent stats for each
        DHCP address pool. The stats collected for each address pool are:

        * The total amount of addresses in that pool.

        * The amount of currently assigned (aka. leased) addresses in that pool.

        * The amount of declined addresses in that pool. That is, addresses in
          that pool that is erroneously used by unkown entities and therefore
          not available for assignment. The set of declined addresses is a
          subset of the set of assigned addresses.

        If the Kea API responds with an empty response to one or more of the
        requests for some stat(s), these stats will be missing in the returned
        list, but a list is still succesfully returned. Other errors during this
        call will cause a subclass of nav.errors.CommunicationError to be raised.
        """
        self._session = self._create_session()
        #TODO: remove local time stuff
        start_time = time.time()
        local_tz_offset = datetime.now().astimezone().utcoffset().total_seconds()
        start_time = start_time + local_tz_offset
        self._start_time = start_time

        pools = sorted(self._fetch_pools())

        stats = []
        for pool in pools:
            stats.extend(self._fetch_pool_stats(pool))

        maybe_updated_pools = sorted(self._fetch_pools())
        if pools != maybe_updated_pools:
            _logger.warning(
                "The DHCP server's address pool configuration was modified while stats "
                "were being fetched. This may cause stats collected during this run to "
                "be associated with wrong address pool."
            )

        self._session.close()
        self._session = None
        end_time = time.time()
        local_tz_offset = datetime.now().astimezone().utcoffset().total_seconds()
        end_time = end_time + local_tz_offset
        _logger.info(
            "Fetched %d stats(s) from %d pool(s) in %.2f seconds from %s",
            len(stats),
            len(pools),
            end_time - start_time,
            self._url,
        )
        return stats


    def _fetch_pools(self) -> Iterator[Pool]:
        """
        Returns one Pool instance per pool listed in the Kea DHCP server's
        configuration.
        """
        config = self._fetch_config()
        subnetkey = f"subnet{self._dhcp_version}"

        for subnet in chain.from_iterable(
            [config.get(subnetkey, [])]
            + [
                network.get(subnetkey, [])
                for network in config.get("shared-networks", [])
            ]
        ):
            yield from self._pools_of_subnet(subnet)


    def _fetch_pool_stats(self, pool: Pool) -> Iterator[GraphiteMetric]:
        for stat_name, api_naming in self._api_namings:
            value = self._fetch_pool_stat_value(pool, api_naming)
            if value is None:
                continue
            path = metric_path_for_dhcp_pool(
                self._name,
                pool.name,
                pool.range_start,
                pool.range_end,
                stat_name
            )
            yield (path, (self._start_time, value))


    def _fetch_pool_stat_value(
        self, pool: KeaPool, api_stat_name: str
    ) -> Optional[int]:
        """
        Return the most recent stat value recorded by the Kea DHCP server for
        the given address pool and api stat name.
        """
        statistic = f"subnet[{pool.subnet_id}].pool[{pool.pool_id}].{api_stat_name}"
        try:
            response = self._send_query("statistic-get", name=statistic)
        except KeaEmpty:
            # This may occur if the subnet we query have been removed from the
            # DHCP server's configuration at time of request
            response = {}

        samples = response.get("arguments", {}).get(statistic, [])

        if len(samples) == 0:
            _logger.info(
                "No samples found when querying for '%s' in pool with range '%s-%s' "
                "and name '%s'",
                api_stat_name,
                pool.range_start,
                pool.range_end,
                pool.name,
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
                raise KeaUnexpected(
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
                "arguments": kwargs,
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
            raise KeaUnexpected(
                "%s does not look like a Kea API endpoint; "
                "response to command '%s' was not valid JSON",
                self._url,
                command,
            ) from err
        except RequestException as err:
            raise CommunicationError from err

        # Any valid response from Kea is a JSON list with one entry corresponding to the
        # response from either the dhcp4 or dhcp6 service we queried
        match responses:
            case [{"result": int(status)} as response]:
                pass
            case {"result": int(status), "text": str(message)}:
                # If the response is a JSON object it's a specific error message
                # See https://kea.readthedocs.io/en/kea-2.6.0/arm/ctrl-channel.html#control-agent-command-response-format
                raise KeaUnexpected(f"{status}: {message}")
            case _:
                raise KeaUnexpected(
                    "%s does not look like a Kea API; "
                    "response JSON structured in an unknown way",
                    self._url,
                )

        _logger.debug(
            "Response from %s to command '%s' was '%s: %s'",
            self._url,
            command,
            status,
            response.get("text", "(no description)")
        )

        _raise_for_kea_status(status)

        return response


    def _pools_of_subnet(self, subnet: dict) -> Iterator[Pool]:
        """
        Returns one _Pool instance per pool configured for a subnet in a Kea
        DHCP server's configuration.
        """
        match subnet:
            case {"id": int(subnet_id)}:
                pass
            case _:
                _logger.debug(
                    "Misconfigured subnet from %s, skipping...",
                    self._url,
                )
                return

        for pool in subnet.get("pools", []):
            match pool:
                case {"pool-id": int(pool_id), "pool": str(pool_range)}:
                    pass
                case _:
                    _logger.debug(
                        'Misconfigured pool for subnet with id %d from %s, skipping... '
                        '(make sure every pool has "pool-id" and "pool" configured)',
                        subnet_id,
                        self._url,
                    )
                    continue

            name = pool.get("user-context", {}).get(self._user_context_poolname_key, None)
            name = name if isinstance(name, str) else ""

            try:
                if "-" in pool_range:
                    # x.x.x.x - x.x.x.x
                    range_start, _, range_end = pool_range.partition("-")
                    range_start = IP(range_start.strip())
                    range_end = IP(range_end.strip())
                else:
                    # x.x.x.x/m
                    ip = IP(pool_range.strip())
                    range_start = IP(ip[0])
                    range_end = IP(ip[-1])
            except ValueError:
                _logger.debug(
                    "Pool range in pool with id %d from %s configured with unknown format '%s', skipping...",
                    pool_id,
                    self._url,
                    pool_range,
                )
                continue

            yield Pool(
                subnet_id=subnet_id,
                pool_id=pool_id,
                name=name,
                range_start=range_start,
                range_end=range_end,
            )


    def _create_session(self) -> Session:
        """
        Creates and returns an HTTP session with authentication based on
        credentials passed during object initialization.
        """
        _logger.debug("Creating new HTTP session for use with Kea API at %s", self._url)

        session = Session()

        retries = Retry(
            total=3,
            backoff_factor=0.1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods={"POST"},
        )

        session.mount("https://", HTTPAdapter(max_retries=retries))
        session.mount("http://", HTTPAdapter(max_retries=retries))

        https = self._url.startswith("https://")

        if not https:
            _logger.warning(
                "Using HTTP to request potentially sensitive data such as API passwords"
            )

        if self._http_basic_user and self._http_basic_password:
            _logger.debug("Using HTTP Basic Authentication")
            if not https:
                _logger.warning("Using HTTP Basic Authentication without HTTPS")
            session.auth = (self._http_basic_user, self._http_basic_password)
        else:
            _logger.debug("Not using HTTP Basic Authentication")

        if self._client_cert_path:
            _logger.debug("Using client certificate authentication")
            if not https:
                raise ConfigurationError(
                    "Authentication using client certificates is only available for urls "
                    "with HTTPS scheme"
                )
            _logger.debug("Certificate path: '%s'", self._client_cert_path)
            if self._client_key_path:
                _logger.debug("Certificate key path: '%s'", self._client_key_path)
                session.cert = (self._client_cert_path, self._client_key_path)
            else:
                session.cert = self._client_cert_path
        else:
            _logger.debug("Not using client certificate authentication")

        return session


class KeaUnexpected(CommunicationError):
    """An unexpected error occurred when communicating with Kea"""


class KeaError(CommunicationError):
    """(API specific) Kea failed during command processing"""


class KeaUnsupported(CommunicationError):
    """(API specific) Unsupported command"""


class KeaEmpty(CommunicationError):
    """(API specific) Requested resource not found"""


class KeaConflict(CommunicationError):
    """
    (API specific) Kea failed to apply requested changes due to conflicts with
    its server state
    """


class _KeaStatus(IntEnum):
    """Status of a response sent from a Kea API"""

    SUCCESS = 0
    ERROR = 1
    UNSUPPORTED = 2
    EMPTY = 3
    CONFLICT = 4


def _raise_for_kea_status(status: int):
    """
    Raises a suitable subclass of CommunicationError if 'status' is not
    _KeaStatus.SUCCESS.
    """
    if status == _KeaStatus.SUCCESS:
        return
    elif status == _KeaStatus.UNSUPPORTED:
        raise KeaUnsupported
    elif status == _KeaStatus.EMPTY:
        raise KeaEmpty
    elif status == _KeaStatus.ERROR:
        raise KeaError
    elif status == _KeaStatus.CONFLICT:
        raise KeaConflict
    else:
        raise KeaUnexpected("Unkown response status")
