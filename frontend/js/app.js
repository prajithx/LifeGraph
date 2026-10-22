const currentPath = window.location.pathname;
const currentPage = currentPath === "/" ? "/" : currentPath;
const languageStorageKey = "lifegraph.language";
let currentLanguage = "en";

try {
  const savedLanguage = window.localStorage.getItem(languageStorageKey);
  if (savedLanguage === "ta" || savedLanguage === "en") currentLanguage = savedLanguage;
} catch {
  currentLanguage = "en";
}

const translate = (key, values = {}) => {
  const english = window.LifeGraphLocales?.en || {};
  const language = window.LifeGraphLocales?.[currentLanguage] || english;
  let text = language[key] || english[key] || key;
  for (const [name, value] of Object.entries(values)) {
    text = text.replaceAll(`{${name}}`, String(value));
  }
  return text;
};

const applyLanguage = (language) => {
  currentLanguage = language === "ta" ? "ta" : "en";
  document.documentElement.lang = currentLanguage;
  for (const element of document.querySelectorAll("[data-i18n]")) {
    element.textContent = translate(element.dataset.i18n);
  }
  for (const element of document.querySelectorAll("[data-i18n-aria]")) {
    element.setAttribute("aria-label", translate(element.dataset.i18nAria));
  }
  for (const element of document.querySelectorAll("[data-i18n-placeholder]")) {
    element.setAttribute("placeholder", translate(element.dataset.i18nPlaceholder));
  }
  for (const element of document.querySelectorAll("[data-language-switch]")) {
    element.value = currentLanguage;
    element.setAttribute("aria-label", translate("language.label"));
  }
  window.dispatchEvent(new CustomEvent("lifegraph:languagechange", {
    detail: { language: currentLanguage },
  }));
};

window.LifeGraphI18n = {
  t: translate,
  get language() { return currentLanguage; },
  serviceName(service) {
    if (currentLanguage !== "ta") return service.name;
    const key = `services.${service.id}.name`;
    const localized = translate(key);
    return localized === key ? service.name : localized;
  },
  servicePurpose(service) {
    if (currentLanguage !== "ta") return service.purpose;
    const key = `services.${service.id}.purpose`;
    const localized = translate(key);
    return localized === key ? service.purpose : localized;
  },
  serviceAuthority(service) {
    if (currentLanguage !== "ta") return service.responsible_authority;
    const key = `services.${service.id}.authority`;
    const localized = translate(key);
    return localized === key ? service.responsible_authority : localized;
  },
  serviceRequirement(service, index) {
    if (currentLanguage !== "ta") return service.requirements[index];
    const key = `services.${service.id}.requirement.${index}`;
    const localized = translate(key);
    return localized === key ? service.requirements[index] : localized;
  },
};

for (const selector of document.querySelectorAll("[data-language-switch]")) {
  selector.addEventListener("change", () => {
    applyLanguage(selector.value);
    try {
      window.localStorage.setItem(languageStorageKey, currentLanguage);
    } catch {
      // Language switching remains available for this page when storage is blocked.
    }
  });
}

applyLanguage(currentLanguage);

for (const link of document.querySelectorAll(".site-nav a, .main-nav a")) {
  if (link.getAttribute("href") === currentPage) {
    link.setAttribute("aria-current", "page");
  }
}

const apiStatus = document.querySelector("[data-api-status]");
if (apiStatus) {
  let apiState = "checking";
  const updateApiStatus = () => {
    const statusKey = apiState === "online"
      ? "common.apiOnline"
      : apiState === "offline"
        ? "common.apiOffline"
        : "common.apiChecking";
    apiStatus.textContent = translate(statusKey);
    apiStatus.dataset.state = apiState;
  };
  window.addEventListener("lifegraph:languagechange", updateApiStatus);
  updateApiStatus();
  fetch("/api/health")
    .then((response) => {
      if (!response.ok) throw new Error("API unavailable");
      return response.json();
    })
    .then(() => {
      apiState = "online";
      updateApiStatus();
    })
    .catch(() => {
      apiState = "offline";
      updateApiStatus();
    });
}

for (const logo of document.querySelectorAll("[data-brand-logo]")) {
  const hideMissingLogo = () => logo.remove();
  if (logo.complete && logo.naturalWidth === 0) {
    hideMissingLogo();
  } else {
    logo.addEventListener("error", hideMissingLogo, { once: true });
  }
}
