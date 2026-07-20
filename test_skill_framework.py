"""验证 skill 框架和所有改动是否正确编译和工作"""
import sys
sys.path.insert(0, "main/xiaozhi-server")

# 1. 测试基础类导入
from plugins_func.skills.base import SkillHints, SkillRegistry
from plugins_func.skills.registry import skill_registry
print("✓ 基础类导入成功")

# 2. 测试注册/读取/注销
hints = SkillHints(
    function_name="test_func",
    keywords=["测试"],
    few_shot_examples=["test example"],
    summary_prompt="test prompt {data}",
    priority=5,
)
skill_registry.register(hints)
all_skills = skill_registry.get_all()
assert len(all_skills) == 1
assert skill_registry.get("test_func") is not None
print(f"✓ 注册中心: 已注册 {len(all_skills)} 个技能")

# 3. 测试关键词表生成
table = skill_registry.build_keyword_table()
assert "测试" in table
assert "test_func" in table
print("✓ 关键词表生成正确")

# 4. 测试 few-shot 示例生成
examples = skill_registry.build_few_shot_examples()
assert "test example" in examples
print("✓ Few-shot 示例生成正确")

# 5. 测试摘要提示词
sp = skill_registry.get_summary_prompt("test_func")
assert sp is not None
assert "{data}" in sp
print("✓ 摘要提示词获取正确")

# 6. 测试注销
skill_registry.unregister("test_func")
assert len(skill_registry.get_all()) == 0
print("✓ 注销功能正常")

# 7. 测试地磅 skill 注册
from plugins_func.skills.weighbridge_skill import register_weighbridge_skill
register_weighbridge_skill()
hints = skill_registry.get("analyze_weighbridge_data")
assert hints is not None
assert len(hints.keywords) > 0
assert len(hints.few_shot_examples) > 0
assert hints.summary_prompt is not None
print(f"✓ 地磅 skill: {len(hints.keywords)} 个关键词, {len(hints.few_shot_examples)} 个示例")
skill_registry.unregister("analyze_weighbridge_data")

# 8. 测试人员 skill 注册
from plugins_func.skills.personnel_skill import register_personnel_skill
register_personnel_skill()
hints = skill_registry.get("analyze_personnel_data")
assert hints is not None
print(f"✓ 人员 skill: {len(hints.keywords)} 个关键词, {len(hints.few_shot_examples)} 个示例")
skill_registry.unregister("analyze_personnel_data")

# 9. 测试车牌 skill 注册
from plugins_func.skills.plate_records_skill import register_plate_records_skill
register_plate_records_skill()
hints = skill_registry.get("query_plate_records")
assert hints is not None
print(f"✓ 车牌 skill: {len(hints.keywords)} 个关键词, {len(hints.few_shot_examples)} 个示例")
skill_registry.unregister("query_plate_records")

# 10. 验证所有函数模块语法正确 (通过 py_compile 验证)
import py_compile
py_compile.compile("main/xiaozhi-server/plugins_func/functions/analyze_weighbridge_data.py", doraise=True)
print("✓ analyze_weighbridge_data.py 语法正确")

py_compile.compile("main/xiaozhi-server/plugins_func/functions/analyze_personnel_data.py", doraise=True)
print("✓ analyze_personnel_data.py 语法正确")

py_compile.compile("main/xiaozhi-server/plugins_func/functions/query_plate_records.py", doraise=True)
print("✓ query_plate_records.py 语法正确")

# 11. 验证 intent_llm 语法正确
py_compile.compile("main/xiaozhi-server/core/providers/intent/intent_llm/intent_llm.py", doraise=True)
print("✓ intent_llm.py 语法正确")

# 12. 验证 intentHandler 语法正确
py_compile.compile("main/xiaozhi-server/core/handle/intentHandler.py", doraise=True)
print("✓ intentHandler.py 语法正确")

# 13. 验证 skill 注册后 keyword_table 和 few_shot 可动态收集
register_weighbridge_skill()
register_personnel_skill()
register_plate_records_skill()
all_skills = skill_registry.get_all()
assert len(all_skills) == 3
kw_table = skill_registry.build_keyword_table()
assert len(kw_table) > 0
few_shots = skill_registry.build_few_shot_examples()
assert len(few_shots) > 0
print(f"✓ 动态收集: 3 个技能, 关键词表长度={len(kw_table)}, 示例数={few_shots.count('```')//2}")

# 14. 验证 intent_llm 中的 reply_result_with_skill_summary 方法已定义
import ast
import textwrap
with open("main/xiaozhi-server/core/providers/intent/intent_llm/intent_llm.py") as f:
    source = f.read()
# 直接搜索方法定义
found = "def reply_result_with_skill_summary" in source
assert found, "reply_result_with_skill_summary method not found in intent_llm.py"
print("✓ IntentProvider.reply_result_with_skill_summary 方法存在")

print("\n===== 所有测试通过 ✓ =====")
