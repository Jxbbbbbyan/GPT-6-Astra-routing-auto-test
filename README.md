# GPT-6 Astra 路由观察与证据记录

本项目帮助整理 ChatGPT、Codex、DSH 等环境中的逐轮回复和模型标识，排查“界面选择的模型、服务端报告的模型与使用感受不一致”的问题。

**规则版本：2.0。不能用知识截止日期自述确认模型身份。** 回答六月、八月或无法确认，都不能单独证明使用了 GPT-4o、GPT-6 或其他模型。思考档位和作品外观也不是模型身份证据。此修正对应 [issue #1](https://github.com/Jxbbbbbyan/GPT-6-Astra-routing-auto-test/issues/1)。

本仓库提供离线 JSONL 记录工具、模拟样本及回归测试。工具不会连接模型服务，不会自动读取浏览器或调用 API，也不会修改服务端路由。它将你已取得的逐请求证据规范化，帮助定位还缺哪些信息。

## 快速验证

使用 Python 3.10 或更高版本，无需第三方依赖、API key 或 full access 权限。从仓库根目录运行：

```bash
python3 skills/gpt6-routing-test/scripts/analyze_records.py examples/observations.jsonl --output observations.jsonl
python3 -m unittest discover -s tests -v
```

示例包含四条**模拟数据**，不是线上实测：同一个模拟模型分别回答六月和八月、一条缺少返回模型标识的记录，以及两次失败后返回另一模拟模型的重试链。

| 输入信息 | 输出 |
| --- | --- |
| 回答包含 `2024 年 6 月` | `reply_observation.date_mentions` 包含 `2024-06` |
| 回答包含 `2024 年 8 月` | `reply_observation.date_mentions` 包含 `2024-08` |
| 回答包含“无法可靠确认”等短语 | `unavailable_phrase_mentioned: true` |
| 缺少 `response_model` | `model_evidence: unknown` |
| 提供 `response_model` | 原样记录，`model_evidence: reported` |
| 任意回复、返回模型或能力分数 | `identity_status: unknown`、`route_status: unverified` |

日期和短语字段只表示**提及**，包括引用、否定和多个日期；它们不表示模型真实的训练截止时间。标识不一致仅设置 `model_label_mismatch`，不自动判为降级。服务端报告值也可能是别名，工具不把它升级为真实后端的证明。

## 记录自己的请求

新建 UTF-8 JSONL 文件，一行对应一轮最终返回。最小记录如下，示例标识应换成自己的值：

```json
{"run_id":"run-001","case_id":"case-001","turn_id":"turn-001","reply":"粘贴这一轮的完整原始回复"}
```

再运行：

```bash
python3 skills/gpt6-routing-test/scripts/analyze_records.py my-records.jsonl --output observations.jsonl
```

可选字段不可取得时省略或填 `null`，不要从回答内容猜测：

| 字段 | 用途 |
| --- | --- |
| `timestamp_utc`、`client_version`、`provider`、`endpoint` | 关联环境与时间；endpoint 不应包含凭据 |
| `conversation_kind`、`history_hash` | 标记新对话或固定旧历史副本 |
| `requested_model`、`requested_effort`、`effective_effort` | 分别记录请求意图与实际取得的档位元数据 |
| `response_model`、`model_evidence_source` | 记录返回模型标签及其来源；不能填写根据回答推测的名称 |
| `request_id`、`response_id` | 将原始回复与具体请求关联 |
| `raw_response` | 保留已脱敏的原始响应，工具不从中自动猜测任何身份字段 |
| `attempts`、`final_attempt_id` | 保存逐次失败、重试及回退记录，明确哪次 attempt 返回了这条回复 |
| `capability_result` | 独立记录任务、验收结果及工具/预算，不能用于改写模型身份 |
| `metadata` | 其他上下文或上游证据及来源；只保存，不自动验证 |

如果有 attempts，每个 attempt 必须有唯一的 `attempt_id` 和 `status`（`success` 或 `error`），同时提供 `final_attempt_id`。其余字段可以包括请求/响应 ID、模型、错误和回退原因。最终 attempt 的返回模型和 ID 会补齐顶层空缺；两者冲突时直接报错，避免串用其他尝试的证据。错误请求用空字符串 `reply`，并明确记录失败的最终 attempt。

工具会拒绝重复的 `run_id/case_id/turn_id`、无效 JSON、缺少最终 attempt 或标识冲突。错误提示包含行号；所有输入验证通过后才替换输出文件，不允许输入输出为同一路径。

## 如何核查 issue #1 这类现象

1. 在出现问题的客户端和提供方中固定模型、档位和提示。新对话与旧对话分开；复用旧对话时使用相同历史副本。不要向被测模型注入本项目的答案映射或预设结论。
2. 输入“你的知识训练截止日期是什么时间？”，保存完整回复，并关联同一轮的请求 ID、界面选择及可取得的服务端模型元数据。不能取得时保持 unknown。
3. 独立运行有明确验收标准的能力任务，记录实际结果。该轮也要重新关联模型证据，不能继承上一轮或整条会话的模型结论。
4. 对比请求标签、返回标签和可信上游解析日志。只有与同次请求关联的可信上游证据，才可用于人工核实实际后端；本工具不会仅凭导入的标签作此确认。
5. 若仍无法定位，再做“新对话/固定旧历史 × low/high”的分组筛查。固定其他参数、各组配额及随机种子，顺序执行并逐条保存。没有身份真值时，只报告回复类别和 unknown 占比，不报告真实降级率。

若返回标签是目标模型、回答却提到六月，应记录为自述与标签的差异，继续查证。若可信上游确认使用了其他模型，才可以进一步定位路由或代理问题。客观任务完成得好或不好，都不能单独确定后端身份。

## 历史结果与兼容性

旧版曾把日期回答直接映射成模型身份，并据此建议避免 low 档位。这些确定性结论已撤回；历史频数作为未经身份校准的回复观察保留在 [历史记录](docs/legacy-results.md)，不能继续解释为降级比例。

技能入口仍为 `skills/gpt6-routing-test/SKILL.md`，现已改为同一套保守记录流程。命令行输出包含 `rule_version: "2.0"`，便于区分旧标签与新记录。CI 会运行离线回归测试。
