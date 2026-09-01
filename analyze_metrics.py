"""저장된 네트워크 측정값을 간단히 요약하고 그래프로 표시합니다."""

# 운영체제와 관계없이 파일 경로를 다루기 위해 Path를 불러옵니다.
from pathlib import Path

# JSONL 데이터를 표 형태로 읽고 계산하기 위해 pandas를 불러옵니다.
import pandas as pd
# latency 변화 그래프를 그리기 위해 matplotlib의 pyplot을 불러옵니다.
import matplotlib.pyplot as plt


# 현재 Python 파일을 기준으로 분석할 JSONL 파일의 위치를 정합니다.
DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "network_metrics.jsonl"
# 빈 파일에서도 같은 schema를 유지하기 위한 열 이름입니다.
METRIC_COLUMNS = [
    "timestamp",
    "target",
    "latency_ms",
    "packet_loss_percent",
]


# JSONL 파일을 읽고 분석에 사용할 데이터를 준비하는 함수입니다.
def load_metrics():
    # 파일이 없거나 비어 있으면 필요한 열을 가진 빈 표를 반환합니다.
    if not DATA_FILE.exists() or DATA_FILE.stat().st_size == 0:
        return pd.DataFrame(columns=METRIC_COLUMNS)

    # JSONL 파일의 각 줄을 하나의 JSON 객체로 읽어 표 형태로 만듭니다.
    metrics = pd.read_json(DATA_FILE, lines=True)

    # timestamp 문자열을 pandas가 계산할 수 있는 날짜와 시간 형식으로 바꿉니다.
    metrics["timestamp"] = pd.to_datetime(metrics["timestamp"])

    # 파일 끝에 있는 가장 최근 측정값 100개만 선택합니다.
    recent_metrics = metrics.tail(100).copy()

    # 준비된 최근 측정 데이터를 호출한 곳으로 돌려줍니다.
    return recent_metrics


# latency와 packet loss의 간단한 요약값을 출력하는 함수입니다.
def print_summary(metrics):
    # 최근 측정값의 평균 latency를 계산합니다.
    average_latency = metrics["latency_ms"].mean()
    # 최근 측정값 중 가장 큰 latency를 찾습니다.
    maximum_latency = metrics["latency_ms"].max()
    # 최근 측정값의 평균 packet loss를 계산합니다.
    average_packet_loss = metrics["packet_loss_percent"].mean()

    # 어떤 범위의 데이터를 분석했는지 출력합니다.
    print("=" * 45)
    print("NetOps Inspector - 네트워크 데이터 분석")
    print("-" * 45)
    print(f"분석한 측정값 수     : {len(metrics)}개")
    # 평균값은 소수점 둘째 자리까지 표시합니다.
    print(f"평균 Latency         : {average_latency:.2f} ms")
    # 최대값은 소수점 둘째 자리까지 표시합니다.
    print(f"최대 Latency         : {maximum_latency:.2f} ms")
    # 평균 손실률은 소수점 둘째 자리까지 표시합니다.
    print(f"평균 Packet Loss     : {average_packet_loss:.2f}%")
    print("=" * 45)


# 시간에 따른 latency 변화를 그래프로 보여주는 함수입니다.
def show_latency_graph(metrics):
    # 가로 10인치, 세로 5인치 크기의 그래프 영역을 만듭니다.
    plt.figure(figsize=(10, 5))
    # x축에는 측정 시간, y축에는 latency를 넣어 선 그래프를 그립니다.
    plt.plot(metrics["timestamp"], metrics["latency_ms"], marker="o")
    # 그래프 제목을 지정합니다.
    plt.title("Network Latency Over Time")
    # x축의 의미를 표시합니다.
    plt.xlabel("Timestamp")
    # y축의 단위가 밀리초임을 표시합니다.
    plt.ylabel("Latency (ms)")
    # 값을 비교하기 쉽도록 옅은 격자선을 추가합니다.
    plt.grid(True, alpha=0.3)
    # 긴 시간 글자가 겹치지 않도록 x축 글자를 자동으로 정리합니다.
    plt.gcf().autofmt_xdate()
    # 제목과 축 글자가 잘리지 않도록 여백을 자동으로 조절합니다.
    plt.tight_layout()
    # 완성된 그래프 창을 화면에 표시합니다.
    plt.show()


# 이 파일을 직접 실행했을 때만 아래 코드를 실행합니다.
if __name__ == "__main__":
    # 데이터 파일이 없으면 분석 대신 안내 메시지를 출력합니다.
    if not DATA_FILE.exists():
        print(f"데이터 파일을 찾을 수 없습니다: {DATA_FILE}")
    # 데이터 파일이 비어 있으면 분석 대신 안내 메시지를 출력합니다.
    elif DATA_FILE.stat().st_size == 0:
        print("저장된 측정 데이터가 없습니다.")
    # 파일에 데이터가 있으면 분석을 진행합니다.
    else:
        # JSONL 데이터를 읽고 최근 100개의 측정값을 가져옵니다.
        metrics = load_metrics()
        # 계산한 요약값을 터미널에 출력합니다.
        print_summary(metrics)
        # latency의 시간 변화를 그래프로 표시합니다.
        show_latency_graph(metrics)
