"""Prepare safe checklist responses from catalogue service records."""


def build_checklist(service):
	requirements = service["requirements"]
	return {
		"service_id": service["id"],
		"requirements": requirements,
		"checklist_metadata": service["checklist_metadata"],
		"category": service["category"],
		"responsible_authority": service["responsible_authority"],
		"official_application_url": service["official_application_url"],
		"official_portal_url": service["official_portal_url"],
		"requirements_source_url": service["requirements_source_url"],
		"source_url": service["source_url"],
		"source_title": service["checklist_metadata"].get("source_title"),
		"verification_date": service["checklist_metadata"].get("verification_date"),
		"source_last_updated": service["checklist_metadata"].get("source_last_updated"),
		"mandatory_optional_classification": service["checklist_metadata"].get(
			"mandatory_optional_classification", "Not verified"
		),
		"eligibility": service["checklist_metadata"].get("eligibility", "Not verified"),
		"fees": service["checklist_metadata"].get("fees", "Not verified"),
		"processing_time": service["checklist_metadata"].get(
			"processing_time", "Not verified"
		),
		"originals_or_photocopies": service["checklist_metadata"].get(
			"originals_or_photocopies", "Not verified"
		),
		"verification_status": service["requirement_verification_status"],
		"requirement_verification_status": service["requirement_verification_status"],
		"message": (
			"Needs verification: no official proof requirements are confirmed."
			if service["requirement_verification_status"] != "verified" or not requirements
			else "Verify with the official authority before applying."
		),
	}