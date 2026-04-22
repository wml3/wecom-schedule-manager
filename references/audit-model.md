# 审计模型

当你需要实现、检查或排查这个 skill 的审计链路时，请参考本文件。

## 目标

每一次企业微信操作，都应留下最小但可追溯的记录，至少能说明：

1. 是谁发起了这次操作
2. 最终解析到了哪个企业微信身份
3. 调用了哪个 API 路径
4. 影响了哪个业务对象
5. 最终成功还是失败

## 存储格式

脚本把审计记录写入 JSON Lines 文件，每行一条记录。

核心字段如下：

| 字段 | 含义 |
| --- | --- |
| `timestamp` | 操作时间，Asia/Shanghai 时区 ISO 格式 |
| `request_id` | 一次完整流程的关联 ID |
| `channel` | 固定为 `wecom` |
| `operator_id` | 发起操作的人或服务标识 |
| `event_type` | 事件类型，例如 `user.resolve`、`schedule.create` |
| `detail` | 脱敏后的请求摘要和响应摘要 |

## 建议记录的事件

- `token.fetch`
- `user.resolve`
- `user.resolve.detail`
- `user.resolve.session_sender_fallback`
- `calendar.create`
- `schedule.list`
- `schedule.get`
- `schedule.create`
- `schedule.update`
- `schedule.cancel`
- `schedule.add_attendees`
- `schedule.del_attendees`
- `schedule.meeting_context.write`
- `schedule.meeting_context.lookup`
- `schedule.meeting_context.delete`
- `schedule.meeting_link.clear`
- `meeting.create`
- `meeting.cancel`
- `reminder.send`

## 脱敏规则

- 不记录 `corp_secret`
- 不记录 `access_token`
- 保留 `errcode` 和 `errmsg`
- 在有帮助时保留 `userid`、`schedule_id`、`meeting_id`、`cal_id`
- 不在公开文档或示例日志中保留真实姓名、真实企业 ID、真实手机号

## 审查建议

1. 先按 `request_id` 串起整条链路
2. 确认 `channel` 始终为 `wecom`
3. 确认写操作前已经完成用户解析
4. 确认最终 API 响应成功或有明确错误码
5. 如果使用了会话发送人回退，检查 `user.resolve.session_sender_fallback`

## 清理建议

测试完成后建议：

1. 取消测试日程
2. 清理本地 `schedule_id -> meeting_id` 关联文件
3. 保留必要的审计记录或按内部规范归档
