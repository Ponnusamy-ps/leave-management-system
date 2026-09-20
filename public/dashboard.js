const token = localStorage.getItem("lms_token");
const storedUser = JSON.parse(localStorage.getItem("lms_user") || "null");

if (!token || !storedUser) {
  window.location.href = "/";
}

const api = async (url, options = {}) => {
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
      Authorization: `Bearer ${token}`
    }
  });

  const data = await response.json().catch(() => ({}));

  if (response.status === 401) {
    logout();
    throw new Error("Session expired.");
  }

  if (!response.ok) throw new Error(data.message || "Request failed.");
  return data;
};

function logout() {
  localStorage.removeItem("lms_token");
  localStorage.removeItem("lms_user");
  window.location.href = "/";
}

document.getElementById("logoutBtn").addEventListener("click", logout);

document.getElementById("welcomeText").textContent = `Hi, ${storedUser.fullName}`;
document.getElementById("roleText").textContent =
  storedUser.role === "admin" ? "Administrator" : "Employee";

const userView = document.getElementById("userView");
const adminView = document.getElementById("adminView");

if (storedUser.role === "admin") {
  adminView.classList.remove("hidden");
  loadAdmin();
} else {
  userView.classList.remove("hidden");
  loadUser();
}

async function loadUser() {
  try {
    const me = await api("/api/me");
    renderBalanceCards(me);
    await loadMyLeaves();
  } catch (error) {
    alert(error.message);
  }
}

function renderBalanceCards(me) {
  document.getElementById("balanceCards").innerHTML = `
    <div class="card"><span class="label">Annual Balance</span><strong class="value">${me.annualBalance} days</strong></div>
    <div class="card"><span class="label">Sick Balance</span><strong class="value">${me.sickBalance} days</strong></div>
    <div class="card"><span class="label">Casual Balance</span><strong class="value">${me.casualBalance} days</strong></div>
    <div class="card"><span class="label">Username</span><strong class="value" style="font-size:20px">${escapeHtml(me.username)}</strong></div>
  `;
}

async function loadMyLeaves() {
  const rows = await api("/api/leaves");
  const tbody = document.getElementById("myLeaves");

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">No leave requests yet.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map(leave => `
    <tr>
      <td>${escapeHtml(leave.leaveType)}</td>
      <td>${formatDate(leave.startDate)} → ${formatDate(leave.endDate)}</td>
      <td>${leave.days}</td>
      <td>${escapeHtml(leave.reason || "-")}</td>
      <td>
        <span class="status ${leave.status}">${leave.status}</span>
        ${leave.adminComment ? `<div style="margin-top:6px;font-size:12px">Admin: ${escapeHtml(leave.adminComment)}</div>` : ""}
      </td>
      <td>
        ${leave.status === "Pending"
          ? `<button class="btn danger" onclick="cancelLeave(${leave.id})">Cancel</button>`
          : "-"}
      </td>
    </tr>
  `).join("");
}

window.cancelLeave = async (id) => {
  if (!confirm("Cancel this pending leave request?")) return;

  try {
    await api(`/api/leaves/${id}`, { method: "DELETE" });
    await loadUser();
  } catch (error) {
    alert(error.message);
  }
};

document.getElementById("showApplyBtn").addEventListener("click", () => {
  document.getElementById("applySection").classList.remove("hidden");
});

document.getElementById("closeApplyBtn").addEventListener("click", () => {
  document.getElementById("applySection").classList.add("hidden");
});

document.getElementById("refreshBtn").addEventListener("click", loadUser);

document.getElementById("leaveForm").addEventListener("submit", async (event) => {
  event.preventDefault();

  const message = document.getElementById("leaveMessage");
  message.textContent = "Submitting...";
  message.className = "message";

  const payload = {
    leaveType: document.getElementById("leaveType").value,
    startDate: document.getElementById("startDate").value,
    endDate: document.getElementById("endDate").value,
    reason: document.getElementById("reason").value
  };

  try {
    await api("/api/leaves", {
      method: "POST",
      body: JSON.stringify(payload)
    });

    message.textContent = "Leave application submitted successfully.";
    message.className = "message success";
    event.target.reset();
    await loadUser();
  } catch (error) {
    message.textContent = error.message;
    message.className = "message error";
  }
});

async function loadAdmin() {
  try {
    const [stats, leaves, users] = await Promise.all([
      api("/api/admin/stats"),
      api("/api/leaves"),
      api("/api/admin/users")
    ]);

    renderAdminCards(stats);
    renderAllLeaves(leaves);
    renderEmployees(users);
  } catch (error) {
    alert(error.message);
  }
}

function renderAdminCards(stats) {
  document.getElementById("adminCards").innerHTML = `
    <div class="card"><span class="label">Employees</span><strong class="value">${stats.employees}</strong></div>
    <div class="card"><span class="label">Total Requests</span><strong class="value">${stats.total}</strong></div>
    <div class="card"><span class="label">Pending</span><strong class="value">${stats.pending}</strong></div>
    <div class="card"><span class="label">Approved</span><strong class="value">${stats.approved}</strong></div>
  `;
}

function renderAllLeaves(rows) {
  const tbody = document.getElementById("allLeaves");

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty">No leave requests available.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map(leave => `
    <tr>
      <td><b>${escapeHtml(leave.employeeName)}</b><br><small>${escapeHtml(leave.username)}</small></td>
      <td>${escapeHtml(leave.leaveType)}</td>
      <td>${formatDate(leave.startDate)} → ${formatDate(leave.endDate)}</td>
      <td>${leave.days}</td>
      <td>${escapeHtml(leave.reason || "-")}</td>
      <td><span class="status ${leave.status}">${leave.status}</span></td>
      <td>
        ${leave.status === "Pending" ? `
          <div class="actions">
            <button class="btn success" onclick="reviewLeave(${leave.id}, 'Approved')">Approve</button>
            <button class="btn reject" onclick="reviewLeave(${leave.id}, 'Rejected')">Reject</button>
          </div>
        ` : "-"}
      </td>
    </tr>
  `).join("");
}

window.reviewLeave = async (id, status) => {
  const adminComment = prompt(
    status === "Approved" ? "Optional approval comment:" : "Reason for rejection:"
  );

  if (status === "Rejected" && adminComment === null) return;

  try {
    await api(`/api/leaves/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, adminComment: adminComment || "" })
    });
    await loadAdmin();
  } catch (error) {
    alert(error.message);
  }
};

function renderEmployees(users) {
  const tbody = document.getElementById("employees");

  if (!users.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">No employees found.</td></tr>`;
    return;
  }

  tbody.innerHTML = users.map(user => `
    <tr>
      <td>${escapeHtml(user.fullName)}</td>
      <td>${escapeHtml(user.username)}</td>
      <td>${escapeHtml(user.email || "-")}</td>
      <td>${user.annualBalance}</td>
      <td>${user.sickBalance}</td>
      <td>${user.casualBalance}</td>
    </tr>
  `).join("");
}

document.getElementById("adminRefreshBtn").addEventListener("click", loadAdmin);

function formatDate(value) {
  const date = new Date(`${value}T00:00:00`);
  return date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
