#
# Copyright (c) 2021 Airbyte, Inc., all rights reserved.
#


from abc import ABC
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple
from urllib.parse import urlparse, parse_qs, urlsplit

import pendulum
import requests
import signal
from airbyte_cdk.logger import AirbyteLogger
from airbyte_cdk.models import SyncMode
from airbyte_cdk.sources.streams import Stream, IncrementalMixin
from airbyte_cdk.sources.streams.http import HttpStream

logger = AirbyteLogger()

# ------------------------------------------------------
# Basic full refresh stream
class MedrioHttpStream(HttpStream, ABC):
    url_base = "https://connectapi.medrio.com/"

    def request_params(
        self,
        stream_state: Mapping[str, Any],
        stream_slice: Mapping[str, any] = None,
        next_page_token: Mapping[str, Any] = None,
    ) -> MutableMapping[str, Any]:
        params = {}
        if next_page_token:
            params.update(next_page_token)
        return params


# ------------------------------------------------------
# API V1 Streams
class MedrioV1Stream(MedrioHttpStream):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.url_base = self.url_base + "api/v1/"

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        # The API does not offer pagination,
        # so we return None to indicate there are no more pages in the response
        return None

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        yield from response_json.get("response", [])


class Studies(MedrioV1Stream):
    primary_key = "studyId"

    def path(self, **kwargs) -> str:
        return "study"


# ------------------------------------------------------
# API V2 Streams
class MedrioV2Stream(MedrioHttpStream):
    def __init__(self, **kwargs):
        self.url_base = self.url_base + "dataview/api/v2/customer/"
        super().__init__(**kwargs)

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        """
        Get the next pagination link from the Medrio api response and parse out the query parameters.

        The Medrio API returns a key "@odata.nextLink" in the json with the link to the next page.
        Adhering to the standard of passing a query param instead of the entire URL,
        we parse out the query param from the URL and pass it along.

        :param response: the most recent response from the API
        :return If there is another page in the result, the $skip param necessary to query the next page in the response.
                If there are no more pages in the result, return nothing.
        """
        decoded_response = response.json()
        if decoded_response.get("@odata.nextLink"):
            return parse_qs(urlsplit(decoded_response.get("@odata.nextLink")).query)

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        yield from response_json.get("value", [])

    def _create_prepared_request(self, **kwargs):
        request = super()._create_prepared_request(**kwargs)
        request.url = (request.url).replace("%24", "$")
        return request

    def read_records(self, **kwargs):
        yield from super().read_records(**kwargs)


class FormStatus(MedrioV2Stream):
    primary_key = "GlobalCollectionPtID"

    def path(self, **kwargs) -> str:
        return "FormStatusReports"


class ApprovalEvent(MedrioV2Stream):
    primary_key = "GlobalApprovalEvent_Id"

    def path(self, **kwargs) -> str:
        return "ApprovalEventReports"


class Queries(MedrioV2Stream):
    primary_key = "GlobalQueryId"
    # cursor_field = "LastUpdatedTimestamp"

    def path(self, **kwargs) -> str:
        return "QueryReports"


def chunk_date_range(start_date: pendulum.Date) -> Iterable[pendulum.Date]:
    """
    Yields a list of the beginning and ending timestamps of each day between the start date and now.
    The return value is a pendulum.period
    """

    now = pendulum.now().date()
    # Each stream_slice contains the beginning and ending timestamp for a 24 hour period
    while start_date <= now:
        yield start_date
        start_date = start_date.add(days=1)


class MedrioV2StreamIncremental(MedrioV2Stream, IncrementalMixin):

    cursor_field = "timestamp_tz"

    def __init__(self, start_date: str, **kwargs):
        super().__init__(**kwargs)
        self._start_date = start_date
        self._cursor_value = pendulum.parse(start_date).to_iso8601_string()

    def request_params(self, config: Mapping[str, Any], **kwargs):
        super().request_params(**kwargs)

    @property
    def state(self) -> Mapping[str, Any]:
        return {self.cursor_field: str(self._cursor_value)} if self._cursor_value else {}

    @state.setter
    def state(self, value: Mapping[str, Any]):
        self._cursor_value = value[self.cursor_field]

    def stream_slices(self, stream_state: Mapping[str, Any] = None, **kwargs) -> Iterable[Optional[Mapping[str, any]]]:
        stream_state = stream_state or {}
        start_date = pendulum.parse(stream_state.get(self.cursor_field, self._start_date)).date()
        for date in chunk_date_range(start_date):
            yield {"date": date.to_date_string()}

    def read_records(self, **kwargs):
        records = super().read_records(**kwargs)
        max_cursor = pendulum.parse(self._cursor_value)
        for record in records:
            yield record
            max_cursor = max(max_cursor, pendulum.parse(record[self.cursor_field]))
        self._cursor_value = max_cursor.to_iso8601_string()

    def request_params(
        self,
        stream_state: Mapping[str, Any],
        stream_slice: Mapping[str, any] = None,
        next_page_token: Mapping[str, Any] = None,
    ) -> MutableMapping[str, Any]:
        params = {}
        if next_page_token:
            params.update(next_page_token)
        if stream_slice is not None:
            params.update({"$filter": f"{self.cursor_field} eq {stream_slice['date']}"})
        return params


class DataAudit(MedrioV2StreamIncremental):
    primary_key = "GlobalDatumId"
    cursor_field = "DataEntryUtcDateVal"

    def path(self, **kwargs) -> str:
        return "DataAuditReports"
