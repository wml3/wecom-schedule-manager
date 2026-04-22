# 用户手册

## 1. 这是什么

`wecom-schedule-manager` 是一个面向 Codex / OpenClaw 的企业微信日程管理 Skill。  
它通过企业微信开放接口，帮助你完成这些事情：

- 解析企业微信用户身份
- 创建和管理企业微信日历
- 创建、查询、更新、取消日程
- 按部门或组织批量添加参会人
- 在日程创建后补建会议
- 单独取消会议，或在取消日程时自动取消关联会议
- 记录审计日志

它适合“助理帮你安排日程”这类自动化场景，不是一个通用个人日历工具。

## 2. 适用范围

适合：

- 企业微信自建应用
- 需要留痕和可审计的日程流程
- 需要先识别组织、再一次性创建完整日程的场景

不适合：

- 邮件、短信、飞书、钉钉等非企业微信渠道
- 统一管理多个平台的会议系统
- 管理其他应用或员工手工创建的普通日程

## 3. 安装

运行环境需要：

- Python 3
- `requests`

安装依赖：

```bash
python3 -m pip install requests
```

Windows：

```powershell
py -m pip install requests
```

## 4. 初始化准备

在正式使用前，请先在企业微信后台准备好：

- `CorpID`
- 自建应用 `AgentID`
- 自建应用 `Secret`
- 应用可见范围

如果企业微信启用了来源 IP 限制，还需要把当前机器的公网出口 IP 加入可信 IP 白名单。

常见报错：

- `60020 not allow to access from your ip`

这通常不是代码问题，而是当前出口 IP 没有加白。

## 5. 关键配置

建议长期配置这些环境变量：

- `WECOM_CORP_ID`
- `WECOM_CORP_SECRET`
- `WECOM_AGENT_ID`
- `WECOM_CAL_ID`
- `WECOM_AUDIT_LOG_PATH`
- `WECOM_CALENDAR_BINDINGS_PATH`
- `WECOM_SCHEDULE_MEETING_LINKS_PATH`
- `operator_id`

说明：

- `WECOM_CAL_ID` 首次可以为空
- `WECOM_CALENDAR_BINDINGS_PATH` 用于维护 `userid -> cal_id`
- `WECOM_SCHEDULE_MEETING_LINKS_PATH` 用于维护 `schedule_id -> meeting_id`
- 如果希望不同团队互不干扰，建议为每个团队或机器人维护独立 `WECOM_CAL_ID`

默认本地文件：

- `logs/wecom_audit.jsonl`
- `logs/wecom_calendar_bindings.json`
- `logs/wecom_schedule_meeting_links.json`

## 6. 第一次接入怎么做

推荐按这个顺序初始化：

1. 配置 `WECOM_CORP_ID`、`WECOM_CORP_SECRET`、`WECOM_AGENT_ID`
2. 先用一个已知用户验证 `resolve-user`
3. 如果还没有日历，先创建一个日历
4. 记下返回的 `cal_id`
5. 再开始创建和管理正式日程

### 6.1 配置环境变量

Windows PowerShell：

```powershell
$env:WECOM_CORP_ID="your-corp-id"
$env:WECOM_CORP_SECRET="your-secret"
$env:WECOM_AGENT_ID="your-agent-id"
$env:WECOM_CAL_ID="your-cal-id"
$env:WECOM_AUDIT_LOG_PATH="logs/wecom_audit.jsonl"
```

Linux / macOS：

```bash
export WECOM_CORP_ID="your-corp-id"
export WECOM_CORP_SECRET="your-secret"
export WECOM_AGENT_ID="your-agent-id"
export WECOM_CAL_ID="your-cal-id"
export WECOM_AUDIT_LOG_PATH="logs/wecom_audit.jsonl"
```

### 6.2 验证用户解析

```bash
python scripts/wecom_schedule_manager.py resolve-user \
  --channel wecom \
  --user-id "<userid>" \
  --operator-id assistant
```

按姓名解析：

```bash
python scripts/wecom_schedule_manager.py resolve-user \
  --channel wecom \
  --name "张三" \
  --operator-id assistant
```

### 6.3 首次创建日历

如果当前还没有 `cal_id`，可以先创建日历：

```bash
python scripts/wecom_schedule_manager.py create-calendar \
  --channel wecom \
  --user-id "<userid>" \
  --summary "团队日历" \
  --operator-id assistant
```

## 7. 怎么使用

### 7.1 创建日程

最基本的创建方式：

```bash
python scripts/wecom_schedule_manager.py create-schedule \
  --channel wecom \
  --user-id "<organizer_userid>" \
  --start "2026-04-16 15:00:00" \
  --end "2026-04-16 15:30:00" \
  --summary "团队沟通日程"
```

如果当前请求来自企业微信会话，且没有单独提供组织者，也可以直接传会话发送人，脚本会默认把他识别为组织者：

```bash
python scripts/wecom_schedule_manager.py create-schedule \
  --channel wecom \
  --session-name "会话发送人姓名" \
  --start "2026-04-16 15:00:00" \
  --end "2026-04-16 15:30:00" \
  --summary "团队沟通日程"
```

### 7.2 推荐先做预检查

推荐优先调用：

- `prepare-schedule-create`

它会先做：

- 用户解析
- 组织识别
- 参会人预检查
- `cal_id` 解析

