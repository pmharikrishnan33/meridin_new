if (!localStorage.getItem("meridin_client_token")) {
    window.location.href = "login.html";
}

const businessName =
    localStorage.getItem(
        "meridin_client_business"
    ) || "Your workspace";

document.getElementById(
    "businessName"
).textContent = businessName;


async function loadOverview() {
    try {
        const data = await apiRequest(
            "/dashboard/client/overview"
        );

        const metrics = data.metrics;

        document.getElementById(
            "productsMetric"
        ).textContent = metrics.products;

        document.getElementById(
            "customersMetric"
        ).textContent = metrics.customers;

        document.getElementById(
            "conversationsMetric"
        ).textContent = metrics.conversations;

        document.getElementById(
            "messagesMetric"
        ).textContent = metrics.messages;

        const container =
            document.getElementById(
                "recentMessages"
            );

        if (!data.recent_messages.length) {
            container.innerHTML =
                '<p class="muted">No messages yet.</p>';

            return;
        }

        container.innerHTML =
            data.recent_messages
                .map(message => `
                    <div class="message-row">
                        <div>
                            <strong>
                                ${escapeHtml(
                                    message.text || "Media message"
                                )}
                            </strong>

                            <span>
                                ${escapeHtml(
                                    message.intent || "Unknown"
                                )}
                            </span>
                        </div>

                        <small>
                            ${formatDate(
                                message.created_at
                            )}
                        </small>
                    </div>
                `)
                .join("");

    } catch (error) {
        console.error(error);
    }
}


async function loadProducts() {
    const container =
        document.getElementById(
            "productsGrid"
        );

    container.innerHTML = "Loading...";

    try {
        const data = await apiRequest(
            "/dashboard/client/products"
        );

        if (!data.items.length) {
            container.innerHTML =
                '<p class="muted">No products found.</p>';

            return;
        }

        container.innerHTML =
            data.items.map(product => {

                const image =
                    product.media?.[0];

                return `
                    <article class="product-card">

                        <div class="product-image">
                            ${
                                image
                                    ? `<img
                                        src="${escapeAttribute(image)}"
                                        alt="${escapeAttribute(product.title)}"
                                      >`
                                    : `<span>No image</span>`
                            }
                        </div>

                        <div class="product-content">

                            <h3>
                                ${escapeHtml(
                                    product.title
                                )}
                            </h3>

                            <p>
                                ${escapeHtml(
                                    product.category || "Uncategorized"
                                )}
                            </p>

                            <strong>
                                ₹${Number(
                                    product.price || 0
                                ).toLocaleString("en-IN")}
                            </strong>

                            <div class="product-meta">
                                Stock:
                                ${product.stock ?? 0}
                            </div>

                        </div>

                    </article>
                `;
            }).join("");

    } catch (error) {
        container.innerHTML =
            `<p class="error">${escapeHtml(error.message)}</p>`;
    }
}


async function loadCollections() {
    const container =
        document.getElementById(
            "collectionsList"
        );

    container.innerHTML = "Loading...";

    try {
        const data = await apiRequest(
            "/dashboard/client/collections"
        );

        if (!data.items.length) {
            container.innerHTML =
                '<p class="muted">No collections yet.</p>';

            return;
        }

        container.innerHTML =
            data.items.map(collection => `
                <article class="collection-card">

                    <div>
                        <h3>
                            ${escapeHtml(
                                collection.name
                            )}
                        </h3>

                        <p>
                            ${escapeHtml(
                                collection.description || ""
                            )}
                        </p>
                    </div>

                    <div>
                        <strong>
                            ${
                                collection.product_ids?.length || 0
                            }
                        </strong>

                        <span>
                            products
                        </span>
                    </div>

                </article>
            `).join("");

    } catch (error) {
        container.innerHTML =
            `<p class="error">${escapeHtml(error.message)}</p>`;
    }
}


