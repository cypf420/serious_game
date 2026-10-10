"""Conservative interpretation of a document's authorization scope.

Public disclosure is not authorization. Unknown prose must be clarified in
the existing meeting resolution rather than silently applying to every home.
"""
import re


def document_covers_household(document, package, household_id: str) -> bool:
    scope = str(document.resolution_snapshot.get("target_scope") or "").strip()
    village_scopes = {"全村", "全村36户", "全村三十六户", "柳林村36户", "柳林村三十六户", "柳林村全体住户", "全体村民"}
    if scope in village_scopes:
        return True
    if not scope and not document.source_meeting_id:
        # The shipped policy predates meeting snapshots. Only its configured
        # identity/type may use the original explicit village-wide scope.
        return any(
            item.get("document_id") == document.document_id
            and item.get("document_type") == document.document_type
            and bool(village_scopes.intersection(item.get("public_scope", [])))
            for item in (package.governance_config or {}).get("initial_documents", [])
        )
    scope = re.sub(r"^(?:仅限|适用于|适用对象[:：]?|适用范围[:：]?)", "", scope).strip()
    scope = re.sub(r"[，,；;]?不适用于其他家庭[。.]?$", "", scope)
    # Enumerated IDs only: mentioning an ID in an exclusion, range or an
    # uncertain description cannot grant authorization.
    if not re.fullmatch(r"[A-Z]+-\d{2}(?:户)?(?:[、,，;；\s]+[A-Z]+-\d{2}(?:户)?)*[。.]?", scope):
        return False
    ids = set(re.findall(r"[A-Z]+-\d{2}", scope))
    known = {household.household_id for household in package.households}
    return ids <= known and household_id in ids


def normalize_followup_plan(value):
    from serious_game_backend.domain.errors import ActionUnavailableError

    if value is None:
        return None
    fields = {"medical_provider", "recheck_interval_days", "employment_receiver", "medical_fee_arrangement"}
    valid = isinstance(value, dict) and set(value) <= fields
    if valid:
        value = {key: item for key, item in value.items() if item is not None}
        valid = (all(isinstance(value[key], str) and 0 < len(value[key].strip()) <= 120
                     for key in ("medical_provider", "employment_receiver") if key in value)
                 and ("recheck_interval_days" not in value or
                      (type(value["recheck_interval_days"]) is int and 1 <= value["recheck_interval_days"] <= 365))
                 and value.get("medical_fee_arrangement", "allocated_medical_service") == "allocated_medical_service")
    if not valid:
        raise ActionUnavailableError("医疗随访与就业转介附件不完整。", details={"field_errors": {
            "followup_plan": "请填写复查机构、复查周期、费用承担方式与就业接收单位。"}})
    return {key: item.strip() if isinstance(item, str) else item for key, item in value.items()}
