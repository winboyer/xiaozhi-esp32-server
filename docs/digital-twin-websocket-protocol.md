# 数字孪生平台 — WebSocket 语音交互订阅协议

> **项目**: 潮白河 OTA 设备语音交互  
> **协议版本**: xiaozhi-digital-twin-ws.v1  
> **通信模式**: WebSocket 订阅-推送（数字孪生平作为 C 端，主动订阅设备事件）  

---

## 一、架构概览

```
OTA设备 ──WebSocket──▶ xiaozhi-server ──WebSocket──▶ 数字孪生平台(C端)
  ws://127.0.0.1:8000      │                ws://127.0.0.1:8000
  /xiaozhi/v1/             │                /xiaozhi/digital-twin/v1/
                           │
    ── 或经过反向代理 ──   │                ── 或经过反向代理 ──
  ws://120.26.34.95:7110   │                ws://120.26.34.95:7110
  /xiaozhi/v1/             │                /xiaozhi/digital-twin/v1/
                           │
                    ① 数字孪生平订阅设备
                    ② OTA设备有语音交互时，实时推送事件
```

**与 HTTP POST 方案的核心区别**：

| 维度 | HTTP POST（旧） | WebSocket（新） |
|------|----------------|----------------|
| 连接方向 | 服务端主动 POST 到 C 端 | C 端主动连接服务端 |
| C 端要求 | 需要公网 HTTP 服务 | 只需 WebSocket 客户端 |
| 连接方式 | 无连接，逐次请求 | 长连接，复用通道 |
| 适用场景 | B 端服务端 | **C 端客户端 / 浏览器** |

---

## 二、WebSocket 端点

### 2.1 连接地址

数字孪生平与 OTA 设备共用同一个 xiaozhi-server 端口，仅路径不同：

| 环境 | OTA 设备 | 数字孪生平 |
|------|---------|-----------|
| 本地 | `ws://127.0.0.1:8000/xiaozhi/v1/` | `ws://127.0.0.1:8000/xiaozhi/digital-twin/v1/` |
| 公网（反向代理） | `ws://120.26.34.95:7110/xiaozhi/v1/` | `ws://120.26.34.95:7110/xiaozhi/digital-twin/v1/` |

### 2.2 认证（可选）

```
查询参数: ?token=<jwt_token>
或 Header: Authorization: Bearer <token>
```

（初期可省略，后续按需启用）

---

## 三、消息协议设计

### 3.1 消息信封（所有消息共有结构）

```json
{
  "type": "<消息类型>",
  "session_id": "<本次 WS 连接的会话 ID>",
  "timestamp": 1753372800123,
  "...": "<类型专属字段>"
}
```

### 3.2 Client → Server（数字孪生平 → xiaozhi-server）

#### 3.2.1 订阅设备 — `subscribe`

