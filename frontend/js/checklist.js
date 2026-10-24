const serviceRoot = document.querySelector("[data-service-app]");
const checklistRoot = document.querySelector("[data-checklist-app]");

if (serviceRoot || checklistRoot) {
	const selectedKey = "lifegraph.selectedServiceId";
	const reminderKeys = [
		"service.reminderConfirm",
		"service.reminderAvailability",
	];
	const t = (key, values) => window.LifeGraphI18n?.t(key, values) || key;
	const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
	const detail = document.querySelector("[data-service-detail]");
	const feedback = document.querySelector("[data-catalogue-feedback]");
	const search = document.querySelector("[data-service-search]");
	let services = [];
	let selectedService = null;
	let feedbackKey = "service.feedbackLoading";
	let serviceLoadError = false;

	const showFeedback = (key) => {
		feedbackKey = key;
		if (feedback) feedback.textContent = t(key);
	};

	const make = (tag, className, text) => {
		const element = document.createElement(tag);
		if (className) element.className = className;
		if (text !== undefined) element.textContent = text;
		return element;
	};

	const selectChecklistService = (service) => {
		selectedService = service;
		try {
			localStorage.setItem(selectedKey, service.id);
		} catch {
			showFeedback("service.feedbackSelectionStorage");
		}
		const params = new URLSearchParams(window.location.search);
		params.set("service", service.id);
		window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
		renderDetails(service);
	};

	const renderEmptyChecklist = () => {
		if (!detail) return;
		detail.replaceChildren();
		if (serviceLoadError || !services.length) {
			detail.append(make("p", "empty-state", t("service.feedbackError")));
			return;
		}

		detail.append(make("h2", "detail-title", t("checklist.chooseService")));
		detail.append(make("p", "service-purpose", t("checklist.chooseServiceHelp")));
		const choices = make("div", "checklist-service-options");
		for (const service of services) {
			const button = make("button", "service-option");
			button.type = "button";
			button.append(make("strong", "", window.LifeGraphI18n?.serviceName(service) || service.name));
			button.append(make("small", "", t("service.needsVerification")));
			button.addEventListener("click", () => selectChecklistService(service));
			choices.append(button);
		}
		detail.append(choices);
	};

	const saveChecklistState = async (serviceId, kind, index, checked) => {
		const response = await fetch(`/api/checklists/${encodeURIComponent(serviceId)}`, {
			method: "PUT",
			headers: {
				"Content-Type": "application/json",
				"X-CSRFToken": csrfToken,
			},
			body: JSON.stringify({ kind, index, checked }),
		});
		if (response.status === 401) {
			showFeedback("service.loginToSaveProgress");
			throw new Error("Authentication required.");
		}
		if (!response.ok) {
			const payload = await response.json().catch(() => ({}));
			throw new Error(payload.error || t("service.feedbackStorage"));
		}
	};

	const evidenceValue = (value) => {
		if (value === "Not verified") return t("service.notVerified");
		if (value === "Not stated by source") return t("service.notStatedBySource");
		return value || t("service.notVerified");
	};
	const localizedEvidenceValue = (metadata, key) => (
		window.LifeGraphI18n?.language === "ta" && metadata[`${key}_ta`]
			? metadata[`${key}_ta`]
			: evidenceValue(metadata[key])
	);

	const renderChecklist = (service, target) => {
		const savedRequirements = Array(service.requirements.length).fill(false);
		const saved = Array(reminderKeys.length).fill(false);
		let updateRequirementProgress = () => {};
		let updateReminderProgress = () => {};
		const requirementsPanel = make("section", "checklist-section");
		const requirementsStatus = service.requirement_verification_status || service.verification_status;
		const sourceMetadata = service.checklist_metadata || {};
		const requirementsVerified = requirementsStatus === "verified"
			&& service.requirements.length > 0;
		requirementsPanel.append(make(
			"h3",
			"detail-section-title",
			t(requirementsVerified ? "service.sourceDocumentsHeading" : "service.requirementsHeading")
		));
		const statusKey = requirementsVerified
			? "service.verified"
			: "service.needsVerification";
		requirementsPanel.append(make("span", "verification-badge", t(statusKey)));
		const hasRequirementsSource = requirementsVerified && service.requirements_source_url;
		const instructions = make(
			"a",
			"source-link requirement-source-link",
			t(hasRequirementsSource ? "service.openRequirementsSource" : "service.openOfficialPortal")
		);
		instructions.href = hasRequirementsSource
			? service.requirements_source_url
			: service.official_portal_url || service.source_url;
		instructions.target = "_blank";
		instructions.rel = "noopener noreferrer";
		requirementsPanel.append(instructions);
		if (sourceMetadata.source_title) {
			requirementsPanel.append(make(
				"p",
				"verification-message source-attribution",
				t("service.checklistSource", {
					title: window.LifeGraphI18n?.language === "ta"
						? sourceMetadata.source_title_ta || sourceMetadata.source_title
						: sourceMetadata.source_title,
					updated: sourceMetadata.source_last_updated || t("service.notVerified"),
					checked: sourceMetadata.verification_date || t("service.notVerified"),
				})
			));
		}
		requirementsPanel.append(make("p", "verification-notice", t("service.verifyBeforeApply")));
		if (sourceMetadata.source_last_updated) {
			requirementsPanel.append(make(
				"p",
				"verification-message",
				t("service.sourceCurrentness", {
					updated: sourceMetadata.source_last_updated,
				})
			));
		}
		if (!requirementsVerified) {
			requirementsPanel.append(make(
				"p",
				"verification-message",
				service.requirements.length
					? t("service.requirementItemsUnverified")
					: t("service.requirementsUnverified")
			));
		}
		if (service.requirements.length) {
			if (sourceMetadata.mandatory_optional_classification) {
				requirementsPanel.append(make(
					"p",
					"verification-message requirement-classification",
					t("service.requirementClassification", {
						classification: evidenceValue(
							sourceMetadata.mandatory_optional_classification
						),
					})
				));
			}
			if (window.LifeGraphI18n?.language === "ta") {
				requirementsPanel.append(make("p", "verification-message", t("service.requirementTranslationNote")));
			}
			const progressLabel = make("p", "progress-label");
			const progress = make("progress", "checklist-progress");
			progress.max = service.requirements.length;
			progress.setAttribute("aria-label", t(
				requirementsVerified
					? "service.sourceDocumentProgressLabel"
					: "service.requirementProgressLabel"
			));
			updateRequirementProgress = () => {
				const done = service.requirements.reduce(
					(count, _, index) => count + (savedRequirements[index] ? 1 : 0),
					0
				);
				progressLabel.textContent = t(
					requirementsVerified
						? "service.sourceDocumentProgress"
						: "service.requirementProgress",
					{
						done,
						total: service.requirements.length,
					}
				);
				progress.value = done;
			};
			requirementsPanel.append(progressLabel, progress);

			const requirementList = make("div", "reminder-list requirement-checklist");
			service.requirements.forEach((requirement, index) => {
				const label = make("label", "reminder-item");
				const input = document.createElement("input");
				input.type = "checkbox";
				input.disabled = true;
				input.dataset.checklistKind = "requirement";
				input.dataset.checklistIndex = String(index);
				input.setAttribute(
					"aria-label",
					window.LifeGraphI18n?.serviceRequirement(service, index) || requirement
				);
				input.addEventListener("change", async () => {
					const next = input.checked;
					input.disabled = true;
					try {
						await saveChecklistState(service.id, "requirement", index, next);
						savedRequirements[index] = next;
					} catch (error) {
						input.checked = !next;
						showFeedback(error.message === "Authentication required."
							? "service.loginToSaveProgress"
							: "service.feedbackStorage");
					} finally {
						input.disabled = false;
						updateRequirementProgress();
					}
				});
				label.append(input, make(
					"span",
					"",
					window.LifeGraphI18n?.serviceRequirement(service, index) || requirement
				));
				requirementList.append(label);
			});
			updateRequirementProgress();
			requirementsPanel.append(requirementList);
		} else {
			requirementsPanel.append(make("p", "empty-requirements", t("service.noProofItems")));
		}
		const limitations = make("dl", "verification-limits");
		for (const [labelKey, valueKey] of [
			["service.eligibility", "eligibility"],
			["service.fees", "fees"],
			["service.processingTime", "processing_time"],
			["service.originalsCopies", "originals_or_photocopies"],
		]) {
			limitations.append(
				make("dt", "", t(labelKey)),
				make("dd", "", localizedEvidenceValue(sourceMetadata, valueKey))
			);
		}
		requirementsPanel.append(limitations);
		target.append(requirementsPanel);

		const reminderPanel = make("section", "checklist-section reminder-section");
		const heading = make("div", "reminder-heading");
		heading.append(make("h3", "detail-section-title", t("service.remindersHeading")));
		heading.append(make("span", "demo-label", t("service.demoNotRequirements")));
		reminderPanel.append(heading);
		reminderPanel.append(make("p", "reminder-caption", t("service.reminderDescription")));
		reminderPanel.append(make("p", "preparation-status-note", t("service.personalProgressNote")));

		const progressLabel = make("p", "progress-label");
		const progress = make("progress", "checklist-progress");
		progress.max = reminderKeys.length;
		progress.setAttribute("aria-label", t("service.progressLabel"));
		updateReminderProgress = () => {
			const doneCount = reminderKeys.reduce(
				(count, _, index) => count + (saved[index] ? 1 : 0),
				0
			);
			progressLabel.textContent = t("service.reminderProgress", {
				done: doneCount,
				total: reminderKeys.length,
			});
			progress.value = doneCount;
		};
		updateReminderProgress();
		reminderPanel.append(progressLabel, progress);

		const list = make("div", "reminder-list");
		reminderKeys.forEach((reminderKey, index) => {
			const label = make("label", "reminder-item");
			const input = document.createElement("input");
			input.type = "checkbox";
			input.disabled = true;
			input.dataset.checklistKind = "reminder";
			input.dataset.checklistIndex = String(index);
			input.setAttribute("aria-label", t(reminderKey));
			input.addEventListener("change", async () => {
				const next = input.checked;
				input.disabled = true;
				try {
					await saveChecklistState(service.id, "reminder", index, next);
					saved[index] = next;
				} catch (error) {
					input.checked = !next;
					showFeedback(error.message === "Authentication required."
						? "service.loginToSaveProgress"
						: "service.feedbackStorage");
				} finally {
					input.disabled = false;
					updateReminderProgress();
				}
			});
			label.append(input, make("span", "", t(reminderKey)));
			list.append(label);
		});
		reminderPanel.append(list);
		target.append(reminderPanel);

		fetch(`/api/checklists/${encodeURIComponent(service.id)}`)
			.then(async (response) => {
				if (response.status === 401) {
					target.querySelectorAll("[data-checklist-kind]").forEach((input) => {
						input.disabled = true;
					});
					showFeedback("service.loginToSaveProgress");
					return null;
				}
				const payload = await response.json();
				if (!response.ok) throw new Error(payload.error || t("service.feedbackStorage"));
				return payload;
			})
			.then((payload) => {
				if (!payload) return;
				payload.requirements.forEach((checked, index) => {
					savedRequirements[index] = Boolean(checked);
				});
				payload.reminders.forEach((checked, index) => {
					saved[index] = Boolean(checked);
				});
				target.querySelectorAll("[data-checklist-kind]").forEach((input) => {
					const values = input.dataset.checklistKind === "requirement"
						? payload.requirements
						: payload.reminders;
					input.checked = Boolean(values[Number(input.dataset.checklistIndex)]);
					input.disabled = false;
				});
				updateRequirementProgress();
				updateReminderProgress();
			})
			.catch(() => showFeedback("service.feedbackStorage"));
	};

	const renderDetails = (service, target = detail) => {
		if (!target) return;
		target.replaceChildren();
		const header = make("div", "detail-header");
		header.append(make("p", "eyebrow", service.category || t("service.region")));
		header.append(make("span", "demo-label", t("service.catalogueEntry")));
		const language = window.LifeGraphI18n?.language;
		target.append(header, make("h2", "detail-title", window.LifeGraphI18n?.serviceName(service) || service.name));
		if (language === "ta") {
			target.append(make("p", "translation-warning", t("service.translationUnverified")));
			target.append(make("p", "service-purpose-source", `${t("service.serviceNameSource")} ${service.name}`));
		}
		target.append(make("p", "service-purpose", window.LifeGraphI18n?.servicePurpose(service) || service.description || service.purpose));
		if (language === "ta") {
			target.append(make("p", "translation-warning", t("service.purposeTranslationNote")));
		}
		if (service.responsible_authority) {
			const authority = window.LifeGraphI18n?.serviceAuthority(service)
				|| service.responsible_authority;
			target.append(make("p", "service-authority", `${t("service.responsibleAuthority")} ${authority}`));
		}

		const requirementsStatus = service.requirement_verification_status || service.verification_status;
		const statusKey = requirementsStatus === "verified"
			? "service.verified"
			: "service.needsVerification";
		const status = make("p", "detail-verification");
		status.append(
			make("span", "verification-badge", t(statusKey)),
			make("span", "verified-date", t("service.lastVerified", {
				date: service.last_verified || t("service.notVerified"),
			}))
		);
		target.append(status);

		const applicationLink = make("a", "source-link", t("service.openOfficialPortal"));
		applicationLink.href = service.official_application_url
			|| service.official_portal_url
			|| service.source_url;
		applicationLink.target = "_blank";
		applicationLink.rel = "noopener noreferrer";
		target.append(make("p", "link-label", t("service.applicationLinkLabel")), applicationLink);
		if (service.requirements_source_url) {
			const requirementsLink = make("a", "source-link", t("service.openRequirementsSource"));
			requirementsLink.href = service.requirements_source_url;
			requirementsLink.target = "_blank";
			requirementsLink.rel = "noopener noreferrer";
			target.append(make("p", "link-label", t("service.requirementsSourceLabel")), requirementsLink);
		}
		if (requirementsStatus !== "verified") {
			target.append(make("p", "verification-warning", t("service.unverifiedWarning")));
		}
		renderChecklist(service, target);

		if (serviceRoot) {
			const checklistLink = make("a", "button button-primary checklist-link", t("service.openChecklist"));
			checklistLink.href = `/checklist?service=${encodeURIComponent(service.id)}`;
			target.append(checklistLink);
		}
	};

	const selectService = (service) => {
		selectedService = service;
		try {
			localStorage.setItem(selectedKey, service.id);
		} catch {
			showFeedback("service.feedbackSelectionStorage");
		}
		const params = new URLSearchParams(window.location.search);
		params.set("service", service.id);
		window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
		if (serviceRoot) renderServices(services, search?.value || "");
		renderDetails(service);
	};

	const renderServices = (items, query = "", emptyMessageKey = "service.noMatches") => {
		const list = document.querySelector("[data-service-list]");
		const count = document.querySelector("[data-service-count]");
		if (!list) return;
		list.replaceChildren();
		const normalizedQuery = query.trim().toLocaleLowerCase();
		const filteredItems = items.filter((service) => {
			const translatedName = window.LifeGraphI18n?.serviceName(service) || service.name;
			return `${service.name} ${translatedName}`.toLocaleLowerCase().includes(normalizedQuery);
		});
		if (count) count.textContent = `(${filteredItems.length})`;
		if (!filteredItems.length) {
			list.append(make("p", "empty-state", t(emptyMessageKey)));
			return;
		}
		const groups = new Map();
		for (const service of filteredItems) {
			const category = service.category || t("service.uncategorized");
			if (!groups.has(category)) groups.set(category, []);
			groups.get(category).push(service);
		}
		for (const [category, groupServices] of groups) {
			const section = make("section", "service-category-group");
			section.append(make("h3", "service-category-title", category === "Everyday Government Services"
				? t("service.everydayCategory")
				: category));
			const categoryItems = make("div", "service-category-items");
			for (const service of groupServices) {
				const button = make("button", "service-option");
				button.type = "button";
				button.setAttribute("aria-pressed", String(selectedService?.id === service.id));
				const icon = make("span", "service-option-icon");
				icon.setAttribute("aria-hidden", "true");
				const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
				svg.setAttribute("viewBox", "0 0 24 24");
				const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
				if (category === "Tamil Nadu e-Sevai Certificates") {
					path.setAttribute("d", "M7 3.75h7l4 4V20H7zM14 4v4h4M10 12h5M10 15h5");
				} else {
					path.setAttribute("d", "M4 20h16M6 20V9l6-4 6 4v11M9 12h2m2 0h2m-6 4h2m2 0h2");
				}
				svg.append(path);
				icon.append(svg);
				button.append(icon);
				button.append(make("strong", "", window.LifeGraphI18n?.serviceName(service) || service.name));
				button.append(make("small", "", t(
					(service.requirement_verification_status || service.verification_status) === "verified"
						? "service.verified"
						: "service.needsVerification"
				)));
				button.addEventListener("click", () => selectService(service));
				categoryItems.append(button);
			}
			section.append(categoryItems);
			list.append(section);
		}
	};

	const loadServices = async (query = "") => {
		showFeedback("service.feedbackLoading");
		try {
			const response = await fetch("/api/services");
			const payload = await response.json();
			if (!response.ok) throw new Error(t("service.feedbackError"));
			services = payload.services;
			serviceLoadError = false;
			showFeedback("service.feedbackCatalogue");
			if (serviceRoot) {
				renderServices(services, query);
				const current = services.find((item) => item.id === selectedService?.id);
				if (current) renderDetails(current);
			}
			return services;
		} catch {
			serviceLoadError = true;
			showFeedback("service.feedbackError");
			if (serviceRoot) renderServices([], "", "service.feedbackError");
			return [];
		}
	};

	if (serviceRoot) {
		search?.addEventListener("input", () => {
			renderServices(
				services,
				search.value,
				serviceLoadError ? "service.feedbackError" : "service.noMatches"
			);
		});
	}

	window.addEventListener("lifegraph:languagechange", () => {
		showFeedback(feedbackKey);
		if (serviceRoot) {
			renderServices(
				services,
				search?.value || "",
				serviceLoadError ? "service.feedbackError" : "service.noMatches"
			);
		}
		if (selectedService) renderDetails(selectedService);
		else if (checklistRoot) renderEmptyChecklist();
	});

	loadServices().then((items) => {
		if (checklistRoot) {
			const params = new URLSearchParams(window.location.search);
			let preferredId = params.get("service");
			if (!preferredId) {
				try {
					preferredId = localStorage.getItem(selectedKey);
				} catch {
					preferredId = null;
					showFeedback("service.feedbackSelectionStorage");
				}
			}
			const selected = items.find((service) => service.id === preferredId);
			if (selected) {
				selectedService = selected;
				renderDetails(selected);
			} else {
				renderEmptyChecklist();
			}
		} else {
			let preferredId = new URLSearchParams(window.location.search).get("service");
			if (!preferredId) {
				try {
					preferredId = localStorage.getItem(selectedKey);
				} catch {
					preferredId = null;
					showFeedback("service.feedbackSelectionStorage");
				}
			}
			const selected = items.find((service) => service.id === preferredId);
			if (selected) selectService(selected);
		}
	});
}
