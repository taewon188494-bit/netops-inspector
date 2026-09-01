"""지금까지 만든 NetOps Inspector 기능을 한 화면에서 보여줍니다."""

# 함수 실행 중 터미널 출력이 대시보드 서버 로그에 섞이지 않게 처리합니다.
import contextlib
# 임시로 터미널 출력을 받을 문자열 공간을 만들기 위해 io를 불러옵니다.
import io
# 프로젝트 내부 파일 경로를 찾기 위해 Path를 불러옵니다.
from pathlib import Path
# app 폴더에서 src 폴더의 모듈을 불러오기 위해 sys를 사용합니다.
import sys

# 표 형태의 대시보드 데이터를 만들기 위해 pandas를 불러옵니다.
import pandas as pd
# 웹 대시보드를 만들기 위해 streamlit을 불러옵니다.
import streamlit as st


# 현재 파일을 기준으로 프로젝트의 최상위 폴더를 찾습니다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 기존 기능 파일이 들어 있는 src 폴더 경로를 만듭니다.
SRC_DIR = PROJECT_ROOT / "src"
# Python이 src 폴더의 모듈을 찾을 수 있도록 검색 경로 앞에 추가합니다.
sys.path.insert(0, str(SRC_DIR))

# 저장된 측정값을 읽는 기존 함수를 가져옵니다.
from analyze_metrics import load_metrics
# 최근 이상징후를 판단하는 기존 함수들을 가져옵니다.
from detect_anomaly import detect_anomaly, load_latest_metric
# 변경 전후 지표 계산과 판정에 사용하는 기존 함수들을 가져옵니다.
from change_analyzer import (
    CHANGE_DESTINATION,
    CHANGE_SOURCE,
    NEW_CAPACITY_MBPS,
    TEST_TARGET_TRAFFIC_MBPS,
    apply_utilization_effects,
    calculate_change_percent,
    capture_link_baseline_metrics,
    change_link_capacity,
    collect_quality_metrics,
    evaluate_change,
)
# 가상 장애 영향과 원인 후보 분석에 사용하는 기존 함수들을 가져옵니다.
from network_simulator import (
    analyze_link_failure_impact,
    create_network,
    find_root_cause_candidates,
)


# 브라우저 탭 제목과 대시보드 화면 너비를 설정합니다.
st.set_page_config(page_title="NetOps Inspector", layout="wide")
# 화면의 메인 제목을 표시합니다.
st.title("NetOps Inspector")


# 기존 함수가 출력하는 simulation 로그를 숨기고 반환값만 받는 함수입니다.
def run_silently(function, *arguments):
    # 출력 문자열을 임시로 받을 공간을 만듭니다.
    hidden_output = io.StringIO()
    # 이 블록 안의 print 결과를 임시 공간으로 보냅니다.
    with contextlib.redirect_stdout(hidden_output):
        # 전달받은 기존 함수를 실행하고 그 결과를 돌려줍니다.
        return function(*arguments)


# 저장된 실제 PC 측정 데이터를 한 번 읽습니다.
try:
    # analyze_metrics.py의 기존 함수가 최근 100개를 준비합니다.
    metrics = load_metrics()
    # detect_anomaly.py의 기존 함수가 가장 최근 측정값을 읽습니다.
    latest_metric = load_latest_metric()
    # 기존 rule-based 함수로 최근 상태와 이유를 판단합니다.
    anomaly_status, anomaly_reasons, anomaly_explanations = detect_anomaly(latest_metric)
    # 데이터가 정상적으로 준비되었음을 기록합니다.
    data_error = None
# 파일이나 데이터 형식에 문제가 있으면 화면에 표시할 내용을 저장합니다.
except Exception as error:
    # 데이터가 없을 때 나머지 화면이 중단되지 않도록 빈 표를 만듭니다.
    metrics = pd.DataFrame()
    # 최근 측정값을 사용할 수 없음을 표시합니다.
    latest_metric = None
    # 전체 상태는 데이터 확인이 필요하므로 CRITICAL로 표시합니다.
    anomaly_status = "CRITICAL"
    # 오류 원인을 목록 형태로 보관합니다.
    anomaly_reasons = ["DATA_UNAVAILABLE"]
    # 사람이 확인할 수 있는 오류 설명을 보관합니다.
    anomaly_explanations = [str(error)]
    # 각 탭에서 같은 오류를 안내할 수 있도록 저장합니다.
    data_error = str(error)


