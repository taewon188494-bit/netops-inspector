"""Tick별 Link Traffic 변화와 학습용 Capacity 상태를 분석합니다."""

# 명령줄에서 Target Link와 Traffic 값을 받기 위해 sys를 불러옵니다.
import sys

# 기존 Flow 기반 network를 그대로 생성합니다.
from network_simulator import create_network
# 기존 Time-series와 같은 Link snapshot 구조를 재사용합니다.
from time_series_simulator import collect_link_snapshot


# 실제 KT나 통신사의 증설 기준이 아닌 학습용 Capacity Rule입니다.
CAPACITY_WARNING_RULES = {
    "watch_utilization_percent": 70,
    "warning_utilization_percent": 85,
    "critical_utilization_percent": 100,
}


# Snapshot list에서 Target Link의 Tick별 Traffic/Capacity/Utilization을 꺼냅니다.
def extract_link_trend(snapshots, source, destination):
    history = []

    for snapshot in snapshots:
        link_snapshot = snapshot.get("link_snapshot")
        if link_snapshot is None:
            continue

        snapshot_source = link_snapshot["source"]
        snapshot_destination = link_snapshot["destination"]
        same_direction = (
            snapshot_source == source and snapshot_destination == destination
        )
        opposite_direction = (
            snapshot_source == destination and snapshot_destination == source
        )

        # NetworkX Graph는 무방향이므로 두 방향을 같은 Link로 취급합니다.
        if same_direction or opposite_direction:
            record = {
                "tick": snapshot["tick"],
                "traffic_mbps": link_snapshot["traffic_mbps"],
                "capacity_mbps": link_snapshot["capacity_mbps"],
                "utilization_percent": round(
                    link_snapshot["utilization_percent"],
                    2,
                ),
            }
            history.append(record)

    if not history:
        raise ValueError(f"Snapshot에서 Link를 찾을 수 없습니다: {source} <-> {destination}")
    return history


# 연속 Tick의 현재 utilization에서 이전 utilization을 빼 변화량을 만듭니다.
def calculate_utilization_changes(history):
    changes = []

    for history_index in range(1, len(history)):
        current_utilization = history[history_index]["utilization_percent"]
        previous_utilization = history[history_index - 1]["utilization_percent"]
        change = current_utilization - previous_utilization
        changes.append(round(change, 2))

    return changes


# 모든 변화량의 부호를 확인해 네 가지 단순 Trend 중 하나를 반환합니다.
def determine_trend_direction(changes):
    if not changes:
        return "STABLE"

    every_change_positive = True
    every_change_negative = True
    every_change_zero = True

    for change in changes:
        if change <= 0:
            every_change_positive = False
        if change >= 0:
            every_change_negative = False
        if change != 0:
            every_change_zero = False

    if every_change_positive:
        return "INCREASING"
    if every_change_negative:
        return "DECREASING"
    if every_change_zero:
        return "STABLE"
    return "FLUCTUATING"


# Tick 사이 utilization 변화량의 단순 평균을 계산합니다.
def calculate_average_utilization_change(changes):
    if not changes:
        return 0.0

    average_change = sum(changes) / len(changes)
    return round(average_change, 2)


# 마지막 utilization과 Trend를 학습용 Capacity 상태로 평가합니다.
def evaluate_capacity_status(history, trend_direction):
    if not history:
        raise ValueError("Capacity 상태를 평가할 Traffic History가 없습니다.")

    latest_utilization = history[-1]["utilization_percent"]

    if latest_utilization >= CAPACITY_WARNING_RULES["critical_utilization_percent"]:
        status = "CRITICAL"
        reason = "UTILIZATION_AT_OR_ABOVE_100_PERCENT"
    elif latest_utilization >= CAPACITY_WARNING_RULES["warning_utilization_percent"]:
        status = "WARNING"
        reason = "UTILIZATION_AT_OR_ABOVE_85_PERCENT"
    elif (
        latest_utilization >= CAPACITY_WARNING_RULES["watch_utilization_percent"]
        and trend_direction == "INCREASING"
    ):
        status = "WATCH"
        reason = "UTILIZATION_ABOVE_70_AND_INCREASING"
    else:
        status = "NORMAL"
        reason = "NO_CAPACITY_RULE_THRESHOLD_MATCHED"

    return {
        "status": status,
        "reason": reason,
        "latest_utilization_percent": latest_utilization,
        "trend_direction": trend_direction,
    }


# 평균 변화가 한 Tick 더 유지된다고 가정한 단순 추정값을 계산합니다.
def estimate_next_utilization(history, average_change):
    if not history:
        raise ValueError("다음 utilization을 추정할 Traffic History가 없습니다.")

    latest_utilization = history[-1]["utilization_percent"]
    estimated_next = latest_utilization + average_change
    return round(estimated_next, 2)


