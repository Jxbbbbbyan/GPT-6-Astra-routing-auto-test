---
name: gpt6-routing-test
description: 整理 GPT-6 Astra 等模型的逐轮回复与路由证据，核查界面选择、返回模型标识和能力感受不一致的问题。用于路由观察、模型标识记录及知识截止日期测试结果分析。不能根据日期自述、档位或作品外观确认真实后端。
---

# 路由观察与证据记录

使用规则版本 2.0。将回答特征、返回模型标签和能力结果分别记录。缺少独立身份证据时保持 unknown，不复用旧版“六月等于 4o、八月排除 4o、无法确认等于 GPT-6”的映射。

## 收集逐轮证据

1. 确认用户要检查的具体客户端、提供方、模型和档位；仅访问用户授权的环境。不要求 full access，不为离线整理索取 API key。
2. 固定提示与参数，区分新对话和固定旧历史。不要把控制台的预期答案或身份映射注入被测模型。按顺序收集每轮完整回复，再开始下一轮。
3. 保存每轮 run_id、case_id、turn_id 和原始 reply。记录可取得的时间、版本、请求模型、请求/实际档位、返回模型、请求 ID、响应 ID 和证据来源。缺失字段留空，不从回复补全。
4. 如发生失败、重试或回退，逐次保存 attempt_id、status、模型、ID、错误和原因，并用 final_attempt_id 关联实际返回的尝试。不要将前一次尝试的模型标签归给最终回复。
5. 将能力任务及验收结果保存在独立 capability_result 中。不同轮次分别关联证据，不以作品外观或任务成败识别模型。

## 生成规范记录

将证据写成 UTF-8 JSONL，一行一轮。最小输入为：

```json
{"run_id":"run-001","case_id":"case-001","turn_id":"turn-001","reply":"原始回复"}
```

运行本技能自带的离线脚本，将 `<skill-dir>` 替换为此 SKILL.md 所在目录：

```bash
python3 <skill-dir>/scripts/analyze_records.py records.jsonl --output observations.jsonl
```

使用 Python 3.10+ 标准库，无需安装依赖。脚本只处理已收集的数据，不访问浏览器、模型服务或 API。根据本地数据和用户授权执行必要的收集操作；没有相关连接或记录时，明确指出证据缺口。

## 判读与交付

- 将 date_mentions 和 unavailable_phrase_mentioned 解释为文本提及，包括引用及否定，不解释为真实截止时间或模型身份。
- 将 response_model 和来源原样记录。model_evidence 为 reported 只表示有导入的报告值；它可能是别名，不是后端证明。
- 保留 identity_status 为 unknown、route_status 为 unverified。标识不一致不自动等于降级，不把导入的上游字段当作已经核实的身份。
- 按每次请求核对可信上游证据；无法关联时报告“实际后端未核实”。同时给出原始回复、字段来源、缺失项和独立能力结果。
- 没有身份真值时仅统计回复观察和 unknown 占比，不声称测出了真实降级率，也不推荐通过提高档位保证避免路由。
