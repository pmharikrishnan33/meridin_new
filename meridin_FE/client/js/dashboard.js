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

                            <div class="product-actions" style="display: flex; gap: 8px; margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border);">
                                <button class="table-button" onclick="editProduct('${product._id}')" style="flex: 1;">Edit</button>
                                <button class="table-button" onclick="deleteProduct('${product._id}')" style="flex: 1; background: #fee2e2; border-color: #fecaca; color: #991b1b;">Delete</button>
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

                    <div style="display: flex; gap: 8px; margin-left: 16px;">
                        <button class="table-button" onclick="editCollection('${collection._id}')" style="padding: 6px 12px; font-size: 12px;">Edit</button>
                        <button class="table-button" onclick="deleteCollection('${collection._id}')" style="padding: 6px 12px; font-size: 12px; background: #fee2e2; border-color: #fecaca; color: #991b1b;">Delete</button>
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


async function loadSettings() {
    try {
        const data = await apiRequest("/dashboard/client/settings");
        const profile = data.business_profile || {};
        const support = data.customer_support || {};
        const ai = data.ai || {};

        document.getElementById("settingsShopName").value = profile.shop_name || data.business_name || "";
        document.getElementById("settingsDescription").value = profile.description || "";
        document.getElementById("settingsPhone").value = profile.phone || "";
        document.getElementById("settingsEmail").value = profile.email || "";
        document.getElementById("settingsWebsite").value = profile.website || "";
        document.getElementById("settingsInstagram").value = profile.instagram || "";
        document.getElementById("settingsAddress").value = profile.address || "";
        document.getElementById("settingsCity").value = profile.city || "";

        document.getElementById("settingsHours").value = support.business_hours || "";
        document.getElementById("settingsDelivery").value = support.delivery_information || "";
        document.getElementById("settingsShipping").value = support.shipping_policy || "";
        document.getElementById("settingsReturns").value = support.return_policy || "";
        document.getElementById("settingsExchange").value = support.exchange_policy || "";
        document.getElementById("settingsCancellation").value = support.cancellation_policy || "";
        document.getElementById("settingsPayments").value = support.payment_methods || "";
        document.getElementById("settingsCod").value = support.cod_available == null ? "" : String(support.cod_available);

        document.getElementById("settingsTone").value = ai.tone || "friendly";
        document.getElementById("settingsLanguage").value = ai.language || "English";
        document.getElementById("settingsLength").value = ai.response_length || "short";
        document.getElementById("settingsGreeting").value = ai.greeting || "";
        document.getElementById("settingsInstructions").value = ai.custom_instructions || "";
    } catch (error) {
        const status = document.getElementById("settingsStatus");
        if (status) status.textContent = error.message || "Failed to load settings.";
    }
}


document.getElementById("settingsForm").addEventListener("submit", async (event) => {
    event.preventDefault();

    const status = document.getElementById("settingsStatus");
    status.textContent = "Saving...";

    const codValue = document.getElementById("settingsCod").value;

    const payload = {
        business_profile: {
            shop_name: document.getElementById("settingsShopName").value.trim(),
            description: document.getElementById("settingsDescription").value.trim() || null,
            phone: document.getElementById("settingsPhone").value.trim() || null,
            email: document.getElementById("settingsEmail").value.trim() || null,
            website: document.getElementById("settingsWebsite").value.trim() || null,
            instagram: document.getElementById("settingsInstagram").value.trim() || null,
            address: document.getElementById("settingsAddress").value.trim() || null,
            city: document.getElementById("settingsCity").value.trim() || null
        },
        customer_support: {
            business_hours: document.getElementById("settingsHours").value.trim() || null,
            delivery_information: document.getElementById("settingsDelivery").value.trim() || null,
            shipping_policy: document.getElementById("settingsShipping").value.trim() || null,
            return_policy: document.getElementById("settingsReturns").value.trim() || null,
            exchange_policy: document.getElementById("settingsExchange").value.trim() || null,
            cancellation_policy: document.getElementById("settingsCancellation").value.trim() || null,
            payment_methods: document.getElementById("settingsPayments").value.trim() || null,
            cod_available: codValue === "" ? null : codValue === "true"
        },
        ai: {
            tone: document.getElementById("settingsTone").value,
            language: document.getElementById("settingsLanguage").value.trim() || "English",
            response_length: document.getElementById("settingsLength").value,
            greeting: document.getElementById("settingsGreeting").value.trim() || null,
            custom_instructions: document.getElementById("settingsInstructions").value.trim()
        }
    };

    try {
        const data = await apiRequest("/dashboard/client/settings", {
            method: "PUT",
            body: JSON.stringify(payload)
        });
        status.textContent = data.saved ? "Saved." : "Saved successfully.";
        localStorage.setItem("meridin_client_business", payload.business_profile.shop_name);
        document.getElementById("businessName").textContent = payload.business_profile.shop_name;
    } catch (error) {
        status.textContent = error.message || "Failed to save settings.";
    }
});


