## 1. Team 数据模型

- [ ] 1.1 创建 `marneo/collaboration/__init__.py`
- [ ] 1.2 创建 `marneo/collaboration/team.py`：TeamMember, TeamConfig, save/load/list
- [ ] 1.3 project.yaml 扩展：team 字段（members, coordinator, team_chat_id）

## 2. Coordinator 逻辑

- [ ] 2.1 创建 `marneo/collaboration/coordinator.py`
- [ ] 2.2 判断任务是否需要团队（LLM 决策）
- [ ] 2.3 拆分任务：为每个专员生成子任务描述
- [ ] 2.4 发送 @mention 消息到团队飞书群
- [ ] 2.5 等待专员回复（超时 60s）
- [ ] 2.6 汇总所有回复，生成最终回复

## 3. 专员响应

- [ ] 3.1 FeishuChannelAdapter 识别团队群中对本员工的 @mention
- [ ] 3.2 专员 Bot 处理子任务，回复到群
- [ ] 3.3 协调者 Bot 监听专员回复（通过群消息）

## 4. CLI 命令

- [ ] 4.1 创建 `marneo/cli/team_cmd.py`
- [ ] 4.2 `marneo team list <project>`：查看团队配置
- [ ] 4.3 `marneo team add <project> <employee> --role 角色`：添加团队成员
- [ ] 4.4 `marneo team remove <project> <employee>`：移除成员
- [ ] 4.5 `marneo team setup <project>`：交互式向导配置团队（选成员+角色+群ID）
- [ ] 4.6 注册到 app.py
