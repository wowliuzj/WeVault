const viewMeta = {
  dashboard: {
    title: "概览",
    subtitle: "查看授权、采集、文章和导出状态。",
  },
  auth: {
    title: "授权状态",
    subtitle: "管理当前用户绑定的微信公众号登录态。",
  },
  sources: {
    title: "公众号源",
    subtitle: "添加公众号后先同步文章列表，再按策略抓正文和评论。",
  },
  articles: {
    title: "文章库",
    subtitle: "统一管理文章列表、正文状态、评论状态和导出操作。",
  },
  tasks: {
    title: "采集任务",
    subtitle: "跟踪列表同步、正文抓取、评论抓取和导出任务。",
  },
  exports: {
    title: "导出中心",
    subtitle: "生成保留文本的 PDF、DOCX 和 Markdown 文件。",
  },
  settings: {
    title: "设置",
    subtitle: "配置默认采集策略和导出偏好。",
  },
};

const titleEl = document.querySelector("#view-title");
const subtitleEl = document.querySelector("#view-subtitle");
const appShell = document.querySelector("#app-shell");
const sidebarToggle = document.querySelector("#sidebar-toggle");
const mobileMenuButton = document.querySelector("#mobile-menu-button");
const userButton = document.querySelector("#user-button");
const userMenu = document.querySelector("#user-menu");
const navItems = document.querySelectorAll(".nav-item");
const views = document.querySelectorAll(".view");

function setView(viewId) {
  navItems.forEach((item) => {
    item.classList.toggle("active", item.dataset.view === viewId);
  });

  views.forEach((view) => {
    view.classList.toggle("active", view.id === viewId);
  });

  titleEl.textContent = viewMeta[viewId].title;
  subtitleEl.textContent = viewMeta[viewId].subtitle;

  appShell.classList.remove("mobile-menu-open");
  mobileMenuButton.setAttribute("aria-expanded", "false");
}

navItems.forEach((item) => {
  item.addEventListener("click", () => {
    setView(item.dataset.view);
  });
});

sidebarToggle.addEventListener("click", () => {
  const isCollapsed = appShell.classList.toggle("sidebar-collapsed");
  sidebarToggle.setAttribute("aria-expanded", String(!isCollapsed));
  sidebarToggle.setAttribute("aria-label", isCollapsed ? "展开侧边栏" : "收起侧边栏");
  sidebarToggle.textContent = isCollapsed ? "›" : "‹";
});

mobileMenuButton.addEventListener("click", () => {
  const isOpen = appShell.classList.toggle("mobile-menu-open");
  mobileMenuButton.setAttribute("aria-expanded", String(isOpen));
  mobileMenuButton.setAttribute("aria-label", isOpen ? "收起菜单" : "展开菜单");
});

userButton.addEventListener("click", (event) => {
  event.stopPropagation();
  const isOpen = userMenu.classList.toggle("open");
  userButton.classList.toggle("active", isOpen);
  userButton.setAttribute("aria-expanded", String(isOpen));
});

document.addEventListener("click", () => {
  userMenu.classList.remove("open");
  userButton.classList.remove("active");
  userButton.setAttribute("aria-expanded", "false");
});
