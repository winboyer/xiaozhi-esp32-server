# 统一语音识别 (ASR) 服务 API

---

## 接口总览

| 方法 | 路径 | Content-Type | 说明 |
|------|------|--------------|------|
| `POST` | `/transcribe` | `application/json` | URL地址语音文件 识别 |
| `POST` | `/transcribe/upload` | `multipart/form-data` | 文件上传识别 |
| `POST` | `/transcribe/stream` | `multipart/form-data` | 流式上传 → （ffmpeg 管道） |
| `WS` | `/stream` | binary | WebSocket 实时 PCM 流 |
| `GET` | `/docs` | — | Swagger 交互式文档 |

---

---

## 1. URL 识别

将公网可访问的音频 URL 提交给 模型进行识别。

### `POST /transcribe`

**请求参数** (`application/json`)：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `audio_url` | string | **是** | — | 音频文件的公网可访问 URL |
| `mime_type` | string | 否 | `audio/mpeg` | 音频 MIME 类型 |
| `enable_itn` | boolean | 否 | `true` | 启用逆文本正则化（数字标准化） |

**请求示例**：
```json
{
  "audio_url": "https://dashscope.oss-cn-beijing.aliyuncs.com/audios/welcome.mp3",
  "enable_itn": true
}
```

**响应示例**：
```json
{
  "text": "欢迎使用阿里云。",
  "backend": "qwen3-asr-flash",
  "duration_ms": 1000.0,
  "request_id": "dc53eafa-6721-993f-ac4a-a5f333972fa7",
  "error": null,
  "usage": {
    "audio_tokens": 42,
    "input_tokens": 42,
    "output_tokens": 12,
    "seconds": 1,
    "total_tokens": 54
  }
}
```

**响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | string | 识别文本 |
| `backend` | string | 使用的后端模型 |
| `duration_ms` | float | 音频时长（毫秒） |
| `request_id` | string | 后端请求 ID |
| `error` | string\|null | 错误信息，正常时为 null |
| `usage` | object | Token 用量统计 |

**调用示例**：
```bash
curl -X POST http://120.26.34.95:7118/transcribe \
  -H "Content-Type: application/json" \
  -d '{
    "audio_url": "https://example.com/audio.mp3",
    "enable_itn": true
  }'
```

**注意事项**：
- 音频 URL 必须能被 服务端（阿里云 DashScope）访问
- 不支持 base64 data URI
- 支持的音频格式：MP3、WAV、FLAC、OGG、M4A 等

---

## 2. 文件上传识别

上传本地音频文件，自动转码为 PCM 后发送给 模型进行流式识别。

### `POST /transcribe/upload`

**请求参数** (`multipart/form-data`)：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `file` | file | **是** | — | 音频文件（支持 MP3/WAV/FLAC/OGG/M4A/AAC 等） |
| `mime_type` | string | 否 | `audio/mpeg` | 文件的 MIME 类型提示 |

**响应示例**：
```json
{
  "text": "华为致力于把数字世界带入每个人、每个家庭、每个组织。构建万物互联的智能世界。",
  "backend": "doubao-stream-v2",
  "duration_ms": 7128.0,
  "request_id": "20260709165447E3A34CB59EE2D06155EB",
  "error": null,
  "usage": {}
}
```

**调用示例**：
```bash
curl -X POST http://120.26.34.95:7118/transcribe/upload \
  -F "file=@/path/to/audio.mp3" \
  -F "mime_type=audio/mpeg"
```

**处理流程**：
```
上传文件 → ffmpeg 转码为 PCM (16kHz/16bit/mono) → WebSocket 流式发送 → Doubao ASR
```

**注意事项**：
- 需要安装 ffmpeg（`conda install -c conda-forge ffmpeg`）
- 大文件建议使用 `/transcribe/stream` 端点避免内存缓冲

---

## 3. 流式上传（`/transcribe/stream`）

通过 ffmpeg stdin/stdout 管道传输，避免将完整文件写入磁盘。

### `POST /transcribe/stream`

**请求参数**：同 `/transcribe/upload`

**调用示例**：
```bash
curl -X POST http://120.26.34.95:7118/transcribe/stream \
  -F "file=@large_audio.mp3" \
  -F "mime_type=audio/mpeg"
```

**数据流**：
```
HTTP Upload → ffmpeg stdin → PCM stdout → Doubao WebSocket → 返回结果
```

全程不落盘，适合大文件或内存受限场景。

---

## 4. WebSocket 实时流（`/stream`）

接收原始 PCM 二进制数据，实时返回识别结果。

### `WS /stream`

**协议**：WebSocket 二进制帧

**输入**（Client → Server）：

| 类型 | 说明 |
|------|------|
| 二进制帧 | PCM 数据块（16kHz, 16bit, mono），建议每帧 60ms（960 samples = 1920 bytes） |
| 空帧 `b""` | 表示音频发送完毕，触发最终识别 |

**输出**（Server → Client）：JSON 格式

```json
{
  "text": "识别结果文本",
  "is_final": true,
  "backend": "doubao-stream-v2",
  "duration_ms": 7128.0,
  "error": null
}
```

**Python 调用示例**：
```python
import asyncio
import websockets

async def stream_recognize(pcm_path: str):
    async with websockets.connect("ws://120.26.34.95:7118/stream") as ws:
        with open(pcm_path, "rb") as f:
            while chunk := f.read(1920):  # 60ms chunks
                await ws.send(chunk)
        await ws.send(b"")  # 结束信号

        result = await ws.recv()
        print(result)

asyncio.run(stream_recognize("audio.pcm"))
```

---

