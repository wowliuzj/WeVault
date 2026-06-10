<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { apiRequest, getAuthHeaders, type TokenResponse, type User } from "./api";

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

const currentView = computed(() => views.find((view) => view.id === activeView.value) ?? views[0]);
const isAuthenticated = computed(() => Boolean(token.value && currentUser.value));

function setSession(response: TokenResponse) {
  token.value = response.access_token;
  currentUser.value = response.user;
  localStorage.setItem("wevault_token", response.access_token);
}

async function loadCurrentUser() {
  if (!token.value) {
    return;
  }

  try {
    currentUser.value = await apiRequest<User>("/auth/me", {
      headers: getAuthHeaders(token.value),
    });
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
  userMenuOpen.value = false;
  localStorage.removeItem("wevault_token");

  if (activeToken) {
    await apiRequest("/auth/logout", {
      method: "POST",
      headers: getAuthHeaders(activeToken),
    }).catch(() => undefined);
  }
}

onMounted(() => {
  document.addEventListener("click", closeUserMenu);
  void loadCurrentUser();
});

onBeforeUnmount(() => {
  document.removeEventListener("click", closeUserMenu);
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
            <div class="metric-value status-good">有效</div>
            <div class="metric-note">最近验证：12 分钟前</div>
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
            <button class="primary-button" type="button">扫码授权</button>
          </div>
          <div class="auth-box">
            <div class="auth-state">
              <span class="status-dot"></span>
              <div>
                <strong>已连接：VaultTech 内容助手</strong>
                <span>Token 有效，Cookie 最近验证于 2026-06-10 14:48</span>
              </div>
            </div>
            <button class="ghost-button" type="button">重新验证</button>
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
  </div>
</template>
