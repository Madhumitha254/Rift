import os


FALLBACK_EXPLANATION = "LLM explanation unavailable"
DEFAULT_MODEL = "gemini-1.5-flash"


def build_gemini_prompt(gene: str, drug: str, phenotype: str, risk: str, rsids: list[str]) -> str:
    rsid_text = ", ".join(rsids) if rsids else "none detected"
    return (
        f"Explain clinically why a {phenotype} metabolizer of {gene} taking {drug} is "
        f"categorized as {risk}. Include mechanism and reference variants {rsid_text}. "
        "Be professional and concise."
    )


def generate_gemini_explanation(gene: str, drug: str, phenotype: str, risk: str, rsids: list[str]) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return FALLBACK_EXPLANATION

    try:
        import google.generativeai as genai
    except ImportError:
        return FALLBACK_EXPLANATION

    prompt = build_gemini_prompt(gene=gene, drug=drug, phenotype=phenotype, risk=risk, rsids=rsids)

    try:
        model_name = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        text = getattr(response, "text", "") or ""
        cleaned = text.strip()
        return cleaned if cleaned else FALLBACK_EXPLANATION
    except Exception:
        return FALLBACK_EXPLANATION
