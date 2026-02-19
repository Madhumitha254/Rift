import re
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_GENES = ("CYP2D6", "CYP2C19", "CYP2C9")


class UnsupportedDrugError(ValueError):
    pass


@dataclass(frozen=True)
class RuleDecision:
    risk: str
    recommendation: str


PHENOTYPE_TABLE = {
    "CYP2D6": {
        "*1/*1": "NM",
        "*1/*4": "IM",
        "*4/*4": "PM",
    },
    "CYP2C19": {
        "*1/*1": "NM",
        "*1/*2": "IM",
        "*2/*2": "PM",
    },
    "CYP2C9": {
        "*1/*1": "NM",
        "*1/*3": "IM",
        "*3/*3": "PM",
    },
}


CPIC_RULES = {
    "CODEINE": {
        "gene": "CYP2D6",
        "phenotypes": {
            "NM": RuleDecision(
                risk="Safe",
                recommendation="Use standard dosing per CPIC-guided interpretation.",
            ),
            "IM": RuleDecision(
                risk="Adjust Dosage",
                recommendation="Consider alternative analgesic or monitor for reduced effect.",
            ),
            "PM": RuleDecision(
                risk="Toxic",
                recommendation="Avoid codeine and use a non-CYP2D6-dependent analgesic.",
            ),
        },
    },
    "CLOPIDOGREL": {
        "gene": "CYP2C19",
        "phenotypes": {
            "NM": RuleDecision(
                risk="Safe",
                recommendation="Use standard clopidogrel therapy.",
            ),
            "IM": RuleDecision(
                risk="Adjust Dosage",
                recommendation="Consider alternative antiplatelet based on clinical context.",
            ),
            "PM": RuleDecision(
                risk="Toxic",
                recommendation="Avoid clopidogrel; prefer alternative antiplatelet therapy.",
            ),
        },
    },
    "WARFARIN": {
        "gene": "CYP2C9",
        "phenotypes": {
            "NM": RuleDecision(
                risk="Safe",
                recommendation="Use standard initiation with INR monitoring.",
            ),
            "IM": RuleDecision(
                risk="Adjust Dosage",
                recommendation="Consider lower initial dose and closer INR monitoring.",
            ),
            "PM": RuleDecision(
                risk="Toxic",
                recommendation="Use substantially lower dose and intensive INR monitoring.",
            ),
        },
    },
}


SEVERITY_BY_RISK = {
    "Safe": "none",
    "Adjust Dosage": "moderate",
    "Toxic": "high",
    "Unknown": "moderate",
}


def _extract_patient_id(lines: list[str], fallback_name: str) -> str:
    for line in lines:
        if line.startswith("##SAMPLE="):
            match = re.search(r"ID=([^,>]+)", line)
            if match:
                return match.group(1).strip()
    for line in lines:
        if line.startswith("#CHROM"):
            parts = line.split("\t")
            if len(parts) > 9 and parts[9].strip():
                return parts[9].strip()
    return fallback_name


def _extract_gene(text: str) -> str | None:
    upper_text = text.upper()
    for field in ("GENE", "SYMBOL", "GENE_NAME", "HGNC"):
        match = re.search(rf"{field}=([^;]+)", upper_text)
        if match:
            raw_value = match.group(1).split(",")[0].strip()
            if raw_value in SUPPORTED_GENES:
                return raw_value
    for gene in SUPPORTED_GENES:
        if gene in upper_text:
            return gene
    return None


def _extract_stars(text: str) -> list[str]:
    found = re.findall(r"\*[0-9A-Za-z]+(?:x\d+)?", text, flags=re.IGNORECASE)
    normalized = []
    for star in found:
        clean_star = star.upper()
        if clean_star not in normalized:
            normalized.append(clean_star)
    return normalized


def _extract_rsid(line: str, id_column: str) -> str | None:
    if id_column.startswith("rs"):
        return id_column
    match = re.search(r"\brs\d+\b", line, flags=re.IGNORECASE)
    if match:
        return match.group(0).lower()
    return None


