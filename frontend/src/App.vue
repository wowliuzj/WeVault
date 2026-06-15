<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import {
  apiRequest,
  getArticleCoverUrl,
  getApiUrl,
  getAuthHeaders,
  getSourceAvatarUrl,
  type Article,
  type ArticleDetail,
  type ArticleListResponse,
  type ArticleSummaryResponse,
  type CollectionTask,
  type ExportJob,
  type SourceSearchItem,
  type SourceSearchResponse,
  type TokenResponse,
  type User,
  type WechatAccount,
  type WechatLoginSession,
  type WechatSource,
} from "./api";

type ViewId = "dashboard" | "auth" | "sources" | "articles" | "tasks" | "exports" | "account";
type AuthMode = "login" | "register";
type ToastKind = "success" | "error";
type SourceViewMode = "list" | "grid";
type SourceModalMode = "search" | "url" | "task" | null;
type ArticleLibraryMode = "active" | "trash";

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
    subtitle: "添加公众号后先同步文章列表，再按策略抓正文。",
  },
  {
    id: "articles",
    label: "文章库",
    icon: "≡",
    title: "文章库",
    subtitle: "统一管理文章列表、正文状态和导出操作。",
  },
  {
    id: "tasks",
    label: "采集任务",
    icon: "↻",
    title: "采集任务",
    subtitle: "跟踪列表同步、正文抓取和导出任务。",
  },
  {
    id: "exports",
    label: "导出中心",
    icon: "⇩",
    title: "导出中心",
    subtitle: "生成保留文本的 PDF、DOCX 和 Markdown 文件。",
  },
  {
    id: "account",
    label: "个人账户",
    icon: "◐",
    title: "个人账户",
    subtitle: "管理当前平台账户的名称和密码。",
  },
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
  inviteCode: "",
});
const accountSaving = ref(false);
const accountError = ref("");
const accountForm = ref({
  displayName: "",
  newPassword: "",
  confirmPassword: "",
});
const wechatAccount = ref<WechatAccount | null>(null);
const wechatLoading = ref(false);
const wechatLoginLoading = ref(false);
const wechatRefreshLoading = ref(false);
const wechatLoginError = ref("");
const wechatRefreshError = ref("");
const wechatLoginSession = ref<WechatLoginSession | null>(null);
const toast = ref<{ kind: ToastKind; message: string } | null>(null);
const sourceViewMode = ref<SourceViewMode>("list");
const sourceModalMode = ref<SourceModalMode>(null);
const sourceSearchKeyword = ref("");
const sourceArticleUrl = ref("");
const sourceSearchLoading = ref(false);
const sourceUrlLoading = ref(false);
const sourceAddLoading = ref(false);
const sourceLoading = ref(false);
const sourceError = ref("");
const sources = ref<WechatSource[]>([]);
const sourceSearchResults = ref<SourceSearchItem[]>([]);
const sourceSearchSubmitted = ref(false);
const sourceUrlSubmitted = ref(false);
const sourcePage = ref(1);
const sourcePageSize = ref(10);
const sourceOperatingId = ref("");
const brokenSourceAvatars = ref<Set<string>>(new Set());
const selectedTaskSource = ref<WechatSource | null>(null);
const taskLoading = ref(false);
const taskSubmitting = ref(false);
const tasks = ref<CollectionTask[]>([]);
const taskPage = ref(1);
const taskPageSize = ref(10);
const exportJobs = ref<ExportJob[]>([]);
const exportLoading = ref(false);
const exportSubmitting = ref(false);
const exportPage = ref(1);
const exportPageSize = ref(10);
const articleExportMenuId = ref("");
const pendingDownloadExportIds = ref<Set<string>>(new Set());
const exportForm = ref({
  name: "",
  formats: ["pdf"] as Array<"pdf" | "docx" | "markdown">,
});
const dashboardArticleLoading = ref(false);
const dashboardArticleTotal = ref(0);
const dashboardContentFetched = ref(0);
const dashboardRecentArticles = ref<Article[]>([]);
const articleLoading = ref(false);
const articleOperatingId = ref("");
const articles = ref<Article[]>([]);
const articleTotal = ref(0);
const articlePage = ref(1);
const articlePageSize = ref(20);
const articleKeyword = ref("");
const articleSourceId = ref("");
const selectedArticleIds = ref<Set<string>>(new Set());
const articleMode = ref<ArticleLibraryMode>("active");
const articleBatchDeleting = ref(false);
const articleBatchRestoring = ref(false);
const articleDetail = ref<ArticleDetail | null>(null);
const articleViewLoadingId = ref("");
const instantArticleTask = ref<{
  taskId: string;
  articleTitle: string;
} | null>(null);
const taskForm = ref({
  range: "7d",
  startDate: "",
  endDate: "",
  limit: 50,
  fetchContent: false,
  skipExisting: true,
});
let wechatLoginTimer: number | undefined;
let toastTimer: number | undefined;
let instantArticleTaskTimer: number | undefined;
let instantArticleTaskTimeout: number | undefined;
let exportPollTimer: number | undefined;
let exportPollInFlight = false;
const exportDownloadInFlightIds = new Set<string>();

const currentView = computed(() => views.find((view) => view.id === activeView.value) ?? views[0]);
const isAuthenticated = computed(() => Boolean(token.value && currentUser.value));
const showWechatLoginModal = computed(() => Boolean(wechatLoginSession.value || wechatLoginError.value));
const showWechatLoginLoading = computed(
  () => wechatLoginLoading.value && !showWechatLoginModal.value,
);
const instantArticleTaskLabel = computed(() => {
  if (!instantArticleTask.value) {
    return "";
  }
  return "正在抓取正文";
});
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
const sourceModalVisible = computed(() => sourceModalMode.value !== null);
const articleDetailHtml = computed(() => {
  const html = articleDetail.value?.content_clean_html || "";
  return html.replace(/(["'])\/api\/v1\//g, `$1${getApiUrl("/api/v1/")}`);
});
const hasValidWechatAuthorization = computed(
  () => Boolean(wechatAccount.value) && wechatAccount.value?.token_status === "valid",
);
const sourceTotalArticles = computed(() =>
  sources.value.reduce((total, source) => total + source.article_count, 0),
);
const activeSourceCount = computed(
  () => sources.value.filter((source) => source.status === "active").length,
);
const sourcePageCount = computed(() =>
  Math.max(1, Math.ceil(sources.value.length / sourcePageSize.value)),
);
const paginatedSources = computed(() => {
  const page = Math.min(sourcePage.value, sourcePageCount.value);
  const start = (page - 1) * sourcePageSize.value;
  return sources.value.slice(start, start + sourcePageSize.value);
});
const taskPageCount = computed(() =>
  Math.max(1, Math.ceil(tasks.value.length / taskPageSize.value)),
);
const paginatedTasks = computed(() => {
  const page = Math.min(taskPage.value, taskPageCount.value);
  const start = (page - 1) * taskPageSize.value;
  return tasks.value.slice(start, start + taskPageSize.value);
});
const exportPageCount = computed(() =>
  Math.max(1, Math.ceil(exportJobs.value.length / exportPageSize.value)),
);
const paginatedExports = computed(() => {
  const page = Math.min(exportPage.value, exportPageCount.value);
  const start = (page - 1) * exportPageSize.value;
  return exportJobs.value.slice(start, start + exportPageSize.value);
});
const articlePageCount = computed(() =>
  Math.max(1, Math.ceil(articleTotal.value / articlePageSize.value)),
);
const selectedArticles = computed(() =>
  articles.value.filter((article) => selectedArticleIds.value.has(article.id)),
);
const hasSelectedArticles = computed(() => selectedArticleIds.value.size > 0);
const isArticleTrashMode = computed(() => articleMode.value === "trash");
const canBatchFetchContent = computed(() =>
  !isArticleTrashMode.value &&
  selectedArticles.value.some((article) =>
    ["pending", "failed"].includes(article.content_status),
  ),
);
const canExportSelectedArticles = computed(
  () => !isArticleTrashMode.value && selectedArticles.value.length > 0,
);
const allVisibleArticlesSelected = computed(
  () =>
    articles.value.length > 0 &&
    articles.value.every((article) => selectedArticleIds.value.has(article.id)),
);
const articleEmptyLabel = computed(() =>
  isArticleTrashMode.value ? "回收箱里还没有文章" : "还没有文章",
);
const articleLoadingLabel = computed(() =>
  isArticleTrashMode.value ? "正在读取回收箱" : "正在读取文章库",
);

function setSession(response: TokenResponse) {
  token.value = response.access_token;
  currentUser.value = response.user;
  resetAccountForm(response.user);
  localStorage.setItem("wevault_token", response.access_token);
}

function resetAccountForm(user = currentUser.value) {
  accountForm.value = {
    displayName: user?.display_name || "",
    newPassword: "",
    confirmPassword: "",
  };
  accountError.value = "";
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
    resetAccountForm(currentUser.value);
    await loadWechatAccount();
    await loadSources();
    await loadDashboardArticles();
    await loadArticles();
    await loadTasks();
    await loadExports();
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
            invite_code: authForm.value.inviteCode,
          };

    const response = await apiRequest<TokenResponse>(path, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setSession(response);
    await loadWechatAccount();
    await loadSources();
    await loadDashboardArticles();
    await loadTasks();
    await loadExports();
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
  if (viewId === "sources") {
    void loadSources();
  }
  if (viewId === "articles") {
    void loadSources();
    void loadArticles();
  }
  if (viewId === "tasks") {
    void loadTasks();
  }
  if (viewId === "exports") {
    void loadExports();
  }
  if (viewId === "account") {
    resetAccountForm();
  }
  if (viewId === "dashboard") {
    void loadDashboardArticles();
    void loadSources();
    void loadTasks();
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

async function submitAccount() {
  accountError.value = "";
  if (accountForm.value.newPassword || accountForm.value.confirmPassword) {
    if (accountForm.value.newPassword !== accountForm.value.confirmPassword) {
      accountError.value = "两次输入的新密码不一致";
      return;
    }
  }

  accountSaving.value = true;
  try {
    const updatedUser = await apiRequest<User>("/auth/me", {
      method: "PATCH",
      headers: authHeaders(),
      body: JSON.stringify({
        display_name: accountForm.value.displayName,
        new_password: accountForm.value.newPassword || null,
      }),
    });
    currentUser.value = updatedUser;
    resetAccountForm(updatedUser);
    showToast("success", "个人账户已更新");
  } catch (error) {
    accountError.value = error instanceof Error ? error.message : "保存个人账户失败";
  } finally {
    accountSaving.value = false;
  }
}

function showToast(kind: ToastKind, message: string) {
  toast.value = { kind, message };
  if (toastTimer !== undefined) {
    window.clearTimeout(toastTimer);
  }
  toastTimer = window.setTimeout(() => {
    toast.value = null;
    toastTimer = undefined;
  }, 2800);
}

function openSourceModal(mode: Exclude<SourceModalMode, null>) {
  if (!hasValidWechatAuthorization.value) {
    showToast("error", "请先完成有效的微信公众号扫码授权");
    return;
  }
  sourceModalMode.value = mode;
  sourceSearchSubmitted.value = false;
  sourceUrlSubmitted.value = false;
  sourceSearchResults.value = [];
}

function closeSourceModal() {
  sourceModalMode.value = null;
  selectedTaskSource.value = null;
}

async function submitSourceSearch() {
  if (!sourceSearchKeyword.value.trim()) {
    return;
  }
  sourceSearchLoading.value = true;
  sourceSearchSubmitted.value = false;
  sourceSearchResults.value = [];
  try {
    const response = await apiRequest<SourceSearchResponse>("/sources/search", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ keyword: sourceSearchKeyword.value.trim(), count: 10 }),
    });
    sourceSearchResults.value = response.items;
    sourceSearchSubmitted.value = true;
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "搜索公众号失败");
  } finally {
    sourceSearchLoading.value = false;
  }
}

async function submitSourceUrl() {
  if (!sourceArticleUrl.value.trim()) {
    return;
  }
  sourceUrlLoading.value = true;
  sourceUrlSubmitted.value = false;
  try {
    await apiRequest<WechatSource>("/sources/from-article-url", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ article_url: sourceArticleUrl.value.trim() }),
    });
    sourceUrlSubmitted.value = true;
    showToast("success", "已添加公众号源");
    closeSourceModal();
    await loadSources();
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "解析文章链接失败");
  } finally {
    sourceUrlLoading.value = false;
  }
}

