const form =
    document.getElementById(
        "loginForm"
    );

const error =
    document.getElementById(
        "loginError"
    );

form.addEventListener(
    "submit",
    async event => {

        event.preventDefault();

        error.textContent = "";

        const email =
            document.getElementById(
                "email"
            ).value.trim();

        const password =
            document.getElementById(
                "password"
            ).value;

        try {

            const result =
                await apiRequest(
                    "/dashboard/auth/admin/login",
                    {
                        method: "POST",
                        body: JSON.stringify({
                            email,
                            password
                        })
                    }
                );

            localStorage.setItem(
                "meridin_admin_token",
                result.access_token
            );

            window.location.href =
                "index.html";

        } catch (err) {

            error.textContent =
                err.message ||
                "Unable to sign in.";
        }
    }
);
