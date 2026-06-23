<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import {
  apiRequest,
  getApiUrl,
  getAuthHeaders,
  type Admin,
  type AdminCreatePayload,
  type AdminStatus,
  type AdminTokenResponse,
  type AdminUpdatePayload,
  type ConsoleArticle,
  type ConsoleArticleDetail,
  type ConsoleArticleListResponse,
  type ConsoleUser,
  type ConsoleUserDetail,
  type ConsoleUserUpdatePayload,
  type UserStatus,
} from "./api";
import { loadTurnstileScript, turnstileSiteKey } from "./turnstile";

type ToastKind = "success" | "error";
type ConsoleView = "admins" | "users" | "user-detail";
type PaginationItem =
  | { type: "page"; key: string; page: number; label: string; active: boolean }
  | { type: "ellipsis"; key: string; label: string };

const token = ref(localStorage.getItem("wevault_console_token") || "");
const currentAdmin = ref<Admin | null>(null);
const activeView = ref<ConsoleView>("admins");
const authLoading = ref(false);
const authError = ref("");
const turnstileContainer = ref<HTMLElement | null>(null);
const turnstileToken = ref("");
const turnstileWidgetId = ref("");
const loginForm = ref({
  email: "",
  password: "",
});
const admins = ref<Admin[]>([]);
const adminLoading = ref(false);
const adminError = ref("");
const selectedAdminId = ref("");
const saving = ref(false);
const creating = ref(false);
const editForm = ref({
  displayName: "",
  status: "active" as AdminStatus,
  newPassword: "",
});
const createForm = ref({
  email: "",
  displayName: "",
  password: "",
  status: "active" as AdminStatus,
});
const users = ref<ConsoleUser[]>([]);
const userLoading = ref(false);
const userError = ref("");
const selectedUserId = ref("");
const userDetail = ref<ConsoleUserDetail | null>(null);
const userDetailLoading = ref(false);
const userEditModalOpen = ref(false);
const userSaving = ref(false);
const userEditForm = ref({
  displayName: "",
  status: "active" as UserStatus,
  newPassword: "",
});
const userArticles = ref<ConsoleArticle[]>([]);
const userArticleTotal = ref(0);
const userArticleLoading = ref(false);
const userArticleKeyword = ref("");
const userArticlePage = ref(1);
const userArticlePageSize = ref(10);
const userArticlePageJump = ref("");
const articleDetail = ref<ConsoleArticleDetail | null>(null);
const articleViewLoadingId = ref("");
const toast = ref<{ kind: ToastKind; message: string } | null>(null);
let toastTimer: number | undefined;

