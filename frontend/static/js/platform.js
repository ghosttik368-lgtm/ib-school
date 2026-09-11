document.addEventListener("DOMContentLoaded", () => {
    const closeToast = (toast) => {
        if (!toast || toast.classList.contains("is-leaving")) return;
        toast.classList.add("is-leaving");
        window.setTimeout(() => toast.remove(), 260);
    };

    document.querySelectorAll(".toast").forEach((toast) => {
        toast.querySelector(".toast__close")?.addEventListener("click", () => closeToast(toast));
        window.setTimeout(() => closeToast(toast), 6500);
    });

    const cards = [...document.querySelectorAll("[data-course-card]")];
    const search = document.querySelector("[data-course-search]");
    const filterButtons = [...document.querySelectorAll("[data-direction]")];
    const empty = document.querySelector("[data-course-empty]");
    let activeDirection = "all";

    const filterCourses = () => {
        const query = (search?.value || "").trim().toLocaleLowerCase("ru");
        let visibleCount = 0;
        cards.forEach((card) => {
            const directionMatches = activeDirection === "all" || card.dataset.direction === activeDirection;
            const searchMatches = !query || (card.dataset.search || "").includes(query);
            const visible = directionMatches && searchMatches;
            card.classList.toggle("is-hidden", !visible);
            if (visible) visibleCount += 1;
        });
        empty?.classList.toggle("is-hidden", visibleCount > 0);
    };

    filterButtons.forEach((button) => {
        button.addEventListener("click", () => {
            activeDirection = button.dataset.direction;
            filterButtons.forEach((item) => item.classList.toggle("is-active", item === button));
            filterCourses();
        });
    });
    search?.addEventListener("input", filterCourses);

    document.querySelectorAll("[data-modal-open]").forEach((button) => {
        button.addEventListener("click", () => {
            const dialog = document.getElementById(button.dataset.modalOpen);
            if (dialog?.showModal) dialog.showModal();
        });
    });

    document.querySelectorAll(".student-modal").forEach((dialog) => {
        dialog.querySelector("[data-modal-close]")?.addEventListener("click", () => dialog.close());
        dialog.addEventListener("click", (event) => {
            const bounds = dialog.getBoundingClientRect();
            const inside = event.clientX >= bounds.left && event.clientX <= bounds.right && event.clientY >= bounds.top && event.clientY <= bounds.bottom;
            if (!inside) dialog.close();
        });
    });

    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm(form.dataset.confirm)) event.preventDefault();
        });
    });

    const chatWindow = document.querySelector("[data-chat-window]");
    if (chatWindow) chatWindow.scrollTop = chatWindow.scrollHeight;
});

