#
# Copyright (c) 2021 Airbyte, Inc., all rights reserved.
#


from abc import ABC
from http.client import REQUEST_TIMEOUT
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
from .medrio_odm import MedrioOdmApi, MedrioOdmXml


logger = AirbyteLogger()

REQUEST_TIMEOUT = 600  # 10 minutes


def timeout_handler(signum, frame):
    raise requests.exceptions.ReadTimeout(f"Timeout {REQUEST_TIMEOUT} seconds")


signal.signal(signal.SIGALRM, timeout_handler)

# Basic full refresh stream
class MedrioHttpStream(HttpStream, ABC):
    url_base = "https://connectapi.medrio.com/"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

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


class MedrioV2Stream(MedrioHttpStream):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.url_base = self.url_base + "dataview/api/v2/customer/"

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

    def _send_request(self, request: requests.PreparedRequest, request_kwargs: Mapping[str, Any]) -> requests.Response:
        try:
            signal.alarm(REQUEST_TIMEOUT)
            out = super()._send_request(request, request_kwargs)
        finally:
            signal.alarm(0)
        return out


# Incremental Streams
def chunk_date_range(start_date: DateTime, interval=pendulum.duration(days=1)) -> Iterable[Period]:
    """
    Yields a list of the beginning and ending timestamps of each day between the start date and now.
    The return value is a pendulum.period
    """

    now = pendulum.now()
    # Each stream_slice contains the beginning and ending timestamp for a 24 hour period
    while start_date <= now:
        end_date = start_date + interval
        yield pendulum.period(start_date, end_date)
        start_date = end_date


class MedrioV2StreamIncremental(MedrioV2Stream, ABC):

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


# ------------------------------------------------------


class Studies(MedrioV1Stream):
    primary_key = "studyId"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def path(self, **kwargs) -> str:
        return "study"


class FormStatus(MedrioV2Stream):
    primary_key = "GlobalCollectionPtID"

    def path(self, **kwargs) -> str:
        return "FormStatusReports"


class ApprovalEvent(MedrioV2Stream):
    primary_key = "GlobalApprovalEvent_Id"

    def path(self, **kwargs) -> str:
        return "ApprovalEventReports"


class Queries(MedrioV2StreamIncremental):
    primary_key = "GlobalQueryId"
    cursor_field = "LastUpdatedTimestamp"

    def path(self, **kwargs) -> str:
        return "QueryReports"


# class ClinicalData(MedrioV2StreamIncremental):
#     primary_key = "GlobalDatumId"

#     def __init__(self, api: MedrioOdmApi, study_id: str, **kwargs):
#         self.api = api
#         self.study_id = study_id
#         super().__init__(**kwargs)

#     def get_json_schema(self):
#         self.name = "odm_clinical"  # change just to get shared json_schema
#         schema = super().get_json_schema()
#         schema["properties"].update(self.extra_schema)
#         self.name = self.stream_name  # change name back now that we've got schema
#         return schema


# class DataAudit(MedrioV2StreamIncremental):
#     primary_key = "GlobalDatumId"
#     cursor_field = "DataEntryUtcDateVal"

#     def path(self, **kwargs) -> str:
#         return "DataAuditReports"


# class MedrioOdm(Stream):
#     primary_key = ["FormOID", "SubjectKey", "ItemGroupRepeatKey"]
#     cursor_field = "DateTimeStamp"
#     stream_name = None
#     name = "odm_clinical"

#     def __init__(self, api: MedrioOdmApi, study_id: str, **kwargs):
#         self.api = api
#         self.study_id = study_id
#         super().__init__(**kwargs)

#     def get_json_schema(self):
#         self.name = "odm_clinical"  # change just to get shared json_schema
#         schema = super().get_json_schema()
#         schema["properties"].update(self.extra_schema)
#         self.name = self.stream_name  # change name back now that we've got schema
#         return schema

#     def update_schema(self, extra_schema: dict, stream_name: str):
#         self.extra_schema = extra_schema
#         self.name = stream_name  # set the name of the schema
#         self.stream_name = stream_name  # capture extra param to keep name

#     def read_records(
#         self,
#         sync_mode: SyncMode,
#         cursor_field: List[str] = None,
#         stream_slice: Mapping[str, Any] = None,
#         stream_state: Mapping[str, Any] = None,
#     ) -> Iterable[Mapping[str, Any]]:
#         xml_string = self.api.main(content_type="AllData", study_id=self.study_id)
#         odm_xml = MedrioOdmXml(xml_string)
#         records = odm_xml.parse_clinical()
#         return records