async function addSourceFromModal(source: SourceSearchItem) {
  if (!source.fakeid || source.already_added) {
    return;
  }
  sourceAddLoading.value = true;
  try {
    await apiRequest<WechatSource>("/sources", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(source),
    });
    showToast("success", `已添加 ${source.name}`);
    closeSourceModal();
    await loadSources();
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "添加公众号源失败");
  } finally {
    sourceAddLoading.value = false;
  }
}

function sourceInitial(name: string) {
  return name.slice(0, 1);
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatFileSize(value?: number | null) {
  if (!value) {
    return "-";
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function sourceStatusLabel(status: WechatSource["status"]) {
  if (status === "active") {
    return "正常";
  }
  return "暂停";
}

function sourceStatusTag(status: WechatSource["status"]) {
  if (status === "active") {
    return "success";
  }
  return "muted";
}

function sourceDescription(source: WechatSource | SourceSearchItem) {
  return source.description || source.alias || "暂无描述";
}

function sourceAvatarSrc(source: WechatSource | SourceSearchItem) {
  return getSourceAvatarUrl(source);
}

function articleCoverSrc(article: Article) {
  return getArticleCoverUrl(article);
}

function articleSourceAvatarSrc(article: Article) {
  return getSourceAvatarUrl(article.source);
}

function isSourceAvatarBroken(source: WechatSource | SourceSearchItem) {
  return Boolean(source.avatar_url && brokenSourceAvatars.value.has(source.avatar_url));
}

function markBrokenSourceAvatar(source: WechatSource | SourceSearchItem) {
  if (source.avatar_url) {
    brokenSourceAvatars.value = new Set([...brokenSourceAvatars.value, source.avatar_url]);
  }
}

function setSourcePage(page: number) {
  sourcePage.value = Math.min(Math.max(page, 1), sourcePageCount.value);
}

function setSourcePageSize(event: Event) {
  const target = event.target as HTMLSelectElement;
  sourcePageSize.value = Number(target.value);
  sourcePage.value = 1;
}

function setTaskPage(page: number) {
  taskPage.value = Math.min(Math.max(page, 1), taskPageCount.value);
}

function setTaskPageSize(event: Event) {
  const target = event.target as HTMLSelectElement;
  taskPageSize.value = Number(target.value);
  taskPage.value = 1;
}

function setExportPage(page: number) {
  exportPage.value = Math.min(Math.max(page, 1), exportPageCount.value);
}

function setExportPageSize(event: Event) {
  const target = event.target as HTMLSelectElement;
  exportPageSize.value = Number(target.value);
  exportPage.value = 1;
}

function setArticlePage(page: number) {
  articlePage.value = Math.min(Math.max(page, 1), articlePageCount.value);
  void loadArticles();
}

function setArticlePageSize(event: Event) {
  const target = event.target as HTMLSelectElement;
  articlePageSize.value = Number(target.value);
  articlePage.value = 1;
  void loadArticles();
}

function searchArticles() {
  articlePage.value = 1;
  void loadArticles();
}

function resetArticleFilters() {
  articleKeyword.value = "";
  articleSourceId.value = "";
  articlePage.value = 1;
  clearArticleSelection();
  void loadArticles();
}

function setArticleMode(mode: ArticleLibraryMode) {
  if (articleMode.value === mode) {
    return;
  }
  articleMode.value = mode;
  articlePage.value = 1;
  clearArticleSelection();
  void loadArticles();
}

function articleStatusLabel(status: Article["content_status"]) {
  const labels: Record<Article["content_status"], string> = {
    pending: "未抓取",
    running: "抓取中",
    fetched: "已抓取",
    failed: "失败",
  };
  return labels[status];
}

function articleStatusTag(status: Article["content_status"]) {
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

function toggleArticleSelection(article: Article) {
  const next = new Set(selectedArticleIds.value);
  if (next.has(article.id)) {
    next.delete(article.id);
  } else {
    next.add(article.id);
  }
  selectedArticleIds.value = next;
}

function toggleVisibleArticleSelection() {
  if (allVisibleArticlesSelected.value) {
    const next = new Set(selectedArticleIds.value);
    articles.value.forEach((article) => next.delete(article.id));
    selectedArticleIds.value = next;
    return;
  }

  selectedArticleIds.value = new Set([
    ...selectedArticleIds.value,
    ...articles.value.map((article) => article.id),
  ]);
}

function clearArticleSelection() {
  selectedArticleIds.value = new Set();
}

function defaultExportName() {
  const now = new Date();
  const stamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(
    now.getDate(),
  ).padStart(2, "0")}`;
  return `WeVault 导出 ${stamp}`;
}

function toggleExportFormat(format: "pdf" | "docx" | "markdown", checked: boolean) {
  const formats = new Set(exportForm.value.formats);
  if (checked) {
    formats.add(format);
  } else {
    formats.delete(format);
  }
  exportForm.value.formats = [...formats];
}

function toggleArticleExportMenu(article: Article) {
  articleExportMenuId.value = articleExportMenuId.value === article.id ? "" : article.id;
}

function closeArticleExportMenu() {
  articleExportMenuId.value = "";
}

function openArticleFromList(article: Article) {
  if (isArticleTrashMode.value) {
    viewOriginalArticle(article);
    return;
  }
  void viewArticle(article);
}

function selectedFetchableArticleIds() {
  return selectedArticles.value
    .filter((article) => ["pending", "failed"].includes(article.content_status))
    .map((article) => article.id);
}

function openTaskModal(source: WechatSource) {
  selectedTaskSource.value = source;
  taskForm.value = {
    range: "7d",
    startDate: "",
    endDate: "",
    limit: 50,
    fetchContent: false,
    skipExisting: true,
  };
  sourceModalMode.value = "task";
}

function toggleTaskFetchContent(value: boolean) {
  taskForm.value.fetchContent = value;
}

async function createSourceArticleTask() {
  if (!selectedTaskSource.value) {
    return;
  }
  if (taskForm.value.range === "custom") {
    if (!taskForm.value.startDate || !taskForm.value.endDate) {
      showToast("error", "请选择自定义开始日期和结束日期");
      return;
    }
    if (taskForm.value.startDate > taskForm.value.endDate) {
      showToast("error", "开始日期不能晚于结束日期");
      return;
    }
  }

  taskSubmitting.value = true;
  try {
    const customRange =
      taskForm.value.range === "custom"
        ? {
            start_date: taskForm.value.startDate,
            end_date: taskForm.value.endDate,
          }
        : {};
    await apiRequest<CollectionTask>("/tasks/source-articles", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({
        source_id: selectedTaskSource.value.id,
        range: taskForm.value.range,
        ...customRange,
        limit: taskForm.value.limit,
        fetch_content: taskForm.value.fetchContent,
        skip_existing: taskForm.value.skipExisting,
      }),
    });
    showToast("success", "采集任务已创建");
    closeSourceModal();
    activeView.value = "tasks";
    await loadTasks();
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "创建采集任务失败");
  } finally {
    taskSubmitting.value = false;
  }
}

async function refreshSource(source: WechatSource) {
  sourceOperatingId.value = source.id;
  try {
    await apiRequest<WechatSource>(`/sources/${source.id}/refresh`, {
      method: "POST",
      headers: authHeaders(),
    });
    showToast("success", `已刷新 ${source.name}`);
    await loadSources();
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "刷新公众号信息失败");
  } finally {
    sourceOperatingId.value = "";
  }
}

async function toggleSourceStatus(source: WechatSource) {
  sourceOperatingId.value = source.id;
  const nextStatus = source.status === "active" ? "paused" : "active";
  try {
    const updatedSource = await apiRequest<WechatSource>(
      `/sources/${source.id}/${nextStatus === "active" ? "resume" : "pause"}`,
      {
        method: "POST",
        headers: authHeaders(),
      },
    );
    sources.value = sources.value.map((item) =>
      item.id === updatedSource.id ? updatedSource : item,
    );
    showToast("success", nextStatus === "active" ? "已启用自动抓取" : "已停用自动抓取");
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "更新公众号源状态失败");
  } finally {
    sourceOperatingId.value = "";
  }
}

async function deleteSource(source: WechatSource) {
  const confirmed = window.confirm(`删除「${source.name}」及所有在库文章？`);
  if (!confirmed) {
    return;
  }

  sourceOperatingId.value = source.id;
  try {
    await apiRequest(`/sources/${source.id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    showToast("success", `已删除 ${source.name}`);
    await loadSources();
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "删除公众号源失败");
  } finally {
    sourceOperatingId.value = "";
  }
}

async function refreshArticle(article: Article) {
  articleOperatingId.value = article.id;
  try {
    const updatedArticle = await apiRequest<Article>(`/articles/${article.id}/refresh`, {
      method: "POST",
      headers: authHeaders(),
    });
    articles.value = articles.value.map((item) =>
      item.id === updatedArticle.id ? updatedArticle : item,
    );
    showToast("success", "文章信息已刷新");
    await loadDashboardArticles();
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "刷新文章失败");
  } finally {
    articleOperatingId.value = "";
  }
}

async function viewArticle(article: Article) {
  if (article.content_status !== "fetched") {
    window.open(article.original_url, "_blank", "noopener,noreferrer");
    return;
  }

  articleViewLoadingId.value = article.id;
  try {
    const detail = await apiRequest<ArticleDetail>(`/articles/${article.id}`, {
      headers: authHeaders(),
    });
    if (!detail.content_clean_html && !detail.content_plain_text) {
      showToast("error", "本地正文为空，已打开原文");
      window.open(article.original_url, "_blank", "noopener,noreferrer");
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

function viewOriginalArticle(article: Article) {
  window.open(article.original_url, "_blank", "noopener,noreferrer");
}

async function deleteArticle(article: Article) {
  const confirmed = window.confirm(`删除文章「${article.title}」？`);
  if (!confirmed) {
    return;
  }

  articleOperatingId.value = article.id;
  try {
    await apiRequest(`/articles/${article.id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    selectedArticleIds.value = new Set(
      [...selectedArticleIds.value].filter((articleId) => articleId !== article.id),
    );
    showToast("success", "文章已删除");
    await loadArticles();
    await loadDashboardArticles();
    await loadSources();
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "删除文章失败");
  } finally {
    articleOperatingId.value = "";
  }
}

async function deleteSelectedArticles() {
  const articleIds = [...selectedArticleIds.value];
  if (articleIds.length === 0) {
    return;
  }

  const confirmed = window.confirm(`删除选中的 ${articleIds.length} 篇文章？`);
  if (!confirmed) {
    return;
  }

  articleBatchDeleting.value = true;
  try {
    const response = await apiRequest<{ deleted: number }>("/articles/batch-delete", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ article_ids: articleIds }),
    });
    selectedArticleIds.value = new Set();
    showToast("success", `已删除 ${response.deleted} 篇文章`);
    await loadArticles();
    await loadDashboardArticles();
    await loadSources();
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "批量删除文章失败");
  } finally {
    articleBatchDeleting.value = false;
  }
}

async function restoreArticle(article: Article) {
  articleOperatingId.value = article.id;
  try {
    await apiRequest<Article>(`/articles/${article.id}/restore`, {
      method: "POST",
      headers: authHeaders(),
    });
    selectedArticleIds.value = new Set(
      [...selectedArticleIds.value].filter((articleId) => articleId !== article.id),
    );
    showToast("success", "文章已恢复");
    await loadArticles();
    await loadDashboardArticles();
    await loadSources();
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "恢复文章失败");
  } finally {
    articleOperatingId.value = "";
  }
}

async function restoreSelectedArticles() {
  const articleIds = [...selectedArticleIds.value];
  if (articleIds.length === 0) {
    return;
  }

  articleBatchRestoring.value = true;
  try {
    const response = await apiRequest<{ restored: number }>("/articles/batch-restore", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ article_ids: articleIds }),
    });
    selectedArticleIds.value = new Set();
    showToast("success", `已恢复 ${response.restored} 篇文章`);
    await loadArticles();
    await loadDashboardArticles();
    await loadSources();
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "批量恢复文章失败");
  } finally {
    articleBatchRestoring.value = false;
  }
}

async function createArticleFetchTask(
  articleIds: string[],
  options: { silent?: boolean } = {},
) {
  if (articleIds.length === 0) {
    return undefined;
  }

  try {
    const response = await apiRequest<{ status: string; task_id: string }>(
      "/articles/fetch-content",
      {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ article_ids: articleIds }),
      },
    );
    if (!options.silent) {
      showToast("success", "正文抓取任务已创建");
    }
    await loadTasks();
    return response.task_id;
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "创建抓取任务失败");
    return undefined;
  }
}

async function fetchArticle(article: Article) {
  const taskId = await createArticleFetchTask([article.id], { silent: true });
  if (!taskId) {
    return;
  }
  startInstantArticleTaskPolling(taskId, article);
}

async function fetchSelectedArticles() {
  await createArticleFetchTask(selectedFetchableArticleIds());
  clearArticleSelection();
}

function stopInstantArticleTaskPolling() {
  if (instantArticleTaskTimer !== undefined) {
    window.clearInterval(instantArticleTaskTimer);
    instantArticleTaskTimer = undefined;
  }
  if (instantArticleTaskTimeout !== undefined) {
    window.clearTimeout(instantArticleTaskTimeout);
    instantArticleTaskTimeout = undefined;
  }
}

function startInstantArticleTaskPolling(
  taskId: string,
  article: Article,
) {
  stopInstantArticleTaskPolling();
  instantArticleTask.value = {
    taskId,
    articleTitle: article.title,
  };

  instantArticleTaskTimer = window.setInterval(() => {
    void pollInstantArticleTask(taskId);
  }, 1500);
  instantArticleTaskTimeout = window.setTimeout(() => {
    stopInstantArticleTaskPolling();
    instantArticleTask.value = null;
    showToast("success", "抓取时间较长，已转入后台任务");
    void loadTasks();
  }, 15000);
  void pollInstantArticleTask(taskId);
}

async function pollInstantArticleTask(taskId: string) {
  if (!instantArticleTask.value || instantArticleTask.value.taskId !== taskId) {
    return;
  }

  try {
    const task = await apiRequest<CollectionTask>(`/tasks/${taskId}`, {
      headers: authHeaders(),
    });
    if (task.status === "succeeded") {
      stopInstantArticleTaskPolling();
      instantArticleTask.value = null;
      showToast("success", "抓取完成");
      await loadArticles();
      await loadDashboardArticles();
      await loadTasks();
    } else if (["failed", "cancelled"].includes(task.status)) {
      stopInstantArticleTaskPolling();
      instantArticleTask.value = null;
      showToast("error", task.error_message || "抓取失败");
      await loadArticles();
      await loadDashboardArticles();
      await loadTasks();
    }
  } catch (error) {
    stopInstantArticleTaskPolling();
    instantArticleTask.value = null;
    showToast("error", error instanceof Error ? error.message : "读取抓取任务失败");
  }
}

function taskStatusLabel(status: CollectionTask["status"]) {
  const labels: Record<CollectionTask["status"], string> = {
    pending: "待执行",
    running: "执行中",
    succeeded: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };
  return labels[status];
}

function taskStatusTag(status: CollectionTask["status"]) {
  if (status === "succeeded") {
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

function exportFormatLabel(job: ExportJob) {
  if (job.format === "pdf") {
    return "PDF";
  }
  if (job.format === "docx") {
    return "DOCX";
  }
  if (job.format === "markdown") {
    return "Markdown";
  }
  return "ZIP";
}

function exportStatusLabel(status: ExportJob["status"]) {
  const labels: Record<ExportJob["status"], string> = {
    pending: "待执行",
    running: "导出中",
    succeeded: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };
  return labels[status];
}

function exportStatusTag(status: ExportJob["status"]) {
  return taskStatusTag(status);
}

function exportArticleCount(job: ExportJob) {
  const match = job.note.match(/(\d+)\s*篇文章/);
  return match ? `${formatNumber(Number(match[1]))} 篇` : "-";
}

function exportFileSize(job: ExportJob) {
  return formatFileSize(job.files[0]?.size_bytes);
}

function taskRunMode(task: CollectionTask) {
  const runMode = task.payload?.run_mode;
  return typeof runMode === "string" ? runMode : "immediate";
}

function canStartTask(task: CollectionTask) {
  const runMode = taskRunMode(task);
  if (task.status === "running" || task.status === "succeeded") {
    return false;
  }
  if (runMode === "recurring") {
    return ["pending", "failed", "cancelled"].includes(task.status);
  }
  if (runMode === "scheduled") {
    return ["pending", "failed"].includes(task.status);
  }
  return false;
}

function canStopTask(task: CollectionTask) {
  return task.status === "running";
}

function canDeleteTask(task: CollectionTask) {
  return ["pending", "failed", "cancelled", "succeeded"].includes(task.status);
}

function taskActionNote(task: CollectionTask) {
  if (task.status === "pending" && taskRunMode(task) === "immediate") {
    return "等待执行";
  }
  return "无操作";
}

async function startTask(task: CollectionTask) {
  try {
    const updatedTask = await apiRequest<CollectionTask>(`/tasks/${task.id}/start`, {
      method: "POST",
      headers: authHeaders(),
    });
    tasks.value = tasks.value.map((item) => (item.id === updatedTask.id ? updatedTask : item));
    showToast("success", "任务已开始");
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "开始任务失败");
  }
}

async function stopTask(task: CollectionTask) {
  try {
    const updatedTask = await apiRequest<CollectionTask>(`/tasks/${task.id}/stop`, {
      method: "POST",
      headers: authHeaders(),
    });
    tasks.value = tasks.value.map((item) => (item.id === updatedTask.id ? updatedTask : item));
    showToast("success", "任务已停止");
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "停止任务失败");
  }
}

async function deleteTask(task: CollectionTask) {
  const confirmed = window.confirm(`删除任务「${task.id.slice(0, 8)}」？`);
  if (!confirmed) {
    return;
  }

  try {
    await apiRequest(`/tasks/${task.id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    tasks.value = tasks.value.filter((item) => item.id !== task.id);
    showToast("success", "任务已删除");
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "删除任务失败");
  }
}

async function logout() {
  const activeToken = token.value;
  token.value = "";
  currentUser.value = null;
  wechatAccount.value = null;
  sources.value = [];
  dashboardArticleTotal.value = 0;
  dashboardContentFetched.value = 0;
  dashboardRecentArticles.value = [];
  articles.value = [];
  articleTotal.value = 0;
  articleMode.value = "active";
  selectedArticleIds.value = new Set();
  resetAccountForm(null);
  stopInstantArticleTaskPolling();
  instantArticleTask.value = null;
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
    if (!hasValidWechatAuthorization.value && sourceModalVisible.value) {
      closeSourceModal();
    }
  } finally {
    wechatLoading.value = false;
  }
}

async function refreshWechatAccount() {
  if (!token.value || !wechatAccount.value) {
    return;
  }

  wechatRefreshLoading.value = true;
  wechatRefreshError.value = "";
  try {
    wechatAccount.value = await apiRequest<WechatAccount>("/wechat/accounts/refresh", {
      method: "POST",
      headers: authHeaders(),
    });
    wechatRefreshError.value = "";
    showToast("success", "授权刷新成功");
    await loadSources();
  } catch (error) {
    wechatRefreshError.value = error instanceof Error ? error.message : "刷新授权失败";
    showToast("error", wechatRefreshError.value);
    await loadWechatAccount();
  } finally {
    wechatRefreshLoading.value = false;
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
        await loadSources();
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

async function loadSources() {
  if (!token.value) {
    sources.value = [];
    return;
  }

  sourceLoading.value = true;
  sourceError.value = "";
  try {
    sources.value = await apiRequest<WechatSource[]>("/sources", {
      headers: authHeaders(),
    });
    if (sourcePage.value > sourcePageCount.value) {
      sourcePage.value = sourcePageCount.value;
    }
  } catch (error) {
    sourceError.value = error instanceof Error ? error.message : "读取公众号源失败";
    showToast("error", sourceError.value);
  } finally {
    sourceLoading.value = false;
  }
}

async function loadDashboardArticles() {
  if (!token.value) {
    dashboardArticleTotal.value = 0;
    dashboardContentFetched.value = 0;
    dashboardRecentArticles.value = [];
    return;
  }

  dashboardArticleLoading.value = true;
  try {
    const response = await apiRequest<ArticleSummaryResponse>("/articles/summary?limit=5", {
      headers: authHeaders(),
    });
    dashboardArticleTotal.value = response.total;
    dashboardContentFetched.value = response.content_fetched;
    dashboardRecentArticles.value = response.recent;
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "读取首页文章数据失败");
  } finally {
    dashboardArticleLoading.value = false;
  }
}

async function loadArticles() {
  if (!token.value) {
    articles.value = [];
    articleTotal.value = 0;
    selectedArticleIds.value = new Set();
    return;
  }

  articleLoading.value = true;
  const params = new URLSearchParams({
    page: String(articlePage.value),
    page_size: String(articlePageSize.value),
  });
  if (isArticleTrashMode.value) {
    params.set("deleted", "true");
  }
  if (articleKeyword.value.trim()) {
    params.set("keyword", articleKeyword.value.trim());
  }
  if (articleSourceId.value) {
    params.set("source_id", articleSourceId.value);
  }

  try {
    const response = await apiRequest<ArticleListResponse>(`/articles?${params.toString()}`, {
      headers: authHeaders(),
    });
    articles.value = response.items;
    articleTotal.value = response.total;
    selectedArticleIds.value = new Set(
      [...selectedArticleIds.value].filter((articleId) =>
        response.items.some((article) => article.id === articleId),
      ),
    );
    if (articlePage.value > articlePageCount.value) {
      articlePage.value = articlePageCount.value;
    }
  } catch (error) {
    showToast(
      "error",
      error instanceof Error
        ? error.message
        : isArticleTrashMode.value
          ? "读取回收箱失败"
          : "读取文章库失败",
    );
  } finally {
    articleLoading.value = false;
  }
}

async function loadTasks() {
  if (!token.value) {
    tasks.value = [];
    return;
  }

  taskLoading.value = true;
  try {
    tasks.value = await apiRequest<CollectionTask[]>("/tasks", {
      headers: authHeaders(),
    });
    if (taskPage.value > taskPageCount.value) {
      taskPage.value = taskPageCount.value;
    }
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "读取采集任务失败");
  } finally {
    taskLoading.value = false;
  }
}

async function loadExports() {
  if (!token.value) {
    exportJobs.value = [];
    return;
  }

  exportLoading.value = true;
  try {
    exportJobs.value = await apiRequest<ExportJob[]>("/exports", {
      headers: authHeaders(),
    });
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "读取导出中心失败");
  } finally {
    exportLoading.value = false;
  }
}

async function createExportJobsForArticles(
  articleIds: string[],
  formats: Array<"pdf" | "docx" | "markdown">,
  name: string,
) {
  if (articleIds.length === 0) {
    showToast("error", "请选择文章再导出");
    return;
  }
  if (formats.length === 0) {
    showToast("error", "请选择导出格式");
    return;
  }

  exportSubmitting.value = true;
  try {
    const uniqueFormats = Array.from(new Set(formats));
    const response = await apiRequest<{ status: string; task_id: string; job_id: string }>(
      "/exports",
      {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          name,
          format: uniqueFormats.length > 1 ? "zip" : uniqueFormats[0],
          formats: uniqueFormats.length > 1 ? uniqueFormats : undefined,
          article_ids: articleIds,
        }),
      },
    );
    pendingDownloadExportIds.value = new Set([...pendingDownloadExportIds.value, response.job_id]);
    showToast("success", uniqueFormats.length > 1 ? "ZIP 导出任务已创建" : "导出任务已创建");
    closeArticleExportMenu();
    clearArticleSelection();
    activeView.value = "exports";
    await loadExports();
    await loadTasks();
    startExportPolling();
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "创建导出任务失败");
  } finally {
    exportSubmitting.value = false;
  }
}

