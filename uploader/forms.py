from django import forms
from django.core.exceptions import ValidationError


MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024


class VCFUploadForm(forms.Form):
    drug_name = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={"required": "Drug name cannot be empty."},
    )
    vcf_file = forms.FileField(
        error_messages={"required": "Please select a .vcf file to upload."}
    )

    def clean_vcf_file(self):
        uploaded_file = self.cleaned_data["vcf_file"]
        if not uploaded_file.name.lower().endswith(".vcf"):
            raise ValidationError("File extension must be .vcf.")

        if uploaded_file.size > MAX_FILE_SIZE_BYTES:
            raise ValidationError("File size must be less than 5MB.")

        return uploaded_file
