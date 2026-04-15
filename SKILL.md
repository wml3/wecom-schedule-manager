---
name: wecom-schedule-manager
description: 通过企业微信 API 严格管理企业日历、日程、提醒和参会人变更，并记录可审计的用户解析与操作日志。适用于 Codex 或 OpenClaw 需要创建日历、查询日程、获取日程详情、创建/更新/取消日程、增删参会人，或发送企业微信提醒消息，同时要求把租户参数作为运行时变量输入而不是写死在代码里的场景。
---

# 企业微信日程管理 Skill

所有日程相关操作都使用内置命令行工具 `scripts/wecom_schedule_manager.py`。

## 快速流程

1. 从用户输入或 skill 配置中收集运行时变量。
2. 强制通道为 `wecom`。
3. 在写入日程前先解析目标企业微信用户。
4. 优先复用现有 `cal_id`；第一次没有时可以留空，先创建日历，再把返回的 `cal_id` 回填到环境或 skill 配置。
5. 执行目标日程操作。
6. 返回 API 结果和审计日志路径。

在收集参数前先阅读 [configuration.md](./references/configuration.md)。
在选择接口或流程前阅读 [api-scenarios.md](./references/api-scenarios.md)。
在检查合规和日志内容时阅读 [audit-model.md](./references/audit-model.md)。
在为非技术用户或新租户做接入时阅读 [getting-started.md](./references/getting-started.md)。

## 必须遵守的规则

- 不要把租户参数写死在脚本里，统一作为变量输入。
- 仅允许 `wecom` 通道。
- 在创建、更新、取消、参会人变更和提醒发送之前，先做 `resolve-user` 语义的用户解析。
- 用户解析和每一次 API 写操作都要记录到审计日志。
- 日志和说明里不要暴露 `corp_secret` 或 `access_token`。

## 核心命令

命令里的占位值由当前请求或 skill 配置填充。

```bash
python scripts/wecom_schedule_manager.py resolve-user \
  --channel wecom \
  --corp-id "$WECOM_CORP_ID" \
  --corp-secret "$WECOM_CORP_SECRET" \
  --agent-id "$WECOM_AGENT_ID" \
  --user-id "<userid>" \
  --operator-id "<operator_id>" \
  --audit-log-path "<audit_log_path>"
```

```bash
python scripts/wecom_schedule_manager.py create-schedule \
  --channel wecom \
  --corp-id "$WECOM_CORP_ID" \
  --corp-secret "$WECOM_CORP_SECRET" \
  --agent-id "$WECOM_AGENT_ID" \
  --cal-id "$WECOM_CAL_ID" \
  --user-id "<userid>" \
  --start "<YYYY-MM-DD HH:MM:SS>" \
  --end "<YYYY-MM-DD HH:MM:SS>" \
  --summary "<summary>" \
  --description "<description>" \
  --operator-id "<operator_id>" \
  --audit-log-path "<audit_log_path>"
```

```bash
python scripts/wecom_schedule_manager.py send-reminder \
  --channel wecom \
  --corp-id "$WECOM_CORP_ID" \
  --corp-secret "$WECOM_CORP_SECRET" \
  --agent-id "$WECOM_AGENT_ID" \
  --touser "<userid1|userid2>" \
  --content "<reminder_text>" \
  --operator-id "<operator_id>" \
  --audit-log-path "<audit_log_path>"
```

## 决策点

### 还没有 calendar id

先执行 `create-calendar`，或者在能够解析用户的前提下使用 `create-schedule --auto-create-calendar`。
第一次接入时 `wecom_cal_id` 可以为空；创建成功后，要把返回的 `cal_id` 保存并回填到环境变量或 OpenClaw skill 长期配置中。
如果你不希望不同团队、不同机器人或不同用途的日程互相影响，建议为每个使用场景自建独立的 `cal_id`。

### 查询日程

使用 `list-schedules` 配合 `--cal-id`，必要时再用 `--attendee-userid`、`--start`、`--end` 做过滤。

### 部分字段更新

使用 `update-schedule`。脚本会先获取当前日程，再合并你提供的变更，并记录两个步骤的日志。

### 只发送提醒

使用 `send-reminder`，并保持通道为 `wecom`。不要切换到邮件或短信。

## OpenClaw 集成说明

向用户或管理员收集这些长期配置：

1. `wecom_corp_id`
2. `wecom_corp_secret`
3. `wecom_agent_id`
4. `wecom_cal_id`（首次可为空，创建后再补回）
5. `operator_id`
6. `audit_log_path`

每次请求只收集业务相关输入，例如：

1. 用户身份信息
2. 目标操作
3. 时间窗口
4. 标题、描述、地点
5. 可选的参会人 JSON 或 `schedule_id`

优先使用环境变量或 OpenClaw 的密钥变量，不要把敏感值直接放进命令历史。

## 编码安全

- 当请求里包含中文、多行描述或很长的参会人 JSON 时，优先使用 `--request-file` 和 `*-file` 方式，不要直接用命令行参数传长文本。
- `--request-stdin` 也适合 Linux/macOS 的流水线或自动化工具。
- 在 Windows 终端里，命令行里的中文可能在进入 Python 前就被转成 `?`。
- 脚本现在会检测明显乱码，并在发送前直接拦截。

## 期望输出

- CLI 返回结构化 JSON。
- 结果中包含 `audit_log_path`。
- 失败时直接返回企业微信的 `errcode` 和 `errmsg`。
- 有值时返回已解析的 `userid`、`schedule_id` 和 `cal_id`。
