if (
    !localStorage.getItem(
        "meridin_admin_token"
    )
) {
    window.location.href =
        "login.html";
}


async function loadOverview() {

    try {

        const data =
            await apiRequest(
                "/dashboard/admin/overview"
            );

        const metrics =
            data.metrics;

        document.getElementById(
            "clientsMetric"
        ).textContent =
            metrics.clients;

        document.getElementById(
            "activeClientsMetric"
        ).textContent =
            metrics.active_clients;

        document.getElementById(
            "messagesMetric"
        ).textContent =
            metrics.messages;

        document.getElementById(
            "customersMetric"
        ).textContent =
            metrics.customers;

    } catch (error) {

        console.error(error);
    }
}


async function loadClients() {

    const container =
        document.getElementById(
            "clientsList"
        );

    try {

        const data =
            await apiRequest(
                "/dashboard/admin/clients"
            );

        if (!data.items.length) {

            container.innerHTML =
                '<p class="muted">No clients.</p>';

            return;
        }

        container.innerHTML = `
            <table>

                <thead>

                    <tr>

                        <th>
                            Business
                        </th>

                        <th>
                            Tenant
                        </th>

                        <th>
                            Status
                        </th>

                        <th>
                            WhatsApp
                        </th>

                        <th>
                            Action
                        </th>

                    </tr>

                </thead>

                <tbody>

                    ${data.items.map(client => `

                        <tr>

                            <td>
                                ${escapeHtml(
                                    client.business_name || "-"
                                )}
                            </td>

                            <td>
                                ${escapeHtml(
                                    client.tenant_id || "-"
                                )}
                            </td>

                            <td>

                                ${
                                    client.is_active
                                        ? `<span class="active-label">
                                            Active
                                           </span>`
                                        : `<span class="inactive-label">
                                            Suspended
                                           </span>`
                                }

                            </td>

                            <td>
                                ${
                                    client.phone_number_id
                                        ? "Connected"
                                        : "Not configured"
                                }
                            </td>

                            <td>

                                <button
                                    class="table-button"
                                    onclick="toggleClient(
                                        '${client._id}',
                                        ${!client.is_active}
                                    )"
                                >
                                    ${
                                        client.is_active
                                            ? "Suspend"
                                            : "Activate"
                                    }
                                </button>

                            </td>

                        </tr>

                    `).join("")}

                </tbody>

            </table>
        `;

    } catch (error) {

        container.innerHTML =
            `<p class="error">
                ${escapeHtml(error.message)}
             </p>`;
    }
}


async function toggleClient(
    clientId,
    newStatus
) {

    try {

        await apiRequest(
            `/dashboard/admin/clients/${clientId}/status`,
            {
                method: "PATCH",

                body: JSON.stringify({
                    is_active: newStatus
                })
            }
        );

        await loadClients();

        await loadOverview();

    } catch (error) {

        alert(error.message);
    }
}