async function createBatchExportJobs() {
  await createExportJobsForArticles(
    [...selectedArticleIds.value],
    exportForm.value.formats,
    defaultExportName(),
  );
}

async function createSingleExportJob(
  article: Article,
  format: "pdf" | "docx" | "markdown",
) {
  await createExportJobsForArticles([article.id], [format], article.title);
}

async function downloadExport(job: ExportJob) {
  try {
    const response = await fetch(getApiUrl(`/api/v1/exports/${job.id}/download`), {
      headers: authHeaders(),
    });
    if (!response.ok) {
      throw new Error(`下载失败：${response.status}`);
    }
    const blob = await response.blob();
    const fileName = job.files[0]?.file_name || `${job.name}.${job.format === "zip" ? "zip" : "md"}`;
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    link.click();
    window.URL.revokeObjectURL(url);
  } catch (error) {
    showToast("error", error instanceof Error ? error.message : "下载导出文件失败");
  }
}

function stopExportPolling() {
  if (exportPollTimer !== undefined) {
    window.clearInterval(exportPollTimer);
    exportPollTimer = undefined;
  }
}

function startExportPolling() {
  if (exportPollTimer !== undefined) {
    return;
  }
  exportPollTimer = window.setInterval(() => {
    void pollPendingExports();
  }, 1500);
  void pollPendingExports();
}

