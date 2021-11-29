import lxml.etree as etree
import io
import requests
import untangle
import urllib.parse as up
import zipfile

from airbyte_cdk.logger import AirbyteLogger
from itertools import chain
from pathlib import Path
from retry import retry

logger = AirbyteLogger()


class MedrioOdmApi:
    def __init__(self, api_key) -> None:
        self.api_key = api_key
        self.base_url = f"https://na13.api.medrio.com/v1/MedrioServiceV1.svc/Customers/{self.api_key}/Studies/"
        self.job_id = None
        self.file_url = None

    def main(self, content_type: str, study_id: str):
        self.post_job_request(content_type, study_id)
        self.get_job_file_url(study_id)
        xml = self.get_file_content()
        return xml

    def get_studies(self):
        response = requests.get(
            url=self.base_url.rstrip("/"),
        )
        xml = untangle.parse(response.text)
        try:
            studies = {
                st.Name.cdata: st.ID.cdata
                for st in xml.MedrioResponse.Records.StudyListing
            }
        except AttributeError as e:
            logger.error(xml.MedrioResponse.Message.cdata)
            raise
        return studies

    def post_job_request(self, content_type: str, study_id: str):
        if self.job_id is not None:
            logger.info(f"Job ID = {self.job_id}. Will not request a new one.")
            return
        assert content_type in ["ConfigOnly", "AllData"]
        payload = f"""<ExportODM xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
        <ContentType>{content_type}</ContentType>
        </ExportODM>"""
        headers = {"Content-Type": "application/xml"}
        url = up.urljoin(self.base_url, str(Path(study_id, "Jobs", "ExportODM")))
        logger.info(url)
        response = requests.post(
            url=url,
            data=payload,
            headers=headers,
        )
        xml = untangle.parse(response.text)
        message = xml.MedrioResponse.Message.cdata
        if message == "Success":
            response_code = xml.MedrioResponse.Code.cdata
            logger.info(f"Request: {response_code}")
            job_status = xml.MedrioResponse.Records.Job.Status.cdata
            logger.info(f"Status: {job_status}")
            job_id = xml.MedrioResponse.Records.Job.JobID.cdata
            logger.info(f"JobID: {job_id}")
            self.job_id = job_id
        else:
            logger.error(f"Request failed: {message}")

    @retry(FileNotFoundError, tries=18, delay=2, backoff=2, max_delay=300)
    def get_job_file_url(self, study_id: str):
        if self.job_id is None:
            raise NameError(
                "job_id not found, please make sure http_request was successful"
            )
        logger.info(f"Requesting JobID: {self.job_id}")
        url = up.urljoin(self.base_url, str(Path(study_id, "Jobs", self.job_id)))
        r = requests.get(url)
        xml = untangle.parse(r.text)
        status = xml.MedrioResponse.Records.Job.Status.cdata
        if status == "Successful":
            logger.info("File has successfully been generated")
            self.file_url = xml.MedrioResponse.Records.Job.File.cdata
        elif status in ("Error", "Purged"):
            logger.error(self.pretty_print(r))
            raise RuntimeError(f"JobID {self.job_id} failed. Status={status}")
        elif status == "Processing":
            raise FileNotFoundError(f"JobID {self.job_id} not ready. Status={status}")
        else:
            raise FileNotFoundError(f"JobID {self.job_id} not ready. Status={status}")

    def get_file_content(self):
        logger.info("Getting job file contents...")
        r = requests.get(self.file_url, stream=True)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml = z.read(z.infolist()[0])
        return xml

    @staticmethod
    def pretty_print(response):
        import xml.dom.minidom as minidom  # beautify XML

        return minidom.parseString(response.text).toprettyxml()


class MedrioOdmXml:
    def __init__(self, xml_string: str):
        self.root = etree.fromstring(xml_string)
        self.nsmap = {
            k if k is not None else "def": v for k, v in self.root.nsmap.items()
        }
        self.config = self.parse_config()

    def parse_clinical(self):
        subject_data = self.root.findall(".//*def:SubjectData", self.nsmap)
        records = []
        for subj in subject_data:
            records.extend(self._json_subject_data(subj))
        return records

    def _json_subject_data(self, subject_data: etree._Element):
        tags = {
            tag: f"{{{self.nsmap['def']}}}{tag}"
            for tag in ("StudyEventData", "FormData", "AuditRecord", "ItemGroupData")
        }
        records = []
        for ev, elem in etree.iterwalk(
            subject_data, events=("end", "start"), tag=tags.values()
        ):
            if ev == "start" and elem.tag == tags["StudyEventData"]:
                event = {k: v for k, v in elem.attrib.items()}
                event.update({self.rm_ns(k): v for k, v in subject_data.items()})
            if ev == "start" and elem.tag == tags["FormData"]:
                form = {k: v for k, v in event.items()}
                for k, v in elem.attrib.items():
                    form.update({self.rm_ns(k): v})
            if ev == "start" and elem.tag == tags["AuditRecord"]:
                form["DateTimeStamp"] = elem.find("def:DateTimeStamp", self.nsmap).text
            if ev == "start" and elem.tag == tags["ItemGroupData"]:
                item_group = {k: v for k, v in form.items()}
                item_group.update({k: v for k, v in elem.attrib.items()})
                item_group["ItemData"] = {
                    ch.get("ItemOID"): ch.text for ch in elem.getchildren()
                }
                records.append(item_group)
        return records

    def parse_config(self):
        forms = {}
        form_data = self.root.findall(".//def:FormDef", self.nsmap)
        item_groups = self._item_groups()
        for form in form_data:
            form_igs = [
                ig.get("ItemGroupOID")
                for ig in form.findall(".//def:ItemGroupRef", self.nsmap)
            ]
            form_igs = {k: item_groups[k] for k in form_igs if k in item_groups}
            items = list(chain(*(list(v["Items"].values()) for v in form_igs.values())))
            forms[form.get("OID")] = {"Name": form.get("Name"), "Items": items}
        return forms

    def _item_groups(self):
        items = {
            item.get("OID"): item.attrib
            for item in self.root.findall(".//def:ItemDef", self.nsmap)
        }
        item_groups = {}
        for item_group in self.root.findall(".//def:ItemGroupDef", self.nsmap):
            item_refs = {
                x.get("ItemOID"): items.get(x.get("ItemOID"))
                for x in item_group.getchildren()
            }
            item_groups[item_group.get("OID")] = {
                "Name": item_group.get("Name"),
                "Items": item_refs,
            }
        return item_groups

    @staticmethod
    def pprint(elem: etree._Element):
        print(etree.tostring(elem, pretty_print=True).decode("utf-8"))

    @staticmethod
    def rm_ns(elem: etree._Element):
        return etree.QName(elem).localname
