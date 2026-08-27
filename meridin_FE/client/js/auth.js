const loginForm = document.getElementById("loginForm");
const loginError = document.getElementById("loginError");

if (loginForm) {
    loginForm.addEventListener("submit", async (event) => {
        event.preventDefault();

        loginError.textContent = "";

        const email =
            document.getElementById("email").value.trim();

        const password =
            document.getElementById("password").value;

        try {
            const result = await apiRequest(
                "/dashboard/auth/client/login",
                {
                    method: "POST",
                    body: JSON.stringify({
                        email,
                        password
                    })
                }
            );

            localStorage.setItem(
                "meridin_client_token",
                result.access_token
            );

            localStorage.setItem(
                "meridin_client_business",
                result.business_name || ""
            );

            window.location.href = "index.html";

        } catch (error) {
            loginError.textContent =
                error.message || "Unable to sign in.";
        }
    });
}
