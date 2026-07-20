# 监控数据智能分析 API

---

## 接口总览

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/intent/analyze` | 自然语言查询（DB / 天气） |
| `GET` | `/api/v1/health` | 健康检查 |
| `GET` | `/` | 交互式测试页面 |

---

## POST `/api/v1/intent/analyze`

### 请求

```json
{
  "query": "自然语言查询文本"
}
```

### 响应

SSE 流式 (`text/event-stream`)，逐 token 实时推送：

```
data: {"token":"渗"}
data: {"token":"压"}
...
data: {"summary":"完整总结文本","elapsed_seconds":3.4}
data: [DONE]
```

### 调用示例

#### 1. 单表查询 — 渗压计

```bash
curl -X POST http://120.26.34.95:7115/api/v1/intent/analyze \
  -H "Content-Type: application/json" \
  -d '{"query":"统计所有渗压计的渗压值"}'
```

#### 2. 单表查询 — 测缝计

```bash
curl -X POST http://120.26.34.95:7115/api/v1/intent/analyze \
  -H "Content-Type: application/json" \
  -d '{"query":"查询测缝计 SF-equip001 的裂缝宽度"}'
```

#### 3. 单表查询 — GNSS

```bash
curl -X POST http://120.26.34.95:7115/api/v1/intent/analyze \
  -H "Content-Type: application/json" \
  -d '{"query":"GNSS 所有设备的位移数据"}'
```

#### 4. 单表查询 — 土压力计

```bash
curl -X POST http://120.26.34.95:7115/api/v1/intent/analyze \
  -H "Content-Type: application/json" \
  -d '{"query":"土压力计的压力值和温度"}'
```

#### 5. 单表查询 — 全站仪

```bash
curl -X POST http://120.26.34.95:7115/api/v1/intent/analyze \
  -H "Content-Type: application/json" \
  -d '{"query":"全站仪的三维坐标数据"}'
```

#### 6. 单表查询 — 雷达液位计

```bash
curl -X POST http://120.26.34.95:7115/api/v1/intent/analyze \
  -H "Content-Type: application/json" \
  -d '{"query":"雷达液位计的液位和流速"}'
```

#### 7. 单表查询 — 阵列雷达流量计

```bash
curl -X POST http://120.26.34.95:7115/api/v1/intent/analyze \
  -H "Content-Type: application/json" \
  -d '{"query":"阵列雷达流量计的流量统计"}'
```

#### 8. 单表查询 — 时差流量计

```bash
curl -X POST http://120.26.34.95:7115/api/v1/intent/analyze \
  -H "Content-Type: application/json" \
  -d '{"query":"超声波时差流量计的流量和流速"}'
```

---

## GET `/api/v1/health`

```bash
curl http://120.26.34.95:7115/api/v1/health
```

响应：

```json
{
  "status": "ok",
  "tables": [
    "deform_crack_meter",
    "deform_gnss",
    "deform_pore_pressure",
    "deform_soil_pressure",
    "deform_total_station",
    "flow_array_radar",
    "flow_radar_level",
    "flow_tof_meter"
  ],
  "timestamp": "2026-07-10T11:00:00.000000"
}
```
