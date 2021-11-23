#
# Copyright (c) 2021 Airbyte, Inc., all rights reserved.
#


from abc import ABC
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple
from urllib.parse import urlparse, parse_qs, urlsplit

import pendulum
import requests
from airbyte_cdk.logger import AirbyteLogger
from airbyte_cdk.models import SyncMode
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http import HttpStream
from .medrio_odm import MedrioOdmApi, MedrioOdmXml


"""
TODO: Most comments in this class are instructive and should be deleted after the source is implemented.

This file provides a stubbed example of how to use the Airbyte CDK to develop both a source connector which supports full refresh or and an
incremental syncs from an HTTP API.

The various TODOs are both implementation hints and steps - fulfilling all the TODOs should be sufficient to implement one basic and one incremental
stream from a source. This pattern is the same one used by Airbyte internally to implement connectors.

The approach here is not authoritative, and devs are free to use their own judgement.

There are additional required TODOs in the files within the integration_tests folder and the spec.json file.
"""

logger = AirbyteLogger()


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

    def parse_response(
        self, response: requests.Response, **kwargs
    ) -> Iterable[Mapping]:
        response_json = response.json()
        yield from response_json.get("value", [])


class MedrioV1Stream(MedrioHttpStream):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.url_base = self.url_base + "api/v1/"

    def next_page_token(
        self, response: requests.Response
    ) -> Optional[Mapping[str, Any]]:
        # The API does not offer pagination,
        # so we return None to indicate there are no more pages in the response
        return None


class MedrioV2Stream(MedrioHttpStream):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.url_base = self.url_base + "dataview/api/v2/customer/"

    def next_page_token(
        self, response: requests.Response
    ) -> Optional[Mapping[str, Any]]:
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


class Studies(MedrioV1Stream):
    primary_key = "studyId"

    def path(
        self,
        stream_state: Mapping[str, Any] = None,
        stream_slice: Mapping[str, Any] = None,
        next_page_token: Mapping[str, Any] = None,
    ) -> str:
        return "study"


# Basic incremental stream
class IncrementalMedrioV2Stream(MedrioV2Stream, ABC):

    state_checkpoint_interval = 10000

    @property
    def cursor_field(self) -> str:
        """
        TODO
        Override to return the cursor field used by this stream e.g: an API entity might always use created_at as the cursor field. This is
        usually id or date based. This field's presence tells the framework this in an incremental stream. Required for incremental.

        :return str: The name of the cursor field.
        """
        return []

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

    def _create_prepared_request(self, **kwargs):
        request = super()._create_prepared_request(**kwargs)
        request.url = (request.url).replace("%24", "$")
        return request


class Queries(IncrementalMedrioV2Stream):
    primary_key = "GlobalQueryId"
    cursor_field = "LastUpdatedTimestamp"

    def path(self, **kwargs) -> str:
        return "QueryReports"


class MedrioOdm(Stream):
    primary_key = ["FormOID", "SubjectKey", "ItemGroupRepeatKey"]
    cursor_field = "DateTimeStamp"
    stream_name = None
    name = "odm_clinical"

    def __init__(self, api: MedrioOdmApi, study_id: str, **kwargs):
        self.api = api
        self.study_id = study_id
        super().__init__(**kwargs)

    def get_json_schema(self):
        self.name = "odm_clinical"  # change just to get shared json_schema
        schema = super().get_json_schema()
        schema["properties"].update(self.extra_schema)
        self.name = self.stream_name  # change name back now that we've got schema
        return schema

    def update_schema(self, extra_schema: dict, stream_name: str):
        self.extra_schema = extra_schema
        self.name = stream_name  # set the name of the schema
        self.stream_name = stream_name  # capture extra param to keep name

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: List[str] = None,
        stream_slice: Mapping[str, Any] = None,
        stream_state: Mapping[str, Any] = None,
    ) -> Iterable[Mapping[str, Any]]:
        xml_string = self.api.main(content_type="AllData", study_id=self.study_id)
        odm_xml = MedrioOdmXml(xml_string)
        records = odm_xml.parse_clinical()
        return records
