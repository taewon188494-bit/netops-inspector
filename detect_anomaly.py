"""가장 최근 네트워크 측정값을 규칙으로 검사하여 이상 여부를 판단합니다."""

# JSON 문자열을 Python 딕셔너리로 바꾸기 위해 json을 불러옵니다.
import json
# 운영체제와 관계없이 파일 경로를 다루기 위해 Path를 불러옵니다.
from pathlib import Path


# 현재 Python 파일을 기준으로 측정 데이터 파일의 위치를 정합니다.
DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "network_metrics.jsonl"

# 이 값을 초과하면 높은 latency로 판단합니다.
LATENCY_THRESHOLD_MS = 100
# 이 값을 초과하면 높은 packet loss로 판단합니다.
PACKET_LOSS_THRESHOLD_PERCENT = 3


# 발견한 이상 원인의 개수로 전체 상태를 정하는 함수입니다.
def determine_status(reasons):
    # 높은 latency와 높은 packet loss가 함께 발견되면 심각한 상태로 봅니다.
    if len(reasons) >= 2:
        return "CRITICAL"
    # 이상 원인이 하나라면 주의가 필요한 상태로 봅니다.
    if len(reasons) == 1:
        return "WARNING"
    # 이상 원인이 없다면 정상 상태로 봅니다.
    return "NORMAL"


# JSONL 파일에서 가장 최근 측정값 하나를 읽는 함수입니다.
def load_latest_metric():
    # UTF-8 형식으로 데이터 파일을 엽니다.
    with DATA_FILE.open("r", encoding="utf-8") as file:
        # 빈 줄을 제외한 모든 줄을 목록으로 만듭니다.
        lines = [line.strip() for line in file if line.strip()]

    # 저장된 측정값이 하나도 없으면 분석할 수 없다는 오류를 만듭니다.
    if not lines:
        raise ValueError("저장된 측정 데이터가 없습니다.")

    # 파일의 마지막 줄을 가장 최근 JSON 객체로 변환합니다.
    return json.loads(lines[-1])


# latency와 packet loss를 기준값과 비교하여 상태를 판단하는 함수입니다.
def detect_anomaly(metric):
    # 최근 측정값에서 latency를 가져옵니다.
    latency = metric["latency_ms"]
    # 최근 측정값에서 packet loss를 가져옵니다.
    packet_loss = metric["packet_loss_percent"]
    # 발견된 이상 원인을 저장할 빈 목록을 만듭니다.
    reasons = []
    # 사람이 이해하기 쉬운 판단 설명을 저장할 빈 목록을 만듭니다.
    explanations = []

    # latency가 기준값 100ms를 초과했는지 확인합니다.
    if latency is not None and latency > LATENCY_THRESHOLD_MS:
        # 높은 latency를 이상 원인으로 추가합니다.
        reasons.append("HIGH_LATENCY")
        # 실제 값과 기준값을 함께 사용해 판단 이유를 설명합니다.
        explanations.append(
            f"Latency {latency}ms가 기준 {LATENCY_THRESHOLD_MS}ms를 초과했습니다."
        )

    # packet loss가 기준값 3%를 초과했는지 확인합니다.
    if packet_loss is not None and packet_loss > PACKET_LOSS_THRESHOLD_PERCENT:
        # 높은 packet loss를 이상 원인으로 추가합니다.
        reasons.append("HIGH_PACKET_LOSS")
        # 실제 값과 기준값을 함께 사용해 판단 이유를 설명합니다.
        explanations.append(
            f"Packet Loss {packet_loss}%가 기준 "
            f"{PACKET_LOSS_THRESHOLD_PERCENT}%를 초과했습니다."
        )

    # 이상 원인이 하나 이상 있으면 경고 상태로 판단합니다.
    if reasons:
        # 원인 개수로 전체 상태를 정합니다.
        status = determine_status(reasons)
        # 전체 상태와 발견한 모든 원인, 설명을 돌려줍니다.
        return status, reasons, explanations

    # 두 값 모두 기준 이내라면 정상이라고 설명합니다.
    explanations.append(
        f"Latency는 {LATENCY_THRESHOLD_MS}ms 이하이고 Packet Loss는 "
        f"{PACKET_LOSS_THRESHOLD_PERCENT}% 이하이므로 정상입니다."
    )
    # 정상 상태와 NORMAL 원인, 설명을 돌려줍니다.
    return "NORMAL", ["NORMAL"], explanations


# 판단 결과를 읽기 좋은 형식으로 출력하는 함수입니다.
def print_result(metric, status, reasons, explanations):
    # 조건에서 정한 형식으로 상태를 출력합니다.
    print(f"Status: {status}")
    # 원인이 여러 개이면 쉼표로 연결하여 모두 출력합니다.
    print(f"Reason: {', '.join(reasons)}")
    # 최근 측정값의 latency를 출력합니다.
    print(f"Latency: {metric['latency_ms']} ms")
    # 최근 측정값의 packet loss를 출력합니다.
    print(f"Packet Loss: {metric['packet_loss_percent']} %")
    # 판단 기준과 실제 값을 비교한 설명의 제목을 출력합니다.
    print("Explanation:")
    # 설명이 여러 개일 수 있으므로 하나씩 반복하여 출력합니다.
    for explanation in explanations:
        # 각 설명 앞에 하이픈을 붙여 읽기 쉽게 표시합니다.
        print(f"- {explanation}")


# 이 파일을 직접 실행했을 때만 아래 코드를 실행합니다.
if __name__ == "__main__":
    # 데이터 파일이 존재하는지 먼저 확인합니다.
    if not DATA_FILE.exists():
        # 파일이 없으면 사용자가 확인할 수 있도록 경로를 출력합니다.
        print(f"데이터 파일을 찾을 수 없습니다: {DATA_FILE}")
    # 파일이 있으면 가장 최근 데이터를 읽고 판단합니다.
    else:
        # 잘못된 데이터 때문에 프로그램이 긴 오류를 출력하지 않도록 처리합니다.
        try:
            # 가장 최근 측정값 하나를 읽습니다.
            latest_metric = load_latest_metric()
            # 최근 측정값이 정상인지 이상인지 판단합니다.
            status, reasons, explanations = detect_anomaly(latest_metric)
            # 최종 판단 결과와 이유를 터미널에 출력합니다.
            print_result(latest_metric, status, reasons, explanations)
        # 파일이 비었거나 JSON 형식이 잘못된 경우 아래 코드를 실행합니다.
        except (ValueError, json.JSONDecodeError, KeyError) as error:
            # 사용자가 문제를 이해할 수 있도록 오류 내용을 짧게 출력합니다.
            print(f"데이터를 분석할 수 없습니다: {error}")