# 가상 링크 장애 시나리오를 만들고 기존 분석 함수를 실행합니다.
incident_network = create_network()
# CORE-01과 AGG-01 사이의 가상 링크 장애 영향 범위를 구합니다.
affected_nodes = run_silently(
    analyze_link_failure_impact, incident_network, "CORE-01", "AGG-01"
)
# 장애가 적용된 같은 그래프에서 기존 Root Cause Candidate 함수를 실행합니다.
root_cause_candidates = find_root_cause_candidates(incident_network)


# 변경 전후 비교를 위한 별도의 가상 네트워크를 만듭니다.
change_network = create_network()
# change_analyzer.py와 같은 재현 가능한 학습용 traffic 값을 사용합니다.
change_network[CHANGE_SOURCE][CHANGE_DESTINATION]["traffic_mbps"] = (
    TEST_TARGET_TRAFFIC_MBPS
)
# utilization 효과가 누적되지 않도록 변경 전 링크 품질을 저장합니다.
change_baseline = capture_link_baseline_metrics(change_network)
# 기존 함수로 변경 전 지표를 before 데이터에 저장합니다.
before = collect_quality_metrics(change_network)
# 기존 함수를 이용해 지정한 링크의 가상 capacity를 변경합니다.
run_silently(
    change_link_capacity,
    change_network,
    CHANGE_SOURCE,
    CHANGE_DESTINATION,
    NEW_CAPACITY_MBPS,
)
# 학습용 utilization rule로 baseline 기준 latency와 loss를 갱신합니다.
run_silently(apply_utilization_effects, change_network, change_baseline)
# 기존 함수로 변경 후 지표를 after 데이터에 저장합니다.
after = collect_quality_metrics(change_network)
# 기존 판정 함수로 최종 결과와 이유를 구합니다.
change_result, change_reasons = evaluate_change(before, after)


# 요청한 네 영역을 탭으로 만듭니다.
overview_tab, monitoring_tab, incident_tab, change_tab = st.tabs(
    ["Overview", "Monitoring", "Incident", "Change Analysis"]
)


# 첫 번째 Overview 영역을 구성합니다.
with overview_tab:
    # 세 개의 핵심 값을 가로로 배치합니다.
    status_column, latency_column, loss_column = st.columns(3)
    # 기존 이상 탐지 결과를 전체 상태로 표시합니다.
    status_column.metric("Overall Status", anomaly_status)

    # 실제 측정 데이터가 있으면 평균 지표를 계산해 표시합니다.
    if not metrics.empty:
        # pandas의 평균 함수로 최근 데이터의 평균 latency를 표시합니다.
        latency_column.metric("Average Latency", f"{metrics['latency_ms'].mean():.2f} ms")
        # pandas의 평균 함수로 최근 데이터의 평균 packet loss를 표시합니다.
        loss_column.metric(
            "Average Packet Loss", f"{metrics['packet_loss_percent'].mean():.2f}%"
        )
    # 데이터가 없으면 숫자 대신 N/A를 표시합니다.
    else:
        latency_column.metric("Average Latency", "N/A")
        loss_column.metric("Average Packet Loss", "N/A")

    # 실제 PC 측정 데이터에서 나온 영역임을 설명합니다.
    st.caption("Overview는 data/network_metrics.jsonl의 최근 측정값을 사용합니다.")
    # 읽기 오류가 있다면 사용자가 원인을 확인할 수 있게 표시합니다.
    if data_error:
        st.error(f"측정 데이터를 읽을 수 없습니다: {data_error}")


