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


loadOverview();
loadClients();
loadMessages();
loadUsage();
