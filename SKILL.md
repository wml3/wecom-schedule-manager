---
name: wecom-schedule-manager
description: 通过企业微信 API 严格管理企业日历、日程、提醒和参会人变更，并记录可审计的用户解析与操作日志。适用于 Codex 或 OpenClaw 需要创建日历、查询日程、获取日程详情、创建/更新/取消日程、按姓名或其他身份字段解析参会人、增删参会人，或发送企业微信提醒消息，同时要求把租户参数作为运行时变量输入而不是写死在代码里的场景。
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

在收集参数前先阅读 [user-manual.md](./references/user-manual.md)。
在选择接口或流程前阅读 [api-scenarios.md](./references/api-scenarios.md)。
在检查合规和日志内容时阅读 [audit-model.md](./references/audit-model.md)。
在为非技术用户或新租户做接入时阅读 [user-manual.md](./references/user-manual.md)。

## 必须遵守的规则

- 不要把租户参数写死在脚本里，统一作为变量输入。
- 仅允许 `wecom` 通道。
- 在创建、更新、取消、参会人变更和提醒发送之前，先做 `resolve-user` 语义的用户解析；需要时可按姓名做精确匹配。
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

如果要把整个团队或部门批量加入参会人，可以直接在创建、更新、增删参会人时使用下面任一组参数：

```bash
python scripts/wecom_schedule_manager.py create-schedule \
  --channel wecom \
  --corp-id "$WECOM_CORP_ID" \
  --corp-secret "$WECOM_CORP_SECRET" \
  --agent-id "$WECOM_AGENT_ID" \
  --cal-id "$WECOM_CAL_ID" \
  --user-id "<organizer_userid>" \
  --start "<YYYY-MM-DD HH:MM:SS>" \
  --end "<YYYY-MM-DD HH:MM:SS>" \
  --summary "<summary>" \
  --attendee-department-name "示例团队"
```

```bash
python scripts/wecom_schedule_manager.py create-schedule \
  --channel wecom \
  --corp-id "$WECOM_CORP_ID" \
  --corp-secret "$WECOM_CORP_SECRET" \
  --agent-id "$WECOM_AGENT_ID" \
  --cal-id "$WECOM_CAL_ID" \
  --user-id "<organizer_userid>" \
  --start "<YYYY-MM-DD HH:MM:SS>" \
  --end "<YYYY-MM-DD HH:MM:SS>" \
  --summary "<summary>" \
  --attendee-department-id "<department_id>" \
  --attendee-direct-only
```

说明：

- `--attendee-department-name` 按部门名称精确匹配；如果重名，改用 `--attendee-department-id`
- 默认会展开子部门成员；如果只要直属成员，追加 `--attendee-direct-only`
- 可以和 `--attendees-json`、`--attendee-names-json` 同时使用，脚本会自动去重合并
- 如果当前请求没有显式 `cal_id`，优先根据当前已解析用户去本地绑定表里读取；创建日程时如果还是没有，就自动创建并绑定一个新的 `cal_id`

如果部门本身是分层组织，例如“一级组织 / 二级团队”，优先使用路径方式做逐层解析：

```bash
python scripts/wecom_schedule_manager.py preview-department-attendees \
  --channel wecom \
  --corp-id "$WECOM_CORP_ID" \
  --corp-secret "$WECOM_CORP_SECRET" \
  --agent-id "$WECOM_AGENT_ID" \
  --attendee-department-path "一级组织/二级团队" \
  --preview-limit 5
```

确认样本成员无误后，再正式创建：

```bash
python scripts/wecom_schedule_manager.py create-schedule \
  --channel wecom \
  --corp-id "$WECOM_CORP_ID" \
  --corp-secret "$WECOM_CORP_SECRET" \
  --agent-id "$WECOM_AGENT_ID" \
  --cal-id "$WECOM_CAL_ID" \
  --user-id "<organizer_userid>" \
  --start "<YYYY-MM-DD HH:MM:SS>" \
  --end "<YYYY-MM-DD HH:MM:SS>" \
  --summary "<summary>" \
  --attendee-department-path "一级组织/二级团队"
```

如果用户给的是更自然的组织短语，例如“创建一个团队沟通日程，添加某个组织下的所有成员”，不要先要求部门 ID。优先让脚本自己遍历组织树：

```bash
python scripts/wecom_schedule_manager.py preview-department-attendees \
  --channel wecom \
  --corp-id "$WECOM_CORP_ID" \
  --corp-secret "$WECOM_CORP_SECRET" \
  --agent-id "$WECOM_AGENT_ID" \
  --attendee-department-query "一级组织二级团队" \
  --preview-limit 5
```

如果返回结果只有一个高置信度组织，就继续直接创建：

```bash
python scripts/wecom_schedule_manager.py create-schedule \
  --channel wecom \
  --corp-id "$WECOM_CORP_ID" \
  --corp-secret "$WECOM_CORP_SECRET" \
  --agent-id "$WECOM_AGENT_ID" \
  --cal-id "$WECOM_CAL_ID" \
  --user-id "<organizer_userid>" \
  --start "<YYYY-MM-DD HH:MM:SS>" \
  --end "<YYYY-MM-DD HH:MM:SS>" \
  --summary "<summary>" \
  --attendee-department-query "一级组织二级团队"
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

对于对话式编排，推荐采用下面这条顺序：

1. 先执行 `prepare-schedule-create`
2. 如果返回 `status=ready`，再执行 `create-schedule`
3. 如果返回 `status=needs_confirmation`，先把候选组织和样本成员给用户确认
4. 日程创建成功后，默认再追问一次“是否需要创建会议？”
5. 只有用户确认后，才执行 `create-meeting`，并优先带上刚创建日程返回的 `schedule_id`
6. 如果这条 `schedule_id` 已经关联过会议，优先返回现有会议关联，不要重复创建第二个会议

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
## Skill Layer Strategy

Use these rules in the skill/orchestration layer even when the script stays generic:

1. If the user did not explicitly provide a title, draft one from the known context first.
2. If the user did not explicitly provide meeting content/description, draft a short usable description first.
3. When returning the drafted title/description, also ask once: "是否需要我进一步拟定更准确的会议主题和会议内容？"
4. Prefer creating the full schedule in one shot after attendee/org resolution succeeds. Do not default to "create first, then add attendees".
5. If org recognition, attendee scope, or title/content is clearly ambiguous, ask for confirmation before creation.
6. Treat schedule and meeting as one-to-one at the conversation level, but schedule is mandatory and meeting is optional.
7. After the schedule is created, ask once: "是否需要基于这个日程继续创建会议？"
8. Only create a meeting when the user explicitly confirms they want one. Otherwise do not create a meeting.
9. When the user confirms meeting creation, prefer reusing the just-created `schedule_id` so the meeting can be linked back to that schedule in logs and local context.

### Drafting Rule

When no explicit title is given, prefer a title using:

1. business object or intent from the user utterance
2. team/department name if available
3. test/official context if present

Examples:

1. `团队沟通日程`
2. `一级组织二级团队沟通日程`

When no explicit description is given, draft a short description containing:

1. target team or attendee scope
2. time or scene if known
3. whether it is a test/verification schedule if applicable

### Meeting Rule

The default conversation sequence should be:

1. prepare schedule
2. create schedule
3. ask whether a meeting should be created
4. create meeting only after an explicit yes
