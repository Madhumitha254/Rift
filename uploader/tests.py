import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .services.gemini_client import FALLBACK_EXPLANATION
from .services.pgx_engine import UnsupportedDrugError, analyze_vcf_and_drug


def make_vcf_content(sample_id: str, variants: list[dict[str, str]]) -> bytes:
    header = [
        "##fileformat=VCFv4.2",
        "##source=unit-test",
        f"##SAMPLE=<ID={sample_id}>",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
    ]
    body = []
    for index, variant in enumerate(variants, start=1):
        body.append(
            (
                "1\t{pos}\t{rsid}\tA\tG\t.\tPASS\tGENE={gene};STAR={star}\tGT\t0/1".format(
                    pos=10000 + index,
                    rsid=variant["rsid"],
                    gene=variant["gene"],
                    star=variant["star"],
                )
            )
        )
    return ("\n".join(header + body) + "\n").encode("utf-8")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class UploadVCFTests(TestCase):
    def test_valid_upload_succeeds_and_saves_file(self):
        upload = SimpleUploadedFile(
            "contacts.vcf",
            b"BEGIN:VCARD\nVERSION:3.0\nFN:Jane Doe\nEND:VCARD\n",
            content_type="text/vcard",
        )
        response = self.client.post(
            reverse("upload_vcf"),
            {"drug_name": "Codeine", "vcf_file": upload},
        )

        self.assertContains(response, "Upload Successful")
        saved_file = Path(settings.MEDIA_ROOT) / "uploads" / "contacts.vcf"
        self.assertTrue(saved_file.exists())

    def test_invalid_extension_returns_error(self):
        upload = SimpleUploadedFile("contacts.txt", b"test", content_type="text/plain")
        response = self.client.post(
            reverse("upload_vcf"),
            {"drug_name": "Aspirin", "vcf_file": upload},
        )

        self.assertContains(response, "File extension must be .vcf.")

    def test_file_at_5mb_limit_returns_error(self):
        upload = SimpleUploadedFile(
            "big.vcf",
            b"a" * (5 * 1024 * 1024),
            content_type="text/vcard",
        )
        response = self.client.post(
            reverse("upload_vcf"),
            {"drug_name": "Aspirin", "vcf_file": upload},
        )

        self.assertContains(response, "File size must be less than 5MB.")

    def test_blank_drug_name_returns_error(self):
        upload = SimpleUploadedFile("contacts.vcf", b"test", content_type="text/vcard")
        response = self.client.post(
            reverse("upload_vcf"),
            {"drug_name": "   ", "vcf_file": upload},
        )

        self.assertContains(response, "Drug name cannot be empty.")

    @patch.dict("os.environ", {"GEMINI_API_KEY": ""})
    def test_supported_drug_returns_deterministic_risk(self):
        vcf = make_vcf_content(
            sample_id="PATIENT-001",
            variants=[
                {"rsid": "rs3892097", "gene": "CYP2D6", "star": "*1"},
                {"rsid": "rs1065852", "gene": "CYP2D6", "star": "*4"},
            ],
        )
        upload = SimpleUploadedFile("patient.vcf", vcf, content_type="text/vcard")

        response = self.client.post(
            reverse("upload_vcf"),
            {"drug_name": "codeine", "vcf_file": upload},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload Successful")
        self.assertContains(response, "PATIENT-001")
        self.assertContains(response, "CODEINE")
        self.assertContains(response, "CYP2D6")
        self.assertContains(response, "*1/*4")
        self.assertContains(response, "IM")
        self.assertContains(response, "Adjust Dosage")

    def test_missing_required_gene_returns_unknown_risk(self):
        vcf = make_vcf_content(
            sample_id="PATIENT-002",
            variants=[
                {"rsid": "rs4244285", "gene": "CYP2C19", "star": "*1"},
                {"rsid": "rs12769205", "gene": "CYP2C19", "star": "*2"},
            ],
        )
        upload = SimpleUploadedFile("patient.vcf", vcf, content_type="text/vcard")

        response = self.client.post(
            reverse("upload_vcf"),
            {"drug_name": "codeine", "vcf_file": upload},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unknown")
        self.assertContains(response, "Insufficient data to apply CPIC rule for CYP2D6.")
        self.assertContains(response, "0.0")

    def test_incomplete_diplotype_lowers_confidence(self):
        vcf = make_vcf_content(
            sample_id="PATIENT-003",
            variants=[
                {"rsid": "rs3892097", "gene": "CYP2D6", "star": "*1"},
            ],
        )
        upload = SimpleUploadedFile("patient.vcf", vcf, content_type="text/vcard")

        response = self.client.post(
            reverse("upload_vcf"),
            {"drug_name": "codeine", "vcf_file": upload},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unknown")
        self.assertContains(response, "0.4")

    def test_unsupported_drug_returns_clean_error_page(self):
        vcf = make_vcf_content(
            sample_id="PATIENT-004",
            variants=[
                {"rsid": "rs3892097", "gene": "CYP2D6", "star": "*1"},
                {"rsid": "rs1065852", "gene": "CYP2D6", "star": "*4"},
            ],
        )
        upload = SimpleUploadedFile("patient.vcf", vcf, content_type="text/vcard")

        response = self.client.post(
            reverse("upload_vcf"),
            {"drug_name": "ibuprofen", "vcf_file": upload},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Unsupported Drug", status_code=400)
        self.assertContains(
            response,
            "Supported drugs: CODEINE, CLOPIDOGREL, WARFARIN.",
            status_code=400,
        )

    @patch.dict("os.environ", {"GEMINI_API_KEY": ""})
    def test_llm_failure_path_returns_fallback_explanation(self):
        vcf = make_vcf_content(
            sample_id="PATIENT-005",
            variants=[
                {"rsid": "rs3892097", "gene": "CYP2D6", "star": "*1"},
                {"rsid": "rs1065852", "gene": "CYP2D6", "star": "*4"},
            ],
        )
        upload = SimpleUploadedFile("patient.vcf", vcf, content_type="text/vcard")

        response = self.client.post(
            reverse("upload_vcf"),
            {"drug_name": "codeine", "vcf_file": upload},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, FALLBACK_EXPLANATION)


class DeterministicEngineTests(TestCase):
    def test_unsupported_drug_raises(self):
        vcf = make_vcf_content(
            sample_id="PATIENT-006",
            variants=[{"rsid": "rs3892097", "gene": "CYP2D6", "star": "*1"}],
        )

        with self.assertRaises(UnsupportedDrugError):
            analyze_vcf_and_drug(vcf_bytes=vcf, filename="x.vcf", drug_name="UNKNOWN_DRUG")

    def test_confidence_and_severity_when_rule_applies(self):
        vcf = make_vcf_content(
            sample_id="PATIENT-007",
            variants=[
                {"rsid": "rs3892097", "gene": "CYP2D6", "star": "*1"},
                {"rsid": "rs1065852", "gene": "CYP2D6", "star": "*4"},
            ],
        )

        result = analyze_vcf_and_drug(vcf_bytes=vcf, filename="x.vcf", drug_name="CODEINE")

        self.assertEqual(result["risk"], "Adjust Dosage")
        self.assertEqual(result["confidence_score"], 1.0)
        self.assertEqual(result["severity"], "moderate")

    def test_confidence_and_severity_with_missing_gene(self):
        vcf = make_vcf_content(
            sample_id="PATIENT-008",
            variants=[
                {"rsid": "rs4244285", "gene": "CYP2C19", "star": "*1"},
                {"rsid": "rs12769205", "gene": "CYP2C19", "star": "*2"},
            ],
        )

        result = analyze_vcf_and_drug(vcf_bytes=vcf, filename="x.vcf", drug_name="CODEINE")

        self.assertEqual(result["risk"], "Unknown")
        self.assertEqual(result["confidence_score"], 0.0)
        self.assertEqual(result["severity"], "moderate")
