# 企业微信日程管理 Skill

一个面向 Codex / OpenClaw 的企业微信日程管理 Skill。

用于通过企业微信开放接口处理这些事情：

- 解析企业微信用户
- 创建企业日历
- 查询、创建、更新、取消日程
- 增删参会人
- 发送企业微信应用提醒
- 记录审计日志

## 适用范围

本 Skill **仅适用于企业微信日程管理场景**。

支持：

- 企业微信通道
- 企业微信自建应用
- 当前应用创建的日历和日程
- 按姓名精确解析参会人

不支持：

- 邮件、短信、飞书、钉钉等其他通道
- 统一管理所有平台会议系统
- 稳定管理员工手工创建的普通日程
- 稳定管理其他应用创建的日历或日程

## 使用限制

- 这个 Skill 主要管理“当前自建应用自己创建的日历”和该日历下的日程。
- 如果企业微信里能看到某条日程，但 Skill 查不到，通常不是脚本故障，而是这条日程不在当前应用的 `CAL_ID` 下。
- 后续查询、更新、取消日程时，会持续依赖同一个 `CAL_ID`。
- 按姓名解析依赖当前自建应用的通讯录可见范围。
- 按姓名解析只做精确匹配；重名时会报冲突，不会自动猜测。

## 使用前必须准备

### 1. 创建企业微信自建应用

请在企业微信管理后台：

1. 进入“应用管理”
2. 创建“自建应用”
3. 配置应用可见范围
4. 记录以下信息：

- `CorpID`
- `AgentID`
- `Secret`

### 2. 确认应用权限可用

至少要能支持这些能力：

- 获取 Access Token
- 解析企业微信用户
- 读取当前应用可见范围内的通讯录成员
- 创建企业日历
- 创建、更新、取消日程
- 发送企业微信应用消息

### 3. 配置可信 IP

如果企业微信启用了来源 IP 限制，需要把运行脚本或 OpenClaw 的服务器公网出口 IP 加入可信 IP。

常见报错：

- `60020 not allow to access from your ip`

### 4. 当前通常不需要可信域名

这个 Skill 目前主要走服务端 API。

对于查询日程、创建日程、更新日程、取消日程、发送提醒这些能力，通常 **不需要** 配置可信域名。

## `CAL_ID` 规则

- `CAL_ID` 对应企业微信里的一个日历容器。
- 第一次接入时，`WECOM_CAL_ID` 可以为空。
- 如果为空，可以先创建日历，或在创建日程时自动创建日历。
- 创建成功后，必须把返回的 `cal_id` 回填到环境变量或 Skill 配置里。
- 后续要持续复用同一个 `CAL_ID`。

为了避免冲突，建议：

- 不同团队使用独立 `CAL_ID`
- 不同机器人使用独立 `CAL_ID`
- 不同业务用途使用独立 `CAL_ID`

## 需要配置的变量

- `WECOM_CORP_ID`
- `WECOM_CORP_SECRET`
- `WECOM_AGENT_ID`
- `WECOM_CAL_ID`
- `WECOM_AUDIT_LOG_PATH`
- `operator_id`

说明：

- `WECOM_CAL_ID` 首次可以为空
- `WECOM_AUDIT_LOG_PATH` 用于保留审计日志
- `operator_id` 用于记录操作者身份
- 如果要按姓名解析参会人，建议额外准备可选的 `WECOM_NAME_DEPARTMENT_ID`，用于缩小姓名解析范围

## 3 分钟接入

1. 安装 Python 3 和 `requests`
2. 配置 `WECOM_CORP_ID`、`WECOM_CORP_SECRET`、`WECOM_AGENT_ID`
3. 先执行一次 `resolve-user` 验证用户解析
4. 如果没有 `WECOM_CAL_ID`，先创建日历
5. 把返回的 `cal_id` 回填到 `WECOM_CAL_ID`
6. 如果要按姓名排会，再验证一次姓名解析是否能覆盖目标成员
7. 再开始创建和管理正式日程

安装依赖：

```bash
python3 -m pip install requests
```

Windows：

```powershell
py -m pip install requests
```

## 中文输入建议

为了避免终端乱码，建议优先使用：

- `--request-file`
- `--request-stdin`
- `--summary-file`
- `--description-file`
- `--location-file`
- `--attendees-file`

## 文档入口

- [SKILL.md](./SKILL.md)
- [快速上手](./references/getting-started.md)
- [配置说明](./references/configuration.md)
- [API 场景映射](./references/api-scenarios.md)
- [审计模型](./references/audit-model.md)

## 发布版本

仓库内已经内置了一个 UTF-8 安全的 GitHub 发版脚本，用来避免中文 release note 在 Windows / PowerShell 下乱码。

发布前准备：

- 配置环境变量 `GITHUB_TOKEN`
- 在 `assets/release-notes/` 下准备一个 UTF-8 编码的 release note 文件

推荐命令：

```bash
python scripts/publish_github_release.py --version v1.0.2 --notes-file assets/release-notes/release-note-template.md
```

这个脚本会自动处理：

- 失效代理环境变量清理
- 推送目标分支
- 创建或更新 tag
- 创建或更新 GitHub Release
- 以 UTF-8 正确写入中文 release note

## 适合谁使用

适合：

- 企业内部自动化平台
- OpenClaw / Codex 技能仓库
- 需要审计留痕的日程流程
- 只希望通过企业微信单一通道管理日程的团队

如果你的目标是统一管理邮箱日历、个人手工日程或多平台会议系统，这个 Skill 不适合直接使用。
