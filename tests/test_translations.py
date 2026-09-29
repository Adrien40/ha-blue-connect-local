"""Translation consistency: no duplicate, missing, or empty key."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

COMPONENT = Path(__file__).parent.parent / "custom_components" / "blue_connect_local"
ROOT = COMPONENT.parent.parent
STRINGS = COMPONENT / "strings.json"
TRANSLATIONS = sorted((COMPONENT / "translations").glob("*.json"))
ALL_FILES = [STRINGS, *TRANSLATIONS]


def _no_duplicates(pairs):
    keys = [k for k, _ in pairs]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise ValueError(f"duplicate JSON keys: {sorted(dupes)}")
    return dict(pairs)


def _load(path: Path) -> dict:
    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates
    )


def _keys(d: dict, prefix: str = "") -> set[str]:
    out: set[str] = set()
    for k, v in d.items():
        out.add(f"{prefix}/{k}")
        if isinstance(v, dict):
            out |= _keys(v, f"{prefix}/{k}")
    return out


def _codes_returned_by(filename: str, function: str) -> set[str]:
    tree = ast.parse((COMPONENT / filename).read_text(encoding="utf-8"))
    func = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == function
    )
    return {
        node.value.elts[1].value
        for node in ast.walk(func)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Tuple)
        and len(node.value.elts) == 2
        and isinstance(node.value.elts[1], ast.Constant)
    }


def _error_keys_in_flows() -> set[str]:
    """Error keys set by the config flow (`errors[...] = "code"`)."""
    tree = ast.parse((COMPONENT / "config_flow.py").read_text(encoding="utf-8"))
    return {
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and any(
            isinstance(t, ast.Subscript)
            and isinstance(t.value, ast.Name)
            and t.value.id == "errors"
            for t in node.targets
        )
    }


def test_translation_files_exist():
    assert len(TRANSLATIONS) >= 19
    assert (COMPONENT / "translations" / "fr.json").exists()


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_valid_json_without_duplicate_keys(path):
    _load(path)


@pytest.mark.parametrize("path", TRANSLATIONS, ids=lambda p: p.name)
def test_same_keys_as_strings_json(path):
    reference = _keys(_load(STRINGS))
    keys = _keys(_load(path))
    assert not reference - keys, f"missing in {path.name}: {sorted(reference - keys)}"
    assert not keys - reference, (
        f"unexpected in {path.name}: {sorted(keys - reference)}"
    )


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_every_validation_error_is_translated_in_both_flows(path):
    data = _load(path)
    codes = _codes_returned_by("validation.py", "validate_calibration")
    codes |= _error_keys_in_flows()
    codes.discard("base")
    assert {"ph_slope_mismatch", "invalid_access_code"} <= codes, (
        "AST extraction broken"
    )
    for flow in ("config", "options"):
        missing = codes - set(data[flow]["error"])
        # `mac_conflict`, `no_mac_provided`, `invalid_mac` only exist in the
        # initial config flow.
        if flow == "options":
            missing -= {"mac_conflict", "no_mac_provided", "invalid_mac"}
        assert not missing, f"{path.name}: {flow}.error lacks {sorted(missing)}"


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_no_empty_strings(path):
    def walk(node, trail=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{trail}/{k}")
        else:
            assert str(node).strip(), f"empty string at {trail}"

    walk(_load(path))


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_raw_orp_sensor_is_translated(path):
    assert _load(path)["entity"]["sensor"]["orp_raw"]["name"].strip()


def test_manifest_and_hacs_are_consistent():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == COMPONENT.name
    assert "bluetooth" in manifest["dependencies"]
    assert all(p.isdigit() for p in manifest["version"].split("."))
    assert hacs["homeassistant"] == "2026.3.0"
    assert hacs["render_readme"] is True


def test_config_flow_fields_have_descriptions():
    """config-flow rule: fields carry a `data_description` (source strings)."""
    steps = _load(STRINGS)["config"]["step"]
    assert {"mac_address", "manual_mac_address", "access_code"} <= set(
        steps["user"]["data_description"]
    )
    assert "access_code" in steps["reauth_confirm"]["data_description"]
    assert {"mac_address", "access_code"} <= set(
        steps["reconfigure"]["data_description"]
    )