const isAuthenticated = computed(() => Boolean(token.value && currentAdmin.value));
const selectedAdmin = computed(
  () => admins.value.find((admin) => admin.id === selectedAdminId.value) || null,
);
const selectedUser = computed(
  () => userDetail.value || users.value.find((user) => user.id === selectedUserId.value) || null,
);
const activeAdminCount = computed(
  () => admins.value.filter((admin) => admin.status === "active").length,
);
const disabledAdminCount = computed(
  () => admins.value.filter((admin) => admin.status === "disabled").length,
);
const activeUserCount = computed(
  () => users.value.filter((user) => user.status === "active").length,
);
const disabledUserCount = computed(
  () => users.value.filter((user) => user.status === "disabled").length,
);
const userArticlePageCount = computed(() =>
  Math.max(1, Math.ceil(userArticleTotal.value / userArticlePageSize.value)),
);
const userArticlePaginationItems = computed(() =>
  buildPaginationItems(userArticlePage.value, userArticlePageCount.value),
);
const articleDetailHtml = computed(() => {
  const html = articleDetail.value?.content_clean_html || "";
  return html.replace(/(["'])\/api\/v1\//g, `$1${getApiUrl("/api/v1/")}`);
});

function authHeaders(): HeadersInit {
  return getAuthHeaders(token.value);
}

async function renderTurnstile() {
  if (!turnstileSiteKey || !turnstileContainer.value || turnstileWidgetId.value) {
    return;
  }

  try {
    await loadTurnstileScript();
    if (!window.turnstile || !turnstileContainer.value || turnstileWidgetId.value) {
      return;
    }
    turnstileWidgetId.value = window.turnstile.render(turnstileContainer.value, {
      sitekey: turnstileSiteKey,
      callback: (value: string) => {
        turnstileToken.value = value;
        authError.value = "";
      },
      "expired-callback": () => {
        turnstileToken.value = "";
      },
      "error-callback": () => {
        turnstileToken.value = "";
        authError.value = "人机验证加载失败，请刷新后重试";
      },
    });
  } catch {
    authError.value = "人机验证加载失败，请检查网络后刷新";
  }
}

function resetTurnstile() {
  turnstileToken.value = "";
  if (window.turnstile && turnstileWidgetId.value) {
    window.turnstile.reset(turnstileWidgetId.value);
  }
}

function buildPaginationItems(currentPage: number, totalPages: number): PaginationItem[] {
  const total = Math.max(1, totalPages);
  const current = Math.min(Math.max(currentPage, 1), total);
  if (total <= 9) {
    return Array.from({ length: total }, (_, index) => {
      const page = index + 1;
      return {
        type: "page",
        key: `page-${page}`,
        page,
        label: String(page),
        active: page === current,
      };
    });
  }

  const pages = new Set<number>([1, total]);
  for (let page = Math.max(2, current - 2); page <= Math.min(total - 1, current + 2); page += 1) {
    pages.add(page);
  }
  if (current <= 4) {
    for (let page = 2; page <= 5; page += 1) {
      pages.add(page);
    }
  }
  if (current >= total - 3) {
    for (let page = total - 4; page < total; page += 1) {
      pages.add(page);
    }
  }

  const items: PaginationItem[] = [];
  let previous = 0;
  for (const page of [...pages].sort((a, b) => a - b)) {
    if (previous > 0 && page - previous > 1) {
      items.push({ type: "ellipsis", key: `ellipsis-${previous}-${page}`, label: "..." });
    }
    items.push({
      type: "page",
      key: `page-${page}`,
      page,
      label: String(page),
      active: page === current,
    });
    previous = page;
  }
  return items;
}

function setSession(response: AdminTokenResponse) {
  token.value = response.access_token;
  currentAdmin.value = response.admin;
  localStorage.setItem("wevault_console_token", response.access_token);
}

function showToast(kind: ToastKind, message: string) {
  toast.value = { kind, message };
  if (toastTimer !== undefined) {
    window.clearTimeout(toastTimer);
  }
  toastTimer = window.setTimeout(() => {
    toast.value = null;
  }, 3000);
}

function statusLabel(status: AdminStatus) {
  const labels: Record<AdminStatus, string> = {
    active: "正常",
    restricted: "受限",
    disabled: "停用",
  };
  return labels[status];
}

function statusTag(status: AdminStatus) {
  if (status === "active") {
    return "success";
  }
  if (status === "disabled") {
    return "warning";
  }
  return "muted";
}

function tokenStatusLabel(status?: string | null) {
  const labels: Record<string, string> = {
    valid: "有效",
    expired: "已过期",
    invalid: "无效",
    unknown: "未知",
  };
  return status ? labels[status] || status : "未授权";
}

function tokenStatusTag(status?: string | null) {
  if (status === "valid") {
    return "success";
  }
  if (status === "expired" || status === "invalid") {
    return "warning";
  }
  return "muted";
}

function sourceStatusLabel(status?: string | null) {
  const labels: Record<string, string> = {
    active: "正常",
    paused: "停用",
    failed: "失败",
  };
  return status ? labels[status] || status : "-";
}

function articleStatusLabel(status: ConsoleArticle["content_status"]) {
  const labels: Record<ConsoleArticle["content_status"], string> = {
    pending: "未抓取",
    running: "抓取中",
    fetched: "已抓取",
    failed: "失败",
  };
  return labels[status];
}

function articleStatusTag(status: ConsoleArticle["content_status"]) {
  if (status === "fetched") {
    return "success";
  }
  if (status === "running") {
    return "progress";
  }
  if (status === "failed") {
    return "warning";
  }
  return "muted";
}

function articleCoverSrc(article: ConsoleArticle) {
  return article.cover_asset_url ? getApiUrl(article.cover_asset_url) : article.cover_url || "";
}

function sourceAvatarSrc(source: ConsoleArticle["source"]) {
  if (source.avatar_asset_url) {
    return getApiUrl(source.avatar_asset_url);
  }
  return source.avatar_url || "";
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatOptionalDateTime(value?: string | null) {
  return value ? formatDateTime(value) : "暂未获取";
}

function syncEditForm(admin: Admin | null) {
  editForm.value = {
    displayName: admin?.display_name || "",
    status: admin?.status || "active",
    newPassword: "",
  };
}

function syncUserEditForm(user: ConsoleUser | null) {
  userEditForm.value = {
    displayName: user?.display_name || "",
    status: user?.status || "active",
    newPassword: "",
  };
}

function setActiveView(view: ConsoleView) {
  activeView.value = view;
  if (view === "admins") {
    void loadAdmins();
  } else if (view === "users") {
    void loadUsers();
  }
}

async function loadMe() {
  if (!token.value) {
    window.setTimeout(() => {
      void renderTurnstile();
    });
    return;
  }

  try {
    currentAdmin.value = await apiRequest<Admin>("/admin/auth/me", {
      headers: authHeaders(),
    });
    await loadAdmins();
    await loadUsers();
  } catch {
    logout(false);
  }
}

async function submitLogin() {
  authLoading.value = true;
  authError.value = "";

  try {
    if (turnstileSiteKey && !turnstileToken.value) {
      authError.value = "请先完成人机验证";
      return;
    }

    const response = await apiRequest<AdminTokenResponse>("/admin/auth/login", {
      method: "POST",
      body: JSON.stringify({
        ...loginForm.value,
        turnstile_token: turnstileToken.value || null,
      }),
    });
    setSession(response);
    await loadAdmins();
    await loadUsers();
  } catch (error) {
    authError.value = error instanceof Error ? error.message : "登录失败";
    resetTurnstile();
  } finally {
    authLoading.value = false;
  }
}

async function loadAdmins() {
  if (!token.value) {
    admins.value = [];
    return;
  }

  adminLoading.value = true;
  adminError.value = "";
  try {
    admins.value = await apiRequest<Admin[]>("/admin/admins", {
      headers: authHeaders(),
    });
    if (!selectedAdminId.value && admins.value.length > 0) {
      selectedAdminId.value = admins.value[0].id;
    }
    if (selectedAdminId.value && !admins.value.some((admin) => admin.id === selectedAdminId.value)) {
      selectedAdminId.value = admins.value[0]?.id || "";
    }
    syncEditForm(selectedAdmin.value);
  } catch (error) {
    adminError.value = error instanceof Error ? error.message : "读取管理员列表失败";
  } finally {
    adminLoading.value = false;
  }
}

async function loadUsers() {
  if (!token.value) {
    users.value = [];
    return;
  }

  userLoading.value = true;
  userError.value = "";
  try {
    users.value = await apiRequest<ConsoleUser[]>("/admin/users", {
      headers: authHeaders(),
    });
    if (selectedUserId.value && !users.value.some((user) => user.id === selectedUserId.value)) {
      selectedUserId.value = "";
      userDetail.value = null;
    }
  } catch (error) {
    userError.value = error instanceof Error ? error.message : "读取用户列表失败";
  } finally {
    userLoading.value = false;
  }
}

function selectAdmin(admin: Admin) {
  selectedAdminId.value = admin.id;
  syncEditForm(admin);
}

function selectUser(user: ConsoleUser) {
  selectedUserId.value = user.id;
  void openUserDetail(user.id);
}

async function openUserDetail(userId: string) {
  selectedUserId.value = userId;
  activeView.value = "user-detail";
  userDetailLoading.value = true;
  userError.value = "";
  userArticlePage.value = 1;
  userArticleKeyword.value = "";
  try {
    userDetail.value = await apiRequest<ConsoleUserDetail>(`/admin/users/${userId}`, {
      headers: authHeaders(),
    });
    syncUserEditForm(userDetail.value);
    await loadUserArticles();
  } catch (error) {
    userError.value = error instanceof Error ? error.message : "读取用户详情失败";
    showToast("error", userError.value);
    activeView.value = "users";
  } finally {
    userDetailLoading.value = false;
  }
}

function backToUsers() {
  activeView.value = "users";
  userEditModalOpen.value = false;
}

async function loadUserArticles() {
  if (!selectedUserId.value || !token.value) {
    userArticles.value = [];
    userArticleTotal.value = 0;
    return;
  }

  userArticleLoading.value = true;
  const params = new URLSearchParams({
    page: String(userArticlePage.value),
    page_size: String(userArticlePageSize.value),
  });
  if (userArticleKeyword.value.trim()) {
    params.set("keyword", userArticleKeyword.value.trim());
  }

  try {
    const response = await apiRequest<ConsoleArticleListResponse>(
      `/admin/users/${selectedUserId.value}/articles?${params.toString()}`,
      { headers: authHeaders() },
    );
    userArticles.value = response.items;
    userArticleTotal.value = response.total;
    if (userArticlePage.value > userArticlePageCount.value) {
      userArticlePage.value = userArticlePageCount.value;
    }
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "读取文章列表失败");
  } finally {
    userArticleLoading.value = false;
  }
}

function searchUserArticles() {
  userArticlePage.value = 1;
  void loadUserArticles();
}

function resetUserArticleSearch() {
  userArticleKeyword.value = "";
  userArticlePage.value = 1;
  void loadUserArticles();
}

function setUserArticlePage(page: number) {
  userArticlePage.value = Math.min(Math.max(page, 1), userArticlePageCount.value);
  userArticlePageJump.value = "";
  void loadUserArticles();
}

function setUserArticlePageSize(event: Event) {
  const target = event.target as HTMLSelectElement;
  userArticlePageSize.value = Number(target.value);
  userArticlePage.value = 1;
  void loadUserArticles();
}

function onlyPageDigits(event: Event) {
  const target = event.target as HTMLInputElement;
  userArticlePageJump.value = target.value.replace(/\D/g, "");
}

function jumpToUserArticlePage() {
  const page = Number(userArticlePageJump.value);
  if (!Number.isInteger(page) || page < 1 || page > userArticlePageCount.value) {
    showToast("error", `请输入 1-${userArticlePageCount.value} 之间的页码`);
    return;
  }
  setUserArticlePage(page);
}

function viewOriginalArticle(article: ConsoleArticle) {
  window.open(article.original_url, "_blank", "noopener,noreferrer");
}

async function openArticleFromList(article: ConsoleArticle) {
  if (article.content_status !== "fetched") {
    viewOriginalArticle(article);
    return;
  }

  articleViewLoadingId.value = article.id;
  try {
    const detail = await apiRequest<ConsoleArticleDetail>(`/admin/articles/${article.id}`, {
      headers: authHeaders(),
    });
    if (!detail.content_clean_html && !detail.content_plain_text) {
      showToast("error", "本地正文为空，已打开原文");
      viewOriginalArticle(article);
      return;
    }
    articleDetail.value = detail;
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "读取正文失败");
  } finally {
    articleViewLoadingId.value = "";
  }
}

function closeArticleDetail() {
  articleDetail.value = null;
}

function openUserEditModal() {
  syncUserEditForm(selectedUser.value);
  userEditModalOpen.value = true;
}

async function saveSelectedAdmin() {
  if (!selectedAdmin.value) {
    return;
  }

  saving.value = true;
  const payload: AdminUpdatePayload = {
    display_name: editForm.value.displayName || null,
    status: editForm.value.status,
  };
  if (editForm.value.newPassword) {
    payload.new_password = editForm.value.newPassword;
  }

  try {
    const updated = await apiRequest<Admin>(`/admin/admins/${selectedAdmin.value.id}`, {
      method: "PATCH",
      headers: authHeaders(),
      body: JSON.stringify(payload),
    });
    admins.value = admins.value.map((admin) => (admin.id === updated.id ? updated : admin));
    if (currentAdmin.value?.id === updated.id) {
      currentAdmin.value = updated;
    }
    syncEditForm(updated);
    showToast("success", "管理员已更新");
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "保存失败");
  } finally {
    saving.value = false;
  }
}

async function saveSelectedUser() {
  if (!selectedUser.value) {
    return;
  }

  userSaving.value = true;
  const payload: ConsoleUserUpdatePayload = {
    display_name: userEditForm.value.displayName || null,
    status: userEditForm.value.status,
  };
  if (userEditForm.value.newPassword) {
    payload.new_password = userEditForm.value.newPassword;
  }

  try {
    const updated = await apiRequest<ConsoleUser>(`/admin/users/${selectedUser.value.id}`, {
      method: "PATCH",
      headers: authHeaders(),
      body: JSON.stringify(payload),
    });
    users.value = users.value.map((user) => (user.id === updated.id ? updated : user));
    if (userDetail.value?.id === updated.id) {
      userDetail.value = {
        ...userDetail.value,
        ...updated,
      };
    }
    syncUserEditForm(updated);
    userEditModalOpen.value = false;
    showToast("success", "用户已更新");
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "保存失败");
  } finally {
    userSaving.value = false;
  }
}

