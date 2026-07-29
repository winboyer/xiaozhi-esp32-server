# 数字孪生平台 — 语音交互事件推送接口设计

> **项目**: 潮白河 OTA 设备语音交互  
> **协议版本**: xiaozhi-digital-twin.v1  
> **推送模式**: 事件驱动 + HTTP POST（无长连接，有交互时才推送）

---

## 一、架构概览

```
OTA设备 ──语音──▶ xiaozhi-server ──HTTP POST──▶ 数字孪生平台
                      │                      POST /api/v1/voice-interaction/event
                      │
              有语音交互事件时才推送
              无交互时什么都不发生
```

---

## 二、接口定义

### 2.1 推送端点

```
POST /api/v1/voice-interaction/event
Content-Type: application/json
```

### 2.2 认证方式

```
Header: Authorization: Bearer <token>
```
（后续按需配置，初期可省略）

---

## 三、四种事件类型

| sub_type    | 触发时机                       | 频率        | 顺序 |
|-------------|-------------------------------|-------------|------|
| `asr`       | ASR 识别出完整文本后立即推送    | 1次/轮      | ①    |
| `llm_stream`| LLM 每生成一段文本 chunk        | 多次/轮     | ②    |
| `llm_done`  | LLM 响应完整结束                | 1次/轮      | ③    |
| `round_end` | 一轮交互完全结束（TTS播完）     | 1次/轮      | ④    |

---

## 四、公共字段（所有事件共有）

| 字段          | 类型    | 说明                                                     |
|---------------|---------|----------------------------------------------------------|
| `sub_type`    | string  | 事件子类型: `asr` / `llm_stream` / `llm_done` / `round_end` |
| `session_id`  | string  | 一次 WebSocket 连接的唯一会话 ID                           |
| `sentence_id` | string  | 当前轮次 ID，同一轮的 asr→llm_stream→llm_done→round_end 共享 |
| `device_id`   | string  | OTA 设备 MAC 地址                                         |
| `device_name` | string  | 设备友好名称                                              |
| `project`     | string  | 项目标识，固定 `"chaobaihe"`                               |
| `sequence`    | int     | 递增序号，从 1 开始，用于排序和丢包检测                      |
| `timestamp`   | int     | 毫秒级 Unix 时间戳                                        |

---

## 五、各事件类型详细字段

### 5.1 sub_type = `asr` — 语音识别结果

ASR 识别完成后**最先**推送，用户说的话立即在数字孪生平台展示，无需等待 LLM 响应。

| 字段              | 类型    | 说明                                  |
|-------------------|---------|---------------------------------------|
| `text`            | string  | ASR 识别文本（去标点去 emoji）          |
| `text_raw`        | string  | ASR 原始文本（保留标点）                |
| `speaker_name`    | string? | 声纹识别出的说话人，未识别时为 `null`    |
| `asr_backend`     | string  | ASR 后端标识，如 `"doubao-bigmodel"`   |
| `asr_duration_ms` | int     | 语音时长（毫秒）                        |

### 5.2 sub_type = `llm_stream` — LLM 流式内容片段

LLM 每生成一段文本就推送一次，数字孪生平台可实现**逐字流式展示**效果。

| 字段              | 类型    | 说明                                              |
|-------------------|---------|---------------------------------------------------|
| `chunk_index`     | int     | 片段索引，从 0 开始                                 |
| `delta_text`      | string  | 本次增量文本                                       |
| `cumulative_text` | string  | 从首 chunk 到当前的累积文本（容错恢复用）            |
| `is_first`        | bool    | 是否为本轮首个 chunk                                |
| `intent_type`     | string  | 意图类型，如 `"chaobaihe_db_query"`                 |

### 5.3 sub_type = `llm_done` — LLM 响应完成

LLM 生成完毕，携带完整文本和性能指标。

