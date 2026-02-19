import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse


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
            {"drug_name": "Aspirin", "vcf_file": upload},
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
