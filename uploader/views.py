from pathlib import Path

from django.core.files.storage import default_storage
from django.shortcuts import render

from .forms import VCFUploadForm


def upload_vcf(request):
    success_message = None
    saved_path = None

    if request.method == "POST":
        form = VCFUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data["vcf_file"]
            safe_name = Path(uploaded_file.name).name
            saved_path = default_storage.save(f"uploads/{safe_name}", uploaded_file)
            success_message = "Upload Successful"
            form = VCFUploadForm()
    else:
        form = VCFUploadForm()

    return render(
        request,
        "uploader/upload.html",
        {"form": form, "success_message": success_message, "saved_path": saved_path},
    )
