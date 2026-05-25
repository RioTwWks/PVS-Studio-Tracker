/**
 * Логика формы проекта (SonarQube project name / key + префикс ключа по группе).
 */
(function () {
  const groupSelect = document.getElementById("GROUP_ID");
  const sonarNameInput = document.getElementById("SONAR_PROJECT_NAME");
  const sonarKeyInput = document.getElementById("SONAR_PROJECT_KEY");

  const projectKeyPrefix = {
    QA: "qa.",
    QD: "qd.",
    QF: "qf.",
    QG: "qg.",
    QS: "qs.",
    QW: "qw.",
    Other_Projects: "",
  };

  if (groupSelect && sonarKeyInput) {
    groupSelect.addEventListener("change", function () {
      const label = groupSelect.options[groupSelect.selectedIndex].text;
      const prefix = projectKeyPrefix[label] || "";
      if (prefix && !sonarKeyInput.dataset.userEdited) {
        sonarKeyInput.value = prefix;
      }
    });
  }

  if (sonarKeyInput) {
    sonarKeyInput.addEventListener("input", function () {
      sonarKeyInput.dataset.userEdited = "1";
    });
  }

  const form = document.querySelector("form.project-ci-form");
  if (!form) return;

  form.addEventListener("submit", function (e) {
    const requiredFields = form.querySelectorAll("[required]");
    let isValid = true;
    let firstInvalid = null;
    let message = "Пожалуйста, заполните все обязательные поля";

    requiredFields.forEach((field) => {
      if (!field.value || !String(field.value).trim()) {
        isValid = false;
        if (!firstInvalid) firstInvalid = field;
      }
      if (field.name === "author_email" && field.value) {
        const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!re.test(field.value)) {
          isValid = false;
          message = "Введите корректный email (user@example.com)";
          if (!firstInvalid) firstInvalid = field;
        }
      }
      if (field.name === "sonar_project_name" && field.value && /\s/.test(field.value)) {
        isValid = false;
        message = "SonarQube Project Name не должен содержать пробелов";
        if (!firstInvalid) firstInvalid = field;
      }
    });

    if (!isValid) {
      e.preventDefault();
      alert("⚠️ " + message);
      if (firstInvalid) firstInvalid.focus();
    }
  });
})();