function showSettings() {
    document.getElementById("settings").scrollIntoView({ behavior: "smooth" });
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
loadSettings();


// ============ MODAL HANDLING ============

const productModal = document.getElementById("productModal");
const collectionModal = document.getElementById("collectionModal");
const productForm = document.getElementById("productForm");
const collectionForm = document.getElementById("collectionForm");
const productCollectionSelect = document.getElementById("productCollection");

function openModal(modal) {
    modal.classList.add("open");
    document.body.style.overflow = "hidden";
    // Focus first input
    const firstInput = modal.querySelector("input, select, textarea");
    if (firstInput) firstInput.focus();
}

function closeModal(modal) {
    modal.classList.remove("open");
    document.body.style.overflow = "";
    modal.querySelector("form").reset();
    document.getElementById("productId").value = "";
    document.getElementById("collectionId").value = "";
}

// Close on backdrop click
document.querySelectorAll(".modal-backdrop").forEach(backdrop => {
    backdrop.addEventListener("click", () => {
        closeModal(backdrop.closest(".modal"));
    });
});

// Close on close button
document.querySelectorAll(".modal-close").forEach(btn => {
    btn.addEventListener("click", () => {
        closeModal(btn.closest(".modal"));
    });
});

// Close on cancel button
document.querySelectorAll(".modal-cancel").forEach(btn => {
    btn.addEventListener("click", () => {
        closeModal(btn.closest(".modal"));
    });
});

// Close on Escape key
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        document.querySelectorAll(".modal.open").forEach(closeModal);
    }
});

// ============ COLLECTION DROPDOWN ============

async function loadCollectionsForDropdown() {
    try {
        const data = await apiRequest("/dashboard/client/collections");
        productCollectionSelect.innerHTML = '<option value="">-- Select collection --</option>';
        data.items.forEach(collection => {
            const option = document.createElement("option");
            option.value = collection._id;
            option.textContent = collection.name;
            productCollectionSelect.appendChild(option);
        });
    } catch (error) {
        console.error("Failed to load collections for dropdown:", error);
    }
}

// ============ CREATE/EDIT PRODUCT ============

document.getElementById("createProductButton").addEventListener("click", () => {
    document.getElementById("productModalTitle").textContent = "Add Product";
    productForm.reset();
    document.getElementById("productId").value = "";
    loadCollectionsForDropdown();
    openModal(productModal);
});

productForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const productId = document.getElementById("productId").value;
    const isEditing = !!productId;

    const productData = {
        title: document.getElementById("productTitle").value.trim(),
        description: document.getElementById("productDescription").value.trim(),
        price: Number(document.getElementById("productPrice").value),
        stock: Number(document.getElementById("productStock").value),
        category: document.getElementById("productCategory").value.trim() || undefined,
        collection_id: document.getElementById("productCollection").value || undefined,
        image: document.getElementById("productImage").value.trim() || undefined
    };

    // Remove undefined values
    Object.keys(productData).forEach(key => productData[key] === undefined && delete productData[key]);

    try {
        const endpoint = isEditing
            ? `/dashboard/client/products/${productId}`
            : "/dashboard/client/products";
        const method = isEditing ? "PATCH" : "POST";

        await apiRequest(endpoint, {
            method,
            body: JSON.stringify(productData)
        });

        closeModal(productModal);
        await loadProducts();
        await loadOverview(); // Refresh metrics
    } catch (error) {
        alert(error.message || "Failed to save product");
    }
});

