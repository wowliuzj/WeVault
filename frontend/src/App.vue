<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import {
  apiRequest,
  getAuthHeaders,
  type TokenResponse,
  type User,
  type WechatAccount,
  type WechatLoginSession,
} from "./api";

type ViewId = "dashboard" | "auth" | "sources" | "articles" | "tasks" | "exports" | "settings";
type AuthMode = "login" | "register";

const views: Array<{ id: ViewId; label: string; icon: string; title: string; subtitle: string }> = [
  {
    id: "dashboard",
    label: "概览",
    icon: "⌂",
    title: "概览",
    subtitle: "查看授权、采集、文章和导出状态。",
  },
  {
    id: "auth",
    label: "授权状态",
    icon: "⌁",
    title: "授权状态",
    subtitle: "管理当前用户绑定的微信公众号登录态。",
  },
  {
    id: "sources",
    label: "公众号源",
    icon: "◎",
    title: "公众号源",
    subtitle: "添加公众号后先同步文章列表，再按策略抓正文和评论。",
  },
  {
    id: "articles",
    label: "文章库",
    icon: "≡",
    title: "文章库",
    subtitle: "统一管理文章列表、正文状态、评论状态和导出操作。",
  },
  {
    id: "tasks",
    label: "采集任务",
    icon: "↻",
    title: "采集任务",
    subtitle: "跟踪列表同步、正文抓取、评论抓取和导出任务。",
  },
  {
    id: "exports",
    label: "导出中心",
    icon: "⇩",
    title: "导出中心",
    subtitle: "生成保留文本的 PDF、DOCX 和 Markdown 文件。",
  },
  {
    id: "settings",
    label: "设置",
    icon: "⚙",
    title: "设置",
    subtitle: "配置默认采集策略和导出偏好。",
  },
];

const recentArticles = [
  {
    title: "AI 产品经理的长期主义",
    source: "产品笔记",
    publishedAt: "2026-06-09",
    contentStatus: "已抓取",
    contentTag: "success",
    commentStatus: "已抓取",
    commentTag: "success",
    action: "导出",
  },
  {
    title: "一文讲清企业知识库落地",
    source: "技术观察站",
    publishedAt: "2026-06-08",
    contentStatus: "待抓取",
    contentTag: "warning",
    commentStatus: "未开始",
    commentTag: "muted",
    action: "抓取",
  },
  {
    title: "内容归档系统的边界",
    source: "SaaS 方法论",
    publishedAt: "2026-06-07",
    contentStatus: "抓取中",
    contentTag: "progress",
    commentStatus: "未开始",
    commentTag: "muted",
    action: "查看",
  },
];

const sources = [
  { name: "产品笔记", note: "18,642 篇文章 · 自动正文开启 · 自动评论关闭" },
  { name: "技术观察站", note: "7,104 篇文章 · 自动正文关闭 · 自动评论关闭" },
  { name: "SaaS 方法论", note: "3,912 篇文章 · 自动正文开启 · 自动评论开启" },
];

const tasks = [
  { type: "fetch_article_content", note: "技术观察站 · 12/40 · running", progress: 30 },
  { type: "fetch_source_articles", note: "产品笔记 · 120/120 · succeeded", progress: 100 },
  { type: "fetch_article_comments", note: "SaaS 方法论 · waiting", progress: 0 },
];

const exports = [
  { name: "产品笔记精选 24 篇", note: "PDF · 保留文本 · 28.4 MB" },
  { name: "企业知识库专题", note: "DOCX · 16 篇文章 · 12.1 MB" },
  { name: "SaaS 方法论评论包", note: "Markdown ZIP · 包含评论" },
];

const activeView = ref<ViewId>("dashboard");
const sidebarCollapsed = ref(false);
const mobileMenuOpen = ref(false);
const userMenuOpen = ref(false);
const authMode = ref<AuthMode>("login");
const authLoading = ref(false);
const authError = ref("");
const token = ref(localStorage.getItem("wevault_token") || "");
const currentUser = ref<User | null>(null);
const authForm = ref({
  email: "",
  password: "",
  displayName: "",
});
const wechatAccount = ref<WechatAccount | null>(null);
const wechatLoading = ref(false);
const wechatLoginLoading = ref(false);
const wechatLoginError = ref("");
const wechatLoginSession = ref<WechatLoginSession | null>(null);
let wechatLoginTimer: number | undefined;

