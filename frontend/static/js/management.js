document.addEventListener("DOMContentLoaded", () => {
    const openDialog = (dialog) => {
        if (!dialog?.showModal) return;
        dialog.showModal();
        const firstInput = dialog.querySelector("input:not([type='hidden']), select, textarea");
        window.setTimeout(() => firstInput?.focus(), 80);
    };

    document.querySelectorAll("[data-dialog-open]").forEach((button) => {
        button.addEventListener("click", () => openDialog(document.getElementById(button.dataset.dialogOpen)));
    });

    document.querySelectorAll(".app-dialog").forEach((dialog) => {
        dialog.querySelectorAll("[data-dialog-close]").forEach((button) => {
            button.addEventListener("click", () => dialog.close());
        });
        dialog.addEventListener("click", (event) => {
            const bounds = dialog.getBoundingClientRect();
            const inside = event.clientX >= bounds.left && event.clientX <= bounds.right && event.clientY >= bounds.top && event.clientY <= bounds.bottom;
            if (!inside) dialog.close();
        });
    });

    const wizardForm = document.querySelector("[data-course-wizard]");
    if (wizardForm) {
        const steps = [...wizardForm.querySelectorAll("[data-step]")];
        const progress = [...wizardForm.querySelectorAll(".wizard-progress span")];
        const title = wizardForm.querySelector("[data-wizard-title]");
        const counter = wizardForm.querySelector("[data-wizard-counter]");
        const back = wizardForm.querySelector("[data-wizard-back]");
        const next = wizardForm.querySelector("[data-wizard-next]");
        const submit = wizardForm.querySelector("[data-wizard-submit]");
        let current = 0;

        const renderStep = () => {
            steps.forEach((step, index) => step.classList.toggle("is-active", index === current));
            progress.forEach((item, index) => item.classList.toggle("is-active", index <= current));
            title.textContent = steps[current].dataset.title;
            counter.textContent = `Шаг ${current + 1} из ${steps.length}`;
            back.disabled = current === 0;
            next.classList.toggle("is-hidden", current === steps.length - 1);
            submit.classList.toggle("is-hidden", current !== steps.length - 1);
        };

        const validateCurrentStep = () => {
            const requiredFields = [...steps[current].querySelectorAll("[required]")];
            for (const field of requiredFields) {
                if (!field.checkValidity()) {
                    field.reportValidity();
                    return false;
                }
            }
            return true;
        };

        next.addEventListener("click", () => {
            if (!validateCurrentStep()) return;
            current = Math.min(current + 1, steps.length - 1);
            renderStep();
        });
        back.addEventListener("click", () => {
            current = Math.max(current - 1, 0);
            renderStep();
        });

        const wizardDialog = document.getElementById("course-wizard");
        wizardDialog?.addEventListener("close", () => {
            current = 0;
            renderStep();
        });

        const coverInput = wizardForm.querySelector("[data-cover-input]");
        const coverName = wizardForm.querySelector("[data-cover-name]");
        coverInput?.addEventListener("change", () => {
            coverName.textContent = coverInput.files[0]?.name || "Файл не выбран";
        });
        renderStep();
    }

    document.querySelectorAll("[data-material-form]").forEach((materialForm) => {
        const kind = materialForm.querySelector("select[name='kind']");
        const dependent = [...materialForm.querySelectorAll("[data-show-for]")];
        const renderMaterialFields = () => {
            const currentKind = kind.value;
            dependent.forEach((section) => {
                const types = section.dataset.showFor.split(",");
                section.classList.toggle("is-visible", types.includes(currentKind));
            });
        };
        kind?.addEventListener("change", renderMaterialFields);
        renderMaterialFields();
    });
});
