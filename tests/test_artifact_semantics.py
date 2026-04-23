from __future__ import annotations

from memco.artifact_semantics import build_artifact_context, evaluate_artifact_freshness
from memco.config import Settings, write_settings


def test_evaluate_artifact_freshness_marks_current_and_stale_artifacts(tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    write_settings(settings)
    context = build_artifact_context(project_root=project_root)

    current = evaluate_artifact_freshness({"artifact_context": context}, project_root=project_root)
    assert current["status"] == "current"
    assert current["current_for_checkout_config"] is True

    stale_checkout_context = {
        **context,
        "checkout": {
            **context["checkout"],
            "status_sha256": "old-checkout-status",
        },
    }
    stale_checkout = evaluate_artifact_freshness(
        {"artifact_context": stale_checkout_context},
        project_root=project_root,
    )
    assert stale_checkout["status"] == "stale"
    assert stale_checkout["current_for_checkout_config"] is False
    assert stale_checkout["stale_relative_to_current_checkout"] is True

    stale_config_context = {
        **context,
        "config_source": {
            **context["config_source"],
            "sha256": "old-config-sha",
        },
    }
    stale_config = evaluate_artifact_freshness(
        {"artifact_context": stale_config_context},
        project_root=project_root,
    )
    assert stale_config["status"] == "stale"
    assert stale_config["current_for_checkout_config"] is False
    assert stale_config["stale_relative_to_current_config"] is True

    stale_env_context = {
        **context,
        "status_source": "env-injected",
        "env_overrides": {
            "used": True,
            "present_keys": ["MEMCO_LLM_API_KEY"],
            "live_credentials_present": True,
            "live_credential_keys": ["MEMCO_LLM_API_KEY"],
        },
    }
    stale_env = evaluate_artifact_freshness(
        {"artifact_context": stale_env_context},
        project_root=project_root,
    )
    assert stale_env["status"] == "stale"
    assert stale_env["current_for_checkout_config"] is False
    assert stale_env["stale_relative_to_current_env"] is True


def test_evaluate_artifact_freshness_marks_legacy_artifact_unknown(tmp_path):
    project_root = tmp_path / "repo"
    settings = Settings(root=project_root)
    write_settings(settings)

    result = evaluate_artifact_freshness({}, project_root=project_root)

    assert result["status"] == "unknown_legacy_artifact"
    assert result["current_for_checkout_config"] is False
    assert result["reason"] == "artifact_missing_context"