// ============ CREATE/EDIT COLLECTION ============

document.getElementById("createCollectionButton").addEventListener("click", () => {
    document.getElementById("collectionModalTitle").textContent = "New Collection";
    collectionForm.reset();
    document.getElementById("collectionId").value = "";
    openModal(collectionModal);
});

collectionForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const collectionId = document.getElementById("collectionId").value;
    const isEditing = !!collectionId;

    const collectionData = {
        name: document.getElementById("collectionName").value.trim(),
        description: document.getElementById("collectionDescription").value.trim() || undefined
    };

    Object.keys(collectionData).forEach(key => collectionData[key] === undefined && delete collectionData[key]);

    try {
        const endpoint = isEditing
            ? `/dashboard/client/collections/${collectionId}`
            : "/dashboard/client/collections";
        const method = isEditing ? "PATCH" : "POST";

        await apiRequest(endpoint, {
            method,
            body: JSON.stringify(collectionData)
        });

        closeModal(collectionModal);
        await loadCollections();
        await loadProducts(); // Refresh products to update collection dropdown
        await loadOverview();
    } catch (error) {
        alert(error.message || "Failed to save collection");
    }
});

// ============ EDIT/DELETE FROM LIST ============

// Make functions globally available for inline onclick handlers
window.editProduct = async function(productId) {
    try {
        // Fetch product details - we need to get it from the loaded data or fetch individually
        // For now, open modal in edit mode - you'd need to fetch product details first
        const data = await apiRequest("/dashboard/client/products");
        const product = data.items.find(p => p._id === productId);
        if (!product) throw new Error("Product not found");

        document.getElementById("productModalTitle").textContent = "Edit Product";
        document.getElementById("productId").value = product._id;
        document.getElementById("productTitle").value = product.title || "";
        document.getElementById("productDescription").value = product.description || "";
        document.getElementById("productPrice").value = product.price || 0;
        document.getElementById("productStock").value = product.stock || 0;
        document.getElementById("productCategory").value = product.category || "";
        document.getElementById("productImage").value = product.media?.[0] || "";

        await loadCollectionsForDropdown();
        if (product.collection_id) {
            document.getElementById("productCollection").value = product.collection_id;
        }

        openModal(productModal);
    } catch (error) {
        alert(error.message || "Failed to load product");
    }
};

window.deleteProduct = async function(productId) {
    if (!confirm("Delete this product?")) return;
    try {
        await apiRequest(`/dashboard/client/products/${productId}`, { method: "DELETE" });
        await loadProducts();
        await loadOverview();
    } catch (error) {
        alert(error.message || "Failed to delete product");
    }
};

window.editCollection = async function(collectionId) {
    try {
        const data = await apiRequest("/dashboard/client/collections");
        const collection = data.items.find(c => c._id === collectionId);
        if (!collection) throw new Error("Collection not found");

        document.getElementById("collectionModalTitle").textContent = "Edit Collection";
        document.getElementById("collectionId").value = collection._id;
        document.getElementById("collectionName").value = collection.name || "";
        document.getElementById("collectionDescription").value = collection.description || "";
        openModal(collectionModal);
    } catch (error) {
        alert(error.message || "Failed to load collection");
    }
};

window.deleteCollection = async function(collectionId) {
    if (!confirm("Delete this collection?")) return;
    try {
        await apiRequest(`/dashboard/client/collections/${collectionId}`, { method: "DELETE" });
        await loadCollections();
        await loadProducts();
        await loadOverview();
    } catch (error) {
        alert(error.message || "Failed to delete collection");
    }
};
