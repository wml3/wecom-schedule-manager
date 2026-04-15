# 快速上手

当你要把这个 skill 接入一个新的企业微信环境，或者准备交给非技术同事使用时，请先阅读本说明。

## 这个 Skill 能做什么

这个 skill 只通过企业微信来管理日程，支持这些场景：

1. 查找企业微信用户并确认正确账号
2. 在没有日历时创建日历
3. 查询日程
4. 创建日程
5. 更新日程
6. 取消日程
7. 通过企业微信应用发送提醒消息

## 使用边界

请特别注意，这个 skill 主要管理的是：

1. 当前企业微信应用自己创建的日历
2. 当前应用创建的日历下的日程

通常不适用于：

1. 其他应用创建的日历或日程
2. 员工在企业微信客户端里手工创建的普通日程
3. 希望“读取整个企业所有日程”的场景

所以，如果你在企业微信里看得到某条日程，但这个 skill 查不到，往往不是脚本故障，而是因为：

1. 那条日程不在当前应用的 `cal_id` 下
2. 那条日程不是通过当前应用接口创建的

## 需要提前准备的信息

在正式使用前，请准备下面这些信息：

1. `CorpID`
2. `AgentID`
3. `Secret`
4. `cal_id`（首次可以为空）
5. 如果企业微信开启了接口来源限制，还需要服务器出口公网 IP
6. 用于审计日志的操作者标识，例如员工姓名、机器人名称或服务名称

## 这些信息怎么获取

### 1. 在企业微信里创建一个应用

进入企业微信管理后台后：

1. 打开“应用管理”
2. 创建“自建应用”
3. 给应用起一个清晰的名字，例如“日程助手”
4. 把应用可见范围配置到需要被管理日程的人员范围

创建完成后，请记下：

1. `AgentID`
2. `Secret`

### 2. 获取企业 CorpID

在企业微信管理后台打开企业信息页面，复制 `CorpID`。

### 3. 准备日历 ID

你有两种方式：

1. 直接使用一个已有的 `cal_id`
2. 先让 skill 自动创建一个日历，再把返回的 `cal_id` 保存下来

如果你现在还没有日历，可以先执行 `create-calendar`。

建议：

1. 第一次接入时，`cal_id` 可以先留空
2. 可以先执行 `create-calendar`，也可以在创建日程时让脚本自动创建
3. 创建成功后，要把返回的 `cal_id` 保存下来，并回填到环境变量、Skill 配置或内部配置文件中
4. 尽量统一使用当前应用创建的专用日历
5. 后续所有通过 skill 管理的日程，都放到这个日历下
6. 如果不希望不同团队、不同同事或不同机器人之间的日程管理互相冲突，建议各自创建并使用独立的 `cal_id`
7. 这样后续查询、更新、取消才不会因为“跨应用/手工创建”而失效

### 4. 配置可信 IP（如果有需要）

如果你们公司启用了 API 来源 IP 限制，就需要把运行脚本的服务器公网 IP 加到应用的可信 IP 列表里。

典型报错是：

- `60020 not allow to access from your ip`

如果你是在云服务器上运行，请向运维或云平台确认这台服务器的公网出口 IP。

### 5. 是否需要配置可信域名

这个 skill 主要调用的是服务端 API。

对当前这些能力来说，通常 **不需要** 配置可信域名：

1. 查询日程
2. 创建日程
3. 更新日程
4. 取消日程
5. 发送提醒消息

只有以后要扩展浏览器页面能力时，才通常会用到可信域名，例如：

1. 网页授权
2. JS-SDK 页面
3. 企业微信内嵌网页应用

## 需要输入到 Skill 的内容

建议把下面这些作为长期配置保存：

1. `WECOM_CORP_ID`
2. `WECOM_CORP_SECRET`
3. `WECOM_AGENT_ID`
4. `WECOM_CAL_ID`
5. `WECOM_AUDIT_LOG_PATH`
6. `operator_id`

每次发起业务请求时，只需要输入当前任务相关的信息：

1. 目标用户身份：`user_id`、`mobile`、`email` 或 `name`
2. 操作类型：查询、创建、更新、取消、提醒
3. 时间范围（如果这个操作需要）
4. 日程标题
5. 日程描述
6. 日程地点
7. 如果是多人会议，还要提供参会人列表，可以直接给 `userid`，也可以给姓名列表

## 按姓名解析的使用说明

现在这个 skill 支持按姓名解析参会人，但有几个前提：

1. 当前企业微信自建应用必须对目标成员具备通讯录可见范围
2. 脚本会在当前应用可见范围内读取部门和成员，再按姓名做本地精确匹配
3. 如果同名成员不止一个，脚本会直接报冲突，不会自动猜人
4. 如果你已经知道 `userid`、手机号或邮箱，仍然优先推荐使用这些更稳定的标识

如果你担心重名，可以补充：

1. `--name-department-id`
2. 或者直接改用 `userid`

## 中文输入的最佳实践

不要把长段中文直接粘贴到终端命令参数里。

推荐使用下面这些方式：

1. `--request-file`
2. `--request-stdin`
3. `--summary-file`
4. `--description-file`
5. `--location-file`
6. `--attendees-file`

