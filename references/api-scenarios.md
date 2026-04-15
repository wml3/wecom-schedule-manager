# API 场景映射

当你需要判断某个用户请求应该调用哪个企业微信接口时，请阅读本文件。

## 覆盖范围

这个 skill 覆盖了企业日程自动化里最常见的企业微信场景：

1. 在操作日程前先解析企业微信用户
2. 当没有可复用 `cal_id` 时创建日历
3. 查询应用自己管理的日历下的日程
4. 获取日程详情
5. 创建日程
6. 更新日程
7. 取消日程
8. 增加或移除参会人
9. 通过企业微信应用发送提醒消息

## 重要限制

这套能力有一个很重要的边界：

1. 主要管理“当前应用自己创建的日历”以及该日历下的日程
2. 不能跨应用管理别的应用创建的日历或日程
3. 对员工在企业微信客户端里手工创建的普通日程，通常不能直接通过这套 API 查询或修改
4. 为了减少互相影响，建议不同团队、不同机器人或不同业务用途使用各自独立的 `cal_id`

因此，如果某条日程在企业微信里肉眼可见，但通过本 skill 查不到，最常见原因是：

1. 这条日程不在当前应用创建的 `cal_id` 下
2. 这条日程是其他应用创建的
3. 这条日程是用户手工创建的，而不是通过当前应用接口创建的

## 接口映射

| 场景 | 接口 | 说明 |
| --- | --- | --- |
| 获取 access token | `GET /cgi-bin/gettoken` | 所有其他调用之前都需要 |
| 通过 userid 解析用户 | `GET /cgi-bin/user/get` | 用于可审计的身份校验 |
| 通过手机号解析用户 | `POST /cgi-bin/user/getuserid` 后接 `GET /cgi-bin/user/get` | 便于在审计日志里保留完整解析链路 |
| 通过邮箱解析用户 | `POST /cgi-bin/user/get_userid_by_email` 后接 `GET /cgi-bin/user/get` | 便于在审计日志里保留完整解析链路 |
| 创建日历 | `POST /cgi-bin/oa/calendar/add` | 当还没有 `cal_id` 时使用 |
| 查询日历下的日程 | `POST /cgi-bin/oa/schedule/get_by_calendar` | 返回目标日历下的应用日程 |
| 获取日程详情 | `POST /cgi-bin/oa/schedule/get` | 在“部分更新”之前先获取现状 |
| 创建日程 | `POST /cgi-bin/oa/schedule/add` | 主要写入流程 |
| 更新日程 | `POST /cgi-bin/oa/schedule/update` | 把现有日程和用户变更合并后更新 |
| 取消日程 | `POST /cgi-bin/oa/schedule/del` | 支持通过 `op_mode`、`op_start_time` 处理重复日程 |
| 增加参会人 | `POST /cgi-bin/oa/schedule/add_attendees` | 适合创建后补充参会人 |
| 移除参会人 | `POST /cgi-bin/oa/schedule/del_attendees` | 适合创建后删减参会人 |
| 发送文本提醒 | `POST /cgi-bin/message/send` | 通过企业微信应用发送提醒，不走邮件/短信 |

## 文档参考

优先参考企业微信官方开发者文档，确认最新字段要求：

- 企业微信开发文档入口：`https://developer.work.weixin.qq.com/document`
- 本次用户提供的官方文档示例：`https://developer.work.weixin.qq.com/document/path/93648`

这些镜像页保留了接口名，通常也标注了官方来源：

- 创建日历：`https://qiyeweixin.apifox.cn/api-10061394`
- 创建日程：`https://apifox.com/apidoc/docs-site/406014/api-10061398`
- 发送应用消息：`https://apifox.com/apidoc/docs-site/406014/api-10061353`
- 增加参会人：`https://apifox.com/apidoc/docs-site/406014/api-10061725`
- 移除参会人：`https://apifox.com/apidoc/docs-site/406014/api-10061726`

如果你要用到这个 skill 里还没覆盖的字段，先回到官方文档确认，再修改脚本。

## 场景建议

### 查询日程

1. 先解析用户
2. 要求提供有效的 `cal_id`
3. 调用 `get_by_calendar`
4. 本地按参会人和时间范围过滤
5. 把用户解析和查询过程写入审计日志

注意：

- `get_by_calendar` 查询到的是“当前应用自己创建的日历”下的日程，不是企业微信里所有日程

### 创建日程

1. 先解析用户
2. 复用已有 `cal_id`，如果第一次没有可以先留空并创建日历
3. 组装参会人列表
4. 创建日程
5. 如果业务要求立即提醒，再调用 `message/send`

注意：

- 推荐始终在本应用创建的日历下创建日程，后续查询、更新、取消才最稳定
- 第一次自动创建出新的 `cal_id` 后，要把它回填到环境变量或 skill 长期配置里，后续持续复用
- 如果担心不同人共用一个日历导致管理冲突，建议按团队或使用主体各自维护独立 `cal_id`

### 更新日程

1. 如果变更涉及组织者或参会人，先解析用户
2. 获取当前日程
3. 把部分更新合并成完整请求体
4. 调用 `update`
5. 把“获取”和“更新”两个动作都写进审计日志

### 取消日程

1. 必须提供 `schedule_id`
2. 如果是重复日程，可按需补充 `op_mode`
3. 调用 `del`
4. 记录取消日志

### 提醒场景

提醒主要有两种方式：

1. 在 `schedule.add` 或 `schedule.update` 里通过 `reminders` 配置日程提醒
2. 通过 `message/send` 发送单独的应用提醒消息

当用户明确要“单独发提醒”时，优先走第二种方式。
