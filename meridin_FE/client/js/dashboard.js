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

        const metrics = data.metrics || {};

        const productsMetric =
            document.getElementById("productsMetric");

        const customersMetric =
            document.getElementById("customersMetric");

        const conversationsMetric =
            document.getElementById("conversationsMetric");

        if (productsMetric) {
            productsMetric.textContent =
                metrics.products ?? 0;
        }

        if (customersMetric) {
            customersMetric.textContent =
                metrics.customers ?? 0;
        }

        if (conversationsMetric) {
            conversationsMetric.textContent =
                metrics.conversations ?? 0;
        }

    } catch (error) {
        console.error(
            "Failed to load overview:",
            error
        );
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
loadAnalytics();
loadSettings();
loadCatalogMetadata();


// ============ MODAL HANDLING ============

const productModal = document.getElementById("productModal");

let selectedProductImageFile = null;
let currentProductImageUrl = "";

function setProductImagePreview(url, status = "") {
    const wrapper = document.getElementById("productImagePreview");
    const image = document.getElementById("productImagePreviewImg");
    const statusElement = document.getElementById("productImageStatus");

    if (!url) {
        wrapper.hidden = true;
        image.removeAttribute("src");
        statusElement.textContent = "";
        return;
    }

    image.src = url;
    statusElement.textContent = status;
    wrapper.hidden = false;
}

function resetProductImageState() {
    selectedProductImageFile = null;
    currentProductImageUrl = "";
    const input = document.getElementById("productImageFile");
    if (input) input.value = "";
    setProductImagePreview("");
}

function convertImageToJpeg(file) {
    return new Promise((resolve, reject) => {
        const objectUrl = URL.createObjectURL(file);
        const image = new Image();

        image.onload = () => {
            try {
                const canvas = document.createElement("canvas");
                canvas.width = image.naturalWidth;
                canvas.height = image.naturalHeight;

                const context = canvas.getContext("2d");
                if (!context) throw new Error("Could not prepare the image.");

                // JPEG has no transparency, so use a white background for PNG/WebP images.
                context.fillStyle = "#ffffff";
                context.fillRect(0, 0, canvas.width, canvas.height);
                context.drawImage(image, 0, 0);

                canvas.toBlob((blob) => {
                    URL.revokeObjectURL(objectUrl);
                    if (!blob) {
                        reject(new Error("Could not convert the image to JPG."));
                        return;
                    }
                    resolve(blob);
                }, "image/jpeg", 0.90);
            } catch (error) {
                URL.revokeObjectURL(objectUrl);
                reject(error);
            }
        };

        image.onerror = () => {
            URL.revokeObjectURL(objectUrl);
            reject(new Error("The selected image could not be read."));
        };

        image.src = objectUrl;
    });
}

async function uploadProductImage(file) {
    if (!file) return currentProductImageUrl;

    if (!file.type.startsWith("image/")) {
        throw new Error("Please select an image file.");
    }

    const maxBytes = 5 * 1024 * 1024;
    if (file.size > maxBytes) {
        throw new Error("Product images must be 5 MB or smaller.");
    }

    setProductImagePreview(
        URL.createObjectURL(file),
        "Converting to JPG..."
    );

    const jpegBlob = await convertImageToJpeg(file);

    if (jpegBlob.size > maxBytes) {
        throw new Error("The converted JPG is larger than 5 MB.");
    }

    setProductImagePreview(
        URL.createObjectURL(jpegBlob),
        "Preparing secure R2 upload..."
    );

    const uploadConfig = await apiRequest(
        "/dashboard/client/products/image-upload-url",
        {
            method: "POST",
            body: JSON.stringify({
                content_length: jpegBlob.size
            })
        }
    );

    if (!uploadConfig.upload_url) {
        throw new Error("R2 upload URL was not returned.");
    }

    const response = await fetch(uploadConfig.upload_url, {
        method: "PUT",
        headers: {
            "Content-Type": "image/jpeg"
        },
        body: jpegBlob
    });

    if (!response.ok) {
        const errorText = await response.text().catch(() => "");
        throw new Error(errorText || "Cloudflare R2 image upload failed.");
    }

    if (!uploadConfig.image_url) {
        throw new Error("R2 did not return an image URL.");
    }

    currentProductImageUrl = uploadConfig.image_url;

    setProductImagePreview(
        currentProductImageUrl,
        "Image uploaded"
    );

    return currentProductImageUrl;
}

document.getElementById("productImageFile").addEventListener("change", (event) => {
    selectedProductImageFile = event.target.files?.[0] || null;
    if (!selectedProductImageFile) {
        setProductImagePreview(currentProductImageUrl);
        return;
    }

    const localUrl = URL.createObjectURL(selectedProductImageFile);
    setProductImagePreview(localUrl, "Selected image");
});
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

let catalogMetadata = { departments: {}, categories: {}, colors: {}, sizes: {}, sizes_by_group: {} };
let productOptions = {};

async function loadCatalogMetadata() {
    try {
        const data = await apiRequest("/dashboard/client/catalog-metadata");
        catalogMetadata = data.metadata || catalogMetadata;
        populateDepartmentOptions();
        populateProductOptionChoices();
    } catch (error) {
        console.error("Failed to load catalog metadata:", error);
        document.getElementById("newProductOption").innerHTML = '<option value="">Metadata unavailable</option>';
    }
}

function mapEntries(map) {
    return Object.entries(map || {}).filter(([id, name]) => name !== "");
}

function populateDepartmentOptions(selectedId = "") {
    const select = document.getElementById("productDepartment");
    select.innerHTML = '<option value="">-- Select department --</option>';
    mapEntries(catalogMetadata.departments).forEach(([id, name]) => {
        const option = document.createElement("option");
        option.value = id;
        option.textContent = name;
        option.selected = String(id) === String(selectedId);
        select.appendChild(option);
    });
    populateCategoryOptions(selectedId ? undefined : "");
}

function populateCategoryOptions(departmentId, selectedId = "") {
    const select = document.getElementById("productCategoryId");
    select.innerHTML = '<option value="">-- Select category --</option>';
    // get_display_maps exposes category IDs without hierarchy. Use the selected
    // department only as a UI hint; the backend remains authoritative.
    mapEntries(catalogMetadata.categories).forEach(([id, name]) => {
        const option = document.createElement("option");
        option.value = id;
        option.textContent = name;
        option.selected = String(id) === String(selectedId);
        select.appendChild(option);
    });
}

document.getElementById("productDepartment").addEventListener("change", () => {
    populateCategoryOptions(document.getElementById("productDepartment").value);
});

function getOptionDefinitions() {
    const definitions = {};
    if (mapEntries(catalogMetadata.colors).length) definitions.Color = mapEntries(catalogMetadata.colors).map(([id, name]) => ({ id: Number(id), name }));
    const sizes = mapEntries(catalogMetadata.sizes);
    if (sizes.length) definitions.Size = sizes.map(([id, name]) => ({ id: Number(id), name }));
    return definitions;
}

function populateProductOptionChoices() {
    const select = document.getElementById("newProductOption");
    const defs = getOptionDefinitions();
    select.innerHTML = '<option value="">Select option to add</option>';
    Object.keys(defs).forEach(name => {
        if (!productOptions[name]) {
            const option = document.createElement("option");
            option.value = name;
            option.textContent = name;
            select.appendChild(option);
        }
    });
}

function resetProductEditor() {
    productOptions = {};
    document.getElementById("productOptionsContainer").innerHTML = "";
    document.getElementById("productVariantsBody").innerHTML = '<tr><td colspan="5" class="muted center">Add option values to generate variants.</td></tr>';
    document.getElementById("productFeatured").checked = false;
    populateProductOptionChoices();
}

function addProductOption(name, existingValues = []) {
    const definitions = getOptionDefinitions();
    if (!name || !definitions[name] || productOptions[name]) return;
    productOptions[name] = existingValues.map(v => ({ id: Number(v.id), name: String(v.name) }));

    const block = document.createElement("div");
    block.className = "product-option-block";
    block.id = `product-option-${name.replace(/\W/g, "-")}`;
    const values = definitions[name];
    block.innerHTML = `
        <div class="product-option-header">
            <strong>${escapeHtml(name)}</strong>
            <button type="button" class="remove-btn" data-option="${escapeAttribute(name)}">Remove</button>
        </div>
        <select class="product-option-value-select">
            <option value="">Select ${escapeHtml(name)} value</option>
            ${values.map(v => `<option value="${v.id}">${escapeHtml(v.name)}</option>`).join("")}
        </select>
        <div class="product-option-values"></div>
    `;
    document.getElementById("productOptionsContainer").appendChild(block);
    const valueSelect = block.querySelector(".product-option-value-select");
    valueSelect.addEventListener("change", () => {
        const id = Number(valueSelect.value);
        if (!id || productOptions[name].some(v => v.id === id)) return;
        const item = values.find(v => v.id === id);
        if (!item) return;
        productOptions[name].push(item);
        renderProductOptionTags(name);
        valueSelect.value = "";
        generateProductVariants();
    });
    block.querySelector(".remove-btn").addEventListener("click", () => {
        delete productOptions[name];
        block.remove();
        populateProductOptionChoices();
        generateProductVariants();
    });
    renderProductOptionTags(name);
    populateProductOptionChoices();
    generateProductVariants();
}

function renderProductOptionTags(name) {
    const block = document.getElementById(`product-option-${name.replace(/\W/g, "-")}`);
    if (!block) return;
    const container = block.querySelector(".product-option-values");
    container.innerHTML = productOptions[name].map(v => `
        <span class="product-option-chip">${escapeHtml(v.name)} <button type="button" data-id="${v.id}">&times;</button></span>
    `).join("");
    container.querySelectorAll("button").forEach(btn => btn.addEventListener("click", () => {
        productOptions[name] = productOptions[name].filter(v => v.id !== Number(btn.dataset.id));
        renderProductOptionTags(name);
        generateProductVariants();
    }));
}

document.getElementById("addProductOption").addEventListener("click", () => {
    addProductOption(document.getElementById("newProductOption").value);
    document.getElementById("newProductOption").value = "";
});

function cartesian(arrays) {
    return arrays.reduce((acc, current) => acc.flatMap(a => current.map(b => [...a, b])), [[]]);
}

function generateProductVariants(existingVariants = null) {
    const names = Object.keys(productOptions).filter(name => productOptions[name].length);
    const body = document.getElementById("productVariantsBody");
    body.innerHTML = "";
    if (!names.length) {
        body.innerHTML = '<tr><td colspan="5" class="muted center">Add option values to generate variants.</td></tr>';
        return;
    }
    const combinations = cartesian(names.map(name => productOptions[name]));
    const old = existingVariants || [];
    combinations.forEach((combo, index) => {
        const tr = document.createElement("tr");
        tr.className = "product-variant-row";
        tr.dataset.options = JSON.stringify(combo.map((v, i) => ({ option: names[i], id: v.id, name: v.name })));
        const oldVariant = old[index] || {};
        const price = oldVariant.price ?? document.getElementById("productPrice").value ?? 0;
        const cost = oldVariant.cost ?? "";
        const stock = oldVariant.stock ?? 0;
        const sku = oldVariant.sku ?? `SKU-${combo.map(v => v.name).join("-").replace(/[^a-zA-Z0-9]/g, "").toUpperCase()}`;
        tr.innerHTML = `
            <td><strong>${escapeHtml(combo.map(v => v.name).join(" / "))}</strong></td>
            <td><input type="number" class="variant-price" min="0" step="0.01" value="${escapeAttribute(price)}"></td>
            <td><input type="number" class="variant-cost" min="0" step="0.01" value="${escapeAttribute(cost)}"></td>
            <td><input type="number" class="variant-stock" min="0" step="1" value="${escapeAttribute(stock)}"></td>
            <td><input type="text" class="variant-sku" value="${escapeAttribute(sku)}"></td>
        `;
        body.appendChild(tr);
    });
}

function collectProductVariants() {
    return Array.from(document.querySelectorAll(".product-variant-row")).map(row => {
        const options = JSON.parse(row.dataset.options);
        const byName = Object.fromEntries(options.map(o => [o.option, o]));
        const variant = {
            price: Number(row.querySelector(".variant-price").value || 0),
            cost: row.querySelector(".variant-cost").value === "" ? null : Number(row.querySelector(".variant-cost").value),
            stock: Number(row.querySelector(".variant-stock").value || 0),
            sku: row.querySelector(".variant-sku").value.trim(),
            options: options.map(o => ({ name: o.option, id: o.id, value: o.name }))
        };
        if (byName.Color) { variant.color_id = byName.Color.id; variant.color = byName.Color.name; }
        if (byName.Size) { variant.size_id = byName.Size.id; variant.size = byName.Size.name; }
        return variant;
    });
}

document.getElementById("createProductButton").addEventListener("click", async () => {
    document.getElementById("productModalTitle").textContent = "Add Product";
    productForm.reset();
    document.getElementById("productId").value = "";
    resetProductImageState();
    resetProductEditor();
    await loadCatalogMetadata();
    await loadCollectionsForDropdown();
    openModal(productModal);
});

productForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const productId = document.getElementById("productId").value;
    const isEditing = !!productId;
    const variants = collectProductVariants();
    const colorIds = [...new Set(productOptions.Color?.map(v => v.id) || [])];
    const sizeIds = [...new Set(productOptions.Size?.map(v => v.id) || [])];
    const colors = [...new Set(productOptions.Color?.map(v => v.name) || [])];
    const sizes = [...new Set(productOptions.Size?.map(v => v.name) || [])];
    const firstVariantStock = variants.length ? variants.reduce((sum, v) => sum + Number(v.stock || 0), 0) : Number(document.getElementById("productStock").value || 0);
    const firstVariantPrice = variants.length ? Number(variants[0].price || 0) : Number(document.getElementById("productPrice").value || 0);

    const productData = {
        title: document.getElementById("productTitle").value.trim(),
        description: document.getElementById("productDescription").value.trim() || null,
        price: firstVariantPrice,
        stock: firstVariantStock,
        department_id: document.getElementById("productDepartment").value ? Number(document.getElementById("productDepartment").value) : null,
        category_id: document.getElementById("productCategoryId").value ? Number(document.getElementById("productCategoryId").value) : null,
        brand: document.getElementById("productBrand").value.trim() || null,
        type: document.getElementById("productType").value.trim() || null,
        color_ids: colorIds,
        color: colors,
        size_ids: sizeIds,
        size: sizes,
        material: document.getElementById("productMaterial").value.trim() || null,
        fit: document.getElementById("productFit").value || null,
        gender: document.getElementById("productGender").value || null,
        age_group: document.getElementById("productAgeGroup").value || null,
        tags: document.getElementById("productTags").value.split(",").map(v => v.trim()).filter(Boolean),
        media: currentProductImageUrl ? [currentProductImageUrl] : [],
        variants,
        attributes: {
            sleeve_length: document.getElementById("productSleeve").value || null,
            neckline: document.getElementById("productNeckline").value || null,
            top_length: document.getElementById("productLength").value || null,
            collection_id: document.getElementById("productCollection").value || null
        },
        is_featured: document.getElementById("productFeatured").checked
    };
    try {
        if (selectedProductImageFile) {
            currentProductImageUrl = await uploadProductImage(selectedProductImageFile);
            productData.media = currentProductImageUrl ? [currentProductImageUrl] : [];
        }

        const endpoint = isEditing ? `/dashboard/client/products/${productId}` : "/dashboard/client/products";
        await apiRequest(endpoint, { method: isEditing ? "PATCH" : "POST", body: JSON.stringify(productData) });
        closeModal(productModal);
        await loadProducts();
        await loadOverview();
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
        const result = await apiRequest(`/dashboard/client/products/${productId}`);
        const product = result.item;
        if (!product) throw new Error("Product not found");
        document.getElementById("productModalTitle").textContent = "Edit Product";
        productForm.reset();
        document.getElementById("productId").value = product._id || product.id || productId;
        document.getElementById("productTitle").value = product.title || "";
        document.getElementById("productDescription").value = product.description || "";
        document.getElementById("productPrice").value = product.price ?? 0;
        document.getElementById("productStock").value = product.stock ?? 0;
        document.getElementById("productBrand").value = product.brand || "";
        document.getElementById("productType").value = product.type || "";
        document.getElementById("productMaterial").value = product.material || "";
        document.getElementById("productFit").value = product.fit || "";
        document.getElementById("productGender").value = product.gender || "";
        document.getElementById("productAgeGroup").value = product.age_group || "";
        document.getElementById("productTags").value = (product.tags || []).join(", ");
        resetProductImageState();
        currentProductImageUrl = product.media?.[0] || "";
        if (currentProductImageUrl) setProductImagePreview(currentProductImageUrl, "Current image");
        document.getElementById("productFeatured").checked = !!product.is_featured;
        const attrs = product.attributes || {};
        document.getElementById("productSleeve").value = attrs.sleeve_length || "";
        document.getElementById("productNeckline").value = attrs.neckline || "";
        document.getElementById("productLength").value = attrs.top_length || "";

        resetProductEditor();
        await loadCatalogMetadata();
        populateDepartmentOptions(product.department_id || "");
        populateCategoryOptions(product.department_id, product.category_id || "");
        await loadCollectionsForDropdown();
        if (attrs.collection_id) document.getElementById("productCollection").value = attrs.collection_id;

        const variantColors = (product.variants || []).map(v => Number(v.color_id)).filter(Number.isFinite);
        const variantSizes = (product.variants || []).map(v => Number(v.size_id)).filter(Number.isFinite);
        const colorIds = [...new Set((product.color_ids?.length ? product.color_ids : variantColors))];
        const sizeIds = [...new Set((product.size_ids?.length ? product.size_ids : variantSizes))];
        if (colorIds.length) {
            addProductOption("Color", colorIds.map((id, index) => ({ id, name: catalogMetadata.colors?.[id] || product.color?.[index] || String(id) })));
        }
        if (sizeIds.length) {
            addProductOption("Size", sizeIds.map((id, index) => ({ id, name: catalogMetadata.sizes?.[id] || product.size?.[index] || String(id) })));
        }
        generateProductVariants(product.variants || []);
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