# History에서 변화량, 방향, 평균과 Capacity 상태를 순서대로 분석합니다.
def analyze_link_traffic_trend(history):
    changes = calculate_utilization_changes(history)
    trend_direction = determine_trend_direction(changes)
    average_change = calculate_average_utilization_change(changes)
    capacity_evaluation = evaluate_capacity_status(history, trend_direction)
    estimated_next = estimate_next_utilization(history, average_change)

    return {
        "history": history,
        "changes": changes,
        "trend_direction": trend_direction,
        "average_change_percent_per_tick": average_change,
        "latest_utilization_percent": capacity_evaluation[
            "latest_utilization_percent"
        ],
        "estimated_next_utilization_percent": estimated_next,
        "capacity_status": capacity_evaluation["status"],
        "capacity_reason": capacity_evaluation["reason"],
    }


# Target Link Traffic만 Tick별로 바꾸고 기존 Link snapshot 형태로 저장합니다.
def run_traffic_growth_scenario(
    source,
    destination,
    start_traffic_mbps,
    increase_per_tick_mbps,
    total_ticks=5,
):
    if total_ticks <= 0:
        raise ValueError("total_ticks는 1 이상이어야 합니다.")
    if start_traffic_mbps < 0:
        raise ValueError("start_traffic_mbps는 0 이상이어야 합니다.")

    network = create_network()
    if not network.has_edge(source, destination):
        raise ValueError(f"가상 Link를 찾을 수 없습니다: {source} <-> {destination}")

    capacity_mbps = network[source][destination]["capacity_mbps"]
    if capacity_mbps <= 0:
        raise ValueError("Target Link capacity는 0보다 커야 합니다.")

    snapshots = []
    for tick in range(total_ticks):
        # 이 분석 시나리오에서만 Target Link의 Traffic을 명시적으로 바꿉니다.
        traffic_mbps = start_traffic_mbps + increase_per_tick_mbps * tick
        if traffic_mbps < 0:
            raise ValueError("Tick별 traffic_mbps는 0 이상이어야 합니다.")

        network[source][destination]["traffic_mbps"] = traffic_mbps
        snapshot = {
            "tick": tick,
            "link_snapshot": collect_link_snapshot(
                network,
                source,
                destination,
            ),
        }
        snapshots.append(snapshot)

    return snapshots


# Growth Snapshot 생성부터 Trend/Capacity 분석까지 전체 순서를 실행합니다.
def run_traffic_trend_scenario(
    source="CORE-01",
    destination="AGG-01",
    start_traffic_mbps=500,
    increase_per_tick_mbps=100,
    total_ticks=5,
):
    snapshots = run_traffic_growth_scenario(
        source,
        destination,
        start_traffic_mbps,
        increase_per_tick_mbps,
        total_ticks,
    )
    history = extract_link_trend(snapshots, source, destination)
    analysis = analyze_link_traffic_trend(history)
    analysis["source"] = source
    analysis["destination"] = destination
    analysis["capacity_mbps"] = history[0]["capacity_mbps"]
    return analysis


# Tick History와 최종 Trend/Capacity 상태를 기본 print로 출력합니다.
def print_traffic_trend_report(result):
    print("=" * 72)
    print("TRAFFIC TREND / CAPACITY WARNING - LEARNING SIMULATION")
    print("실제 Traffic Forecast 또는 실제 Capacity Planning 결과가 아닙니다.")
    print("=" * 72)
    print(f"Target Link : {result['source']} <-> {result['destination']}")
    print(f"Capacity    : {result['capacity_mbps']} Mbps")

    print("\n[History]")
    for record in result["history"]:
        print(f"T{record['tick']}")
        print(f"  Traffic     : {record['traffic_mbps']} Mbps")
        print(f"  Utilization : {record['utilization_percent']:.2f}%")

    print("\n[Trend]")
    if result["changes"]:
        change_texts = []
        for change in result["changes"]:
            change_texts.append(f"{change:+.2f}%")
        print(f"Changes          : {', '.join(change_texts)}")
    else:
        print("Changes          : None")
    print(f"Direction        : {result['trend_direction']}")
    print(
        f"Average Change   : "
        f"{result['average_change_percent_per_tick']:.2f}% per Tick"
    )
    print(f"Latest Util      : {result['latest_utilization_percent']:.2f}%")
    print(
        f"Estimated Next   : "
        f"{result['estimated_next_utilization_percent']:.2f}%"
    )
    print(f"Capacity Status  : {result['capacity_status']}")
    print(f"Reason           : {result['capacity_reason']}")
    print("=" * 72)


# 이 파일을 직접 실행하면 기본 또는 사용자 지정 Traffic Trend를 분석합니다.
if __name__ == "__main__":
    arguments = sys.argv[1:]

    try:
        if not arguments:
            generated_result = run_traffic_trend_scenario()
        elif len(arguments) == 5:
            start_traffic = int(arguments[2])
            increase_per_tick = int(arguments[3])
            total_ticks = int(arguments[4])
            generated_result = run_traffic_trend_scenario(
                arguments[0],
                arguments[1],
                start_traffic,
                increase_per_tick,
                total_ticks,
            )
        else:
            raise ValueError(
                "사용법: python src/traffic_trend_analyzer.py "
                "[장비1 장비2 start_traffic increase_per_tick total_ticks]"
            )

        print_traffic_trend_report(generated_result)
    except ValueError as error:
        print(f"Traffic Trend 분석을 실행할 수 없습니다: {error}")
