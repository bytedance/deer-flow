"""Unit tests for cross-modal consistency auditing."""

from __future__ import annotations

from src.scientific_vision.cross_modal_consistency import (
    build_consistency_audit,
    extract_candidate_claims,
    merge_vision_recheck,
)


def test_extract_candidate_claims_handles_quantitative_scientific_text():
    text = "条带明显变暗，处理组信号降低约20%。另外细胞群发生偏移。"
    claims = extract_candidate_claims(text, max_claims=10)
    assert len(claims) >= 2
    assert any(isinstance(c.get("numbers"), list) and 20.0 in c.get("numbers") for c in claims)
    assert any(c.get("claim_type") in {"western_blot_intensity", "facs_population", "embedding_shift"} for c in claims)


def test_build_consistency_audit_supports_claim_when_evidence_matches():
    narrative = "处理组条带变暗约20%，并且聚类分离更清晰。"
    report_payload = {
        "image": {"image_path": "/mnt/user-data/uploads/fig1.png"},
        "report": {
            "image_type": "western_blot",
            "findings": [
                {"claim": "treated lane appears darker than control", "evidence_ids": ["E1"]},
                {"claim": "signal decrease is approximately 18-22%", "evidence_ids": ["E2"]},
            ],
            "quantitative_observations": [
                {"metric": "signal_drop", "estimate": "20% decrease"},
            ],
        },
    }
    analysis_payload = {
        "schema_version": "deerflow.raw_data.embedding_analysis.v1",
        "runs": [
            {
                "silhouette_cluster": 0.63,
                "knn_batch_mixing": {"mixing_score": 0.71},
            }
        ],
    }

    audit = build_consistency_audit(
        narrative_text=narrative,
        report_payloads=[report_payload],
        analysis_payloads=[analysis_payload],
        report_paths=["/mnt/user-data/outputs/report.json"],
        analysis_paths=["/mnt/user-data/outputs/analysis.json"],
        max_claims=10,
    )
    assert audit["schema_version"] == "deerflow.cross_modal_consistency.v1"
    assert audit["summary"]["claims_total"] >= 1
    assert len(audit["claims"]) >= 1
    assert any(c["verdict"] in {"supported", "partially_supported"} for c in audit["claims"])


def test_build_consistency_audit_emits_claim_decomposition_provenance_uncertainty():
    narrative = "处理组条带降低约20%，并在药物处理后出现更明显分离。"
    report_payload = {
        "report": {
            "image_type": "western_blot",
            "findings": [{"claim": "treated lane appears darker with around 20% drop"}],
        }
    }
    audit = build_consistency_audit(
        narrative_text=narrative,
        report_payloads=[report_payload],
        analysis_payloads=[],
        report_paths=["/mnt/user-data/outputs/report.json"],
        analysis_paths=[],
    )
    assert audit["claims"]
    claim = audit["claims"][0]
    assert claim.get("entailment") in {"supported", "partial", "contradicted"}
    assert isinstance(claim.get("claim_decomposition"), dict)
    assert isinstance(claim.get("provenance"), list)
    assert isinstance(claim.get("uncertainty"), dict)


def test_merge_vision_recheck_can_promote_contradicted_verdict():
    audit = {
        "summary": {"claims_total": 1, "supported": 1, "partially_supported": 0, "unsupported": 0, "contradicted": 0},
        "claims": [
            {
                "id": "C1",
                "text": "signal decreased",
                "claim_type": "western_blot_intensity",
                "verdict": "supported",
            }
        ],
    }
    merged = merge_vision_recheck(
        audit_payload=audit,
        vision_checks={
            "C1": {
                "verdict": "contradicted",
                "reason": "visual recheck indicates opposite trend",
                "confidence": 0.8,
            }
        },
    )
    assert merged["claims"][0]["verdict"] == "contradicted"
    assert merged["summary"]["contradicted"] == 1