async function createAdmin() {
  creating.value = true;
  const payload: AdminCreatePayload = {
    email: createForm.value.email,
    password: createForm.value.password,
    display_name: createForm.value.displayName || null,
    status: createForm.value.status,
  };

  try {
    const created = await apiRequest<Admin>("/admin/admins", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(payload),
    });
    admins.value = [created, ...admins.value];
    selectedAdminId.value = created.id;
    syncEditForm(created);
    createForm.value = {
      email: "",
      displayName: "",
      password: "",
      status: "active",
    };
    showToast("success", "管理员已创建");
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "创建失败");
  } finally {
    creating.value = false;
  }
}

async function logout(callApi = true) {
  const activeToken = token.value;
  token.value = "";
  currentAdmin.value = null;
  admins.value = [];
  users.value = [];
  selectedAdminId.value = "";
  selectedUserId.value = "";
  userDetail.value = null;
  userEditModalOpen.value = false;
  localStorage.removeItem("wevault_console_token");

  if (callApi && activeToken) {
    await apiRequest("/admin/auth/logout", {
      method: "POST",
      headers: getAuthHeaders(activeToken),
    }).catch(() => undefined);
  }

  window.setTimeout(() => {
    void renderTurnstile();
  });
}

onMounted(() => {
  void loadMe();
});
</script>