const currentView = computed(() => views.find((view) => view.id === activeView.value) ?? views[0]);
const isAuthenticated = computed(() => Boolean(token.value && currentUser.value));
const showWechatLoginModal = computed(() => Boolean(wechatLoginSession.value || wechatLoginError.value));
const showWechatLoginLoading = computed(
  () => wechatLoginLoading.value && !showWechatLoginModal.value,
);
const wechatStatusLabel = computed(() => {
  if (wechatLoading.value) {
    return "读取中";
  }
  return wechatAccount.value ? "有效" : "未授权";
});
const wechatStatusNote = computed(() => {
  if (wechatLoading.value) {
    return "正在读取授权状态";
  }
  if (!wechatAccount.value) {
    return "扫码后可采集公众号文章";
  }
  return `当前公众号：${wechatAccount.value.nickname}`;
});
const wechatExpiresLabel = computed(() => formatDateTime(wechatAccount.value?.expires_at));

function setSession(response: TokenResponse) {
  token.value = response.access_token;
  currentUser.value = response.user;
  localStorage.setItem("wevault_token", response.access_token);
}

function authHeaders(): HeadersInit {
  return getAuthHeaders(token.value);
}

async function loadCurrentUser() {
  if (!token.value) {
    return;
  }

  try {
    currentUser.value = await apiRequest<User>("/auth/me", {
      headers: getAuthHeaders(token.value),
    });
    await loadWechatAccount();
  } catch {
    logout();
  }
}

