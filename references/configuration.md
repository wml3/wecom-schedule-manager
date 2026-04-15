# 配置说明

当你需要向用户收集参数，或把这个 skill 接入 OpenClaw 时，请先阅读本文件。

## 通道限制

本 skill 只允许使用 `wecom` 通道。

- 始终传入 `--channel wecom`
- 如果用户要求通过邮件、短信、钉钉、飞书等其他通道管理日程，应拒绝并说明仅支持企业微信
- 每次操作都要把所选通道记录进审计日志

## 必要运行时参数

这些值可以通过 skill 配置、提示变量、环境变量或 CLI 参数提供。

| 参数 | CLI 参数 | 环境变量 | 是否必填 | 说明 |
| --- | --- | --- | --- | --- |
| 企业 ID | `--corp-id` | `WECOM_CORP_ID` | 是 | 用于获取访问令牌的企业标识 |
| 应用 Secret | `--corp-secret` | `WECOM_CORP_SECRET` | 是 | 调用企业微信 API 的应用密钥 |
| 应用 AgentID | `--agent-id` | `WECOM_AGENT_ID` | 是 | 用于创建日历和发送应用消息提醒的应用标识 |
| 日历 ID | `--cal-id` | `WECOM_CAL_ID` | 视情况而定 | 日程操作使用的日历容器。查询/创建/更新/取消通常都需要；第一次接入时可以先留空，配合 `--auto-create-calendar` 或先执行 `create-calendar` 自动创建，再把返回的 `cal_id` 回填 |
| 操作者标识 | `--operator-id` | 无 | 强烈建议 | 写入审计日志的人或自动化服务标识 |
| 审计日志路径 | `--audit-log-path` | `WECOM_AUDIT_LOG_PATH` | 强烈建议 | 保存可审计事件的 JSONL 文件路径 |

## 用户解析输入

凡是需要“审计可追踪的用户解析”的流程，都应提供一种用户身份输入。

| 使用场景 | CLI 参数 | 说明 |
| --- | --- | --- |
| 已知 userid | `--user-id` | 最直接，也会被记录日志 |
| 通过手机号解析 | `--mobile` | 会调用 `/user/getuserid`，随后调用 `/user/get` |
| 通过邮箱解析 | `--email` | 会调用 `/user/get_userid_by_email`，随后调用 `/user/get` |
| 通过姓名精确解析 | `--name` | 会先读取当前应用可见范围内的通讯录，再做本地精确匹配；重名时会报冲突，不会自动猜测 |

按姓名解析时，还可以补充：

| 参数 | CLI 参数 | 说明 |
| --- | --- | --- |
| 部门范围缩小 | `--name-department-id` | 可选。用于把姓名解析限制在某个部门范围内，减少重名冲突 |

姓名解析的注意事项：

1. 这不是企业微信提供的“按姓名直接换 userid”接口，而是脚本先读取当前应用可见范围内的通讯录，再在本地做精确匹配。
2. 这要求当前自建应用具备通讯录可见范围，并且目标成员在该范围内。
3. 当前只做精确匹配，不做模糊匹配。
4. 如果出现重名，脚本会直接报冲突，要求改用 `userid`、手机号、邮箱，或通过 `--name-department-id` 缩小范围。

## 日程相关输入

| 参数 | CLI 参数 | 何时需要 | 格式 |
| --- | --- | --- | --- |
| 开始时间 | `--start` | 创建或更新时间时 | `YYYY-MM-DD HH:MM:SS`，按北京时间解析 |
| 结束时间 | `--end` | 创建或更新时间时 | `YYYY-MM-DD HH:MM:SS`，按北京时间解析 |
| 标题 | `--summary` | 创建日历或日程时 | 普通文本 |
| 描述 | `--description` | 建议所有写操作都提供 | 普通文本 |
| 地点 | `--location` | 创建或更新时可选 | 普通文本 |
| 参会人 | `--attendees-json` | 创建/更新/增删参会人时 | JSON 列表，例如 `[{"userid":"alice"}]` |
| 参会人姓名 | `--attendee-names-json` | 创建/更新/增删参会人时 | JSON 列表，例如 `["张三","李四"]`，脚本会按姓名精确解析出 userid |
| 日程 ID | `--schedule-id` | 获取/更新/取消/增删参会人时 | 企业微信返回的字符串 |
| 多个日程 ID | `--schedule-ids` | 批量获取时 | 逗号分隔 |
| 提醒配置 | `--reminders-json` | 高级创建/更新场景 | 直接传给企业微信的 JSON 对象 |