# 두 번째 Monitoring 영역을 구성합니다.
with monitoring_tab:
    # 실제 측정 데이터가 있으면 시간 순서 그래프 두 개를 표시합니다.
    if not metrics.empty:
        # timestamp를 그래프의 x축으로 사용할 표를 준비합니다.
        chart_data = metrics.set_index("timestamp")
        # 시간에 따른 latency 변화를 Streamlit 선 그래프로 표시합니다.
        st.subheader("Latency Over Time")
        st.line_chart(chart_data[["latency_ms"]])
        # 시간에 따른 packet loss 변화를 Streamlit 선 그래프로 표시합니다.
        st.subheader("Packet Loss Over Time")
        st.line_chart(chart_data[["packet_loss_percent"]])
    # 데이터가 없으면 그래프 대신 안내 문구를 표시합니다.
    else:
        st.info("표시할 monitoring 데이터가 없습니다.")


# 세 번째 Incident 영역을 구성합니다.
with incident_tab:
    # 실제 PC 데이터에서 찾은 가장 최근 이상징후를 표시합니다.
    st.subheader("최근 이상징후")
    st.write(f"Status: **{anomaly_status}**")
    st.write(f"Reason: {', '.join(anomaly_reasons)}")
    # 기존 탐지 함수가 만든 설명을 하나씩 표시합니다.
    for explanation in anomaly_explanations:
        st.write(f"- {explanation}")

    # 아래 결과는 실제 장애가 아닌 simulation임을 명확히 표시합니다.
    st.warning(
        "아래 Root Cause Candidate와 Affected Nodes는 "
        "CORE-01 <-> AGG-01 링크 DOWN simulation 결과입니다."
    )
    # 기존 원인 후보 분석 결과를 표시합니다.
    st.subheader("Root Cause Candidate")
    # 각 후보의 원인과 근거를 화면에 출력합니다.
    for candidate in root_cause_candidates:
        st.write(f"**{candidate['cause']}** — {candidate['target']}")
        st.write(f"근거: {candidate['evidence']}")
        st.write(f"설명: {candidate['explanation']}")

    # 기존 영향 분석 함수가 반환한 EDGE 노드 목록을 표시합니다.
    st.subheader("Affected Nodes")
    # 영향받은 노드를 하나씩 목록으로 출력합니다.
    for node in affected_nodes:
        st.write(f"- {node}")


# 네 번째 Change Analysis 영역을 구성합니다.
with change_tab:
    # 이 결과도 실제 변경이 아닌 simulation임을 명확히 표시합니다.
    st.info(
        f"SIMULATION ONLY: {CHANGE_SOURCE} <-> {CHANGE_DESTINATION}의 capacity를 "
        f"{NEW_CAPACITY_MBPS} Mbps로 변경한 비교입니다."
    )
    # 표에 표시할 지표 이름과 딕셔너리 키를 정의합니다.
    comparison_rows = [
        ("Average Latency (ms)", "average_latency_ms"),
        ("Packet Loss (%)", "packet_loss_percent"),
        ("Max Traffic Utilization (%)", "max_traffic_utilization_percent"),
        ("Connected EDGE Nodes", "connected_edge_nodes"),
    ]
    # 기존 함수 결과를 대시보드 표에 맞는 행 목록으로 바꿉니다.
    comparison_data = []
    # 각 지표의 before, after, 변화율을 하나씩 준비합니다.
    for label, key in comparison_rows:
        # 기존 변화율 계산 함수를 재사용합니다.
        change_percent = calculate_change_percent(before[key], after[key])
        # 표에 들어갈 한 행을 추가합니다.
        comparison_data.append(
            {
                "Metric": label,
                "Before": round(before[key], 2),
                "After": round(after[key], 2),
                "Change": "N/A" if change_percent is None else f"{change_percent:+.2f}%",
            }
        )
    # 준비한 before/after 데이터를 표로 표시합니다.
    st.dataframe(pd.DataFrame(comparison_data), width="stretch", hide_index=True)
    # 기존 변경 판정 함수가 계산한 최종 결과와 이유를 표시합니다.
    st.subheader(f"Final Result: {change_result}")
    # 판정 근거가 여러 개일 수 있으므로 하나씩 출력합니다.
    for reason in change_reasons:
        st.write(f"- {reason}")