async function submitAuth() {
  authLoading.value = true;
  authError.value = "";

  try {
    const path = authMode.value === "login" ? "/auth/login" : "/auth/register";
    const payload =
      authMode.value === "login"
        ? {
            email: authForm.value.email,
            password: authForm.value.password,
          }
        : {
            email: authForm.value.email,
            password: authForm.value.password,
            display_name: authForm.value.displayName || null,
          };

    const response = await apiRequest<TokenResponse>(path, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setSession(response);
    await loadWechatAccount();
  } catch (error) {
    authError.value = error instanceof Error ? error.message : "登录失败";
  } finally {
    authLoading.value = false;
  }
}

function switchAuthMode(mode: AuthMode) {
  authMode.value = mode;
  authError.value = "";
}

function setView(viewId: ViewId) {
  activeView.value = viewId;
  mobileMenuOpen.value = false;

  if (viewId === "auth") {
    void loadWechatAccount();
  }
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value;
}

function toggleMobileMenu() {
  mobileMenuOpen.value = !mobileMenuOpen.value;
}

function toggleUserMenu(event: MouseEvent) {
  event.stopPropagation();
  userMenuOpen.value = !userMenuOpen.value;
}

function closeUserMenu() {
  userMenuOpen.value = false;
}

async function logout() {
  const activeToken = token.value;
  token.value = "";
  currentUser.value = null;
  wechatAccount.value = null;
  closeWechatLogin();
  userMenuOpen.value = false;
  localStorage.removeItem("wevault_token");

  if (activeToken) {
    await apiRequest("/auth/logout", {
      method: "POST",
      headers: getAuthHeaders(activeToken),
    }).catch(() => undefined);
  }
}

async function loadWechatAccount() {
  if (!token.value) {
    return;
  }

  wechatLoading.value = true;
  try {
    wechatAccount.value = await apiRequest<WechatAccount | null>("/wechat/accounts/current", {
      headers: authHeaders(),
    });
  } finally {
    wechatLoading.value = false;
  }
}

function stopWechatLoginPolling() {
  if (wechatLoginTimer !== undefined) {
    window.clearInterval(wechatLoginTimer);
    wechatLoginTimer = undefined;
  }
}

async function pollWechatLoginStatus(loginId: string) {
  if (!token.value) {
    return;
  }

  try {
    const session = await apiRequest<WechatLoginSession>(`/wechat/login/${loginId}/status`, {
      headers: authHeaders(),
    });
    wechatLoginSession.value = session;

    if (["confirmed", "expired", "failed"].includes(session.status)) {
      stopWechatLoginPolling();
      if (session.status === "confirmed") {
        await loadWechatAccount();
        closeWechatLogin();
      }
    }
  } catch (error) {
    wechatLoginError.value = error instanceof Error ? error.message : "获取扫码状态失败";
    stopWechatLoginPolling();
  }
}

async function startWechatLogin() {
  if (!token.value) {
    return;
  }

  stopWechatLoginPolling();
  wechatLoginLoading.value = true;
  wechatLoginError.value = "";
  wechatLoginSession.value = null;

  try {
    const session = await apiRequest<WechatLoginSession>("/wechat/login/qrcode", {
      method: "POST",
      headers: authHeaders(),
    });
    wechatLoginSession.value = session;
    wechatLoginTimer = window.setInterval(() => {
      void pollWechatLoginStatus(session.login_id);
    }, 2500);
  } catch (error) {
    wechatLoginError.value = error instanceof Error ? error.message : "创建扫码登录失败";
  } finally {
    wechatLoginLoading.value = false;
  }
}

function closeWechatLogin() {
  stopWechatLoginPolling();
  wechatLoginSession.value = null;
  wechatLoginError.value = "";
}

function formatDateTime(value?: string | null) {
  if (!value) {
    return "暂未获取";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

async function logoutWechatAccount() {
  if (!token.value) {
    return;
  }

  await apiRequest("/wechat/accounts/logout", {
    method: "POST",
    headers: authHeaders(),
  });
  await loadWechatAccount();
}

onMounted(() => {
  document.addEventListener("click", closeUserMenu);
  void loadCurrentUser();
});

onBeforeUnmount(() => {
  document.removeEventListener("click", closeUserMenu);
  stopWechatLoginPolling();
});
</script>

<template>
  <main v-if="!isAuthenticated" class="auth-page">
    <section class="auth-card">
      <div class="auth-brand">
        <div class="brand-mark">WV</div>
        <div>
          <div class="brand-name">WeVault</div>
          <div class="brand-subtitle">公众号内容库</div>
        </div>
      </div>

      <div class="auth-heading">
        <h1>{{ authMode === "login" ? "登录" : "创建账户" }}</h1>
        <p>登录后管理公众号源、文章采集任务和导出文件。</p>
      </div>

      <div class="auth-tabs" role="tablist" aria-label="认证方式">
        <button
          type="button"
          :class="{ active: authMode === 'login' }"
          @click="switchAuthMode('login')"
        >
          登录
        </button>
        <button
          type="button"
          :class="{ active: authMode === 'register' }"
          @click="switchAuthMode('register')"
        >
          注册
        </button>
      </div>

      <form class="auth-form" @submit.prevent="submitAuth">
        <label>
          <span>邮箱</span>
          <input v-model="authForm.email" type="email" autocomplete="email" required />
        </label>
        <label v-if="authMode === 'register'">
          <span>显示名称</span>
          <input v-model="authForm.displayName" type="text" maxlength="80" autocomplete="name" />
        </label>
        <label>
          <span>密码</span>
          <input
            v-model="authForm.password"
            type="password"
            autocomplete="current-password"
            minlength="8"
            required
          />
        </label>
        <p v-if="authError" class="auth-error">{{ authError }}</p>
        <button class="primary-button auth-submit" type="submit" :disabled="authLoading">
          {{ authLoading ? "处理中..." : authMode === "login" ? "登录" : "注册并登录" }}
        </button>
      </form>
    </section>
  </main>

  <div
    v-else
    class="app-shell"
    :class="{ 'sidebar-collapsed': sidebarCollapsed, 'mobile-menu-open': mobileMenuOpen }"
  >
    <aside class="sidebar" aria-label="主导航">
      <div class="brand">
        <div class="brand-left">
          <div class="brand-mark">WV</div>
          <div class="brand-copy">
            <div class="brand-name">WeVault</div>
            <div class="brand-subtitle">公众号内容库</div>
          </div>
        </div>
        <button
          class="sidebar-toggle"
          type="button"
          :aria-label="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
          :aria-expanded="!sidebarCollapsed"
          @click="toggleSidebar"
        >
          {{ sidebarCollapsed ? "›" : "‹" }}
        </button>
        <button
          class="mobile-menu-button"
          type="button"
          :aria-label="mobileMenuOpen ? '收起菜单' : '展开菜单'"
          :aria-expanded="mobileMenuOpen"
          @click="toggleMobileMenu"
        >
          <span></span>
          <span></span>
          <span></span>
        </button>
      </div>

      <nav class="nav-list">
        <button
          v-for="view in views"
          :key="view.id"
          class="nav-item"
          :class="{ active: activeView === view.id }"
          type="button"
          @click="setView(view.id)"
        >
          <span class="nav-icon">{{ view.icon }}</span>
          <span class="nav-label">{{ view.label }}</span>
        </button>
      </nav>

      <div class="sidebar-footer">
        <button
          class="user-button"
          :class="{ active: userMenuOpen }"
          type="button"
          aria-haspopup="menu"
          :aria-expanded="userMenuOpen"
          @click="toggleUserMenu"
        >
          <span class="user-avatar">{{ currentUser?.email.slice(0, 1).toUpperCase() }}</span>
          <span class="user-copy">
            <span class="user-name">{{ currentUser?.email }}</span>
            <span class="user-role">个人空间</span>
          </span>
        </button>
        <div class="user-menu" :class="{ open: userMenuOpen }" role="menu">
          <button type="button" role="menuitem" @click.stop="logout">注销</button>
        </div>
      </div>
    </aside>

    <main class="main">
      <header class="topbar">
        <div>
          <h1>{{ currentView.title }}</h1>
          <p>{{ currentView.subtitle }}</p>
        </div>
        <div class="topbar-actions">
          <button class="ghost-button" type="button">搜索</button>
          <button class="primary-button" type="button">添加公众号源</button>
        </div>
      </header>

      <section v-if="activeView === 'dashboard'" class="view active">
        <div class="metric-grid">
          <article class="metric">
            <div class="metric-label">授权状态</div>
            <div class="metric-value" :class="wechatAccount ? 'status-good' : 'status-warning'">
              {{ wechatStatusLabel }}
            </div>
            <div class="metric-note">{{ wechatStatusNote }}</div>
            <div v-if="wechatAccount" class="wechat-account-card compact">
              <img
                v-if="wechatAccount.avatar_url"
                :src="wechatAccount.avatar_url"
                alt=""
                class="wechat-avatar"
              />
              <span v-else class="wechat-avatar fallback">微</span>
              <div>
                <strong>{{ wechatAccount.nickname }}</strong>
                <span>到期：{{ wechatExpiresLabel }}</span>
              </div>
            </div>
            <button
              v-if="!wechatAccount"
              class="small-button metric-action"
              type="button"
              :disabled="wechatLoginLoading"
              @click="startWechatLogin"
            >
              扫码授权
            </button>
          </article>
          <article class="metric">
            <div class="metric-label">公众号源</div>
            <div class="metric-value">18</div>
            <div class="metric-note">3 个开启自动抓取</div>
          </article>
          <article class="metric">
            <div class="metric-label">文章库</div>
            <div class="metric-value">1,284</div>
            <div class="metric-note">已抓正文 426 篇</div>
          </article>
          <article class="metric">
            <div class="metric-label">评论</div>
            <div class="metric-value">9,672</div>
            <div class="metric-note">今日新增 248 条</div>
          </article>
        </div>

        <div class="content-grid">
          <section class="panel wide-panel">
            <div class="panel-header">
              <div>
                <h2>最近文章</h2>
                <p>列表同步后，用户可以选择需要抓正文和评论的文章。</p>
              </div>
              <button class="small-button" type="button">批量抓取</button>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>标题</th>
                    <th>公众号</th>
                    <th>发布时间</th>
                    <th>正文</th>
                    <th>评论</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="article in recentArticles" :key="article.title">
                    <td>{{ article.title }}</td>
                    <td>{{ article.source }}</td>
                    <td>{{ article.publishedAt }}</td>
                    <td><span class="tag" :class="article.contentTag">{{ article.contentStatus }}</span></td>
                    <td><span class="tag" :class="article.commentTag">{{ article.commentStatus }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section class="panel">
            <div class="panel-header">
              <div>
                <h2>任务队列</h2>
                <p>采集和导出都作为后台任务执行。</p>
              </div>
            </div>
            <ol class="activity-list">
              <li>
                <span class="activity-dot running"></span>
                <div>
                  <strong>抓取正文</strong>
                  <span>技术观察站 · 12/40</span>
                </div>
              </li>
              <li>
                <span class="activity-dot done"></span>
                <div>
                  <strong>同步文章列表</strong>
                  <span>产品笔记 · 完成</span>
                </div>
              </li>
              <li>
                <span class="activity-dot pending"></span>
                <div>
                  <strong>导出 Markdown</strong>
                  <span>已排队</span>
                </div>
              </li>
            </ol>
          </section>
        </div>
      </section>

      <section v-else-if="activeView === 'auth'" class="view active">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>微信公众号授权</h2>
              <p>第一版每个用户只能启用一个公众号登录态，数据库保留多授权扩展能力。</p>
            </div>
            <button class="primary-button" type="button" :disabled="wechatLoginLoading" @click="startWechatLogin">
              {{ wechatAccount ? "重新授权" : "扫码授权" }}
            </button>
          </div>
          <div v-if="wechatLoading" class="auth-box">
            <div class="auth-state">
              <span class="activity-dot pending"></span>
              <div>
                <strong>正在读取授权状态</strong>
                <span>请稍候</span>
              </div>
            </div>
          </div>
          <div v-else-if="wechatAccount" class="auth-box">
            <div class="auth-state">
              <img
                v-if="wechatAccount.avatar_url"
                :src="wechatAccount.avatar_url"
                alt=""
                class="wechat-avatar"
              />
              <span v-else class="wechat-avatar fallback">微</span>
              <div>
                <strong>已连接：{{ wechatAccount.nickname }}</strong>
                <span>
                  Token {{ wechatAccount.token_status }} · 到期：{{ wechatExpiresLabel }}
                </span>
                <span>最近验证：{{ formatDateTime(wechatAccount.last_verified_at) }}</span>
              </div>
            </div>
            <button class="ghost-button" type="button" @click="logoutWechatAccount">退出授权</button>
          </div>
          <div v-else class="auth-box">
            <div class="auth-state">
              <span class="activity-dot pending"></span>
              <div>
                <strong>未连接微信公众号</strong>
                <span>扫码授权后才能搜索公众号源和采集文章列表。</span>
              </div>
            </div>
            <button class="ghost-button" type="button" @click="startWechatLogin">扫码授权</button>
          </div>
        </section>
      </section>

      <section v-else-if="activeView === 'sources'" class="view active">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>公众号源</h2>
              <p>通过名称搜索或文章链接添加，添加后先同步文章列表。</p>
            </div>
            <div class="inline-actions">
              <button class="ghost-button" type="button">粘贴文章链接</button>
              <button class="primary-button" type="button">搜索公众号</button>
            </div>
          </div>
          <div class="source-list">
            <article v-for="source in sources" :key="source.name" class="source-row">
              <div>
                <strong>{{ source.name }}</strong>
                <span>{{ source.note }}</span>
              </div>
              <button class="small-button" type="button">同步列表</button>
            </article>
          </div>
        </section>
      </section>

      <section v-else-if="activeView === 'articles'" class="view active">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>文章库</h2>
              <p>文章列表与正文抓取分离，方便用户控制采集范围。</p>
            </div>
            <div class="inline-actions">
              <button class="ghost-button" type="button">抓取评论</button>
              <button class="primary-button" type="button">抓取正文</button>
            </div>
          </div>
          <div class="filter-bar">
            <input type="search" placeholder="搜索标题、公众号、作者" />
            <select>
              <option>全部公众号</option>
              <option>产品笔记</option>
              <option>技术观察站</option>
            </select>
            <select>
              <option>全部状态</option>
              <option>正文待抓取</option>
              <option>评论待抓取</option>
            </select>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th><input type="checkbox" aria-label="全选文章" /></th>
                  <th>标题</th>
                  <th>公众号</th>
                  <th>发布时间</th>
                  <th>正文</th>
                  <th>评论</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="article in recentArticles" :key="article.title">
                  <td><input type="checkbox" /></td>
                  <td>{{ article.title }}</td>
                  <td>{{ article.source }}</td>
                  <td>{{ article.publishedAt }}</td>
                  <td><span class="tag" :class="article.contentTag">{{ article.contentStatus }}</span></td>
                  <td><span class="tag" :class="article.commentTag">{{ article.commentStatus }}</span></td>
                  <td><button class="link-button" type="button">{{ article.action }}</button></td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </section>

      <section v-else-if="activeView === 'tasks'" class="view active">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>采集任务</h2>
              <p>用于观察列表同步、正文抓取、评论抓取和导出进度。</p>
            </div>
          </div>
          <div class="task-list">
            <article v-for="task in tasks" :key="task.type" class="task-row">
              <div>
                <strong>{{ task.type }}</strong>
                <span>{{ task.note }}</span>
              </div>
              <progress :value="task.progress" max="100"></progress>
            </article>
          </div>
        </section>
      </section>

      <section v-else-if="activeView === 'exports'" class="view active">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>导出中心</h2>
              <p>PDF、DOCX、Markdown 都基于已保存的 clean HTML 和 Markdown 生成。</p>
            </div>
            <button class="primary-button" type="button">新建导出</button>
          </div>
          <div class="export-grid">
            <article v-for="item in exports" :key="item.name" class="export-item">
              <strong>{{ item.name }}</strong>
              <span>{{ item.note }}</span>
              <button class="small-button" type="button">下载</button>
            </article>
          </div>
        </section>
      </section>

      <section v-else class="view active">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>设置</h2>
              <p>控制默认采集策略、导出格式和保存位置。</p>
            </div>
          </div>
          <div class="settings-list">
            <label>
              <span>添加公众号源后自动抓取正文</span>
              <input type="checkbox" />
            </label>
            <label>
              <span>正文抓取完成后自动抓取评论</span>
              <input type="checkbox" />
            </label>
            <label>
              <span>每次同步最多抓取文章数</span>
              <input type="number" min="1" value="50" />
            </label>
          </div>
        </section>
      </section>
    </main>

    <div v-if="showWechatLoginLoading" class="loading-backdrop" aria-live="polite">
      <div class="loading-card">
        <div class="loading-gif" aria-hidden="true"></div>
        <span>正在生成扫码二维码</span>
      </div>
    </div>

    <div v-if="showWechatLoginModal" class="modal-backdrop">
      <section
        class="modal-dialog wechat-login-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="wechat-login-title"
      >
        <button class="modal-close" type="button" aria-label="关闭扫码授权" @click="closeWechatLogin">
          ×
        </button>
        <div class="modal-header">
          <div>
            <h2 id="wechat-login-title">扫码授权</h2>
            <p>二维码有效期 5 分钟，扫码成功后授权状态会自动更新。</p>
          </div>
        </div>
        <div v-if="wechatLoginError" class="auth-error">{{ wechatLoginError }}</div>
        <div v-else-if="wechatLoginSession" class="wechat-login-box">
          <div class="qr-box">
            <img v-if="wechatLoginSession.qr_url" :src="wechatLoginSession.qr_url" alt="微信扫码登录二维码" />
            <span v-else>QR</span>
          </div>
          <div>
            <strong>状态：{{ wechatLoginSession.status }}</strong>
            <span>{{ wechatLoginSession.message || "等待微信扫码确认" }}</span>
            <span>过期时间：{{ wechatLoginSession.expires_at }}</span>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