<template>
  <main v-if="!isAuthenticated" class="login-page">
    <section class="login-card">
      <div class="brand">
        <span class="brand-mark">WV</span>
        <div>
          <strong>WeVault Console</strong>
          <span>管理员后台</span>
        </div>
      </div>

      <div class="login-heading">
        <h1>登录控制台</h1>
        <p>管理后台管理员账户。</p>
      </div>

      <form class="form" @submit.prevent="submitLogin">
        <label>
          <span>邮箱</span>
          <input v-model="loginForm.email" type="email" autocomplete="email" required />
        </label>
        <label>
          <span>密码</span>
          <input
            v-model="loginForm.password"
            type="password"
            autocomplete="current-password"
            required
          />
        </label>
        <div v-if="turnstileSiteKey" ref="turnstileContainer" class="turnstile-box"></div>
        <p v-if="authError" class="error-text">{{ authError }}</p>
        <button
          class="primary-button"
          type="submit"
          :disabled="authLoading || (Boolean(turnstileSiteKey) && !turnstileToken)"
        >
          {{ authLoading ? "登录中..." : "登录" }}
        </button>
      </form>
    </section>
  </main>

  <div v-else class="console-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">WV</span>
        <div>
          <strong>Console</strong>
          <span>{{ currentAdmin?.display_name || currentAdmin?.email }}</span>
        </div>
      </div>
      <nav class="nav-list">
        <button
          class="nav-item"
          :class="{ active: activeView === 'admins' }"
          type="button"
          @click="setActiveView('admins')"
        >
          管理员
        </button>
        <button
          class="nav-item"
          :class="{ active: activeView === 'users' || activeView === 'user-detail' }"
          type="button"
          @click="setActiveView('users')"
        >
          用户
        </button>
      </nav>
      <button class="ghost-button" type="button" @click="logout()">注销</button>
    </aside>

    <main class="workspace">
      <header class="topbar">
        <div>
          <h1>
            {{ activeView === "admins" ? "管理员" : activeView === "users" ? "用户" : "用户详情" }}
          </h1>
          <p>
            {{
              activeView === "admins"
                ? "第一版暂不区分权限，所有管理员都可以维护管理员账户。"
                : activeView === "users"
                  ? "查看和维护平台用户信息。"
                  : "查看用户授权、公众号源和账户信息。"
            }}
          </p>
        </div>
        <button
          v-if="activeView !== 'user-detail'"
          class="secondary-button"
          type="button"
          :disabled="activeView === 'admins' ? adminLoading : userLoading"
          @click="activeView === 'admins' ? loadAdmins() : loadUsers()"
        >
          {{ activeView === "admins" ? (adminLoading ? "刷新中..." : "刷新") : userLoading ? "刷新中..." : "刷新" }}
        </button>
      </header>

      <section v-if="activeView === 'admins'" class="metric-grid">
        <article class="metric">
          <span>管理员总数</span>
          <strong>{{ admins.length }}</strong>
        </article>
        <article class="metric">
          <span>正常</span>
          <strong>{{ activeAdminCount }}</strong>
        </article>
        <article class="metric">
          <span>停用</span>
          <strong>{{ disabledAdminCount }}</strong>
        </article>
      </section>
      <section v-else-if="activeView === 'users'" class="metric-grid">
        <article class="metric">
          <span>用户总数</span>
          <strong>{{ users.length }}</strong>
        </article>
        <article class="metric">
          <span>正常</span>
          <strong>{{ activeUserCount }}</strong>
        </article>
        <article class="metric">
          <span>停用</span>
          <strong>{{ disabledUserCount }}</strong>
        </article>
      </section>

      <section v-if="activeView === 'admins'" class="content-grid">
        <article class="panel wide-panel">
          <div class="panel-header">
            <div>
              <h2>管理员列表</h2>
              <p>点击一行查看并更新详情。</p>
            </div>
          </div>
          <div v-if="adminLoading" class="empty-state">正在读取管理员</div>
          <div v-else-if="adminError" class="empty-state error">{{ adminError }}</div>
          <div v-else-if="admins.length === 0" class="empty-state">还没有管理员</div>
          <div v-else class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>管理员</th>
                  <th>状态</th>
                  <th>创建时间</th>
                  <th>更新时间</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="admin in admins"
                  :key="admin.id"
                  :class="{ selected: selectedAdminId === admin.id }"
                  @click="selectAdmin(admin)"
                >
                  <td>
                    <div class="admin-cell">
                      <span class="avatar">{{ admin.email.slice(0, 1).toUpperCase() }}</span>
                      <div>
                        <strong>{{ admin.display_name || admin.email }}</strong>
                        <span>{{ admin.email }}</span>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span class="tag" :class="statusTag(admin.status)">
                      {{ statusLabel(admin.status) }}
                    </span>
                  </td>
                  <td>{{ formatDateTime(admin.created_at) }}</td>
                  <td>{{ formatDateTime(admin.updated_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>

        <aside class="side-stack">
          <article class="panel">
            <div class="panel-header">
              <div>
                <h2>详情</h2>
                <p>更新显示名称、状态或密码。</p>
              </div>
            </div>
            <div v-if="!selectedAdmin" class="empty-state">请选择管理员</div>
            <form v-else class="form" @submit.prevent="saveSelectedAdmin">
              <label>
                <span>邮箱</span>
                <input :value="selectedAdmin.email" type="email" disabled />
              </label>
              <label>
                <span>显示名称</span>
                <input v-model="editForm.displayName" type="text" maxlength="80" />
              </label>
              <label>
                <span>状态</span>
                <select v-model="editForm.status">
                  <option value="active">正常</option>
                  <option value="restricted">受限</option>
                  <option value="disabled">停用</option>
                </select>
              </label>
              <label>
                <span>新密码</span>
                <input
                  v-model="editForm.newPassword"
                  type="password"
                  minlength="8"
                  maxlength="128"
                  placeholder="留空则不修改"
                />
              </label>
              <button class="primary-button" type="submit" :disabled="saving">
                {{ saving ? "保存中..." : "保存" }}
              </button>
            </form>
          </article>

          <article class="panel">
            <div class="panel-header">
              <div>
                <h2>新增管理员</h2>
                <p>创建后可直接登录 Console。</p>
              </div>
            </div>
            <form class="form" @submit.prevent="createAdmin">
              <label>
                <span>邮箱</span>
                <input v-model="createForm.email" type="email" autocomplete="off" required />
              </label>
              <label>
                <span>显示名称</span>
                <input v-model="createForm.displayName" type="text" maxlength="80" />
              </label>
              <label>
                <span>密码</span>
                <input
                  v-model="createForm.password"
                  type="password"
                  minlength="8"
                  maxlength="128"
                  autocomplete="new-password"
                  required
                />
              </label>
              <label>
                <span>状态</span>
                <select v-model="createForm.status">
                  <option value="active">正常</option>
                  <option value="restricted">受限</option>
                  <option value="disabled">停用</option>
                </select>
              </label>
              <button class="secondary-button" type="submit" :disabled="creating">
                {{ creating ? "创建中..." : "创建管理员" }}
              </button>
            </form>
          </article>
        </aside>
      </section>

      <section v-else-if="activeView === 'users'" class="content-grid single-column">
        <article class="panel wide-panel">
          <div class="panel-header">
            <div>
              <h2>用户列表</h2>
              <p>点击一行进入用户详情。</p>
            </div>
          </div>
          <div v-if="userLoading" class="empty-state">正在读取用户</div>
          <div v-else-if="userError" class="empty-state error">{{ userError }}</div>
          <div v-else-if="users.length === 0" class="empty-state">还没有用户</div>
          <div v-else class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>用户</th>
                  <th>授权公众号</th>
                  <th>状态</th>
                  <th>创建时间</th>
                  <th>更新时间</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="user in users"
                  :key="user.id"
                  :class="{ selected: selectedUserId === user.id }"
                  @click="selectUser(user)"
                >
                  <td>
                    <div class="admin-cell">
                      <span class="avatar">{{ user.email.slice(0, 1).toUpperCase() }}</span>
                      <div>
                        <strong>{{ user.display_name || user.email }}</strong>
                        <span>{{ user.email }}</span>
                      </div>
                    </div>
                  </td>
                  <td>
                    <div v-if="user.wechat_account" class="wechat-cell">
                      <img
                        v-if="user.wechat_account.avatar_url"
                        :src="user.wechat_account.avatar_url"
                        alt=""
                      />
                      <span v-else class="wechat-avatar-fallback">微</span>
                      <div>
                        <strong>{{ user.wechat_account.nickname }}</strong>
                        <span class="tag" :class="tokenStatusTag(user.wechat_account.token_status)">
                          {{ tokenStatusLabel(user.wechat_account.token_status) }}
                        </span>
                      </div>
                    </div>
                    <span v-else class="muted-text">未授权</span>
                  </td>
                  <td>
                    <span class="tag" :class="statusTag(user.status)">
                      {{ statusLabel(user.status) }}
                    </span>
                  </td>
                  <td>{{ formatDateTime(user.created_at) }}</td>
                  <td>{{ formatDateTime(user.updated_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>
      </section>

      <section v-else class="user-detail-page">
        <div v-if="userDetailLoading" class="empty-state">正在读取用户详情</div>
        <div v-else-if="!userDetail" class="empty-state">请选择用户</div>
        <template v-else>
          <section class="panel user-profile-panel">
            <button class="link-button" type="button" @click="backToUsers">返回用户列表</button>
            <div class="user-profile-main">
              <span class="avatar large">{{ userDetail.email.slice(0, 1).toUpperCase() }}</span>
              <div>
                <h2>{{ userDetail.display_name || userDetail.email }}</h2>
                <p>{{ userDetail.email }}</p>
                <span class="tag" :class="statusTag(userDetail.status)">
                  {{ statusLabel(userDetail.status) }}
                </span>
              </div>
            </div>
            <button class="secondary-button" type="button" @click="openUserEditModal">编辑</button>
          </section>

          <section class="panel">
            <div class="panel-header">
              <div>
                <h2>授权公众号</h2>
                <p>用户扫码授权过的公众号登录态。</p>
              </div>
            </div>
            <div v-if="userDetail.wechat_accounts.length === 0" class="empty-state">未授权公众号</div>
            <div v-else class="wechat-account-list">
              <article
                v-for="account in userDetail.wechat_accounts"
                :key="account.id"
                class="wechat-account-item"
              >
                <div class="wechat-detail-heading">
                  <img v-if="account.avatar_url" :src="account.avatar_url" alt="" />
                  <span v-else class="wechat-avatar-fallback">微</span>
                  <div>
                    <strong>{{ account.nickname }}</strong>
                    <span>{{ account.username || account.biz || "-" }}</span>
                  </div>
                </div>
                <span class="tag" :class="tokenStatusTag(account.token_status)">
                  {{ tokenStatusLabel(account.token_status) }}
                </span>
                <dl>
                  <div>
                    <dt>到期时间</dt>
                    <dd>{{ formatOptionalDateTime(account.expires_at) }}</dd>
                  </div>
                  <div>
                    <dt>最近验证</dt>
                    <dd>{{ formatOptionalDateTime(account.last_verified_at) }}</dd>
                  </div>
                </dl>
              </article>
            </div>
          </section>

          <section class="panel">
            <div class="panel-header">
              <div>
                <h2>公众号源</h2>
                <p>用户关注并采集的公众号源。</p>
              </div>
            </div>
            <div v-if="userDetail.sources.length === 0" class="empty-state">还没有公众号源</div>
            <div v-else class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>公众号</th>
                    <th>最后抓取</th>
                    <th>在库文章</th>
                    <th>状态</th>
                    <th>自动更新</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="source in userDetail.sources" :key="source.id" class="static-row">
                    <td>
                      <div class="wechat-cell">
                        <img v-if="source.avatar_url" :src="source.avatar_url" alt="" />
                        <span v-else class="wechat-avatar-fallback">微</span>
                        <div>
                          <strong>{{ source.name }}</strong>
                          <span>{{ source.alias || source.description || "-" }}</span>
                        </div>
                      </div>
                    </td>
                    <td>{{ formatOptionalDateTime(source.last_list_fetched_at) }}</td>
                    <td>{{ source.article_count }}</td>
                    <td>
                      <span class="tag" :class="statusTag(source.status === 'active' ? 'active' : 'disabled')">
                        {{ sourceStatusLabel(source.status) }}
                      </span>
                    </td>
                    <td>
                      <span class="tag" :class="source.auto_fetch_enabled ? 'success' : 'muted'">
                        {{ source.auto_fetch_enabled ? "开启" : "关闭" }}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section class="panel">
            <div class="panel-header">
              <div>
                <h2>文章列表</h2>
                <p>按标题、摘要或公众号搜索该用户的文章。</p>
              </div>
              <button
                class="secondary-button"
                type="button"
                :disabled="userArticleLoading"
                @click="loadUserArticles"
              >
                {{ userArticleLoading ? "刷新中..." : "刷新" }}
              </button>
            </div>
            <form class="filter-bar" @submit.prevent="searchUserArticles">
              <input
                v-model="userArticleKeyword"
                type="search"
                placeholder="搜索标题、摘要、公众号"
              />
              <button class="primary-button" type="submit" :disabled="userArticleLoading">搜索</button>
              <button
                class="secondary-button"
                type="button"
                :disabled="userArticleLoading"
                @click="resetUserArticleSearch"
              >
                重置
              </button>
            </form>
            <div v-if="userArticleLoading" class="empty-state">正在读取文章</div>
            <div v-else-if="userArticles.length === 0" class="empty-state">还没有文章</div>
            <template v-else>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>封面</th>
                      <th>文章</th>
                      <th>公众号</th>
                      <th>发布时间</th>
                      <th>正文</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="article in userArticles" :key="article.id" class="static-row">
                      <td>
                        <button
                          class="article-cover-button"
                          type="button"
                          :aria-label="`查看 ${article.title}`"
                          @click="openArticleFromList(article)"
                        >
                          <img
                            v-if="article.cover_url || article.cover_asset_url"
                            class="article-cover"
                            :src="articleCoverSrc(article)"
                            :alt="article.title"
                          />
                          <span v-else class="article-cover article-cover-empty">WV</span>
                        </button>
                      </td>
                      <td>
                        <button
                          class="article-title-cell article-title-button"
                          type="button"
                          @click="openArticleFromList(article)"
                        >
                          <strong>{{ article.title }}</strong>
                          <span>{{ article.digest || "暂无摘要" }}</span>
                        </button>
                      </td>
                      <td>
                        <div class="wechat-cell">
                          <img
                            v-if="article.source.avatar_url || article.source.avatar_asset_url"
                            :src="sourceAvatarSrc(article.source)"
                            :alt="article.source.name"
                          />
                          <span v-else class="wechat-avatar-fallback">微</span>
                          <div>
                            <strong>{{ article.source.name }}</strong>
                          </div>
                        </div>
                      </td>
                      <td>{{ formatOptionalDateTime(article.publish_time) }}</td>
                      <td>
                        <span class="tag" :class="articleStatusTag(article.content_status)">
                          {{ articleStatusLabel(article.content_status) }}
                        </span>
                      </td>
                      <td>
                        <button class="link-button" type="button" @click="viewOriginalArticle(article)">
                          查看原文
                        </button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div class="pagination-bar">
                <div class="pagination-controls">
                  <label>
                    <span>每页</span>
                    <select :value="userArticlePageSize" @change="setUserArticlePageSize">
                      <option :value="10">10</option>
                      <option :value="20">20</option>
                      <option :value="50">50</option>
                    </select>
                  </label>
                  <form class="page-jump-form" @submit.prevent="jumpToUserArticlePage">
                    <span>跳至</span>
                    <input
                      v-model="userArticlePageJump"
                      type="text"
                      inputmode="numeric"
                      pattern="[0-9]*"
                      :placeholder="String(userArticlePage)"
                      @input="onlyPageDigits"
                    />
                    <span>页</span>
                    <button class="link-button" type="submit">跳转</button>
                  </form>
                  <span>共 {{ userArticleTotal }} 篇</span>
                </div>
                <div class="pagination-links">
                  <button
                    class="page-button"
                    type="button"
                    :disabled="userArticlePage <= 1"
                    @click="setUserArticlePage(1)"
                  >
                    <<
                  </button>
                  <button
                    class="page-button"
                    type="button"
                    :disabled="userArticlePage <= 1"
                    @click="setUserArticlePage(userArticlePage - 1)"
                  >
                    上一页
                  </button>
                  <template v-for="item in userArticlePaginationItems" :key="item.key">
                    <button
                      v-if="item.type === 'page'"
                      class="page-button"
                      :class="{ active: item.active }"
                      type="button"
                      @click="setUserArticlePage(item.page)"
                    >
                      {{ item.label }}
                    </button>
                    <span v-else class="page-ellipsis">{{ item.label }}</span>
                  </template>
                  <button
                    class="page-button"
                    type="button"
                    :disabled="userArticlePage >= userArticlePageCount"
                    @click="setUserArticlePage(userArticlePage + 1)"
                  >
                    下一页
                  </button>
                  <button
                    class="page-button"
                    type="button"
                    :disabled="userArticlePage >= userArticlePageCount"
                    @click="setUserArticlePage(userArticlePageCount)"
                  >
                    >>
                  </button>
                </div>
              </div>
            </template>
          </section>
        </template>
      </section>
    </main>

    <div v-if="userEditModalOpen && selectedUser" class="modal-backdrop">
      <section class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="user-edit-title">
        <div class="panel-header">
          <div>
            <h2 id="user-edit-title">编辑用户</h2>
            <p>{{ selectedUser.email }}</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" @click="userEditModalOpen = false">
            ×
          </button>
        </div>
        <form class="form" @submit.prevent="saveSelectedUser">
          <label>
            <span>显示名称</span>
            <input v-model="userEditForm.displayName" type="text" maxlength="80" />
          </label>
          <label>
            <span>状态</span>
            <select v-model="userEditForm.status">
              <option value="active">正常</option>
              <option value="restricted">受限</option>
              <option value="disabled">停用</option>
            </select>
          </label>
          <label>
            <span>新密码</span>
            <input
              v-model="userEditForm.newPassword"
              type="password"
              minlength="8"
              maxlength="128"
              placeholder="留空则不修改"
            />
          </label>
          <div class="modal-actions">
            <button class="secondary-button" type="button" @click="userEditModalOpen = false">
              取消
            </button>
            <button class="primary-button" type="submit" :disabled="userSaving">
              {{ userSaving ? "保存中..." : "保存" }}
            </button>
          </div>
        </form>
      </section>
    </div>

    <div v-if="articleDetail" class="modal-backdrop">
      <section
        class="modal-panel article-detail-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="article-detail-title"
      >
        <div class="panel-header">
          <div>
            <h2 id="article-detail-title">{{ articleDetail.title }}</h2>
            <p>
              {{ articleDetail.source.name }}
              <span v-if="articleDetail.publish_time">
                · {{ formatDateTime(articleDetail.publish_time) }}
              </span>
            </p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" @click="closeArticleDetail">
            ×
          </button>
        </div>
        <div class="article-detail-actions">
          <a :href="articleDetail.original_url" target="_blank" rel="noreferrer">查看原文</a>
        </div>
        <article
          v-if="articleDetailHtml"
          class="article-detail-body"
          v-html="articleDetailHtml"
        ></article>
        <pre v-else class="article-detail-text">{{ articleDetail.content_plain_text }}</pre>
      </section>
    </div>

    <div v-if="toast" class="toast" :class="toast.kind">{{ toast.message }}</div>
  </div>
</template>