| 字段              | 类型     | 说明                                              |
|-------------------|----------|---------------------------------------------------|
| `full_text`       | string   | 完整回复文本                                       |
| `total_chunks`    | int      | `llm_stream` 总片段数                               |
| `intent_type`     | string   | 意图类型                                           |
| `query_tables`    | string[] | 查询的数据表名列表                                  |
| `query_fields`    | string[] | 关注的指标字段列表                                  |
| `timing_ms`       | object   | 各环节耗时（见下方子字段）                           |
| `timing_ms.total` | int      | 总耗时（ASR 文本完成 → LLM 回复完成）                |
| `timing_ms.asr`   | int      | ASR 识别耗时                                       |
| `timing_ms.intent_classify` | int | LLM 意图分类耗时                               |
| `timing_ms.data_query`     | int | DataQueryEngine 数据查询耗时                   |
| `timing_ms.llm_summary`    | int | LLM 总结生成耗时                               |
| `llm_model`       | string   | 使用的 LLM 模型名，如 `"deepseek-v4-flash"`        |

### 5.4 sub_type = `round_end` — 本轮交互结束

TTS 语音播报完毕后推送，标志着本轮交互完全结束。

| 字段                       | 类型   | 说明                                        |
|----------------------------|--------|---------------------------------------------|
| `reason`                   | string | 结束原因: `"completed"` / `"aborted"` / `"error"` |
| `summary`                  | object | 本轮交互摘要                                 |
| `summary.user_text`        | string | 用户说的话                                   |
| `summary.assistant_text`   | string | AI 回复内容                                  |
| `summary.intent_type`      | string | 意图类型                                     |
| `summary.action_type`      | string | 处理方式: `"llm_summary"` / `"tool_response"` / `"direct_answer"` |

---

## 六、POST 请求示例

### 6.1 示例一：ASR 识别结果

```bash
curl -X POST http://数字孪生平地址/api/v1/voice-interaction/event \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer xxx" \
  -d '{
    "sub_type": "asr",
    "session_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "sentence_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "device_id": "AA:BB:CC:DD:EE:FF",
    "device_name": "潮白河-监测站1号",
    "project": "chaobaihe",
    "sequence": 1,
    "timestamp": 1753372800123,
    "text": "今天测缝计的数据有没有异常",
    "text_raw": "今天测缝计的数据有没有异常？",
    "speaker_name": null,
    "asr_backend": "doubao-bigmodel",
    "asr_duration_ms": 1580
  }'
```

### 6.2 示例二：LLM 流式片段（第1段）

```bash
curl -X POST http://数字孪生平地址/api/v1/voice-interaction/event \
  -H "Content-Type: application/json" \
  -d '{
    "sub_type": "llm_stream",
    "session_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "sentence_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "device_id": "AA:BB:CC:DD:EE:FF",
    "device_name": "潮白河-监测站1号",
    "project": "chaobaihe",
    "sequence": 2,
    "timestamp": 1753372800890,
    "chunk_index": 0,
    "delta_text": "根据监测数据，",
    "cumulative_text": "根据监测数据，",
    "is_first": true,
    "intent_type": "chaobaihe_db_query"
  }'
```

### 6.3 示例三：LLM 流式片段（中间段）

```bash
curl -X POST http://数字孪生平地址/api/v1/voice-interaction/event \
  -H "Content-Type: application/json" \
  -d '{
    "sub_type": "llm_stream",
    "session_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "sentence_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "device_id": "AA:BB:CC:DD:EE:FF",
    "device_name": "潮白河-监测站1号",
    "project": "chaobaihe",
    "sequence": 3,
    "timestamp": 1753372801230,
    "chunk_index": 1,
    "delta_text": "测缝计JM-01在过去24小时内",
    "cumulative_text": "根据监测数据，测缝计JM-01在过去24小时内",
    "is_first": false,
    "intent_type": "chaobaihe_db_query"
  }'
```

### 6.4 示例四：LLM 流式片段（最后段）

```bash
curl -X POST http://数字孪生平地址/api/v1/voice-interaction/event \
  -H "Content-Type: application/json" \
  -d '{
    "sub_type": "llm_stream",
    "session_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "sentence_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "device_id": "AA:BB:CC:DD:EE:FF",
    "device_name": "潮白河-监测站1号",
    "project": "chaobaihe",
    "sequence": 4,
    "timestamp": 1753372801890,
    "chunk_index": 2,
    "delta_text": "数据稳定，未发现异常。建议持续关注。",
    "cumulative_text": "根据监测数据，测缝计JM-01在过去24小时内数据稳定，未发现异常。建议持续关注。",
    "is_first": false,
    "intent_type": "chaobaihe_db_query"
  }'
```

