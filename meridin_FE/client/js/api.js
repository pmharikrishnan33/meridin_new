const API_BASE_URL = window.MERIDIN_API_BASE_URL || "https://meridin-new.vercel.app/api";

async function apiRequest(endpoint, options = {}) {
    const token = localStorage.getItem("meridin_client_token");

    const headers = {
        "Content-Type": "application/json",
        ...(options.headers || {})
    };

    if (token) {
        headers.Authorization = `Bearer ${token}`;
    }

    const response = await fetch(
        `${API_BASE_URL}${endpoint}`,
        {
            ...options,
            headers
        }
    );

    if (response.status === 401) {
        localStorage.removeItem("meridin_client_token");
        window.location.href = "login.html";
        throw new Error("Authentication required.");
    }

    const contentType =
        response.headers.get("content-type") || "";

    let data = null;

    if (contentType.includes("application/json")) {
        data = await response.json();
    } else {
        data = await response.text();
    }

    if (!response.ok) {
        const message =
            typeof data === "object" && data?.detail
                ? data.detail
                : `Request failed with status ${response.status}`;

        throw new Error(message);
    }

    return data;
}
