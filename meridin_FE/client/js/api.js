const isLocal =
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1";

// Current production API remains on Vercel. When the API moves to Google
// Cloud, change only this production URL to https://api.meridin.in/api.
const API_BASE_URL =
    window.MERIDIN_API_BASE_URL ||
    (isLocal
        ? "http://127.0.0.1:8000/api"
        : "https://meridin-new.vercel.app/api");


async function apiRequest(endpoint, options = {}) {
    const token =
        localStorage.getItem("meridin_client_token");

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
        localStorage.removeItem("meridin_client_business");
        window.location.href = "login.html";
        throw new Error("Authentication required.");
    }

    const contentType =
        response.headers.get("content-type") || "";

    const data = contentType.includes("application/json")
        ? await response.json()
        : await response.text();

    if (!response.ok) {
        const message =
            typeof data === "object" && data?.detail
                ? data.detail
                : `Request failed with status ${response.status}`;

        throw new Error(message);
    }

    return data;
}
