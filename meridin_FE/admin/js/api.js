const API_BASE_URL = "http://127.0.0.1:8000/api";

async function apiRequest(endpoint, options = {}) {

    const token =
        localStorage.getItem(
            "meridin_admin_token"
        );

    const headers = {
        "Content-Type": "application/json",
        ...(options.headers || {})
    };

    if (token) {
        headers.Authorization =
            `Bearer ${token}`;
    }

    const response = await fetch(
        `${API_BASE_URL}${endpoint}`,
        {
            ...options,
            headers
        }
    );

    if (response.status === 401) {

        localStorage.removeItem(
            "meridin_admin_token"
        );

        window.location.href =
            "login.html";

        throw new Error(
            "Authentication required."
        );
    }

    const data =
        await response.json();

    if (!response.ok) {

        throw new Error(
            data?.detail ||
            `Request failed: ${response.status}`
        );
    }

    return data;
}
