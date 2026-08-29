import streamlit as st

from tv_quant.model_routing import recommend_model


st.set_page_config(page_title="Codex 模型路由", page_icon="🧭", layout="wide")
st.title("Codex 模型路由")
st.caption("按任务复杂度选择最低足够的模型与推理强度；不以速度作为取舍。")
st.info("此页面只提供建议，不会自动切换当前 Codex 会话，也不会连接 OpenD 或修改项目数据。")

task_text = st.text_area(
    "任务描述",
    placeholder="例如：修复 Futu 数据刷新，并补回归测试",
)
paths_text = st.text_area(
    "涉及文件（可选，每行一个）",
    placeholder="src/tv_quant/pattern_finder/futu_service.py",
)

if task_text.strip():
    decision = recommend_model(
        task_text,
        tuple(line for line in paths_text.splitlines() if line.strip()),
    )
    st.subheader(f"建议：{decision.model} · {decision.reasoning_effort}")
    first, second, third = st.columns(3)
    first.metric("复杂度分数", decision.complexity_score)
    second.metric("风险下限", decision.hard_floor or "无")
    third.metric("优化目标", "Token 最小化")
    st.write("判断依据：")
    for reason in decision.reasons:
        st.write(f"- {reason}")
    st.write("需要升级时：")
    for condition in decision.escalate_when:
        st.write(f"- {condition}")
else:
    st.caption("输入任务描述后会自动生成建议。")
