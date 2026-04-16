# User Manual

## 1. 概述

`wecom-schedule-manager` 用于通过企业微信开放接口管理企业微信自建应用下的日历和日程，支持：

- 解析企业微信用户
- 创建日历
- 查询、创建、更新、取消日程
- 批量解析和维护参会人
- 创建后补建会议
- 记录审计日志

它更适合“对话式助理”或“自动化流程”场景，而不是通用个人日历工具。

## 2. 安装要求

需要：

- Python 3
- `requests`
- 可访问企业微信开放接口的网络环境

安装依赖：

```bash
python3 -m pip install requests
```

Windows：

```powershell
py -m pip install requests
```

## 3. 接入前准备

在企业微信管理后台准备：

- `CorpID`
- 自建应用 `AgentID`
- 自建应用 `Secret`
- 应用可见范围
- 如启用了来源 IP 限制，还需要当前执行环境的出口 IP

常见报错：

- `60020 not allow to access from your ip`

这说明当前出口 IP 不在可信 IP 白名单中。

## 4. 关键配置

建议长期配置这些变量：

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

默认本地文件：

- `logs/wecom_audit.jsonl`
- `logs/wecom_calendar_bindings.json`
- `logs/wecom_schedule_meeting_links.json`

## 5. 使用边界

这个 skill 主要管理：

- 当前企业微信自建应用创建的日历
- 当前应用创建的日历下的日程

通常不适合：

- 读取企业内所有历史日程
- 管理其他应用创建的日程
- 管理员工在客户端手工创建的普通日程

## 6. 快速开始

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

创建后请保存返回的 `cal_id`。

## 7. 日程使用细节

### 7.1 创建日程

```bash
python scripts/wecom_schedule_manager.py create-schedule \
  --channel wecom \
  --user-id "<organizer_userid>" \
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

如果组织不够明确，会先返回候选组织供确认。

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

按组织路径：

```bash
python scripts/wecom_schedule_manager.py preview-department-attendees \
  --channel wecom \
  --attendee-department-path "一级组织/二级团队" \
  --preview-limit 5
```

按自然语言短语：

```bash
python scripts/wecom_schedule_manager.py preview-department-attendees \
  --channel wecom \
  --attendee-department-query "一级组织二级团队" \
  --preview-limit 5
```

### 7.4 更新、取消、维护参会人

支持：

- `update-schedule`
- `cancel-schedule`
- `add-attendees`
- `del-attendees`

这些动作都基于 `schedule_id` 执行。

## 8. 会议补建流程

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

- 如果 `schedule_id` 已经关联过会议，脚本会直接返回已有会议关联
- 这样可以避免同一条日程重复建会

## 9. 用户级 `cal_id` 自动绑定

支持“用户首次使用时自动建日历，后续自动复用”的模式：

1. 先解析用户身份
2. 查本地 `userid -> cal_id` 绑定
3. 若不存在，则在创建日程时自动创建日历
4. 写回绑定文件

这适合“不同用户使用不同日历容器”的场景。

## 10. 中文输入建议

为了避免终端乱码，建议优先使用：

- `--request-file`
- `--request-stdin`
- `--summary-file`
- `--description-file`
- `--location-file`
- `--attendees-file`

推荐直接复用模板：

- `assets/request-templates/create-schedule-request.json`
- `assets/request-templates/create-schedule-request-path.json`
- `assets/request-templates/create-schedule-request-department.json`
- `assets/request-templates/prepare-schedule-create-request.json`
- `assets/request-templates/create-meeting-request.json`

## 11. 常见问题

### 11.1 `60020 not allow to access from your ip`

原因：当前出口 IP 不在企业微信可信 IP 白名单中。

### 11.2 `90457 invalid calendar id`

原因通常是：

- `cal_id` 为空
- `cal_id` 无效
- `cal_id` 属于别的企业或别的应用

### 11.3 企业微信里能看到日程，但 skill 查不到

通常是因为：

- 该日程不在当前应用的日历下
- 该日程不是由当前应用创建

### 11.4 标题或描述出现乱码

优先改用 UTF-8 文件输入，不要直接在终端里拼长中文参数。

## 12. 补充文档

- [配置说明](./configuration.md)
- [快速接入](./getting-started.md)
- [API 场景映射](./api-scenarios.md)
- [审计模型](./audit-model.md)