这是在 Windows、Linux、macOS 上避免出现 `????` 乱码最稳妥的方式。

## 首次接入建议流程

1. 确认机器上已经安装 Python 3
2. 安装 `requests`
3. 配置 `WECOM_CORP_ID`、`WECOM_CORP_SECRET`、`WECOM_AGENT_ID`
4. 用一个已知员工测试 `resolve-user`
5. 如果还没有日历，先运行 `create-calendar`
6. 把返回的 `cal_id` 回填到 `WECOM_CAL_ID` 或 Skill 长期配置
7. 试创建一条小范围测试日程
8. 打开企业微信确认日程显示正常

## 安装 Python 和 requests

### Windows

1. 安装官方版 Python 3
2. 打开 PowerShell
3. 运行 `py -m pip install requests`

### Linux

1. 确认已经安装 Python 3
2. 运行 `python3 -m pip install requests`

### macOS

1. 确认已经安装 Python 3
2. 运行 `python3 -m pip install requests`

## 最安全的使用方式

建议优先使用 UTF-8 JSON 请求文件，而不是直接在命令行里拼长参数。

下面是一个请求对象示例：

```json
{
  "user_id": "replace-with-organizer-userid",
  "summary": "请替换为会议标题",
  "description": "请替换为会议说明",
  "location": "请替换为会议地点",
  "start": "2026-01-01 09:00:00",
  "end": "2026-01-01 10:00:00",
  "attendee_names_json": [
    "张三",
    "李四"
  ]
}
```

然后通过 `create-schedule` 配合 `--request-file` 调用脚本。

你也可以直接从这些模板开始：

1. `assets/request-templates/create-schedule-request.json`
2. `assets/request-templates/update-schedule-request.json`

## 示例命令

### Windows PowerShell

先设置长期变量：

```powershell
$env:WECOM_CORP_ID="你的CorpID"
$env:WECOM_CORP_SECRET="你的Secret"
$env:WECOM_AGENT_ID="你的AgentID"
$env:WECOM_CAL_ID="你的cal_id"
$env:WECOM_AUDIT_LOG_PATH="logs/wecom_audit.jsonl"
```

解析用户：

```powershell
py .\scripts\wecom_schedule_manager.py resolve-user --channel wecom --user-id your_userid --operator-id assistant
```

按姓名解析用户：

```powershell
py .\scripts\wecom_schedule_manager.py resolve-user --channel wecom --name 张三 --operator-id assistant
```

通过 UTF-8 JSON 文件创建日程：

```powershell
py .\scripts\wecom_schedule_manager.py create-schedule --channel wecom --request-file .\assets\request-templates\create-schedule-request.json --operator-id assistant
```

### Linux 或 macOS

先设置长期变量：

```bash
export WECOM_CORP_ID="你的CorpID"
export WECOM_CORP_SECRET="你的Secret"
export WECOM_AGENT_ID="你的AgentID"
export WECOM_CAL_ID="你的cal_id"
export WECOM_AUDIT_LOG_PATH="logs/wecom_audit.jsonl"
```

解析用户：

```bash
python3 ./scripts/wecom_schedule_manager.py resolve-user --channel wecom --user-id your_userid --operator-id assistant
```

按姓名解析用户：

```bash
python3 ./scripts/wecom_schedule_manager.py resolve-user --channel wecom --name 张三 --operator-id assistant
```

通过 UTF-8 JSON 文件创建日程：

```bash
python3 ./scripts/wecom_schedule_manager.py create-schedule --channel wecom --request-file ./assets/request-templates/create-schedule-request.json --operator-id assistant
```

### 通过标准输入传入 JSON

这个方式很适合自动化系统：

```bash
cat request.json | python3 ./scripts/wecom_schedule_manager.py create-schedule --channel wecom --request-stdin --operator-id assistant
```

## 常见问题

### `60020 not allow to access from your ip`

说明运行脚本的服务器 IP 不在可信 IP 列表里。

### `90457 invalid calendar id`

说明 `cal_id` 为空、无效，或者属于别的企业。

处理建议：

1. 如果你是第一次接入，可以先不要手填 `cal_id`，直接先创建一个日历
2. 确认创建成功后，把返回的 `cal_id` 回填到 `WECOM_CAL_ID`
3. 不要混用别的应用、别的企业，或者其他团队专用的 `cal_id`

### 企业微信里明明有日程，但 skill 查不到

最常见原因是：

1. 那条日程不在当前应用创建的日历下
2. 那条日程是别的应用创建的
3. 那条日程是员工手工创建的普通日程

这属于接口能力边界，不一定是脚本故障。

### `90493 deprecated parameter`

通常说明你在使用旧版脚本。请更新到当前 skill 的最新代码。

### 标题或描述显示成 `????`

说明中文在进入 Python 之前就已经被终端破坏了。请改用 `--request-file` 或 `--request-stdin`。

## 官方参考资料

- 企业微信开发文档入口：`https://developer.work.weixin.qq.com/document`
- 本次对接参考的官方文档示例：`https://developer.work.weixin.qq.com/document/path/93648`
- 创建日历镜像页：`https://qiyeweixin.apifox.cn/api-10061394`
- 创建日程镜像页：`https://apifox.com/apidoc/docs-site/406014/api-10061398`
