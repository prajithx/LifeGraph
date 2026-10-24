const uploadInput = document.querySelector("[data-document-upload-input]");
const uploadStatus = document.querySelector("[data-document-upload-status]");
const uploadButton = document.querySelector("[data-document-upload-confirm]");
const documentList = document.querySelector("[data-document-list]");
const uploadTriggers = document.querySelectorAll("[data-document-upload-trigger]");
const documentNameInput = document.querySelector("[data-document-name]");
const issueDateInput = document.querySelector("[data-document-issue-date]");
const expiryDateInput = document.querySelector("[data-document-expiry-date]");
const reminderInputs = document.querySelectorAll("[data-document-reminder]");
const reminderList = document.querySelector("[data-document-reminders]");

if (uploadInput && uploadStatus && uploadButton) {
  const maxUploadSize = 10 * 1024 * 1024;
  const supportedExtensions = new Set(["pdf", "png", "jpg", "jpeg"]);
  const translate = (key, values) => window.LifeGraphI18n?.t(key, values) || key;
  const uploadErrorKeys = {
    invalid_filename: "dashboard.documentErrorInvalidFilename",
    unsupported_type: "dashboard.documentErrorUnsupportedType",
    too_large: "dashboard.documentErrorTooLarge",
    empty_file: "dashboard.documentErrorEmptyFile",
    invalid_contents: "dashboard.documentErrorInvalidContents",
    missing_file: "dashboard.documentErrorMissingFile",
    store_failed: "dashboard.documentErrorStoreFailed",
  };
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  let uploading = false;
  let selectedFile = null;
  let selectedFileValid = false;
  let lastStatus = ["dashboard.uploadIdle", {}];

  const renderStatus = () => {
    const values = { ...lastStatus[1] };
    if (values.messageKey) values.message = translate(values.messageKey);
    if (Number.isFinite(values.fileSize)) values.size = formatSize(values.fileSize);
    uploadStatus.textContent = translate(lastStatus[0], values);
  };

  const setStatus = (key, values = {}, state = "") => {
    lastStatus = [key, values];
    renderStatus();
    uploadStatus.dataset.state = state;
  };

  const formatSize = (size) => {
    if (size < 1024 * 1024) {
      return translate("dashboard.uploadSizeKb", {
        size: Math.max(1, Math.ceil(size / 1024)),
      });
    }
    return translate("dashboard.uploadSizeMb", {
      size: (size / (1024 * 1024)).toFixed(2),
    });
  };

  const setUploadButton = (busy) => {
    uploadButton.disabled = busy || !selectedFileValid;
    uploadButton.setAttribute("aria-busy", String(busy));
    uploadButton.textContent = busy
      ? translate("dashboard.uploadingButton")
      : translate("dashboard.confirmUpload");
  };

  const isSupported = (file) => {
    const extension = file.name.split(".").pop()?.toLowerCase();
    return extension && supportedExtensions.has(extension);
  };

  const appendUploadedDocument = (id, filename, size) => {
    if (!documentList) return;
    if (!documentList.querySelector("[data-document-id]")) {
      documentList.replaceChildren();
    }
    const row = document.createElement("li");
    row.className = "uploaded-document";
    row.dataset.documentId = id;

    const icon = document.createElement("span");
    icon.className = "file-icon file-green";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "✓";

    const name = document.createElement("span");
    name.className = "document-name";
    const title = document.createElement("a");
    title.href = `/api/documents/${encodeURIComponent(id)}`;
    title.textContent = filename;
    const details = document.createElement("small");
    details.dataset.documentSize = String(size);
    updateDocumentRow(details);
    name.append(title, details);

    const state = document.createElement("span");
    state.className = "document-state state-available";
    state.dataset.i18n = "dashboard.uploaded";
    state.textContent = translate(state.dataset.i18n);
    const remove = document.createElement("button");
    remove.className = "document-delete";
    remove.type = "button";
    remove.dataset.i18n = "dashboard.deleteDocument";
    remove.textContent = translate(remove.dataset.i18n);
    remove.addEventListener("click", async () => {
      remove.disabled = true;
      try {
        const response = await fetch(`/api/documents/${encodeURIComponent(id)}`, {
          method: "DELETE",
          headers: { "X-CSRFToken": csrfToken },
        });
        if (!response.ok) throw new Error(translate("dashboard.deleteFailure"));
        row.remove();
        if (!documentList.querySelector("[data-document-id]")) {
          showEmptyDocumentMessage();
        }
      } catch {
        remove.disabled = false;
        setStatus("dashboard.deleteFailure", {}, "error");
      }
    });
    row.append(icon, name, state, remove);
    const edit = document.createElement("button");
    edit.className = "document-edit";
    edit.type = "button";
    edit.dataset.i18n = "dashboard.editDocument";
    edit.textContent = translate(edit.dataset.i18n);
    edit.addEventListener("click", () => editDocument(row, {
      id,
      document_name: row.dataset.documentName || "",
      issue_date: row.dataset.issueDate || "",
      expiry_date: row.dataset.expiryDate || "",
      reminder_intervals: JSON.parse(row.dataset.reminderIntervals || "[]"),
    }));
    row.append(edit);
    documentList.append(row);
    return row;
  };

  const applyMetadataInputs = (document) => {
    documentNameInput.value = document.document_name || "";
    issueDateInput.value = document.issue_date || "";
    expiryDateInput.value = document.expiry_date || "";
    reminderInputs.forEach((input) => {
      input.checked = (document.reminder_intervals || []).includes(Number(input.value));
    });
  };

  const metadataPayload = () => ({
    document_name: documentNameInput.value,
    issue_date: issueDateInput.value,
    expiry_date: expiryDateInput.value,
    reminder_intervals: [...reminderInputs]
      .filter((input) => input.checked)
      .map((input) => Number(input.value)),
  });

  const editDocument = async (row, document) => {
    applyMetadataInputs(document);
    documentNameInput.focus();
    uploadStatus.textContent = translate("dashboard.editingDocument");
    uploadButton.textContent = translate("dashboard.saveDocument");
    uploadButton.disabled = false;
    uploadButton.dataset.editingDocumentId = document.id;
  };

  const showEmptyDocumentMessage = () => {
    if (!documentList) return;
    documentList.replaceChildren();
    const empty = document.createElement("li");
    empty.className = "empty-document-state";
    empty.dataset.documentEmpty = "true";
    empty.textContent = translate("dashboard.noPrivateDocuments");
    documentList.append(empty);
  };

  const updateDocumentRow = (element) => {
    element.textContent = translate("dashboard.uploadedDocumentSize", {
      size: formatSize(Number(element.dataset.documentSize)),
    });
  };

  const updateDocumentTranslations = () => {
    if (!documentList) return;
    for (const element of documentList.querySelectorAll("[data-document-size]")) {
      updateDocumentRow(element);
    }
    const empty = documentList.querySelector("[data-document-empty]");
    if (empty) empty.textContent = translate("dashboard.noPrivateDocuments");
    for (const element of documentList.querySelectorAll("[data-i18n]")) {
      element.textContent = translate(element.dataset.i18n);
    }
  };

  const loadDocuments = async () => {
    if (!documentList) return;
    try {
      const response = await fetch("/api/documents");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || translate("dashboard.uploadNetworkError"));
      documentList.replaceChildren();
      if (!payload.documents.length) {
        showEmptyDocumentMessage();
        return;
      }
      for (const document of payload.documents) {
        const row = appendUploadedDocument(document.id, document.filename, document.size);
        if (row) {
          row.dataset.documentName = document.document_name || "";
          row.dataset.issueDate = document.issue_date || "";
          row.dataset.expiryDate = document.expiry_date || "";
          row.dataset.reminderIntervals = JSON.stringify(document.reminder_intervals || []);
        }
      }
      loadReminders();
    } catch {
      setStatus("dashboard.documentListFailure", {}, "error");
    }
  };

  uploadTriggers.forEach((trigger) => {
    trigger.addEventListener("click", (event) => {
      event.preventDefault();
      if (!uploading) uploadInput.click();
    });
  });

  uploadInput.addEventListener("change", () => {
    const file = uploadInput.files?.[0];
    if (!file) return;

    selectedFile = file;
    selectedFileValid = false;
    if (!isSupported(file)) {
      setStatus("dashboard.uploadFailure", {
        filename: file.name,
        messageKey: "dashboard.uploadInvalidType",
      }, "error");
      setUploadButton(false);
      return;
    }
    if (file.size > maxUploadSize) {
      setStatus("dashboard.uploadFailure", {
        filename: file.name,
        messageKey: "dashboard.uploadTooLarge",
      }, "error");
      setUploadButton(false);
      return;
    }

    setStatus("dashboard.uploadReady", {
      filename: file.name,
      fileSize: file.size,
    }, "ready");
    selectedFileValid = true;
    setUploadButton(false);
  });

  uploadButton.addEventListener("click", async () => {
    const editingId = uploadButton.dataset.editingDocumentId;
    if (editingId) {
      try {
        const response = await fetch(`/api/documents/${encodeURIComponent(editingId)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
          body: JSON.stringify(metadataPayload()),
        });
        if (!response.ok) throw new Error();
        delete uploadButton.dataset.editingDocumentId;
        uploadButton.textContent = translate("dashboard.confirmUpload");
        uploadButton.disabled = true;
        setStatus("dashboard.documentSaved", {}, "success");
        loadDocuments();
        loadReminders();
      } catch {
        setStatus("dashboard.documentSaveFailure", {}, "error");
      }
      return;
    }
    if (!selectedFile || !selectedFileValid || uploading || !isSupported(selectedFile)) return;
    if (selectedFile.size > maxUploadSize) {
      setStatus("dashboard.uploadFailure", {
        filename: selectedFile.name,
        messageKey: "dashboard.uploadTooLarge",
      }, "error");
      return;
    }

    uploading = true;
    setStatus("dashboard.uploading", { filename: selectedFile.name }, "loading");
    setUploadButton(true);

    const formData = new FormData();
    formData.append("document", selectedFile);
    const metadata = metadataPayload();
    formData.append("document_name", metadata.document_name);
    formData.append("issue_date", metadata.issue_date);
    formData.append("expiry_date", metadata.expiry_date);
    formData.append("reminder_intervals", JSON.stringify(metadata.reminder_intervals));
    let failureMessageKey = "dashboard.uploadNetworkError";
    try {
      const response = await fetch("/api/documents/upload", {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken },
        body: formData,
      });
      let payload = {};
      if (response.headers.get("content-type")?.includes("application/json")) {
        payload = await response.json();
      }
      if (
        response.status !== 201
        || typeof payload.id !== "string"
        || typeof payload.filename !== "string"
        || !Number.isFinite(payload.size)
      ) {
        failureMessageKey = uploadErrorKeys[payload.error_code]
          || "dashboard.uploadNetworkError";
        throw new Error("Upload request failed.");
      }

      appendUploadedDocument(payload.id, payload.filename, payload.size);
      setStatus("dashboard.uploadSuccess", {
        filename: payload.filename,
        fileSize: payload.size,
      }, "success");
      selectedFile = null;
      selectedFileValid = false;
      uploadInput.value = "";
      applyMetadataInputs({});
    } catch {
      setStatus("dashboard.uploadFailure", {
        filename: selectedFile.name,
        messageKey: failureMessageKey,
      }, "error");
    } finally {
      uploading = false;
      setUploadButton(false);
      loadDocuments();
    }
  });

  const loadReminders = async () => {
    if (!reminderList) return;
    try {
      const response = await fetch("/api/documents/notifications");
      const payload = await response.json();
      if (!response.ok) throw new Error();
      reminderList.replaceChildren();
      if (!payload.notifications.length) {
        reminderList.append(Object.assign(document.createElement("li"), {
          className: "empty-document-state",
          textContent: translate("dashboard.noReminders"),
        }));
        return;
      }
      payload.notifications.forEach((notification) => {
        const item = document.createElement("li");
        item.className = `document-reminder reminder-${notification.state}`;
        item.textContent = `${notification.document_name} — ${notification.due_date}`;
        const manage = document.createElement("a");
        manage.href = "/dashboard#your-documents";
        manage.dataset.i18n = "dashboard.manageDocument";
        manage.textContent = translate(manage.dataset.i18n);
        const dismiss = document.createElement("button");
        dismiss.type = "button";
        dismiss.dataset.i18n = "dashboard.dismissReminder";
        dismiss.textContent = translate(dismiss.dataset.i18n);
        dismiss.addEventListener("click", async () => {
          await fetch(`/api/documents/notifications/${notification.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
            body: JSON.stringify({ status: "dismissed" }),
          });
          loadReminders();
        });
        item.append(document.createTextNode(" "), manage, dismiss);
        reminderList.append(item);
      });
    } catch {
      reminderList.replaceChildren();
      reminderList.append(Object.assign(document.createElement("li"), {
        className: "empty-document-state",
        textContent: translate("dashboard.reminderLoadFailure"),
      }));
    }
  };

  window.addEventListener("lifegraph:languagechange", () => {
    renderStatus();
    uploadButton.textContent = uploading
      ? translate("dashboard.uploadingButton")
      : translate("dashboard.confirmUpload");
    updateDocumentTranslations();
    loadReminders();
  });

  setUploadButton(false);
  loadDocuments();
  loadReminders();
}