async function loadMessages() {

    const container =
        document.getElementById(
            "messagesList"
        );

    try {

        const data =
            await apiRequest(
                "/dashboard/admin/messages"
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

                        <th>
                            Tenant
                        </th>

                        <th>
                            Direction
                        </th>

                        <th>
                            Message
                        </th>

                        <th>
                            Intent
                        </th>

                        <th>
                            Time
                        </th>

                    </tr>

                </thead>

                <tbody>

                    ${data.items.map(message => `

                        <tr>

                            <td>
                                ${escapeHtml(
                                    message.tenant_id || "-"
                                )}
                            </td>

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
            `<p class="error">
                ${escapeHtml(error.message)}
             </p>`;
    }
}


async function loadUsage() {

    const container =
        document.getElementById(
            "usageList"
        );

    try {

        const data =
            await apiRequest(
                "/dashboard/admin/usage"
            );

        container.innerHTML = `

            <section class="panel">

                <h2>
                    AI model usage
                </h2>

                <div class="analytics-list">

                    ${
                        data.ai_model_usage.length
                            ? data.ai_model_usage
                                .slice(0, 20)
                                .map(item => `

                                    <div>

                                        <span>
                                            ${escapeHtml(
                                                item.tenant_id || "-"
                                            )}
                                        </span>

                                        <strong>
                                            ${item.tokens_used ?? item.tokens ?? "-"}
                                        </strong>

                                    </div>

                                `).join("")
                            : '<p class="muted">No AI usage records.</p>'
                    }

                </div>

            </section>

            <section class="panel">

                <h2>
                    Meta conversation usage
                </h2>

                <div class="analytics-list">

                    ${
                        data.meta_conversation_usage.length
                            ? data.meta_conversation_usage
                                .slice(0, 20)
                                .map(item => `

                                    <div>

                                        <span>
                                            ${escapeHtml(
                                                item.tenant_id || "-"
                                            )}
                                        </span>

                                        <strong>
                                            ${item.messages ?? item.count ?? "-"}
                                        </strong>

                                    </div>

                                `).join("")
                            : '<p class="muted">No Meta usage records.</p>'
                    }

                </div>

            </section>

        `;

    } catch (error) {

        container.innerHTML =
            `<p class="error">
                ${escapeHtml(error.message)}
             </p>`;
    }
}


document.getElementById(
    "logoutButton"
).addEventListener(
    "click",
    () => {

        localStorage.removeItem(
            "meridin_admin_token"
        );

        window.location.href =
            "login.html";
    }
);


function formatDate(value) {

    if (!value) {
        return "-";
    }

    return new Date(value)
        .toLocaleString(
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



async function loadR2Usage() {
    const container = document.getElementById("r2UsageList");

    try {
        const data = await apiRequest("/dashboard/admin/r2-usage");
        const usage = data.usage || {};
        const limits = data.limits || {};
        const guard = data.guard_limits || {};
        const cf = data.cloudflare || {};

        const statusText = data.blocked
            ? "STOPPED"
            : data.warning
                ? "WARNING"
                : "SAFE";

        const statusClass = data.blocked
            ? "inactive-label"
            : data.warning
                ? "warning-label"
                : "active-label";

        container.innerHTML = `
            <section class="panel">
                <h2>Global safety status</h2>
                <p><span class="${statusClass}">${statusText}</span></p>
                <p class="muted">Meridin stops new image activity at 90% of each free-tier limit.</p>
                <p class="muted">Warning starts at 80%.</p>
                <p class="muted">Month: ${escapeHtml(data.month || "-")}</p>
            </section>

            <section class="panel">
                <h2>Storage</h2>
                <p><strong>${usage.storage_gb ?? 0} GB</strong> / ${limits.storage_bytes ? (limits.storage_bytes / 1000000000).toFixed(0) : 10} GB</p>
                <p class="muted">${usage.storage_percent ?? 0}% used</p>
                <p class="muted">Guard: ${guard.storage_bytes ? (guard.storage_bytes / 1000000000).toFixed(1) : 9} GB</p>
            </section>

            <section class="panel">
                <h2>Class A</h2>
                <p><strong>${Number(usage.class_a || 0).toLocaleString()}</strong> / ${Number(limits.class_a || 1000000).toLocaleString()}</p>
                <p class="muted">${usage.class_a_percent ?? 0}% used</p>
                <p class="muted">Guard: ${Number(guard.class_a || 900000).toLocaleString()}</p>
            </section>

            <section class="panel">
                <h2>Class B</h2>
                <p><strong>${Number(usage.class_b || 0).toLocaleString()}</strong> / ${Number(limits.class_b || 10000000).toLocaleString()}</p>
                <p class="muted">${usage.class_b_percent ?? 0}% used</p>
                <p class="muted">Guard: ${Number(guard.class_b || 9000000).toLocaleString()}</p>
            </section>

            <section class="panel">
                <h2>Cloudflare reported operations</h2>
                <p>Class A: <strong>${Number(cf.cloudflare_class_a || 0).toLocaleString()}</strong></p>
                <p>Class B: <strong>${Number(cf.cloudflare_class_b || 0).toLocaleString()}</strong></p>
                <p class="muted">Cloudflare analytics can lag. Meridin also uses Redis guard counters.</p>
            </section>

            <section class="panel">
                <h2>Meridin guard counters</h2>
                <p>Upload reservations: <strong>${Number(data.guard_counters?.class_a_reserved || 0).toLocaleString()}</strong></p>
                <p>Image views: <strong>${Number(data.guard_counters?.class_b_views || 0).toLocaleString()}</strong></p>
                <p class="muted">Scope: global, not tenant-specific.</p>
            </section>
        `;
    } catch (error) {
        container.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
    }
}

document.getElementById("refreshR2Button")?.addEventListener("click", loadR2Usage);

loadOverview();
loadClients();
loadMessages();
loadUsage();
loadR2Usage();