如果组织不够明确，会先返回候选组织供确认，再决定是否正式创建。

### 7.3 批量添加团队成员

按部门名称：

```bash
python scripts/wecom_schedule_manager.py create-schedule \
  --channel wecom \
  --user-id "<organizer_userid>" \
  --start "2026-04-16 15:00:00" \
  --end "2026-04-16 15:30:00" \
  --summary "团队沟通日程" \
  --attendee-department-name "示例团队"
```

按组织路径预览：

```bash
python scripts/wecom_schedule_manager.py preview-department-attendees \
  --channel wecom \
  --attendee-department-path "一级组织/二级团队" \
  --preview-limit 5
```

按自然语言组织短语预览：

```bash
python scripts/wecom_schedule_manager.py preview-department-attendees \
  --channel wecom \
  --attendee-department-query "一级组织二级团队" \
  --preview-limit 5
```

### 7.4 更新、取消和维护参会人

支持这些动作：

- `update-schedule`
- `cancel-schedule`
- `cancel-meeting`
- `add-attendees`
- `del-attendees`

这些动作都基于 `schedule_id` 执行。

### 7.5 会议补建

默认策略是：

1. 先创建日程
2. 创建成功后询问用户是否需要创建会议
3. 用户确认后，再调用 `create-meeting`
4. 优先复用刚创建日程返回的 `schedule_id`

示例：

```bash
python scripts/wecom_schedule_manager.py create-meeting \
  --channel wecom \
  --schedule-id "<just_created_schedule_id>" \
  --user-id "<organizer_userid>"
```

说明：

- 如果该 `schedule_id` 已经关联过会议，脚本会直接返回已有会议关联
- 这样可以避免同一条日程重复建会
- 会议开始时间建议使用未来时间；如果传入过去时间，企业微信通常会返回 `invalid meeting_start`
- 这个 skill 已经内置企业微信会议创建能力，不需要再切换到其他会议 skill

### 7.6 取消会议和联动清理

如果只是单独取消会议，可以直接执行：

```bash
python scripts/wecom_schedule_manager.py cancel-meeting \
  --channel wecom \
  --meeting-id "<meeting_id>"
```

如果会议是通过本 skill 基于某条日程创建的，也可以直接按 `schedule_id` 取消：

```bash
python scripts/wecom_schedule_manager.py cancel-meeting \
  --channel wecom \
  --schedule-id "<schedule_id>"
```

如果你要删除一条已经关联会议的日程，建议直接执行 `cancel-schedule`。  
脚本会先取消关联会议，再取消日程，并清理本地 `schedule_id -> meeting_id` 关联。

## 8. 两个自动绑定能力

### 8.1 用户级 `cal_id` 自动绑定

支持“用户首次使用时自动建日历，后续自动复用”的模式：

1. 先解析用户身份
2. 查本地 `userid -> cal_id` 绑定
3. 如果不存在，则在创建日程时自动创建日历
4. 写回绑定文件

### 8.2 日程与会议关联绑定

支持“先创建日程，再确认创建会议”的闭环：

1. 创建日程时记录 `schedule_id`
2. 创建会议时优先复用这条 `schedule_id`
3. 写回 `schedule_id -> meeting_id`
4. 后续再次触发时可识别是否已经建过会
5. 取消日程时会同步清理本地关联上下文

## 9. 中文输入建议

为了避免终端乱码，建议优先使用：

- `--request-file`
- `--request-stdin`
- `--summary-file`
- `--description-file`
- `--location-file`
- `--attendees-file`

推荐直接复用这些模板：

- `assets/request-templates/create-schedule-request.json`
- `assets/request-templates/create-schedule-request-path.json`
- `assets/request-templates/create-schedule-request-department.json`
- `assets/request-templates/prepare-schedule-create-request.json`
- `assets/request-templates/create-meeting-request.json`
- `assets/request-templates/cancel-meeting-request.json`

## 10. FAQ

### 10.1 `60020 not allow to access from your ip`

原因：当前出口 IP 不在企业微信可信 IP 白名单中。

### 10.2 `90457 invalid calendar id`

常见原因：

- `cal_id` 为空
- `cal_id` 无效
- `cal_id` 属于别的企业或别的应用

### 10.3 企业微信里能看到日程，但 skill 查不到

通常是因为：

- 该日程不在当前应用的日历下
- 该日程不是由当前应用创建

### 10.4 姓名解析失败或重名

这是预期限制，不是脚本异常。  
更稳妥的方式是直接使用：

- `userid`
- 手机号
- 邮箱

如果必须按姓名解析，建议配合 `--name-department-id` 缩小范围。

### 10.5 标题或描述出现乱码

优先改用 UTF-8 文件输入，不要直接在终端里拼接长中文参数。

### 10.6 为什么取消日程后还要清理本地关联

因为脚本会本地维护 `schedule_id -> meeting_id` 关系，方便后续补建会议时避免重复创建。  
现在执行 `cancel-schedule` 时，脚本会自动移除对应的本地上下文，减少测试数据残留。

### 10.7 为什么不要切到别的会议 skill

因为这个 skill 已经内置企业微信会议创建和取消能力，而且会维护本地 `schedule_id -> meeting_id` 关联。  
如果切到别的会议 skill，通常拿不到这层本地上下文，也无法保证和企业微信日程保持一致。
