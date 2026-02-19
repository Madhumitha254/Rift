from pathlib import Path
from time import perf_counter

from django.core.files.storage import default_storage
from django.shortcuts import render

from .forms import VCFUploadForm
from .services.gemini_client import generate_gemini_explanation
from .services.pgx_engine import UnsupportedDrugError, analyze_vcf_and_drug


def upload_vcf(request):
    success_message = None
    saved_path = None
    analysis_result = None

    if request.method == "POST":
        form = VCFUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data["vcf_file"]
            drug_name = form.cleaned_data["drug_name"]
            safe_name = Path(uploaded_file.name).name
            saved_path = default_storage.save(f"uploads/{safe_name}", uploaded_file)

            with default_storage.open(saved_path, "rb") as file_handle:
                vcf_bytes = file_handle.read()

            started_at = perf_counter()
            try:
                analysis_result = analyze_vcf_and_drug(
                    vcf_bytes=vcf_bytes,
                    filename=safe_name,
                    drug_name=drug_name,
                )
            except UnsupportedDrugError:
                return render(
                    request,
                    "uploader/error.html",
                    {
                        "error_title": "Unsupported Drug",
                        "error_detail": (
                            f"Drug '{drug_name}' is not supported. "
                            "Supported drugs: CODEINE, CLOPIDOGREL, WARFARIN."
                        ),
                    },
                    status=400,
                )

            processing_time_ms = int((perf_counter() - started_at) * 1000)
            analysis_result["quality_metrics"]["processing_time_ms"] = processing_time_ms

            analysis_result["explanation"] = generate_gemini_explanation(
                gene=analysis_result["gene"],
                drug=analysis_result["drug"],
                phenotype=analysis_result["phenotype"],
                risk=analysis_result["risk"],
                rsids=analysis_result["rsids"],
            )

            success_message = "Upload Successful"
            form = VCFUploadForm(initial={"drug_name": drug_name})
    else:
        form = VCFUploadForm()

    return render(
        request,
        "uploader/upload.html",
        {
            "form": form,
            "success_message": success_message,
            "saved_path": saved_path,
            "analysis_result": analysis_result,
        },
    )
