"""打印 15 个潮白河提问的完整回答"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from intent_api_server import DataQueryEngine, classify_intent, match_intent, summarize_stream

engine = DataQueryEngine('/Users/jinyfeng/Downloads/monitoring_standard.sql')

questions = [
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

print('=' * 70)
for qid, qtext in questions:
    c = classify_intent(qtext, engine)
    tbls = c.get('tbls', []) or list(engine.all_stats.keys())
    m = match_intent(qtext, engine)
    fields = [x[1] for x in m.get('metrics', []) if x[1]]
    summary = ''.join(summarize_stream(qtext, tbls, fields, engine))
    print(f'[{qid}] {qtext}')
    print(f'  >> {summary}')
    print()
print('=' * 70)
