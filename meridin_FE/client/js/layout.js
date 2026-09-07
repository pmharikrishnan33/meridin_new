(function () {
    const button = document.getElementById("mobileMenuButton");
    const menu = document.getElementById("mobileMenu");

    if (!button || !menu) return;

    button.addEventListener("click", () => {
        const open = menu.classList.toggle("open");
        button.setAttribute("aria-expanded", String(open));
        button.textContent = open ? "×" : "☰";
    });

    menu.querySelectorAll("a").forEach(link => {
        link.addEventListener("click", () => {
            menu.classList.remove("open");
            button.setAttribute("aria-expanded", "false");
            button.textContent = "☰";
        });
    });
})();