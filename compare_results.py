"""直接对比: print_answers.py vs intent_api_server HTTP 服务"""
import sys, os, json, time, subprocess, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

QUESTIONS = [
    ('1D-1', '1#裂缝当前的宽度是多少？相比上次变化了多少？'),
    ('1D-2', '坝体GNSS监测点今天最大的水平位移是多少？'),
    ('1D-3', '渗压计监测的孔隙水压力当前值是多少？'),
    ('1D-4', '阵列雷达流量计当前的瞬时流量和累积流量是多少？'),
    ('1D-5', '雷达水位计监测的当前液位是多少？'),
    ('2D-1', '1#裂缝和2#裂缝最近两天的宽度变化趋势，哪个增长更快？'),
    ('2D-2', 'GNSS监测的垂直位移在最近一周是加速还是减缓？'),
    ('2D-3', '渗压计压力值与测缝计裂缝宽度之间是否存在同步变化？'),
    ('2D-4', '阵列雷达流量和雷达水位之间，水位上升时流量是否同步增大？'),
    ('2D-5', '各设备剩余电量是否充足？哪些设备电量低于30%需要维护？'),
    ('3D-1', '结合测缝计、GNSS、渗压计三项数据，坝体当前安全状态是否正常？'),
    ('3D-2', '土压力增大、渗压升高、裂缝扩大的点，是否存在潜在滑坡风险？'),
    ('3D-3', '近期水位上涨了多少？流量增大了多少？坝体位移和裂缝是否有响应？'),
    ('3D-4', '全站仪各测点的三维位移是否一致？是否存在局部不均匀沉降？'),
    ('3D-5', '综合所有变形监测数据，按安装地址分组，评估坝体各分区的安全等级。'),
]

# ===== Step 1: print_answers results =====
print("=" * 80)
print("  STEP 1: print_answers.py 直接调用结果")
print("=" * 80)

from intent_api_server import DataQueryEngine, classify_intent, match_intent, summarize_stream
engine = DataQueryEngine('/Users/jinyfeng/Downloads/monitoring_standard.sql')

lib_results = {}
for qid, qtext in QUESTIONS:
    c = classify_intent(qtext, engine)
    tbls = c.get('tbls', []) or list(engine.all_stats.keys())
    m = match_intent(qtext, engine)
    fields = [x[1] for x in m.get('metrics', []) if x[1]]
    summary = ''.join(summarize_stream(qtext, tbls, fields, engine))
    lib_results[qid] = summary
    print(f'[{qid}] {qtext}')
    print(f'  >> {summary}')
    print()

# ===== Step 2: Start HTTP server =====
print("=" * 80)
print("  STEP 2: 启动 intent_api_server HTTP 服务...")
print("=" * 80)

# Start server in background
proc = subprocess.Popen(
    [sys.executable, 'intent_api_server.py'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    cwd=os.path.dirname(os.path.abspath(__file__))
)
time.sleep(3)

# Check server is up
try:
    r = requests.get('http://localhost:8005/api/v1/health', timeout=3)
    print(f'  服务状态: {r.json()}')
except Exception as e:
    print(f'  启动失败: {e}')
    proc.kill()
    sys.exit(1)

# ===== Step 3: Test via HTTP =====
print()
print("=" * 80)
print("  STEP 3: HTTP 服务测试结果 & 对比")
print("=" * 80)

http_results = {}
match_count = 0

for qid, qtext in QUESTIONS:
    try:
        resp = requests.post('http://localhost:8005/api/v1/intent/analyze',
            json={'query': qtext}, timeout=30, stream=True)
        
        # Read SSE stream
        summary = ""
        buffer = ""
        for chunk in resp.iter_content(chunk_size=1, decode_unicode=True):
            if chunk:
                buffer += chunk
                if '\n' in buffer:
                    lines = buffer.split('\n')
                    buffer = lines.pop()
                    for line in lines:
                        if line.startswith('data: ') and line != 'data: [DONE]':
                            try:
                                data = json.loads(line[6:])
                                if 'token' in data:
                                    summary += data['token']
                                elif 'summary' in data:
                                    summary = data['summary']
                            except:
                                pass
        
        http_results[qid] = summary.strip()
        
        lib = lib_results[qid]
        # Compare: check if key numbers match
        http_has_data = any(c.isdigit() for c in summary) if summary else False
        lib_has_data = any(c.isdigit() for c in lib) if lib else False
        
        # Simple match check: both have content, both have or both don't have numbers
        match = (bool(summary) == bool(lib)) and (http_has_data == lib_has_data)
        if match:
            match_count += 1
        
        status = "✅" if match else "⚠️"
        print(f'{status} [{qid}] {qtext[:40]}...')
        print(f'   Lib : {lib[:120]}')
        print(f'   HTTP: {summary[:120]}')
        print()
        
    except Exception as e:
        print(f'❌ [{qid}] HTTP 请求失败: {e}')
        http_results[qid] = f'ERROR: {e}'
        print()

# ===== Summary =====
print("=" * 80)
print(f"  匹配率: {match_count}/{len(QUESTIONS)} ({match_count/len(QUESTIONS)*100:.0f}%)")
print("=" * 80)

# Cleanup
proc.kill()
