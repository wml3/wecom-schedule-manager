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

## 用户级 CAL_ID 自动绑定

现在不一定需要手工维护全局 `WECOM_CAL_ID`。

推荐流程：

- 用户先通过 `userid`、手机号、邮箱或姓名解析出稳定身份
- 脚本优先读取本地绑定文件 `logs/wecom_calendar_bindings.json`
- 如果这个用户已经绑定过 `cal_id`，后续直接复用
- 如果是首次使用且当前在创建日程，脚本会自动创建一个新日历，并把 `userid -> cal_id` 写回绑定文件

这更适合真实业务场景里的“用户 A 来对话，就自动用 A 自己的日历容器”。

## 中文输入建议

为了避免终端乱码，建议优先使用：

- `--request-file`
- `--request-stdin`
- `--summary-file`
- `--description-file`
- `--location-file`
- `--attendees-file`

## 团队/部门批量加人

如果你的目标是“创建一个团队沟通日程，并把某个组织下的所有成员都加进去”，优先把这个团队作为企业微信部门处理，然后直接用部门参数批量展开成员：

```bash
python scripts/wecom_schedule_manager.py create-schedule \
  --channel wecom \
  --user-id "<organizer_userid>" \
  --start "2026-04-16 15:00:00" \
  --end "2026-04-16 15:30:00" \
  --summary "团队沟通日程" \
  --attendee-department-name "示例团队"
```

补充说明：

- 默认会展开子部门成员
- 如果只需要直属成员，追加 `--attendee-direct-only`
- 如果部门名称可能重名，改用 `--attendee-department-id`
- 这组参数同样适用于 `update-schedule`、`add-attendees`、`del-attendees`
- 可直接参考模板：`assets/request-templates/create-schedule-request-department.json`

如果组织是分层的，比如“一级组织”是上层，“二级团队”是下层，建议改用路径解析并先做预览确认：

```bash
python scripts/wecom_schedule_manager.py preview-department-attendees \
  --channel wecom \
  --attendee-department-path "一级组织/二级团队" \
  --preview-limit 5
```

这个命令会返回：

- 最终命中的部门
- 部门总成员数
- 前几个样本成员，便于创建者确认是否拉对组织

确认无误后，再用同一条路径创建日程：

```bash
python scripts/wecom_schedule_manager.py create-schedule \
  --channel wecom \
  --user-id "<organizer_userid>" \
  --start "2026-04-16 15:00:00" \
  --end "2026-04-16 15:30:00" \
  --summary "团队沟通日程" \
  --attendee-department-path "一级组织/二级团队"
```

如果用户给的是更自然的表述，例如“添加某个组织下的所有成员”，现在也可以直接让脚本自行遍历：

```bash
python scripts/wecom_schedule_manager.py preview-department-attendees \
  --channel wecom \
  --attendee-department-query "一级组织二级团队" \
  --preview-limit 5
```

这条能力的默认行为是：

- 先在当前可见组织树中搜索最可能的完整路径
- 如果命中结果足够明确，直接返回对应组织和样本成员
- 只有当候选组织分数接近、存在歧义时，才建议用户确认

正式创建时也可以直接复用同一个短语：

```bash
python scripts/wecom_schedule_manager.py create-schedule \
  --channel wecom \
  --user-id "<organizer_userid>" \
  --start "2026-04-16 15:00:00" \
  --end "2026-04-16 15:30:00" \
  --summary "团队沟通日程" \
  --attendee-department-query "一级组织二级团队"
```

可直接参考模板：`assets/request-templates/prepare-schedule-create-request.json`

## 一次性创建策略

现在更推荐的对话/编排流程不是“先创建日程，再补加参会人”，而是：

1. 先执行 `prepare-schedule-create`
2. 如果组织识别清晰，就直接返回 `ready`
3. 如果组织识别存在歧义，就返回候选组织和样本成员，先向用户确认
4. 确认后再执行 `create-schedule`，一次性把完整参会人写进去

示例：

```bash
python scripts/wecom_schedule_manager.py prepare-schedule-create \
  --channel wecom \
  --user-id "<organizer_userid>" \
  --start "2026-04-16 15:00:00" \
  --end "2026-04-16 15:30:00" \
  --summary "团队沟通日程" \
  --attendee-department-query "一级组织二级团队"
```

## 会议追加创建

创建日程后，脚本默认不会自动创建会议，而是建议继续追问一次“是否需要创建会议？”。

如果用户确认需要会议，再单独执行：

```bash
python scripts/wecom_schedule_manager.py create-meeting \
  --channel wecom \
  --user-id "<organizer_userid>" \
  --start "2026-04-16 15:00:00" \
  --end "2026-04-16 15:30:00" \
  --summary "团队沟通会议" \
  --attendee-department-query "一级组织二级团队"
```

## Skill 编排建议

如果这一层是对话式 skill，而不是底层脚本，推荐默认按下面规则执行：

1. 用户没明确给主题时，先基于组织名、场景词、测试/正式语境自动拟一个主题
2. 用户没明确给内容时，先自动拟一个简短内容
3. 返回拟定结果时，顺带追问一句：
   `是否需要我进一步拟定更准确的会议主题和会议内容？`
4. 优先在组织识别成功后一次性创建完整日程，不要默认“先创建日程、再补加参会人”
5. 只有在组织识别、人员范围或主题内容不够确定时，才先向用户确认
6. 日程创建成功后，再问一次：
   `是否需要基于这个日程继续创建会议？`
7. 用户没有明确表达需要会议时，不要创建会议

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