### 6.5 示例五：LLM 响应完成

```bash
curl -X POST http://数字孪生平地址/api/v1/voice-interaction/event \
  -H "Content-Type: application/json" \
  -d '{
    "sub_type": "llm_done",
    "session_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "sentence_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "device_id": "AA:BB:CC:DD:EE:FF",
    "device_name": "潮白河-监测站1号",
    "project": "chaobaihe",
    "sequence": 5,
    "timestamp": 1753372802350,
    "full_text": "根据监测数据，测缝计JM-01在过去24小时内数据稳定，未发现异常。建议持续关注。",
    "total_chunks": 3,
    "intent_type": "chaobaihe_db_query",
    "query_tables": ["sensor_crack_meter"],
    "query_fields": ["value", "status"],
    "timing_ms": {
      "total": 4200,
      "asr": 1580,
      "intent_classify": 350,
      "data_query": 120,
      "llm_summary": 2150
    },
    "llm_model": "deepseek-v4-flash"
  }'
```

### 6.6 示例六：本轮交互结束

```bash
curl -X POST http://数字孪生平地址/api/v1/voice-interaction/event \
  -H "Content-Type: application/json" \
  -d '{
    "sub_type": "round_end",
    "session_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "sentence_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "device_id": "AA:BB:CC:DD:EE:FF",
    "device_name": "潮白河-监测站1号",
    "project": "chaobaihe",
    "sequence": 6,
    "timestamp": 1753372808900,
    "reason": "completed",
    "summary": {
      "user_text": "今天测缝计的数据有没有异常",
      "assistant_text": "根据监测数据，测缝计JM-01在过去24小时内数据稳定，未发现异常。建议持续关注。",
      "intent_type": "chaobaihe_db_query",
      "action_type": "llm_summary"
    }
  }'
```

---

## 七、完整推送时序

```
14:32:00  POST ①  sub_type="asr"           ← ASR 识别完立即发
14:32:01  POST ②  sub_type="llm_stream"     ← LLM 流式 chunk 0
14:32:02  POST ③  sub_type="llm_stream"     ← LLM 流式 chunk 1
14:32:02  POST ④  sub_type="llm_stream"     ← LLM 流式 chunk 2
14:32:03  POST ⑤  sub_type="llm_done"       ← LLM 全部完成
14:32:05  POST ⑥  sub_type="round_end"      ← TTS 播完
```

**关键**：
- `sequence` 按 device_id 递增，从 1 开始，确保顺序
- `sentence_id` 同一轮保持一致，串联 asr → llm_stream → llm_done → round_end
- `cumulative_text` 在每个 llm_stream 中都带，用于丢包容错恢复

---

## 八、数字孪生平接收端参考

```javascript
// 数字孪生平台 - 接收语音交互事件
app.post('/api/v1/voice-interaction/event', (req, res) => {
    const { sub_type, device_id, sentence_id, text, delta_text, full_text, timestamp } = req.body;

    // 按 device_id + sentence_id 定位对话卡片
    const card = getOrCreateInteractionCard(device_id, sentence_id);

    switch (sub_type) {
        case 'asr':
            card.addUserMessage(text, timestamp);
            break;
        case 'llm_stream':
            card.appendAIMessage(delta_text);    // 逐字流式展示
            break;
        case 'llm_done':
            card.markAIComplete(req.body);       // 标记完成，显示性能指标
            break;
        case 'round_end':
            card.archive(req.body.summary);      // 归档保存
            break;
    }

    res.json({ ok: true, sequence: req.body.sequence });
});
```

---

## 九、注意事项

1. **event-driven**：只有语音交互发生时才有 POST，无交互时无任何请求
2. **asr 先行**：ASR 结果不等 LLM，立即推送到数字孪生平展示
3. **流式展示**：`llm_stream` 后缀为 `stream` 而非 `chunk`，强调数字孪生平可实现逐字 typing 效果
4. **容错设计**：`cumulative_text` 保证即使丢失中间 chunk 也能正确展示完整内容
5. **顺序保证**：`sequence` 按 `device_id` 递增，数字孪生平可检测丢包（sequence 跳号）
6. **幂等处理**：数字孪生平应按 `device_id + sentence_id + sub_type` 做幂等，防止重复推送
