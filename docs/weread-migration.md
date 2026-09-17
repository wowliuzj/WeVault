# 微信读书双通道迁移方案

日期：2026-09-17

## 目标

保留现有微信公众号通道，新增微信读书备用通道。新增字段均允许为空，旧来源、旧文章和旧链接无需一次性改写。

## 数据库变化

迁移 `20260917_0014_add_weread_integration.py` 将：

- 新增 `weread_sessions`：每个用户一条加密授权记录；
- 新增 `weread_login_sessions`：保存扫码过程；
- `wechat_sources` 新增 `weread_book_id`、`weread_matched_at`；
- `articles` 新增 `weread_review_id`、`weread_original_id`；
- 增加用户内 `bookId` 唯一约束，以及用户内 `reviewId` 唯一约束。

迁移不修改已有 `fakeid`、`biz`、`appmsgid`、文章 URL 或正文。

## 上线顺序

1. 备份 PostgreSQL 数据库；
2. 确认生产 `SECRET_KEY` 已固定，升级后不要更换，否则已保存的微信读书凭据无法解密；
3. 停止 worker，避免代码与数据库结构短暂不一致；
4. 在后端容器/虚拟环境安装新依赖；
5. 执行 `alembic upgrade head`；
6. 发布后端和前端；
7. 启动 API、worker，并检查健康接口和 worker 日志；
8. 先用测试用户完成微信读书扫码，再对单个来源绑定 `bookId` 并测试最近 30 天列表和少量正文。

示例命令（按生产部署方式调整）：

```bash
cd backend
pip install -e .
alembic current
alembic upgrade head
alembic current
```

## 数据补充策略

不执行全表批量更新：

1. 用户完成微信读书授权后，按需为缺少 `bookId` 的来源做匹配；
2. 自动搜索接口当前不能保证返回公众号，因此保留人工绑定接口：
   - `POST /api/v1/sources/from-weread`：用名称和 `book_id` 新建来源；
   - `PATCH /api/v1/sources/{source_id}/weread-binding`：为旧来源补 `book_id`；
3. 来源通过微信读书同步列表时，按 `appmsgid + itemidx` 匹配已有文章并补 `reviewId`；
4. 已抓取正文的旧文章无需补 `reviewId`；尚未抓取正文的文章在后续列表同步中逐步补齐。

## 回滚

优先回滚应用代码但保留新增 nullable 字段和表，旧版本不会读取它们。确认不再需要微信读书数据后才执行：

```bash
cd backend
alembic downgrade 20260622_0013
```

降级会删除微信读书授权、`bookId` 和 `reviewId` 数据，执行前必须备份。

## 验收清单

- 旧微信公众号授权、来源搜索和列表同步不受影响；
- 微信读书扫码、刷新、退出可用；
- 有 `fakeid` 且公众号授权有效时优先旧通道；
- 旧列表失败或无 `fakeid` 时，有 `bookId` 可走微信读书；
- 微信读书列表能为历史文章补 `reviewId`；
- 正文旧通道失败后，有 `reviewId` 可走微信读书；
- 仅微信读书通道可用的来源仍可自动调度；
- 微信读书原始大 HTML 不写入 `article_contents.raw_html`。
