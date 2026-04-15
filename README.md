# 企业微信日程管理 Skill

这是一个面向 Codex / OpenClaw 的企业微信日程管理 Skill，用于通过企业微信开放接口统一管理日历、日程、参会人和提醒消息。

它适合企业内部自动化助手、运营机器人、行政排会、培训通知、团队例会管理等场景。

## 适用范围

本 Skill 仅适用于 **企业微信日程管理场景**，并且仅支持：

- 企业微信用户解析
- 企业微信日历创建
- 企业微信日程查询
- 企业微信日程创建、更新、取消
- 企业微信参会人增删
- 企业微信应用消息提醒
- 审计日志记录

本 Skill **不支持** 邮件、短信、飞书、钉钉或其他通道的日程管理。

## 重要使用限制

在正式使用前，请先明确这几个边界：

- 只能管理“当前企业微信自建应用”自己创建的日历，以及该日历下的日程。
- 不能稳定管理其他应用创建的日历或日程。
- 通常不能直接查询或修改员工在企业微信客户端里手工创建的普通日程。
- 如果企业微信里肉眼看得到某条日程，但这个 Skill 查不到，最常见原因不是脚本故障，而是那条日程不在当前应用的 `cal_id` 下。

## 使用前必须准备的条件

要让这个 Skill 正常工作，必须先准备好企业微信侧配置。

### 1. 创建企业微信自建应用

请在企业微信管理后台中：

1. 进入“应用管理”
2. 创建一个“自建应用”
3. 设置应用名称，例如“日程助手”
4. 把应用可见范围配置到需要被管理的人员范围

创建完成后，需要记录：

- `CorpID`
- `AgentID`
- `Secret`

### 2. 开通并确认相关权限

这个 Skill 要调用企业微信服务端 API，因此对应应用需要具备相关接口能力。实际对接时，至少要确认：

- 应用可以获取 Access Token
- 应用可以读取和解析企业微信用户身份
- 应用可以创建企业日历
- 应用可以创建、更新、取消日程
- 应用可以发送企业微信应用消息

如果你们企业对应用权限做了额外管控，请先让企业微信管理员确认这个自建应用可用。

### 3. 配置可信 IP

如果企业微信应用启用了接口来源 IP 限制，还需要把运行脚本或运行 OpenClaw 的服务器出口公网 IP 加入应用可信 IP 列表。

否则常见报错是：

- `60020 not allow to access from your ip`

### 4. 当前场景通常不需要可信域名

本 Skill 当前主要调用的是服务端 API。

对下面这些能力，通常 **不需要** 配置可信域名：

- 查询日程
- 创建日程
- 更新日程
- 取消日程
- 发送提醒

只有未来要接企业微信网页授权、JS-SDK 或内嵌 H5 页面时，才通常需要再配置可信域名。

## `CAL_ID` 使用要求

`CAL_ID` 是这个 Skill 能否稳定管理日程的关键参数。

请务必注意：

- `CAL_ID` 对应的是企业微信中的一个日历容器。
- 本 Skill 后续查询、更新、取消日程时，会依赖这个 `CAL_ID`。
- 如果你没有现成的 `CAL_ID`，第一次可以留空。
- 第一次留空时，可以先执行创建日历，或在创建日程时让脚本自动创建日历。
- 创建成功后，脚本会返回新的 `cal_id`，你需要把它回填到环境变量、OpenClaw 长期变量或内部配置文件中。
- 后续必须持续复用同一个 `CAL_ID`，否则容易出现“日程看得到，但 Skill 管不到”的情况。

为了避免多人、多团队、多机器人互相冲突，建议：

- 不同团队使用各自独立的 `CAL_ID`
- 不同业务用途使用各自独立的 `CAL_ID`
- 不同自动化机器人使用各自独立的 `CAL_ID`

## 需要配置的变量

建议把下面这些配置成长期变量：

- `WECOM_CORP_ID`
- `WECOM_CORP_SECRET`
- `WECOM_AGENT_ID`
- `WECOM_CAL_ID`
- `WECOM_AUDIT_LOG_PATH`
- `operator_id`

其中：

- `WECOM_CAL_ID` 首次可以为空
- `WECOM_AUDIT_LOG_PATH` 用于保留审计日志
- `operator_id` 用于标记是谁在发起操作，方便审计追踪

## 安装方式

### 方式一：复制到 Skills 仓库

把整个 `wecom-schedule-manager/` 目录复制到目标 Skills 仓库中即可。

### 方式二：直接作为独立仓库使用

如果你是从 GitHub 获取这个项目，可以直接克隆后放入 Skills 目录：

```bash
git clone <your-repo-url>
```

## 运行环境要求

- Python 3
- `requests`

安装依赖：

```bash
python3 -m pip install requests
```

Windows 下可以使用：

```powershell
py -m pip install requests
```

## 快速开始

建议第一次接入按这个顺序操作：

1. 配置 `WECOM_CORP_ID`、`WECOM_CORP_SECRET`、`WECOM_AGENT_ID`
2. 先用一个已知员工测试 `resolve-user`
3. 如果没有 `WECOM_CAL_ID`，先创建日历
4. 把返回的 `cal_id` 保存并回填到 `WECOM_CAL_ID`
5. 再开始创建和管理正式日程

## 中文输入建议

为了避免 Windows、Linux、macOS 终端中的中文乱码，建议优先使用：

- `--request-file`
- `--request-stdin`
- `--summary-file`
- `--description-file`
- `--location-file`
- `--attendees-file`

尽量不要直接把长段中文内容粘贴进命令行参数。

## 目录说明

- `SKILL.md`：Skill 主说明
- `agents/openai.yaml`：Skill 元数据
- `scripts/wecom_schedule_manager.py`：核心脚本
- `references/getting-started.md`：中文上手说明
- `references/configuration.md`：参数和变量说明
- `references/api-scenarios.md`：接口边界和场景映射
- `references/audit-model.md`：审计日志模型说明
- `assets/request-templates/`：请求模板

## 推荐先读哪些文档

如果你是第一次接入，建议按这个顺序看：

1. [快速上手](./references/getting-started.md)
2. [配置说明](./references/configuration.md)
3. [API 场景映射](./references/api-scenarios.md)
4. [审计模型](./references/audit-model.md)

## 适合谁使用

这个 Skill 适合：

- 企业内部自动化平台
- OpenClaw / Codex 技能仓库
- 需要审计留痕的日程管理流程
- 只希望通过企业微信单一通道管理日程的团队

如果你的需求是统一管理邮箱日历、个人手工日程或多平台会议系统，这个 Skill 不适合直接使用。
