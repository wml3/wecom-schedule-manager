---
name: wecom-schedule-manager
description: 通过企业微信 API 管理企业日历、日程、会议和提醒，先解析用户身份，再执行可审计的日程操作。适用于 Codex 或 OpenClaw 需要创建、查询、更新、取消日程，按姓名或组织批量解析参会人，并在创建后补建会议的场景。
---

# 企业微信日程管理 Skill

所有日程相关操作都通过 `scripts/wecom_schedule_manager.py` 执行。

## 快速流程

1. 收集运行时参数和企业微信配置。
2. 强制通道为 `wecom`。
3. 先解析组织者身份；如果缺少组织者，可回退到企业微信会话发送人。
4. 优先复用已有 `cal_id`；首次可留空，由脚本自动创建并本地绑定。
5. 正式执行日程、会议或提醒操作。
6. 返回结构化 JSON 结果和审计日志路径。

开始前建议先阅读：

- [用户手册](./references/user-manual.md)
- [API 场景映射](./references/api-scenarios.md)
- [审计模型](./references/audit-model.md)

## 必须遵守的规则

- 仅允许使用 `wecom` 通道。
- 不要把 `CorpSecret`、`access_token` 等敏感信息写死在脚本或模板里。
- 写操作前优先完成用户解析；允许按 `userid`、手机号、邮箱、姓名解析。
- 所有用户解析、日程写入、会议创建、提醒发送都必须写入审计日志。
- 只管理“当前应用有权限访问的企业微信日历和日程”，不要承诺跨应用或跨来源统一管理。

## 推荐编排顺序

1. 先执行 `prepare-schedule-create`。
2. 如果返回 `status=ready`，再执行 `create-schedule`。
3. 如果返回 `status=needs_confirmation`，先让用户确认组织或参会范围。
4. 日程创建成功后，再询问是否需要创建会议。
5. 只有用户明确确认后，才执行 `create-meeting`。
6. 创建会议时优先复用刚创建日程的 `schedule_id`。

## 决策提示

### 缺少 `cal_id`

- 首次接入时可以留空。
- 脚本会在创建日程时自动建日历，并把新的 `cal_id` 写入本地绑定文件。
- 为避免不同团队互相干扰，建议每个团队或机器人维护独立 `cal_id`。

### 按姓名解析参会人

- Skill 已支持按姓名解析。
- 如果出现重名，应该缩小部门范围，或改用 `userid`、手机号、邮箱。

### 会议创建

- `create-meeting` 应基于未来时间的日程执行。
- 同一条 `schedule_id` 已有会议关联时，优先复用已有会议，不重复建会。

## 期望输出

- 返回结构化 JSON。
- 包含 `audit_log_path`。
- 成功时尽量返回已解析的 `userid`、`cal_id`、`schedule_id`、`meeting_id`。
- 失败时直接保留企业微信的 `errcode` 和 `errmsg`。