def parse_vcf(vcf_text: str, filename: str) -> dict:
    parsed_genes: dict[str, dict[str, list[str]]] = {}
    lines = [line.rstrip("\n") for line in vcf_text.splitlines()]
    patient_id = _extract_patient_id(lines, Path(filename).stem or "Unknown")

    for line in lines:
        if not line or line.startswith("#"):
            continue
        columns = line.split("\t")
        if len(columns) < 8:
            continue

        rsid = _extract_rsid(line, columns[2].strip())
        info = columns[7].strip()
        combined_text = f"{line};{info}"
        gene = _extract_gene(combined_text)
        if not gene:
            continue

        if gene not in parsed_genes:
            parsed_genes[gene] = {"stars": [], "rsids": []}

        for star in _extract_stars(combined_text):
            if star not in parsed_genes[gene]["stars"]:
                parsed_genes[gene]["stars"].append(star)

        if rsid and rsid not in parsed_genes[gene]["rsids"]:
            parsed_genes[gene]["rsids"].append(rsid)

    return {
        "patient_id": patient_id,
        "genes": parsed_genes,
        "vcf_parsing_success": True,
    }


def _star_sort_key(star: str) -> tuple[int, str]:
    match = re.match(r"\*(\d+)(.*)", star)
    if not match:
        return (9999, star)
    return (int(match.group(1)), match.group(2))


def build_diplotype(stars: list[str]) -> str | None:
    if len(stars) < 2:
        return None
    first_two = sorted(stars[:2], key=_star_sort_key)
    return f"{first_two[0]}/{first_two[1]}"


def map_phenotype(gene: str, diplotype: str | None) -> str:
    if not diplotype:
        return "Unknown"
    return PHENOTYPE_TABLE.get(gene, {}).get(diplotype, "Unknown")


def _confidence_score(gene_detected: bool, diplotype_complete: bool, rule_applied: bool) -> float:
    score = 0.0
    if gene_detected:
        score += 0.4
    if diplotype_complete:
        score += 0.3
    if rule_applied:
        score += 0.3
    return round(min(score, 1.0), 2)


def _unknown_recommendation(required_gene: str) -> str:
    return f"Insufficient data to apply CPIC rule for {required_gene}."


def analyze_vcf_and_drug(vcf_bytes: bytes, filename: str, drug_name: str) -> dict:
    try:
        vcf_text = vcf_bytes.decode("utf-8")
        parsed = parse_vcf(vcf_text, filename)
    except UnicodeDecodeError:
        parsed = {
            "patient_id": Path(filename).stem or "Unknown",
            "genes": {},
            "vcf_parsing_success": False,
        }

    normalized_drug = drug_name.strip().upper()
    if normalized_drug not in CPIC_RULES:
        raise UnsupportedDrugError(f"Unsupported drug: {drug_name}")

    rule_config = CPIC_RULES[normalized_drug]
    required_gene = rule_config["gene"]
    gene_data = parsed["genes"].get(required_gene)

    gene_detected = bool(gene_data and (gene_data["stars"] or gene_data["rsids"]))
    diplotype = build_diplotype(gene_data["stars"]) if gene_data else None
    phenotype = map_phenotype(required_gene, diplotype)
    rule_decision = rule_config["phenotypes"].get(phenotype)
    rule_applied = bool(rule_decision)

    if rule_decision:
        risk = rule_decision.risk
        recommendation = rule_decision.recommendation
    else:
        risk = "Unknown"
        recommendation = _unknown_recommendation(required_gene)

    confidence_score = _confidence_score(gene_detected, bool(diplotype), rule_applied)
    severity = SEVERITY_BY_RISK.get(risk, "moderate")

    return {
        "patient_id": parsed["patient_id"],
        "drug": normalized_drug,
        "gene": required_gene,
        "diplotype": diplotype or "Unknown",
        "phenotype": phenotype,
        "risk": risk,
        "recommendation": recommendation,
        "severity": severity,
        "confidence_score": confidence_score,
        "rsids": gene_data["rsids"] if gene_data else [],
        "parsed_genes": parsed["genes"],
        "quality_metrics": {
            "vcf_parsing_success": parsed["vcf_parsing_success"],
            "gene_detected": gene_detected,
            "rule_applied": rule_applied,
            "confidence_score": confidence_score,
        },
        "clinical_trace": {
            "drug_requested": normalized_drug,
            "required_gene": required_gene,
            "detected_diplotype": diplotype or "Unknown",
            "derived_phenotype": phenotype,
            "cpic_rule_applied": "Yes" if rule_applied else "No",
            "final_risk_outcome": risk,
        },
    }
