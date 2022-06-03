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
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http import HttpStream
from pendulum import DateTime, Period

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
        logger.info(f"Parsing response for stream {self.name}")
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
        logger.info(f"Parsing response for stream {self.name}")
        response_json = response.json()
        yield from response_json.get("value", [])

    def _create_prepared_request(self, **kwargs):
        request = super()._create_prepared_request(**kwargs)
        request.url = (request.url).replace("%24", "$")
        return request

    def read_records(self, **kwargs):
        logger.info(f"Reading records for stream {self.name}")
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


class MedrioV2StreamIncremental(MedrioV2Stream):

    state_checkpoint_interval = 10000

    def get_updated_state(
        self,
        current_stream_state: MutableMapping[str, Any],
        latest_record: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """
        Override to determine the latest state after reading the latest record. This typically compares the cursor_field from the latest record and
        the current state and picks the 'most' recent cursor. This is how a stream's state is determined. Required for incremental.
        """
        record_value = latest_record.get(self.cursor_field)
        state_value = current_stream_state.get(self.cursor_field) or record_value
        max_cursor = max(pendulum.parse(state_value), pendulum.parse(record_value))
        return {self.cursor_field: str(max_cursor)}