```json
{
  "type": "subscribe",
  "session_id": "dt-session-uuid",
  "timestamp": 1753372800000,
  "device_ids": ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"],
  "project": "chaobaihe"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | ✅ | 固定 `"subscribe"` |
| `device_ids` | string[] | ✅ | 要订阅的设备 MAC 地址列表 |
| `project` | string | ❌ | 项目过滤，不填则不过滤 |

#### 3.2.2 取消订阅 — `unsubscribe`

```json
{
  "type": "unsubscribe",
  "session_id": "dt-session-uuid",
  "timestamp": 1753372800000,
  "device_ids": ["AA:BB:CC:DD:EE:FF"]
}
```

不传 `device_ids` 则取消全部订阅。

#### 3.2.3 心跳 — `ping`

```json
{
  "type": "ping",
  "session_id": "dt-session-uuid",
  "timestamp": 1753372800000
}
```

建议每 30 秒发送一次。

---

### 3.3 Server → Client（xiaozhi-server → 数字孪生平）

#### 3.3.1 连接确认 — `welcome`

连接建立后立即发送：

```json
{
  "type": "welcome",
  "session_id": "srv-generated-uuid",
  "timestamp": 1753372800000,
  "version": "xiaozhi-digital-twin-ws.v1"
}
```

#### 3.3.2 订阅确认 — `subscribed`

```json
{
  "type": "subscribed",
  "session_id": "srv-generated-uuid",
  "timestamp": 1753372800000,
  "device_ids": ["AA:BB:CC:DD:EE:FF"],
  "message": "已订阅 1 台设备"
}
```

#### 3.3.3 心跳响应 — `pong`

```json
{
  "type": "pong",
  "session_id": "srv-generated-uuid",
  "timestamp": 1753372800000
}
```

#### 3.3.4 语音交互事件 — `voice_event`（核心）

```json
{
  "type": "voice_event",
  "session_id": "srv-generated-uuid",
  "timestamp": 1753372800123,
  "sub_type": "asr | llm_stream | llm_done | round_end",
  "sequence": 1,
  "device_id": "AA:BB:CC:DD:EE:FF",
  "device_name": "潮白河-监测站1号",
  "project": "chaobaihe",
  "device_session_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "sentence_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "payload": { /* 见下方各子类型 */ }
}
```

**公共字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 固定 `"voice_event"` |
| `sub_type` | string | 事件子类型 |
| `sequence` | int | 按 `device_id` 递增，用于排序和丢包检测 |
| `device_id` | string | OTA 设备 MAC 地址 |
| `device_name` | string | 设备友好名称 |
| `project` | string | 项目标识 |
| `device_session_id` | string | OTA 设备 WebSocket 连接的 session_id（一次设备连接） |
| `sentence_id` | string | 当前轮次 ID，同一轮的 4 个子事件共享 |
| `payload` | object | 各事件类型的专属数据 |

---

### 3.4 各事件 `payload` 详细结构

#### 3.4.1 `sub_type = "asr"` — 语音识别结果

```json
{
  "sub_type": "asr",
  "sequence": 1,
  "device_id": "AA:BB:CC:DD:EE:FF",
  "device_name": "潮白河-监测站1号",
  "project": "chaobaihe",
  "device_session_id": "f47ac10b-...",
  "sentence_id": "a1b2c3d4-...",
  "timestamp": 1753372800123,
  "payload": {
    "text": "今天测缝计的数据有没有异常",
    "text_raw": "今天测缝计的数据有没有异常？",
    "speaker_name": null,
    "asr_backend": "doubao-bigmodel",
    "asr_duration_ms": 1580
  }
}
```

| payload 字段 | 类型 | 说明 |
|-------------|------|------|
| `text` | string | 去标点去 emoji 的文本（用于展示） |
| `text_raw` | string | 原始文本（保留标点） |
| `speaker_name` | string? | 声纹识别结果，未识别时为 `null` |
| `asr_backend` | string | ASR 后端标识 |
| `asr_duration_ms` | int | 语音时长（毫秒） |

**数字孪生平处理**：收到后**立即显示**用户说话内容，无需等待 LLM。

---

#### 3.4.2 `sub_type = "llm_stream"` — LLM 流式内容片段

```json
{
  "sub_type": "llm_stream",
  "sequence": 2,
  "device_id": "AA:BB:CC:DD:EE:FF",
  "device_name": "潮白河-监测站1号",
  "project": "chaobaihe",
  "device_session_id": "f47ac10b-...",
  "sentence_id": "a1b2c3d4-...",
  "timestamp": 1753372800890,
  "payload": {
    "chunk_index": 0,
    "delta_text": "根据监测数据，",
    "cumulative_text": "根据监测数据，",
    "is_first": true,
    "intent_type": "chaobaihe_db_query"
  }
}
```

| payload 字段 | 类型 | 说明 |
|-------------|------|------|
| `chunk_index` | int | 片段索引，从 0 开始 |
| `delta_text` | string | 本次增量文本 |
| `cumulative_text` | string | 从首 chunk 到当前的累积文本 |
| `is_first` | bool | 是否为本轮首个 chunk |
| `intent_type` | string | 意图类型 |

**数字孪生平处理**：实现**逐字流式展示**（typing effect），每次 `delta_text` 追加到 AI 回复区域。

**容错**：如果中途断连再重连时收到事件，用 `cumulative_text` 直接覆盖展示，避免丢失中间 chunk。

---

#### 3.4.3 `sub_type = "llm_done"` — LLM 响应完成

```json
{
  "sub_type": "llm_done",
  "sequence": 5,
  "device_id": "AA:BB:CC:DD:EE:FF",
  "device_name": "潮白河-监测站1号",
  "project": "chaobaihe",
  "device_session_id": "f47ac10b-...",
  "sentence_id": "a1b2c3d4-...",
  "timestamp": 1753372802350,
  "payload": {
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
  }
}
```

| payload 字段 | 类型 | 说明 |
|-------------|------|------|
| `full_text` | string | 完整回复文本 |
| `total_chunks` | int | `llm_stream` 总片段数 |
| `intent_type` | string | 意图类型 |
| `query_tables` | string[] | 查询的数据表名列表 |
| `query_fields` | string[] | 关注的指标字段列表 |
| `timing_ms` | object | 各环节耗时 |
| `llm_model` | string | 使用的 LLM 模型名 |

**数字孪生平处理**：标记流式展示完成，可用 `full_text` 校验前面 chunk 拼接是否正确，并可展示性能指标。

---

#### 3.4.4 `sub_type = "round_end"` — 本轮交互结束

```json
{
  "sub_type": "round_end",
  "sequence": 6,
  "device_id": "AA:BB:CC:DD:EE:FF",
  "device_name": "潮白河-监测站1号",
  "project": "chaobaihe",
  "device_session_id": "f47ac10b-...",
  "sentence_id": "a1b2c3d4-...",
  "timestamp": 1753372808900,
  "payload": {
    "reason": "completed",
    "summary": {
      "user_text": "今天测缝计的数据有没有异常",
      "assistant_text": "根据监测数据，测缝计JM-01在过去24小时内数据稳定，未发现异常。建议持续关注。",
      "intent_type": "chaobaihe_db_query",
      "action_type": "llm_summary"
    }
  }
}
```

| payload 字段 | 类型 | 说明 |
|-------------|------|------|
| `reason` | string | `"completed"` / `"aborted"` / `"error"` |
| `summary` | object | 本轮交互摘要 |

---

## 四、完整推送时序

```
数字孪生平                           xiaozhi-server                         OTA 设备
    │                                      │                                    │
    │── WS 连接 ──────────────────────────▶│                                    │
    │◀─ welcome ──────────────────────────│                                    │
    │── subscribe(device_ids) ───────────▶│                                    │
    │◀─ subscribed ───────────────────────│                                    │
    │                                      │◀── 语音输入 ──────────────────────│
    │                                      │   (VAD → ASR)                      │
    │◀─ voice_event(asr) ────────────────│  ← ASR 识别完成                     │
    │   "今天测缝计的数据有没有异常"                                             │
    │                                      │   (Intent → LLM 流式)              │
    │◀─ voice_event(llm_stream #0) ──────│  ← LLM chunk                        │
    │◀─ voice_event(llm_stream #1) ──────│  ← LLM chunk                        │
    │◀─ voice_event(llm_stream #2) ──────│  ← LLM chunk                        │
    │◀─ voice_event(llm_done) ───────────│  ← LLM 完成                         │
    │                                      │   (TTS 播报中...)                  │
    │◀─ voice_event(round_end) ──────────│  ← TTS 播完                         │
    │                                      │                                    │
```

---

## 五、数字孪生平接收端参考（JavaScript）

```javascript
class DigitalTwinClient {
  constructor(url) {
    this.ws = new WebSocket(url);
    this.deviceCards = new Map(); // device_id + sentence_id → 卡片
    this.setupHandlers();
  }

  setupHandlers() {
    this.ws.onopen = () => {
      // 连接成功后订阅设备
      this.subscribe(['AA:BB:CC:DD:EE:FF']);
    };

    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case 'voice_event':
          this.handleVoiceEvent(msg);
          break;
        case 'subscribed':
          console.log('已订阅:', msg.device_ids);
          break;
        case 'pong':
          // 心跳正常
          break;
      }
    };
  }

  subscribe(deviceIds) {
    this.ws.send(JSON.stringify({
      type: 'subscribe',
      session_id: this.sessionId,
      timestamp: Date.now(),
      device_ids: deviceIds,
    }));
  }

  // 按 device_id + sentence_id 定位对话卡片
  getCard(deviceId, sentenceId) {
    const key = `${deviceId}:${sentenceId}`;
    if (!this.deviceCards.has(key)) {
      this.deviceCards.set(key, {
        deviceId, sentenceId,
        userText: '',
        aiText: '',
        aiChunks: 0,
        intentType: '',
        status: 'listening', // listening → thinking → speaking → done
      });
    }
    return this.deviceCards.get(key);
  }

  handleVoiceEvent(msg) {
    const { sub_type, device_id, device_name, sentence_id, payload, sequence } = msg;
    const card = this.getCard(device_id, sentence_id);

    switch (sub_type) {
      case 'asr':
        card.userText = payload.text;
        card.status = 'thinking';
        // UI: 新建对话卡片，显示用户消息
        this.ui.createCard(card, device_name);
        this.ui.showUserMessage(card, payload.text, payload.speaker_name);
        break;

      case 'llm_stream':
        card.status = 'speaking';
        if (payload.is_first) {
          card.aiText = payload.delta_text;
        } else {
          card.aiText += payload.delta_text;
        }
        // UI: 流式追加 AI 回复（typing effect）
        this.ui.updateAIMessage(card, card.aiText, false);
        break;

      case 'llm_done':
        // UI: 用 full_text 校验并修正，标记流式完成
        card.aiText = payload.full_text;
        card.intentType = payload.intent_type;
        this.ui.updateAIMessage(card, payload.full_text, true);
        this.ui.showTiming(card, payload.timing_ms);
        break;

      case 'round_end':
        card.status = 'done';
        // UI: 归档保存本轮对话
        this.ui.archiveCard(card, payload.summary);
        break;
    }
  }

  // 心跳保持
  startHeartbeat() {
    setInterval(() => {
      if (this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({
          type: 'ping',
          session_id: this.sessionId,
          timestamp: Date.now(),
        }));
      }
    }, 30000);
  }
}
```

---

## 六、实现方案（代码改动清单）

### 6.1 新增文件

| 文件 | 说明 |
|------|------|
| `core/digital_twin/__init__.py` | 模块初始化 |
| `core/digital_twin/digital_twin_manager.py` | **数字孪生管理器**：管理所有数字孪生 WS 连接 + 设备订阅关系 |
| `core/digital_twin/digital_twin_handler.py` | **数字孪生连接处理器**：单个数字孪生客户端的消息收发 |

### 6.2 修改文件

| 文件 | 改动内容 |
|------|---------|
| `core/websocket_server.py` | 新增 `/xiaozhi/digital-twin/v1/` 路由分发；初始化 `DigitalTwinManager` |
| `core/connection.py` | 在 `chat()` 和 `startToChat()` 等位置调用 `self.server.dt_manager.push_event()` 推送事件 |
| `core/handle/receiveAudioHandle.py` | ASR 完成后调用推送 |
| `core/handle/sendAudioHandle.py` | TTS 播完后（`round_end`）调用推送 |

### 6.3 推送 Hook 点

```
① ASR 完成  →  receiveAudioHandle.py::startToChat()
               push_event(device_id, "asr", payload)

② LLM chunk →  connection.py::chat() 中 each chunk
               push_event(device_id, "llm_stream", payload)

③ LLM 完成  →  connection.py::chat() 中 depth==0 时
               push_event(device_id, "llm_done", payload)

④ TTS 播完  →  sendAudioHandle.py::send_tts_message(state="stop")
               push_event(device_id, "round_end", payload)
```

---

## 七、注意事项

1. **长连接管理**：数字孪生平断开后自动清理订阅关系，不残留
2. **心跳保活**：建议客户端每 30s 发 `ping`，服务端 90s 无消息则主动断开
3. **幂等处理**：数字孪生平按 `device_id + sentence_id + sub_type` 做幂等，防止重复推送
4. **丢包容错**：`sequence` 按 `device_id` 递增，数字孪生平检测 sequence 跳号可请求重推
5. **`cumulative_text`**：每个 `llm_stream` 都携带，即使丢失中间 chunk 也能恢复完整文本
6. **多设备订阅**：一个数字孪生客户端可同时订阅多台 OTA 设备
7. **向后兼容**：新增 WebSocket 端点不影响现有的 OTA 设备 `/xiaozhi/v1/` 连接
