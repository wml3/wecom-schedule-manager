# API 场景映射

当你需要判断某个用户请求应该调用哪一组企业微信接口时，请优先参考这份文档。

## 覆盖范围

这个 skill 主要覆盖以下企业微信场景：

1. 解析企业微信用户身份
2. 首次创建并绑定应用日历
3. 查询当前应用管理的日历和日程
4. 创建、更新、取消日程
5. 批量增删参会人
6. 创建会议并与 `schedule_id` 建立关联
7. 发送应用提醒消息

## 重要限制

这套能力有几个明确边界：

1. 只能稳定管理“当前应用创建或已绑定的 `cal_id`”下的日程
2. 不能替代企业微信客户端去统一管理员工手工创建的所有个人日程
3. 不能跨应用管理其他应用创建的日历和日程
4. 会议创建依赖未来时间；过去时间会返回 `invalid meeting_start`

如果企业微信里肉眼能看到某条日程，但 skill 查不到，最常见原因是：

1. 这条日程不在当前应用绑定的 `cal_id` 下
2. 这条日程是其他应用创建的
3. 这条日程是用户手工创建的，不属于当前应用管理范围

## 接口映射

| 场景 | 接口 | 说明 |
| --- | --- | --- |
| 获取 access token | `GET /cgi-bin/gettoken` | 所有其他调用前都需要 |
| 通过 userid 解析用户 | `GET /cgi-bin/user/get` | 最稳定的身份解析方式 |
| 通过手机号解析用户 | `POST /cgi-bin/user/getuserid` + `GET /cgi-bin/user/get` | 适合从会话或表单拿到手机号时使用 |
| 通过邮箱解析用户 | `POST /cgi-bin/user/get_userid_by_email` + `GET /cgi-bin/user/get` | 适合企业邮箱场景 |
| 通过姓名解析用户 | `GET /cgi-bin/department/list` + `GET /cgi-bin/user/simplelist` + `GET /cgi-bin/user/get` | skill 在本地补齐的姓名精确匹配能力 |
| 创建日历 | `POST /cgi-bin/oa/calendar/add` | 首次没有 `cal_id` 时使用 |
| 查询日历下的日程 | `POST /cgi-bin/oa/schedule/get_by_calendar` | 查询当前应用日历下的日程 |
| 获取日程详情 | `POST /cgi-bin/oa/schedule/get` | 更新前建议先读现状 |
| 创建日程 | `POST /cgi-bin/oa/schedule/add` | 核心写入接口 |
| 更新日程 | `POST /cgi-bin/oa/schedule/update` | 合并新旧字段后写回 |
| 取消日程 | `POST /cgi-bin/oa/schedule/del` | 支持处理重复日程参数 |
| 增加参会人 | `POST /cgi-bin/oa/schedule/add_attendees` | 创建后补参会人 |
| 移除参会人 | `POST /cgi-bin/oa/schedule/del_attendees` | 创建后删参会人 |
| 创建会议 | `POST /cgi-bin/meeting/create` | 会议开始时间必须有效且通常为未来时间 |
| 发送应用提醒 | `POST /cgi-bin/message/send` | 通过企业微信应用发提醒，不走邮件或短信 |

## 场景建议

### 创建日程

推荐顺序：

1. 解析组织者身份
2. 解析组织或参会人范围
3. 确认 `cal_id`
4. 创建日程
5. 如有需要，再单独创建会议

### 按姓名解析参会人

推荐顺序：

1. 枚举当前应用可见部门
2. 遍历成员列表
3. 在本地做姓名精确匹配
4. 结果唯一时返回 `userid`
5. 结果为空或重名时要求用户补充范围

说明：

- 这不是企业微信原生“按姓名查 userid”接口，而是 skill 在本地补上的解析能力
- 前提是当前自建应用对通讯录有可见范围

### 会议补建

推荐顺序：

1. 先创建日程
2. 把 `schedule_id` 本地持久化
3. 用户确认需要会议后，再执行 `create-meeting`
4. 成功后写回 `schedule_id -> meeting_id`

### 清理测试数据

推荐顺序：

1. 使用 `cancel-schedule` 取消测试日程
2. 本地自动清理对应的 `schedule_id` 关联上下文
3. 如企业内部还保留了独立会议记录，再按内部管理方式进一步处理