async function pollPendingExports() {
  if (exportPollInFlight) {
    return;
  }
  exportPollInFlight = true;
  if (pendingDownloadExportIds.value.size === 0) {
    stopExportPolling();
    exportPollInFlight = false;
    return;
  }
  try {
    await loadExports();
    const remaining = new Set(pendingDownloadExportIds.value);
    for (const job of exportJobs.value) {
      if (!remaining.has(job.id)) {
        continue;
      }
      if (job.status === "succeeded") {
        remaining.delete(job.id);
        pendingDownloadExportIds.value = new Set(remaining);
        if (!exportDownloadInFlightIds.has(job.id)) {
          exportDownloadInFlightIds.add(job.id);
          try {
            await downloadExport(job);
          } finally {
            exportDownloadInFlightIds.delete(job.id);
          }
        }
      } else if (["failed", "cancelled"].includes(job.status)) {
        remaining.delete(job.id);
        showToast("error", job.error_message || "导出失败");
      }
    }
    pendingDownloadExportIds.value = remaining;
    if (remaining.size === 0) {
      stopExportPolling();
    }
  } finally {
    exportPollInFlight = false;
  }
}

onMounted(() => {
  document.addEventListener("click", closeUserMenu);
  void loadCurrentUser();
});

onBeforeUnmount(() => {
  document.removeEventListener("click", closeUserMenu);
  stopWechatLoginPolling();
  stopInstantArticleTaskPolling();
  stopExportPolling();
  if (toastTimer !== undefined) {
    window.clearTimeout(toastTimer);
  }
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
        <label v-if="authMode === 'register'">
          <span>邀请码</span>
          <input
            v-model="authForm.inviteCode"
            type="text"
            maxlength="80"
            autocomplete="off"
            required
          />
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
            <span class="user-name">{{ currentUser?.display_name || currentUser?.email }}</span>
            <span class="user-role">{{ currentUser?.email }}</span>
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
            <div class="metric-value">{{ sources.length }}</div>
            <div class="metric-note">{{ activeSourceCount }} 个状态正常</div>
          </article>
          <article class="metric">
            <div class="metric-label">文章库</div>
            <div class="metric-value">
              {{ dashboardArticleLoading ? "..." : dashboardArticleTotal }}
            </div>
            <div class="metric-note">已抓正文 {{ dashboardContentFetched }} 篇</div>
          </article>
          <article class="metric">
            <div class="metric-label">导出中心</div>
            <div class="metric-value">18</div>
            <div class="metric-note">本周生成 6 个文件</div>
          </article>
        </div>

        <div class="content-grid">
          <section class="panel wide-panel">
            <div class="panel-header">
              <div>
                <h2>最近文章</h2>
                <p>列表同步后，用户可以选择需要抓正文的文章。</p>
              </div>
              <button class="small-button" type="button" @click="setView('articles')">进入文章库</button>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>标题</th>
                    <th>公众号</th>
                    <th>发布时间</th>
                    <th>正文</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="dashboardArticleLoading">
                    <td colspan="4">正在读取最近文章</td>
                  </tr>
                  <tr v-else-if="dashboardRecentArticles.length === 0">
                    <td colspan="4">还没有文章</td>
                  </tr>
                  <tr v-for="article in dashboardRecentArticles" v-else :key="article.id">
                    <td>{{ article.title }}</td>
                    <td>{{ article.source.name }}</td>
                    <td>{{ formatDateTime(article.publish_time) }}</td>
                    <td>
                      <span class="tag" :class="articleStatusTag(article.content_status)">
                        {{ articleStatusLabel(article.content_status) }}
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
            <button
              v-if="!wechatAccount"
              class="primary-button"
              type="button"
              :disabled="wechatLoginLoading"
              @click="startWechatLogin"
            >
              扫码授权
            </button>
          </div>
          <p v-if="wechatRefreshError" class="auth-error">{{ wechatRefreshError }}</p>
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
            <div class="inline-actions auth-row-actions">
              <button
                class="ghost-button"
                type="button"
                :disabled="wechatRefreshLoading"
                @click="refreshWechatAccount"
              >
                {{ wechatRefreshLoading ? "刷新中..." : "刷新授权" }}
              </button>
              <button
                class="ghost-button"
                type="button"
                :disabled="wechatLoginLoading"
                @click="startWechatLogin"
              >
                重新授权
              </button>
              <button class="ghost-button" type="button" @click="logoutWechatAccount">退出授权</button>
            </div>
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
              <p>只管理公众号源本身，文章同步和正文抓取在后续流程处理。</p>
            </div>
            <div class="inline-actions">
              <div class="segmented-control" aria-label="公众号源视图">
                <button
                  type="button"
                  :class="{ active: sourceViewMode === 'list' }"
                  @click="sourceViewMode = 'list'"
                >
                  列表
                </button>
                <button
                  type="button"
                  :class="{ active: sourceViewMode === 'grid' }"
                  @click="sourceViewMode = 'grid'"
                >
                  网格
                </button>
              </div>
              <button
                class="ghost-button"
                type="button"
                :disabled="!hasValidWechatAuthorization"
                :title="hasValidWechatAuthorization ? '通过文章链接添加' : '请先扫码授权微信公众号'"
                @click="openSourceModal('url')"
              >
                粘贴文章链接
              </button>
              <button
                class="primary-button"
                type="button"
                :disabled="!hasValidWechatAuthorization"
                :title="hasValidWechatAuthorization ? '搜索公众号' : '请先扫码授权微信公众号'"
                @click="openSourceModal('search')"
              >
                搜索公众号
              </button>
            </div>
          </div>

          <div v-if="!hasValidWechatAuthorization" class="source-auth-notice">
            <span>添加公众号源需要先完成微信公众号扫码授权。</span>
            <button class="small-button" type="button" @click="startWechatLogin">扫码授权</button>
          </div>
          <p v-if="sourceError" class="auth-error">{{ sourceError }}</p>

          <div class="source-summary-grid">
            <article class="source-summary-item">
              <strong>{{ sources.length }}</strong>
              <span>已关注公众号</span>
            </article>
            <article class="source-summary-item">
              <strong>{{ formatNumber(sourceTotalArticles) }}</strong>
              <span>在库文章</span>
            </article>
            <article class="source-summary-item">
              <strong>{{ activeSourceCount }}</strong>
              <span>状态正常</span>
            </article>
          </div>

          <div v-if="sourceLoading" class="empty-state">正在读取公众号源</div>
          <div v-else-if="sources.length === 0" class="empty-state">
            还没有公众号源
          </div>
          <div v-else-if="sourceViewMode === 'list'" class="source-table-wrap">
            <table class="source-table">
              <thead>
                <tr>
                  <th>Logo</th>
                  <th>公众号</th>
                  <th>最后抓取</th>
                  <th>在库文章</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="source in paginatedSources" :key="source.id">
                  <td>
                    <img
                      v-if="source.avatar_url && !isSourceAvatarBroken(source)"
                      :src="sourceAvatarSrc(source)"
                      alt=""
                      class="source-avatar"
                      @error="markBrokenSourceAvatar(source)"
                    />
                    <span v-else class="source-avatar fallback">
                      {{ sourceInitial(source.name) }}
                    </span>
                  </td>
                  <td>
                    <div class="source-name-cell">
                      <strong>{{ source.name }}</strong>
                      <span>{{ sourceDescription(source) }}</span>
                    </div>
                  </td>
                  <td>{{ formatDateTime(source.last_list_fetched_at) }}</td>
                  <td>{{ formatNumber(source.article_count) }}</td>
                  <td>
                    <span class="tag" :class="sourceStatusTag(source.status)">
                      {{ sourceStatusLabel(source.status) }}
                    </span>
                  </td>
                  <td>
                    <div class="source-actions">
                      <button
                        class="link-button"
                        type="button"
                        :disabled="sourceOperatingId === source.id"
                        @click="refreshSource(source)"
                      >
                        刷新
                      </button>
                      <button class="link-button" type="button" @click="openTaskModal(source)">
                        抓取
                      </button>
                      <button
                        class="link-button"
                        type="button"
                        :disabled="sourceOperatingId === source.id"
                        @click="toggleSourceStatus(source)"
                      >
                        {{ source.status === "active" ? "停用" : "启用" }}
                      </button>
                      <button
                        class="link-button danger"
                        type="button"
                        :disabled="sourceOperatingId === source.id"
                        @click="deleteSource(source)"
                      >
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="source-list source-grid">
            <article v-for="source in paginatedSources" :key="source.id" class="source-row">
              <div class="source-main">
                <img
                  v-if="source.avatar_url && !isSourceAvatarBroken(source)"
                  :src="sourceAvatarSrc(source)"
                  alt=""
                  class="source-avatar"
                  @error="markBrokenSourceAvatar(source)"
                />
                <span v-else class="source-avatar fallback">
                  {{ sourceInitial(source.name) }}
                </span>
                <div>
                  <strong>{{ source.name }}</strong>
                  <span>{{ sourceDescription(source) }}</span>
                </div>
              </div>
              <dl class="source-meta">
                <div>
                  <dt>最后抓取</dt>
                  <dd>{{ formatDateTime(source.last_list_fetched_at) }}</dd>
                </div>
                <div>
                  <dt>在库文章</dt>
                  <dd>{{ formatNumber(source.article_count) }}</dd>
                </div>
                <div>
                  <dt>状态</dt>
                  <dd>
                    <span class="tag" :class="sourceStatusTag(source.status)">
                      {{ sourceStatusLabel(source.status) }}
                    </span>
                  </dd>
                </div>
              </dl>
              <div class="source-actions">
                <button
                  class="link-button"
                  type="button"
                  :disabled="sourceOperatingId === source.id"
                  @click="refreshSource(source)"
                >
                  刷新
                </button>
                <button class="link-button" type="button" @click="openTaskModal(source)">
                  抓取
                </button>
                <button
                  class="link-button"
                  type="button"
                  :disabled="sourceOperatingId === source.id"
                  @click="toggleSourceStatus(source)"
                >
                  {{ source.status === "active" ? "停用" : "启用" }}
                </button>
                <button
                  class="link-button danger"
                  type="button"
                  :disabled="sourceOperatingId === source.id"
                  @click="deleteSource(source)"
                >
                  删除
                </button>
              </div>
            </article>
          </div>
          <div v-if="sources.length > 0" class="source-pagination">
            <label>
              <span>每页</span>
              <select :value="sourcePageSize" @change="setSourcePageSize">
                <option :value="10">10</option>
                <option :value="20">20</option>
                <option :value="50">50</option>
              </select>
            </label>
            <div class="pagination-links">
              <button
                class="link-button"
                type="button"
                :disabled="sourcePage <= 1"
                @click="setSourcePage(sourcePage - 1)"
              >
                上一页
              </button>
              <button
                v-for="page in sourcePageCount"
                :key="page"
                class="page-button"
                :class="{ active: page === sourcePage }"
                type="button"
                @click="setSourcePage(page)"
              >
                {{ page }}
              </button>
              <button
                class="link-button"
                type="button"
                :disabled="sourcePage >= sourcePageCount"
                @click="setSourcePage(sourcePage + 1)"
              >
                下一页
              </button>
            </div>
          </div>
        </section>
      </section>

      <section v-else-if="activeView === 'articles'" class="view active">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>{{ isArticleTrashMode ? "文章回收箱" : "文章库" }}</h2>
              <p>
                {{
                  isArticleTrashMode
                    ? "查看已删除文章，可按标题或公众号搜索并恢复。"
                    : "文章列表与正文抓取分离，方便用户控制采集范围。"
                }}
              </p>
            </div>
            <div class="panel-actions">
              <div class="segmented-control">
                <button
                  type="button"
                  :class="{ active: articleMode === 'active' }"
                  @click="setArticleMode('active')"
                >
                  文章库
                </button>
                <button
                  type="button"
                  :class="{ active: articleMode === 'trash' }"
                  @click="setArticleMode('trash')"
                >
                  回收箱
                </button>
              </div>
              <button class="ghost-button" type="button" :disabled="articleLoading" @click="loadArticles">
                {{ articleLoading ? "刷新中..." : "刷新" }}
              </button>
            </div>
          </div>
          <form class="filter-bar article-filter-bar" @submit.prevent="searchArticles">
            <input
              v-model="articleKeyword"
              type="search"
              placeholder="搜索标题、公众号、作者"
            />
            <select v-model="articleSourceId">
              <option value="">全部公众号</option>
              <option v-for="source in sources" :key="source.id" :value="source.id">
                {{ source.name }}
              </option>
            </select>
            <button class="primary-button" type="submit" :disabled="articleLoading">搜索</button>
            <button class="ghost-button" type="button" :disabled="articleLoading" @click="resetArticleFilters">
              重置
            </button>
          </form>

          <div v-if="hasSelectedArticles" class="article-bulk-bar">
            <span>已选择 {{ selectedArticleIds.size }} 篇</span>
            <button
              v-if="!isArticleTrashMode && canBatchFetchContent"
              class="primary-button"
              type="button"
              @click="fetchSelectedArticles"
            >
              抓取正文
            </button>
            <button
              v-if="!isArticleTrashMode"
              class="primary-button"
              type="button"
              :disabled="!canExportSelectedArticles || exportSubmitting"
              @click="createBatchExportJobs"
            >
              {{ exportSubmitting ? "创建中..." : "导出" }}
            </button>
            <div v-if="!isArticleTrashMode" class="export-format-checks">
              <label>
                <input
                  type="checkbox"
                  :checked="exportForm.formats.includes('pdf')"
                  @change="toggleExportFormat('pdf', ($event.target as HTMLInputElement).checked)"
                />
                PDF
              </label>
              <label>
                <input
                  type="checkbox"
                  :checked="exportForm.formats.includes('docx')"
                  @change="toggleExportFormat('docx', ($event.target as HTMLInputElement).checked)"
                />
                DOCX
              </label>
              <label>
                <input
                  type="checkbox"
                  :checked="exportForm.formats.includes('markdown')"
                  @change="toggleExportFormat('markdown', ($event.target as HTMLInputElement).checked)"
                />
                Markdown
              </label>
            </div>
            <button
              v-if="isArticleTrashMode"
              class="primary-button"
              type="button"
              :disabled="articleBatchRestoring"
              @click="restoreSelectedArticles"
            >
              {{ articleBatchRestoring ? "恢复中..." : "恢复文章" }}
            </button>
            <button
              v-else
              class="link-button danger"
              type="button"
              :disabled="articleBatchDeleting"
              @click="deleteSelectedArticles"
            >
              {{ articleBatchDeleting ? "删除中..." : "删除文章" }}
            </button>
            <button class="link-button" type="button" @click="clearArticleSelection">取消选择</button>
          </div>

          <div v-if="articleLoading" class="empty-state">{{ articleLoadingLabel }}</div>
          <div v-else-if="articles.length === 0" class="empty-state">{{ articleEmptyLabel }}</div>
          <template v-else>
            <div class="article-table-wrap">
              <table class="article-table">
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      class="article-select-checkbox"
                      aria-label="全选当前页文章"
                      :checked="allVisibleArticlesSelected"
                      @change="toggleVisibleArticleSelection"
                    />
                  </th>
                  <th>封面</th>
                  <th>文章</th>
                  <th>公众号</th>
                  <th>发布时间</th>
                  <th>{{ isArticleTrashMode ? "删除时间" : "正文" }}</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="article in articles" :key="article.id">
                  <td>
                    <input
                      type="checkbox"
                      class="article-select-checkbox"
                      :aria-label="`选择 ${article.title}`"
                      :checked="selectedArticleIds.has(article.id)"
                      @change="toggleArticleSelection(article)"
                    />
                  </td>
                  <td>
                    <button
                      class="article-cover-button"
                      type="button"
                      :aria-label="`查看 ${article.title}`"
                      @click="openArticleFromList(article)"
                    >
                      <img
                        v-if="article.cover_url"
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
                    <div class="article-source-cell">
                      <img
                        v-if="article.source.avatar_url"
                        class="article-source-avatar"
                        :src="articleSourceAvatarSrc(article)"
                        :alt="article.source.name"
                      />
                      <div v-else class="article-source-avatar article-source-avatar-empty">
                        {{ sourceInitial(article.source.name) }}
                      </div>
                      <span>{{ article.source.name }}</span>
                    </div>
                  </td>
                  <td>{{ formatDateTime(article.publish_time) }}</td>
                  <td v-if="isArticleTrashMode">
                    {{ formatDateTime(article.deleted_at) }}
                  </td>
                  <td v-else>
                    <button
                      v-if="['pending', 'failed'].includes(article.content_status)"
	                      class="link-button"
	                      type="button"
	                      @click="fetchArticle(article)"
	                    >
	                      抓取
                    </button>
                    <span v-else class="tag" :class="articleStatusTag(article.content_status)">
                      {{ articleStatusLabel(article.content_status) }}
                    </span>
                  </td>
	                  <td>
                    <div class="article-actions">
                      <template v-if="isArticleTrashMode">
                        <button class="link-button" type="button" @click="viewOriginalArticle(article)">
                          查看
                        </button>
                        <button
                          class="link-button"
                          type="button"
                          :disabled="articleOperatingId === article.id"
                          @click="restoreArticle(article)"
                        >
                          恢复
                        </button>
                      </template>
                      <template v-else>
                      <button
                        class="link-button"
                        type="button"
                        :disabled="articleOperatingId === article.id"
                        @click="refreshArticle(article)"
                      >
                        刷新
                      </button>
                      <button
                        class="link-button"
                        type="button"
                        :disabled="articleViewLoadingId === article.id"
                        @click="viewArticle(article)"
                      >
                        {{ articleViewLoadingId === article.id ? "读取中..." : "查看" }}
                      </button>
                      <div class="inline-export-menu">
                        <button
                          class="link-button"
                          type="button"
                          @click="toggleArticleExportMenu(article)"
                        >
                          导出
                        </button>
                        <div v-if="articleExportMenuId === article.id" class="export-popover">
                          <button type="button" @click="createSingleExportJob(article, 'pdf')">
                            PDF
                          </button>
                          <button type="button" @click="createSingleExportJob(article, 'docx')">
                            DOCX
                          </button>
                          <button type="button" @click="createSingleExportJob(article, 'markdown')">
                            MD
                          </button>
                        </div>
                      </div>
                      <button
                        class="link-button danger"
                        type="button"
                        :disabled="articleOperatingId === article.id"
                        @click="deleteArticle(article)"
                      >
                        删除
                      </button>
                      </template>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
            </div>

            <div class="article-card-list">
              <article v-for="article in articles" :key="article.id" class="article-row">
                <input
                  type="checkbox"
                  class="article-select-checkbox"
                  :aria-label="`选择 ${article.title}`"
                  :checked="selectedArticleIds.has(article.id)"
                  @change="toggleArticleSelection(article)"
                />
                <button
                  class="article-cover-button"
                  type="button"
                  :aria-label="`查看 ${article.title}`"
                  @click="openArticleFromList(article)"
                >
                  <img
                    v-if="article.cover_url"
                    class="article-cover"
                    :src="articleCoverSrc(article)"
                    :alt="article.title"
                  />
                  <span v-else class="article-cover article-cover-empty">WV</span>
                </button>
                <div class="article-title-cell">
                  <button
                    class="article-title-button"
                    type="button"
                    @click="openArticleFromList(article)"
                  >
                    <strong>{{ article.title }}</strong>
                  </button>
                  <span>{{ article.digest || "暂无摘要" }}</span>
                  <div class="article-source-cell">
                    <img
                      v-if="article.source.avatar_url"
                      class="article-source-avatar"
                      :src="articleSourceAvatarSrc(article)"
                      :alt="article.source.name"
                    />
                    <div v-else class="article-source-avatar article-source-avatar-empty">
                      {{ sourceInitial(article.source.name) }}
                    </div>
                    <span>{{ article.source.name }}</span>
                    <small>{{ formatDateTime(article.publish_time) }}</small>
                  </div>
                  <div v-if="isArticleTrashMode" class="article-mobile-status">
                    <span class="tag muted">删除于 {{ formatDateTime(article.deleted_at) }}</span>
                  </div>
                  <div v-else class="article-mobile-status">
                    <span class="tag" :class="articleStatusTag(article.content_status)">
                      正文 {{ articleStatusLabel(article.content_status) }}
                    </span>
                  </div>
                  <div class="article-actions">
                    <button
                      v-if="!isArticleTrashMode && ['pending', 'failed'].includes(article.content_status)"
                      class="link-button"
                      type="button"
                      @click="fetchArticle(article)"
                    >
                      抓取正文
                    </button>
                    <template v-if="isArticleTrashMode">
                      <button class="link-button" type="button" @click="viewOriginalArticle(article)">
                        查看
                      </button>
                      <button
                        class="link-button"
                        type="button"
                        :disabled="articleOperatingId === article.id"
                        @click="restoreArticle(article)"
                      >
                        恢复
                      </button>
                    </template>
                    <template v-else>
                    <button class="link-button" type="button" @click="refreshArticle(article)">
                      刷新
                    </button>
                    <button
                      class="link-button"
                      type="button"
                      :disabled="articleViewLoadingId === article.id"
                      @click="viewArticle(article)"
                    >
                      {{ articleViewLoadingId === article.id ? "读取中..." : "查看" }}
                    </button>
                    <div class="inline-export-menu">
                      <button
                        class="link-button"
                        type="button"
                        @click="toggleArticleExportMenu(article)"
                      >
                        导出
                      </button>
                      <div v-if="articleExportMenuId === article.id" class="export-popover">
                        <button type="button" @click="createSingleExportJob(article, 'pdf')">
                          PDF
                        </button>
                        <button type="button" @click="createSingleExportJob(article, 'docx')">
                          DOCX
                        </button>
                        <button type="button" @click="createSingleExportJob(article, 'markdown')">
                          MD
                        </button>
                      </div>
                    </div>
                    <button class="link-button danger" type="button" @click="deleteArticle(article)">
                      删除
                    </button>
                    </template>
                  </div>
                </div>
              </article>
            </div>

            <div class="source-pagination">
              <label>
                <span>每页</span>
                <select :value="articlePageSize" @change="setArticlePageSize">
                  <option :value="10">10</option>
                  <option :value="20">20</option>
                  <option :value="50">50</option>
                </select>
              </label>
              <div class="pagination-links">
                <button
                  class="link-button"
                  type="button"
                  :disabled="articlePage <= 1"
                  @click="setArticlePage(articlePage - 1)"
                >
                  上一页
                </button>
                <button
                  v-for="page in articlePageCount"
                  :key="page"
                  class="page-button"
                  :class="{ active: page === articlePage }"
                  type="button"
                  @click="setArticlePage(page)"
                >
                  {{ page }}
                </button>
                <button
                  class="link-button"
                  type="button"
                  :disabled="articlePage >= articlePageCount"
                  @click="setArticlePage(articlePage + 1)"
                >
                  下一页
                </button>
              </div>
            </div>
          </template>
        </section>
      </section>

      <section v-else-if="activeView === 'tasks'" class="view active">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>采集任务</h2>
              <p>用于观察列表同步、正文抓取和导出进度。</p>
            </div>
            <button class="ghost-button" type="button" :disabled="taskLoading" @click="loadTasks">
              {{ taskLoading ? "刷新中..." : "刷新" }}
            </button>
          </div>
          <div v-if="taskLoading" class="empty-state">正在读取采集任务</div>
          <div v-else-if="tasks.length === 0" class="empty-state">还没有采集任务</div>
          <template v-else>
            <div class="task-table-wrap">
              <table class="task-table">
                <thead>
                  <tr>
                    <th>任务类型</th>
                    <th>任务参数</th>
                    <th>状态</th>
                    <th>创建时间</th>
                    <th>开始时间</th>
                    <th>结束时间</th>
                    <th>错误</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="task in paginatedTasks" :key="task.id">
                    <td>{{ task.task_type }}</td>
                    <td>
                      <div class="task-note-cell">
                        <strong>{{ task.note }}</strong>
                        <span>{{ task.id }}</span>
                      </div>
                    </td>
                    <td>
                      <span class="tag" :class="taskStatusTag(task.status)">
                        {{ taskStatusLabel(task.status) }}
                      </span>
                    </td>
                    <td>{{ formatDateTime(task.created_at) }}</td>
                    <td>{{ formatDateTime(task.started_at) }}</td>
                    <td>{{ formatDateTime(task.finished_at) }}</td>
                    <td>{{ task.error_message || "-" }}</td>
                    <td>
                      <div class="task-actions">
                        <button
                          v-if="canStartTask(task)"
                          class="link-button"
                          type="button"
                          @click="startTask(task)"
                        >
                          开始
                        </button>
                        <button
                          v-if="canStopTask(task)"
                          class="link-button danger"
                          type="button"
                          @click="stopTask(task)"
                        >
                          停止
                        </button>
                        <button
                          v-if="canDeleteTask(task)"
                          class="link-button danger"
                          type="button"
                          @click="deleteTask(task)"
                        >
                          删除
                        </button>
                        <span v-if="!canStartTask(task) && !canStopTask(task) && !canDeleteTask(task)">
                          {{ taskActionNote(task) }}
                        </span>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div class="task-card-list">
              <article v-for="task in paginatedTasks" :key="task.id" class="task-row">
                <div>
                  <strong>{{ task.task_type }}</strong>
                  <span>{{ task.note }}</span>
                  <span>创建时间：{{ formatDateTime(task.created_at) }}</span>
                  <span>开始时间：{{ formatDateTime(task.started_at) }}</span>
                  <span>结束时间：{{ formatDateTime(task.finished_at) }}</span>
                </div>
                <div class="task-status-cell">
                  <span class="tag" :class="taskStatusTag(task.status)">
                    {{ taskStatusLabel(task.status) }}
                  </span>
                </div>
                <div class="task-actions">
                  <button
                    v-if="canStartTask(task)"
                    class="link-button"
                    type="button"
                    @click="startTask(task)"
                  >
                    开始
                  </button>
                  <button
                    v-if="canStopTask(task)"
                    class="link-button danger"
                    type="button"
                    @click="stopTask(task)"
                  >
                    停止
                  </button>
                  <button
                    v-if="canDeleteTask(task)"
                    class="link-button danger"
                    type="button"
                    @click="deleteTask(task)"
                  >
                    删除
                  </button>
                  <span v-if="!canStartTask(task) && !canStopTask(task) && !canDeleteTask(task)">
                    {{ taskActionNote(task) }}
                  </span>
                </div>
              </article>
            </div>

            <div class="source-pagination">
              <label>
                <span>每页</span>
                <select :value="taskPageSize" @change="setTaskPageSize">
                  <option :value="10">10</option>
                  <option :value="20">20</option>
                  <option :value="50">50</option>
                </select>
              </label>
              <div class="pagination-links">
                <button
                  class="link-button"
                  type="button"
                  :disabled="taskPage <= 1"
                  @click="setTaskPage(taskPage - 1)"
                >
                  上一页
                </button>
                <button
                  v-for="page in taskPageCount"
                  :key="page"
                  class="page-button"
                  :class="{ active: page === taskPage }"
                  type="button"
                  @click="setTaskPage(page)"
                >
                  {{ page }}
                </button>
                <button
                  class="link-button"
                  type="button"
                  :disabled="taskPage >= taskPageCount"
                  @click="setTaskPage(taskPage + 1)"
                >
                  下一页
                </button>
              </div>
            </div>
          </template>
        </section>
      </section>

      <section v-else-if="activeView === 'exports'" class="view active">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>导出中心</h2>
              <p>PDF、DOCX、Markdown 都基于已保存的 clean HTML 和 Markdown 生成。</p>
            </div>
            <button class="ghost-button" type="button" :disabled="exportLoading" @click="loadExports">
              {{ exportLoading ? "刷新中..." : "刷新" }}
            </button>
          </div>
          <div v-if="exportLoading" class="empty-state">正在读取导出任务</div>
          <div v-else-if="exportJobs.length === 0" class="empty-state">
            还没有导出任务，请在文章库中选择已抓取正文的文章后导出。
          </div>
          <template v-else>
            <div class="export-table-wrap">
              <table class="export-table">
                <thead>
                  <tr>
                    <th>导出名称</th>
                    <th>格式</th>
                    <th>状态</th>
                    <th>文章数</th>
                    <th>创建时间</th>
                    <th>完成时间</th>
                    <th>过期时间</th>
                    <th>文件大小</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in paginatedExports" :key="item.id">
                    <td>
                      <div class="task-note-cell">
                        <strong>{{ item.name }}</strong>
                        <span>{{ item.id }}</span>
                      </div>
                    </td>
                    <td>{{ exportFormatLabel(item) }}</td>
                    <td>
                      <span class="tag" :class="exportStatusTag(item.status)">
                        {{ exportStatusLabel(item.status) }}
                      </span>
                    </td>
                    <td>{{ exportArticleCount(item) }}</td>
                    <td>{{ formatDateTime(item.created_at) }}</td>
                    <td>{{ formatDateTime(item.finished_at) }}</td>
                    <td>{{ formatDateTime(item.expires_at) }}</td>
                    <td>{{ exportFileSize(item) }}</td>
                    <td>
                      <div class="task-actions">
                        <button
                          class="link-button"
                          type="button"
                          :disabled="item.status !== 'succeeded' || item.files.length === 0"
                          @click="downloadExport(item)"
                        >
                          下载
                        </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div class="export-card-list">
              <article v-for="item in paginatedExports" :key="item.id" class="task-row">
                <div>
                  <strong>{{ item.name }}</strong>
                  <span>{{ exportFormatLabel(item) }} · {{ exportArticleCount(item) }}</span>
                  <span>创建时间：{{ formatDateTime(item.created_at) }}</span>
                  <span>完成时间：{{ formatDateTime(item.finished_at) }}</span>
                  <span>过期时间：{{ formatDateTime(item.expires_at) }}</span>
                  <span>文件大小：{{ exportFileSize(item) }}</span>
                </div>
                <div class="task-status-cell">
                  <span class="tag" :class="exportStatusTag(item.status)">
                    {{ exportStatusLabel(item.status) }}
                  </span>
                </div>
                <div class="task-actions">
                  <button
                    class="link-button"
                    type="button"
                    :disabled="item.status !== 'succeeded' || item.files.length === 0"
                    @click="downloadExport(item)"
                  >
                    下载
                  </button>
                </div>
              </article>
            </div>

            <div class="source-pagination">
              <label>
                <span>每页</span>
                <select :value="exportPageSize" @change="setExportPageSize">
                  <option :value="10">10</option>
                  <option :value="20">20</option>
                  <option :value="50">50</option>
                </select>
              </label>
              <div class="pagination-links">
                <button
                  class="link-button"
                  type="button"
                  :disabled="exportPage <= 1"
                  @click="setExportPage(exportPage - 1)"
                >
                  上一页
                </button>
                <button
                  v-for="page in exportPageCount"
                  :key="page"
                  class="page-button"
                  :class="{ active: page === exportPage }"
                  type="button"
                  @click="setExportPage(page)"
                >
                  {{ page }}
                </button>
                <button
                  class="link-button"
                  type="button"
                  :disabled="exportPage >= exportPageCount"
                  @click="setExportPage(exportPage + 1)"
                >
                  下一页
                </button>
              </div>
            </div>
          </template>
        </section>
      </section>

      <section v-else-if="activeView === 'account'" class="view active">
        <section class="panel account-panel">
          <div class="panel-header">
            <div>
              <h2>个人账户</h2>
              <p>邮箱用于登录，暂不支持修改。</p>
            </div>
          </div>

          <form class="modal-form account-form" @submit.prevent="submitAccount">
            <label>
              <span>邮箱</span>
              <input :value="currentUser?.email" type="email" disabled />
            </label>
            <label>
              <span>显示名称</span>
              <input v-model="accountForm.displayName" type="text" maxlength="80" autocomplete="name" />
            </label>
            <div class="account-password-group">
              <label>
                <span>新密码</span>
                <input
                  v-model="accountForm.newPassword"
                  type="password"
                  autocomplete="new-password"
                  minlength="8"
                />
              </label>
              <label>
                <span>确认新密码</span>
                <input
                  v-model="accountForm.confirmPassword"
                  type="password"
                  autocomplete="new-password"
                  minlength="8"
                />
              </label>
            </div>
            <p v-if="accountError" class="form-error">{{ accountError }}</p>
            <div class="modal-actions">
              <button class="ghost-button" type="button" :disabled="accountSaving" @click="resetAccountForm()">
                重置
              </button>
              <button class="primary-button" type="submit" :disabled="accountSaving">
                {{ accountSaving ? "保存中..." : "保存修改" }}
              </button>
            </div>
          </form>
        </section>
      </section>

    </main>

    <div v-if="showWechatLoginLoading" class="loading-backdrop" aria-live="polite">
      <div class="loading-card">
        <div class="loading-gif" aria-hidden="true"></div>
        <span>正在生成扫码二维码</span>
      </div>
    </div>

    <div v-if="instantArticleTask" class="loading-backdrop" aria-live="polite">
      <div class="loading-card">
        <div class="loading-gif" aria-hidden="true"></div>
        <span>{{ instantArticleTaskLabel }}</span>
        <small>{{ instantArticleTask.articleTitle }}</small>
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
            <a
              class="register-link"
              href="https://mp.weixin.qq.com/cgi-bin/registermidpage?action=index&weblogo=1&lang=zh_CN"
              target="_blank"
              rel="noreferrer"
            >
              注册新的公众号
            </a>
          </div>
        </div>
      </section>
    </div>

    <div v-if="sourceModalVisible" class="modal-backdrop">
      <section
        class="modal-dialog source-modal"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="
          sourceModalMode === 'search'
            ? 'source-search-title'
            : sourceModalMode === 'task'
              ? 'source-task-title'
              : 'source-url-title'
        "
      >
        <button class="modal-close" type="button" aria-label="关闭" @click="closeSourceModal">
          ×
        </button>

        <template v-if="sourceModalMode === 'search'">
          <div class="modal-header">
            <div>
              <h2 id="source-search-title">搜索公众号</h2>
              <p>通过公众号名称搜索并添加到源列表。</p>
            </div>
          </div>
          <form class="modal-form" @submit.prevent="submitSourceSearch">
            <label>
              <span>公众号名称</span>
              <input v-model="sourceSearchKeyword" type="search" placeholder="输入公众号名称" />
            </label>
            <div class="modal-actions">
              <button class="ghost-button" type="button" @click="closeSourceModal">取消</button>
              <button
                class="primary-button"
                type="submit"
                :disabled="sourceSearchLoading || !sourceSearchKeyword.trim()"
              >
                {{ sourceSearchLoading ? "搜索中..." : "搜索" }}
              </button>
            </div>
          </form>

          <div v-if="sourceSearchSubmitted" class="modal-result-list">
            <article
              v-for="source in sourceSearchResults"
              :key="source.fakeid || source.name"
              class="modal-result-item source-search-result"
            >
              <div class="source-main">
                <img
                  v-if="source.avatar_url && !isSourceAvatarBroken(source)"
                  :src="sourceAvatarSrc(source)"
                  alt=""
                  class="source-avatar"
                  @error="markBrokenSourceAvatar(source)"
                />
                <span v-else class="source-avatar fallback">
                  {{ sourceInitial(source.name) }}
                </span>
                <div>
                  <strong>{{ source.name }}</strong>
                  <span>{{ sourceDescription(source) }}</span>
                </div>
              </div>
              <button
                class="small-button"
                type="button"
                :disabled="source.already_added || sourceAddLoading"
                @click="addSourceFromModal(source)"
              >
                {{ source.already_added ? "已添加" : sourceAddLoading ? "添加中..." : "添加" }}
              </button>
            </article>
            <div v-if="sourceSearchResults.length === 0" class="empty-state">
              未找到匹配的公众号
            </div>
          </div>
        </template>

        <template v-else-if="sourceModalMode === 'task'">
          <div class="modal-header">
            <div>
              <h2 id="source-task-title">创建采集任务</h2>
              <p>{{ selectedTaskSource?.name }} · 创建后由 worker 立即执行。</p>
            </div>
          </div>
          <form class="modal-form" @submit.prevent="createSourceArticleTask">
            <label>
              <span>时间范围</span>
              <select v-model="taskForm.range">
                <option value="7d">最近 7 天</option>
                <option value="30d">最近 30 天</option>
                <option value="90d">最近 90 天</option>
                <option value="custom">自定义</option>
                <option value="all">全部</option>
              </select>
            </label>
            <div v-if="taskForm.range === 'custom'" class="date-range-row">
              <label>
                <span>开始日期</span>
                <input v-model="taskForm.startDate" type="date" />
              </label>
              <label>
                <span>结束日期</span>
                <input v-model="taskForm.endDate" type="date" />
              </label>
            </div>
            <label>
              <span>最多文章数</span>
              <select v-model.number="taskForm.limit">
                <option :value="30">30</option>
                <option :value="50">50</option>
                <option :value="100">100</option>
                <option :value="0">不设限</option>
              </select>
            </label>
            <label class="checkbox-row">
              <span>采集正文</span>
              <input
                type="checkbox"
                :checked="taskForm.fetchContent"
                @change="toggleTaskFetchContent(($event.target as HTMLInputElement).checked)"
              />
            </label>
            <label class="checkbox-row">
              <span>跳过已存在文章</span>
              <input v-model="taskForm.skipExisting" type="checkbox" />
            </label>
            <div class="readonly-row">
              <span>执行方式</span>
              <strong>立即执行</strong>
            </div>
            <div class="modal-actions">
              <button class="ghost-button" type="button" @click="closeSourceModal">取消</button>
              <button class="primary-button" type="submit" :disabled="taskSubmitting">
                {{ taskSubmitting ? "创建中..." : "创建任务" }}
              </button>
            </div>
          </form>
        </template>

        <template v-else>
          <div class="modal-header">
            <div>
              <h2 id="source-url-title">通过文章链接添加</h2>
              <p>粘贴公众号文章链接，解析文章所属公众号后添加为源。</p>
            </div>
          </div>
          <form class="modal-form" @submit.prevent="submitSourceUrl">
            <label>
              <span>文章链接</span>
              <textarea
                v-model="sourceArticleUrl"
                rows="4"
                placeholder="https://mp.weixin.qq.com/s/..."
              ></textarea>
            </label>
            <div class="modal-actions">
              <button class="ghost-button" type="button" @click="closeSourceModal">取消</button>
              <button
                class="primary-button"
                type="submit"
                :disabled="sourceUrlLoading || !sourceArticleUrl.trim()"
              >
                {{ sourceUrlLoading ? "解析中..." : "解析" }}
              </button>
            </div>
          </form>
          <div v-if="sourceUrlSubmitted" class="url-preview-box">
            <strong>文章链接已提交解析</strong>
            <span>{{ sourceArticleUrl }}</span>
          </div>
        </template>
      </section>
    </div>

    <div v-if="articleDetail" class="modal-backdrop">
      <section
        class="modal-dialog article-detail-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="article-detail-title"
      >
        <button class="modal-close" type="button" aria-label="关闭正文" @click="closeArticleDetail">
          ×
        </button>
        <div class="modal-header article-detail-header">
          <div>
            <h2 id="article-detail-title">{{ articleDetail.title }}</h2>
            <p>
              {{ articleDetail.source.name }}
              <span v-if="articleDetail.publish_time"> · {{ formatDateTime(articleDetail.publish_time) }}</span>
              <span v-if="articleDetail.content_fetched_at">
                · 抓取于 {{ formatDateTime(articleDetail.content_fetched_at) }}
              </span>
            </p>
          </div>
          <a
            class="small-button"
            :href="articleDetail.original_url"
            target="_blank"
            rel="noreferrer"
          >
            原文
          </a>
        </div>
        <article v-if="articleDetailHtml" class="article-detail-body" v-html="articleDetailHtml"></article>
        <pre v-else class="article-detail-text">{{ articleDetail.content_plain_text }}</pre>
      </section>
    </div>

    <div v-if="toast" class="toast" :class="toast.kind" role="status">
      {{ toast.message }}
    </div>
  </div>
</template>
