## ADDED Requirements

### Requirement: 项目团队配置
项目 SHALL 支持配置多员工团队，指定协调者和专员角色。

#### Scenario: 配置团队
- **WHEN** 用户运行 `marneo team setup affiliate-ops`
- **THEN** 向导引导选择员工、分配角色（协调者/专员）、填写团队飞书群 ID，保存到 project.yaml

#### Scenario: 协调者拆分任务
- **WHEN** 用户向协调者员工发送复杂任务请求
- **THEN** 协调者判断需要协作，在团队飞书群中 @mention 各专员并分配子任务

#### Scenario: 专员处理子任务
- **WHEN** 专员员工的 Bot 在团队群中收到协调者 @mention
- **THEN** 专员处理子任务，将结果回复到团队群

#### Scenario: 协调者汇总结果
- **WHEN** 所有专员在超时时间内（60s）回复完毕
- **THEN** 协调者汇总所有专员结果，生成综合回复发送给原始用户
