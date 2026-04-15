# 审计模型

当你需要实现或检查 skill 的审计要求时，请阅读本文件。

## 目标

每一次企业微信操作，都应留下最小但可追溯的记录，至少能说明：

1. 是谁发起了这次操作
2. 解析出来的是哪个企业微信身份
3. 调用了哪个 API 路径
4. 影响了哪个业务对象
5. 最终是成功还是失败

## 存储格式

脚本会把审计记录写入指定的 JSON Lines 文件。

每一行包含这些字段：

| 字段 | 含义 |
| --- | --- |
| `timestamp` | 操作时间，Asia/Shanghai 时区的 ISO 格式 |
| `request_id` | 一次完整流程的关联 ID |
| `channel` | 固定为 `wecom` |
| `operator_id` | 发起操作的人或服务标识 |
| `event_type` | 事件类型，例如 `user.resolve` 或 `schedule.create` |
| `detail` | 脱敏后的请求和响应摘要 |

## 必须记录的审计事件

- `token.fetch`
- `user.resolve`
- `user.resolve.detail`
- `calendar.create`
- `schedule.list`
- `schedule.get`
- `schedule.create`
- `schedule.update`
- `schedule.cancel`
- `schedule.add_attendees`
- `schedule.del_attendees`
- `reminder.send`

## 脱敏规则

- 不记录 `corp_secret`
- 不记录 `access_token`
- 保留返回的 `errcode` 和 `errmsg`
- 在有帮助时保留 `schedule_id`、`cal_id`、解析出的 `userid` 和目标身份信息

## 建议的审查方式

1. 按 `request_id` 聚合整条流程
2. 确认 `channel` 一直是 `wecom`
3. 确认在写入日程之前已经完成用户解析
4. 确认最终 API 响应成功
5. 如果“解析出的身份”和“最终目标接收人”明显不一致，应升级处理