async function loadMessages() {
    const container =
        document.getElementById(
            "messagesList"
        );

    try {
        const data = await apiRequest(
            "/dashboard/client/messages"
        );

        if (!data.items.length) {
            container.innerHTML =
                '<p class="muted">No messages.</p>';

            return;
        }

        container.innerHTML = `
            <table>
                <thead>
                    <tr>
                        <th>Direction</th>
                        <th>Message</th>
                        <th>Intent</th>
                        <th>Confidence</th>
                        <th>Time</th>
                    </tr>
                </thead>

                <tbody>
                    ${data.items.map(message => `
                        <tr>
                            <td>
                                ${escapeHtml(
                                    message.direction || "-"
                                )}
                            </td>

                            <td>
                                ${escapeHtml(
                                    message.text || "Media"
                                )}
                            </td>

                            <td>
                                ${escapeHtml(
                                    message.intent || "-"
                                )}
                            </td>

                            <td>
                                ${
                                    message.intent_confidence != null
                                        ? `${(
                                            message.intent_confidence * 100
                                        ).toFixed(1)}%`
                                        : "-"
                                }
                            </td>

                            <td>
                                ${formatDate(
                                    message.created_at
                                )}
                            </td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `;

    } catch (error) {
        container.innerHTML =
            `<p class="error">${escapeHtml(error.message)}</p>`;
    }
}


async function loadLeads() {
    const container =
        document.getElementById(
            "leadsList"
        );

    try {
        const data = await apiRequest(
            "/dashboard/client/leads"
        );

        if (!data.items.length) {
            container.innerHTML =
                '<p class="muted">No classified leads yet.</p>';

            return;
        }

        container.innerHTML = `
            <table>
                <thead>
                    <tr>
                        <th>Intent</th>
                        <th>Message</th>
                        <th>Confidence</th>
                        <th>Time</th>
                    </tr>
                </thead>

                <tbody>
                    ${data.items.map(message => `
                        <tr>
                            <td>
                                ${escapeHtml(
                                    message.intent || "-"
                                )}
                            </td>

                            <td>
                                ${escapeHtml(
                                    message.text || "Media"
                                )}
                            </td>

                            <td>
                                ${
                                    message.intent_confidence != null
                                        ? `${(
                                            message.intent_confidence * 100
                                        ).toFixed(1)}%`
                                        : "-"
                                }
                            </td>

                            <td>
                                ${formatDate(
                                    message.created_at
                                )}
                            </td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `;

    } catch (error) {
        container.innerHTML =
            `<p class="error">${escapeHtml(error.message)}</p>`;
    }
}


async function loadAnalytics() {
    const container =
        document.getElementById(
            "analyticsData"
        );

    try {
        const data = await apiRequest(
            "/dashboard/client/analytics?days=7"
        );

        const dailyHtml = `
            <section class="panel">
                <h2>Daily messages</h2>

                ${
                    data.daily.length
                        ? `
                            <div class="analytics-list">
                                ${data.daily.map(row => `
                                    <div>
                                        <span>
                                            ${escapeHtml(row._id)}
                                        </span>

                                        <strong>
                                            ${row.messages}
                                        </strong>
                                    </div>
                                `).join("")}
                            </div>
                        `
                        : '<p class="muted">No data.</p>'
                }
            </section>
        `;

        const intentHtml = `
            <section class="panel">
                <h2>Top intents</h2>

                ${
                    data.intents.length
                        ? `
                            <div class="analytics-list">
                                ${data.intents.map(row => `
                                    <div>
                                        <span>
                                            ${escapeHtml(row._id)}
                                        </span>

                                        <strong>
                                            ${row.count}
                                        </strong>
                                    </div>
                                `).join("")}
                            </div>
                        `
                        : '<p class="muted">No intent data.</p>'
                }
            </section>
        `;

        container.innerHTML =
            dailyHtml + intentHtml;

    } catch (error) {
        container.innerHTML =
            `<p class="error">${escapeHtml(error.message)}</p>`;
    }
}


document.getElementById(
    "reloadProducts"
).addEventListener(
    "click",
    loadProducts
);


document.getElementById(
    "logoutButton"
).addEventListener(
    "click",
    () => {
        localStorage.removeItem(
            "meridin_client_token"
        );

        localStorage.removeItem(
            "meridin_client_business"
        );

        window.location.href =
            "login.html";
    }
);


function showProducts() {
    document.getElementById(
        "products"
    ).scrollIntoView({
        behavior: "smooth"
    });
}


function showCollections() {
    document.getElementById(
        "collections"
    ).scrollIntoView({
        behavior: "smooth"
    });
}


function showAnalytics() {
    document.getElementById(
        "analytics"
    ).scrollIntoView({
        behavior: "smooth"
    });
}


function formatDate(value) {
    if (!value) {
        return "-";
    }

    return new Date(value).toLocaleString(
        "en-IN",
        {
            dateStyle: "medium",
            timeStyle: "short"
        }
    );
}


function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function escapeAttribute(value) {
    return escapeHtml(value);
}


loadOverview();
loadProducts();
loadCollections();
loadMessages();
loadLeads();
loadAnalytics();