如果涉及中文、长描述或较长的参会人 JSON，建议不要直接用命令行参数，而是改用 UTF-8 文件输入：

| 参数 | 文件参数 | 格式 |
| --- | --- | --- |
| 标题 | `--summary-file` | UTF-8 文本文件 |
| 描述 | `--description-file` | UTF-8 文本文件 |
| 地点 | `--location-file` | UTF-8 文本文件 |
| 提醒内容 | `--content-file` | UTF-8 文本文件 |
| 参会人 | `--attendees-file` | UTF-8 JSON 文件 |
| 参会人姓名 | `--attendee-names-file` | UTF-8 JSON 文件 |
| 共享对象 | `--shares-file` | UTF-8 JSON 文件 |
| 可见范围 | `--public-range-file` | UTF-8 JSON 文件 |
| 提醒配置 | `--reminders-file` | UTF-8 JSON 文件 |
| 整体请求 | `--request-file` | 包含多个字段的 UTF-8 JSON 文件 |
| 标准输入请求 | `--request-stdin` | 从标准输入读取 UTF-8 JSON 对象 |

## 日历相关输入

| 参数 | CLI 参数 | 说明 |
| --- | --- | --- |
| 日历管理员 | `--admins` | 逗号分隔的用户 ID |
| 日历共享对象 | `--shares-json` | 描述谁可以访问日历的 JSON 列表 |
| 公开范围 | `--public-range-json` | 可选的公开范围 JSON |
| 颜色 | `--color` | 例如 `#FF3030` |
| 是否设为默认 | `--set-as-default` | `0` 或 `1` |
| 是否公开 | `--is-public` | `0` 或 `1` |
| 是否为企业日历 | `--is-corp-calendar` | `0` 或 `1` |

### `cal_id` 使用建议

1. `WECOM_CAL_ID` 在第一次接入时可以为空，不必一开始就手工准备好。
2. 如果为空，可以先执行 `create-calendar`，或者在创建日程时使用 `--auto-create-calendar`。
3. 脚本创建成功后会返回新的 `cal_id`，请立即把它写回环境变量、OpenClaw 长期变量或内部配置文件。
4. 后续查询、更新、取消时，应始终复用同一个 `cal_id`，否则容易出现“企业微信里看得到，但 skill 查不到”的情况。
5. 如果你不希望不同团队、不同助理、不同业务场景的日程混在一起，建议每个使用主体单独创建自己的 `cal_id`，避免互相干扰。

## 提醒相关输入

`send-reminder` 用于发送单独的企业微信应用消息提醒。

| 参数 | CLI 参数 | 是否必填 | 说明 |
| --- | --- | --- | --- |
| 接收人 | `--touser` | 是，除非已经完成用户解析 | 企业微信接收人字符串，例如 `user1|user2` |
| 提醒内容 | `--content` | 是 | 文本消息内容 |

## 建议给 OpenClaw 配置的长期变量

建议在 skill 层面配置这些长期变量：

1. `wecom_corp_id`：企业 CorpID
2. `wecom_corp_secret`：企业微信应用 Secret
3. `wecom_agent_id`：企业微信应用 AgentID
4. `wecom_cal_id`：日历 ID，首次可以留空，创建后再补回
5. `operator_id`：审计日志中的操作者标识
6. `audit_log_path`：审计日志文件路径

针对每一次请求，只收集任务相关参数：

1. 用户身份：`user_id`、`mobile`、`email` 或 `name`
2. 操作类型：查询、创建、更新、取消、提醒、参会人维护
3. 时间范围：`start`、`end`
4. 日程信息：`summary`、`description`、`location`
5. 可选：参会人 `userid` 列表、参会人姓名列表或 `schedule_id`

## 安全说明

- 不要在日志中记录 `corp_secret` 或 `access_token`
- 审计日志属于敏感操作记录，应妥善保管
- 优先使用环境变量或 OpenClaw 的密钥输入，不要把敏感值直接放在命令历史中

## 编码说明

- 在 Windows 或 PowerShell 环境下，尽量不要把长中文直接放进命令行参数
- 优先使用 `--request-file`、`--request-stdin` 或上面的文本文件参数
- 脚本现在会拦截 `summary`、`description`、`location`、`content` 中明显的乱码，例如连续的 `?`
- 同时支持 UTF-8 和带 BOM 的 UTF-8 文件
