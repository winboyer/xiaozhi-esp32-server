"""
潮白河数据库 15 个提问的意图理解验证脚本
测试 classify_intent + summarize_stream 对每个问题的处理能力
"""
import sys
import os
import time
import json

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from intent_api_server import DataQueryEngine, classify_intent, match_intent, summarize_stream

SQL_FILE = "/Users/jinyfeng/Downloads/monitoring_standard.sql"

# ==================== 15 个测试提问 ====================
TEST_QUESTIONS = {
    # ---- 一维：直接查询单表/单指标 ----
    "1D-1": "1#裂缝当前的宽度是多少？相比上次变化了多少？",
    "1D-2": "坝体GNSS监测点今天最大的水平位移是多少？",
    "1D-3": "渗压计监测的孔隙水压力当前值是多少？",
    "1D-4": "阵列雷达流量计当前的瞬时流量和累积流量是多少？",
    "1D-5": "雷达水位计监测的当前液位是多少？",
    
    # ---- 二维：跨设备对比 / 时序变化 ----
    "2D-1": "1#裂缝和2#裂缝最近两天的宽度变化趋势，哪个增长更快？",
    "2D-2": "GNSS监测的垂直位移在最近一周是加速还是减缓？",
    "2D-3": "渗压计压力值与测缝计裂缝宽度之间是否存在同步变化？",
    "2D-4": "阵列雷达流量和雷达水位之间，水位上升时流量是否同步增大？",
    "2D-5": "各设备剩余电量是否充足？哪些设备电量低于30%需要维护？",
    
    # ---- 三维：综合分析 / 安全研判 ----
    "3D-1": "结合测缝计、GNSS、渗压计三项数据，坝体当前安全状态是否正常？",
    "3D-2": "土压力增大、渗压升高、裂缝扩大的点，是否存在潜在滑坡风险？",
    "3D-3": "近期水位上涨了多少？流量增大了多少？坝体位移和裂缝是否有响应？",
    "3D-4": "全站仪各测点的三维位移是否一致？是否存在局部不均匀沉降？",
    "3D-5": "综合所有变形监测数据，按安装地址分组，评估坝体各分区的安全等级。",
}


def run_test(engine):
    """运行所有测试问题，返回每个问题的诊断结果"""
    results = []
    total = len(TEST_QUESTIONS)
    
    for qid, question in TEST_QUESTIONS.items():
        result = {
            "id": qid,
            "question": question,
            "intent_cat": None,
            "tables_matched": [],
            "fields_matched": [],
            "summary_length": 0,
            "passed": False,
            "error": None,
        }
        
        try:
            # 1. 意图分类
            classification = classify_intent(question, engine)
            result["intent_cat"] = classification.get("cat", "unknown")
            result["tables_matched"] = classification.get("tbls", [])
            
            # 2. 检查是否为 DB 查询
            if result["intent_cat"] != "db":
                result["error"] = f"意图分类为 '{result['intent_cat']}'，未识别为数据库查询"
                results.append(result)
                continue
            
            # 3. 字段匹配
            matched = match_intent(question, engine)
            result["fields_matched"] = [m[1] for m in matched.get("metrics", []) if m[1]]
            
            # 4. 生成总结
            tables = result["tables_matched"] or list(engine.all_stats.keys())
            summary_parts = list(summarize_stream(
                question, tables, result["fields_matched"], engine
            ))
            summary = "".join(summary_parts)
            result["summary_length"] = len(summary)
            
            if summary and len(summary.strip()) > 20:
                result["passed"] = True
            else:
                result["error"] = f"总结内容过短 ({len(summary)} 字符)"
                
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        
        results.append(result)
    
    return results


def print_report(results):
    """打印测试报告"""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    db_classified = sum(1 for r in results if r["intent_cat"] == "db")
    has_summary = sum(1 for r in results if r["summary_length"] > 0)
    
    print("\n" + "=" * 70)
    print(f"  潮白河数据库提问验证报告")
    print(f"  测试提问数: {total}  通过: {passed}  通过率: {passed/total*100:.0f}%")
    print(f"  DB分类正确: {db_classified}/{total}  有总结产出: {has_summary}/{total}")
    print("=" * 70)
    
    for r in results:
        status = "✅" if r["passed"] else "❌"
        print(f"\n{status} [{r['id']}] {r['question'][:50]}...")
        print(f"   意图分类: {r['intent_cat']}  |  匹配表: {r['tables_matched']}")
        print(f"   匹配字段: {r['fields_matched'][:5]}")
        print(f"   总结长度: {r['summary_length']} 字符")
        if r["error"]:
            print(f"   ⚠️  {r['error']}")
    
    # 分类统计
    dim1 = [r for r in results if r["id"].startswith("1D")]
    dim2 = [r for r in results if r["id"].startswith("2D")]
    dim3 = [r for r in results if r["id"].startswith("3D")]
    
    print("\n--- 按维度统计 ---")
    for label, group in [("一维(直接查询)", dim1), ("二维(对比分析)", dim2), ("三维(综合分析)", dim3)]:
        p = sum(1 for r in group if r["passed"])
        print(f"  {label}: {p}/{len(group)} 通过 ({p/len(group)*100:.0f}%)")
    
    return passed, total


if __name__ == "__main__":
    print("正在初始化 DataQueryEngine...")
    t0 = time.time()
    engine = DataQueryEngine(SQL_FILE)
    print(f"初始化完成，{len(engine.tables)} 张表，耗时 {time.time()-t0:.1f}s")
    print(f"表列表: {list(engine.tables.keys())}")
    
    results = run_test(engine)
    passed, total = print_report(results)
    
    # 保存详细结果
    report_file = "chaobaihe_test_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump([{k: v for k, v in r.items()} for r in results], f, ensure_ascii=False, indent=2)
    print(f"\n详细报告已保存至: {report_file}")
    
    # 返回退出码
    rate = passed / total
    if rate >= 0.8:
        print(f"\n✅ 通过率 {rate*100:.0f}% ≥ 80%，验证通过")
        sys.exit(0)
    else:
        print(f"\n❌ 通过率 {rate*100:.0f}% < 80%，需要优化")
        sys.exit(1)
