"""학습용 simulation에서 네트워크 변경 전후 품질을 비교합니다."""

# 기존 가상 네트워크 생성 및 NetworkX 경로 확인 함수를 재사용합니다.
from network_simulator import create_network, find_edge_paths


# 테스트에서 변경할 가상 링크와 capacity를 정합니다.
CHANGE_SOURCE = "CORE-01"
CHANGE_DESTINATION = "AGG-01"
NEW_CAPACITY_MBPS = 450
# 테스트가 매번 같은 결과를 내도록 대상 링크 traffic을 500Mbps로 사용합니다.
TEST_TARGET_TRAFFIC_MBPS = 500

# 아래 기준은 실제 통신사나 실제 네트워크 운영 기준이 아닙니다.
# NetOps Inspector의 동작을 확인하기 위한 학습용 simulation rule입니다.
UTILIZATION_NORMAL_LIMIT = 70
UTILIZATION_WARNING_LIMIT = 85
UTILIZATION_FAIL_LIMIT = 100

# 평균 path latency가 before보다 50% 이상 증가하면 WARNING입니다.
LATENCY_WARNING_PERCENT = 50
# 평균 path packet loss가 0.1%p 이상 증가하면 WARNING입니다.
PACKET_LOSS_WARNING_PERCENT_POINT = 0.1


# undirected graph 링크를 항상 같은 딕셔너리 키로 만드는 함수입니다.
def make_link_key(source, destination):
    # 장비 이름을 정렬한 tuple로 만들면 링크 방향이 바뀌어도 같은 키가 됩니다.
    return tuple(sorted((source, destination)))


# 변경 전 링크별 latency와 packet loss를 baseline으로 복사하는 함수입니다.
def capture_link_baseline_metrics(network):
    # 링크별 before 값을 저장할 빈 딕셔너리를 만듭니다.
    baseline_metrics = {}

    # 그래프에 있는 모든 링크를 하나씩 확인합니다.
    for source, destination, link in network.edges(data=True):
        # 링크 양 끝 장비 이름으로 방향에 영향을 받지 않는 키를 만듭니다.
        link_key = make_link_key(source, destination)
        # utilization 효과를 적용하기 전 latency와 loss를 복사합니다.
        baseline_metrics[link_key] = {
            "latency_ms": link["latency_ms"],
            "packet_loss_percent": link["packet_loss_percent"],
        }

    # 여러 번 계산할 때도 변하지 않는 before 기준값을 돌려줍니다.
    return baseline_metrics


# utilization에 따라 학습용 latency/loss 효과를 적용하는 함수입니다.
def apply_utilization_effects(network, baseline_metrics, print_details=True):
    # 기존 analyzer에서는 규칙을 출력하고 Incident 보고서에서는 생략할 수 있습니다.
    if print_details:
        print("[SIMULATION RULE] 실제 통신망 운영 기준이 아닌 프로젝트 검증 규칙입니다.")

    # 그래프에 있는 모든 링크를 하나씩 확인합니다.
    for source, destination, link in network.edges(data=True):
        # DOWN 링크에는 utilization 기반 품질 효과를 적용하지 않습니다.
        if link["status"] == "DOWN":
            continue

        # traffic을 현재 capacity로 나누어 utilization 백분율을 계산합니다.
        utilization = link["traffic_mbps"] / link["capacity_mbps"] * 100
        # 현재 링크의 변경 전 baseline을 딕셔너리에서 가져옵니다.
        baseline = baseline_metrics[make_link_key(source, destination)]

        # utilization이 70% 미만이면 baseline 품질을 그대로 사용합니다.
        if utilization < UTILIZATION_NORMAL_LIMIT:
            latency_multiplier = 1.0
            packet_loss_addition = 0.0
            applied_rule = "utilization < 70%: no quality change"
        # utilization이 70% 이상 85% 미만이면 작은 품질 저하를 적용합니다.
        elif utilization < UTILIZATION_WARNING_LIMIT:
            latency_multiplier = 1.2
            packet_loss_addition = 0.2
            applied_rule = "70% <= utilization < 85%: latency x1.2, loss +0.2%p"
        # utilization이 85% 이상 100% 미만이면 큰 품질 저하를 적용합니다.
        elif utilization < UTILIZATION_FAIL_LIMIT:
            latency_multiplier = 2.0
            packet_loss_addition = 1.0
            applied_rule = "85% <= utilization < 100%: latency x2, loss +1.0%p"
        # utilization이 100% 이상이면 가장 큰 학습용 품질 저하를 적용합니다.
        else:
            latency_multiplier = 4.0
            packet_loss_addition = 5.0
            applied_rule = "utilization >= 100%: latency x4, loss +5.0%p"

        # 누적 계산을 막기 위해 현재값이 아니라 before latency를 곱합니다.
        link["latency_ms"] = round(baseline["latency_ms"] * latency_multiplier, 2)
        # before loss에 규칙 값을 더하고 100%를 넘지 않도록 제한합니다.
        link["packet_loss_percent"] = min(
            100.0,
            round(baseline["packet_loss_percent"] + packet_loss_addition, 2),
        )

        # 어떤 링크에 어떤 규칙이 적용됐는지는 요청한 실행에서만 출력합니다.
        if print_details:
            print(f"- {source} <-> {destination}: {utilization:.2f}%")
            print(f"  Applied: {applied_rule}")
            print(
                f"  Latency: {baseline['latency_ms']} -> {link['latency_ms']} ms, "
                f"Packet Loss: {baseline['packet_loss_percent']} "
                f"-> {link['packet_loss_percent']}%"
            )


# 한 EDGE→CORE 경로의 latency와 단순화된 packet loss를 계산합니다.
def calculate_path_quality(network, path):
    # 경로에 포함된 링크 값을 더할 변수를 0으로 시작합니다.
    path_latency = 0.0
    path_packet_loss = 0.0

    # zip으로 경로에서 서로 이웃한 장비 쌍을 하나씩 가져옵니다.
    for source, destination in zip(path, path[1:]):
        # 현재 장비 쌍을 연결하는 링크 속성을 가져옵니다.
        link = network[source][destination]
        # 링크 latency를 모두 더해 end-to-end path latency를 만듭니다.
        path_latency += link["latency_ms"]
        # 학습용 단순 계산으로 경로의 링크 packet loss를 모두 더합니다.
        path_packet_loss += link["packet_loss_percent"]

    # packet loss 합은 100%를 넘지 않게 제한합니다.
    # 이 값은 실제 E2E loss 공식이 아닌 학습용 단순 합산입니다.
    return path_latency, min(path_packet_loss, 100.0)


# 현재 가상 네트워크의 path 기반 summary 지표를 계산하는 함수입니다.
def collect_quality_metrics(network):
    # NetworkX 경로 탐색으로 모든 EDGE 노드의 CORE-01 경로를 확인합니다.
    edge_paths = find_edge_paths(network)
    # 연결된 EDGE의 path latency와 loss를 저장할 목록입니다.
    path_latencies = []
    path_packet_losses = []

    # EDGE 노드별 경로를 하나씩 확인합니다.
    for path in edge_paths.values():
        # None은 CORE-01까지 연결되지 않은 EDGE이므로 계산에서 제외합니다.
        if path is None:
            continue
        # 현재 EDGE 경로의 latency와 단순 loss를 계산합니다.
        path_latency, path_packet_loss = calculate_path_quality(network, path)
        # 계산한 값을 각 목록에 추가합니다.
        path_latencies.append(path_latency)
        path_packet_losses.append(path_packet_loss)

    # path가 있는 EDGE 수와 없는 EDGE 수를 계산합니다.
    connected_edge_nodes = len(path_latencies)
    disconnected_edge_nodes = len(edge_paths) - connected_edge_nodes

    # 연결된 path가 있으면 평균 및 최대 품질을 계산합니다.
    if path_latencies:
        average_path_latency = sum(path_latencies) / len(path_latencies)
        max_path_latency = max(path_latencies)
        average_packet_loss = sum(path_packet_losses) / len(path_packet_losses)
    # 모든 EDGE가 끊겼다면 계산할 path가 없으므로 0으로 표시합니다.
    else:
        average_path_latency = 0.0
        max_path_latency = 0.0
        average_packet_loss = 0.0

    # DOWN이 아닌 active link만 utilization 계산 대상으로 선택합니다.
    active_links = [
        link
        for _, _, link in network.edges(data=True)
        if link["status"] != "DOWN"
    ]
    # active link 중 가장 높은 utilization을 계산합니다.
    max_utilization = max(
        (
            link["traffic_mbps"] / link["capacity_mbps"] * 100
            for link in active_links
        ),
        default=0.0,
    )

    # 요청한 여섯 가지 network summary를 딕셔너리로 만듭니다.
    summary = {
        "connected_edge_nodes": connected_edge_nodes,
        "disconnected_edge_nodes": disconnected_edge_nodes,
        "average_path_latency_ms": average_path_latency,
        "max_path_latency_ms": max_path_latency,
        "average_packet_loss_percent": average_packet_loss,
        "max_utilization_percent": max_utilization,
    }

    # 기존 dashboard 코드와의 호환을 위해 이전 키도 같은 값으로 제공합니다.
    summary["average_latency_ms"] = average_path_latency
    summary["packet_loss_percent"] = average_packet_loss
    summary["max_traffic_utilization_percent"] = max_utilization
    # 완성된 network summary를 돌려줍니다.
    return summary


# 특정 가상 링크의 capacity를 변경하는 함수입니다.
def change_link_capacity(
    network,
    source,
    destination,
    new_capacity_mbps,
    print_details=True,
):
    # 존재하지 않는 링크를 선택하면 이해하기 쉬운 오류를 만듭니다.
    if not network.has_edge(source, destination):
        raise ValueError(f"가상 링크를 찾을 수 없습니다: {source} <-> {destination}")
    # 0 이하의 capacity는 utilization 계산에 사용할 수 없습니다.
    if new_capacity_mbps <= 0:
        raise ValueError("새 capacity는 0보다 커야 합니다.")

    # 변경할 가상 링크의 속성과 기존 capacity를 가져옵니다.
    link = network[source][destination]
    old_capacity_mbps = link["capacity_mbps"]
    # 실제 네트워크가 아닌 simulation 그래프의 capacity만 변경합니다.
    link["capacity_mbps"] = new_capacity_mbps

    # 기존 analyzer에서는 출력하고 Change Workflow report에서는 생략합니다.
    if print_details:
        print("[SIMULATION ONLY] 실제 통신망을 변경하지 않습니다.")
        print(f"Target Link: {source} <-> {destination}")
        print(f"Capacity: {old_capacity_mbps} -> {new_capacity_mbps} Mbps")


# before와 after 사이의 변화율을 계산하는 함수입니다.
def calculate_change_percent(before_value, after_value):
    # 두 값이 모두 0이면 변화가 없으므로 0%입니다.
    if before_value == 0 and after_value == 0:
        return 0.0
    # before가 0이면 0으로 나눌 수 없어 비율을 계산할 수 없습니다.
    if before_value == 0:
        return None
    # 일반적인 변화율 공식으로 증가 또는 감소 비율을 계산합니다.
    return (after_value - before_value) / before_value * 100


# before와 after summary 및 변화율을 표 형태로 출력하는 함수입니다.
def print_comparison_table(before, after):
    # 표에 표시할 여섯 가지 summary 이름과 키를 정의합니다.
    rows = [
        ("Connected EDGE Nodes", "connected_edge_nodes"),
        ("Disconnected EDGE Nodes", "disconnected_edge_nodes"),
        ("Average Path Latency (ms)", "average_path_latency_ms"),
        ("Max Path Latency (ms)", "max_path_latency_ms"),
        ("Average Packet Loss (%)", "average_packet_loss_percent"),
        ("Max Utilization (%)", "max_utilization_percent"),
    ]

    # 표 제목과 열 이름을 출력합니다.
    print("\n" + "=" * 82)
    print(f"{'Metric':<33}{'Before':>14}{'After':>14}{'Change':>21}")
    print("-" * 82)

    # 여섯 가지 지표를 한 줄씩 출력합니다.
    for label, key in rows:
        # 현재 지표의 변화율을 계산합니다.
        change_percent = calculate_change_percent(before[key], after[key])
        # before가 0이라 계산할 수 없으면 N/A로 표시합니다.
        change_text = "N/A" if change_percent is None else f"{change_percent:+.2f}%"
        # before, after, 변화율을 같은 열 너비로 맞춰 출력합니다.
        print(
            f"{label:<33}{before[key]:>14.2f}{after[key]:>14.2f}"
            f"{change_text:>21}"
        )

    # 표의 끝을 표시합니다.
    print("=" * 82)


# 변경 결과를 PASS, WARNING, FAIL 중 하나로 판단하는 함수입니다.
def evaluate_change(before, after):
    # 판정 근거와 FAIL/WARNING 발견 여부를 저장합니다.
    reasons = []
    has_fail_condition = False
    has_warning_condition = False

    # 연결 가능한 EDGE 수가 감소하면 FAIL 조건입니다.
    if after["connected_edge_nodes"] < before["connected_edge_nodes"]:
        has_fail_condition = True
        reasons.append("Connected EDGE node count decreased")

    # 어떤 active link라도 100% 이상이면 max utilization도 100% 이상입니다.
    if after["max_utilization_percent"] >= UTILIZATION_FAIL_LIMIT:
        has_fail_condition = True
        reasons.append("Link utilization reached or exceeded 100%")

    # 85% 이상이면 FAIL이 아니더라도 최소 WARNING 조건입니다.
    if after["max_utilization_percent"] >= UTILIZATION_WARNING_LIMIT:
        has_warning_condition = True
        reasons.append("Max utilization reached or exceeded 85%")

    # 평균 path latency가 before보다 얼마나 증가했는지 계산합니다.
    latency_change = calculate_change_percent(
        before["average_path_latency_ms"], after["average_path_latency_ms"]
    )
    # 평균 path latency가 50% 이상 증가하면 WARNING 조건입니다.
    if latency_change is not None and latency_change >= LATENCY_WARNING_PERCENT:
        has_warning_condition = True
        reasons.append(f"Average path latency increased by {latency_change:.2f}%")

    # 평균 path loss의 증가량을 퍼센트 포인트 단위로 계산합니다.
    packet_loss_increase = (
        after["average_packet_loss_percent"]
        - before["average_packet_loss_percent"]
    )
    # 설정한 의미 있는 증가 기준 이상이면 WARNING 조건입니다.
    if packet_loss_increase >= PACKET_LOSS_WARNING_PERCENT_POINT:
        has_warning_condition = True
        reasons.append(
            f"Average packet loss increased by {packet_loss_increase:.2f}%p"
        )

    # FAIL 조건이 WARNING보다 우선합니다.
    if has_fail_condition:
        return "FAIL", reasons
    # FAIL은 없지만 WARNING 조건이 있으면 WARNING입니다.
    if has_warning_condition:
        return "WARNING", reasons
    # 어떤 조건도 없으면 PASS와 정상 이유를 돌려줍니다.
    return "PASS", ["No change rule threshold was exceeded"]


# 이 파일을 직접 실행했을 때 학습용 capacity 변경을 시험합니다.
if __name__ == "__main__":
    # 출력이 실제 통신망 분석이 아닌 학습용 simulation임을 알립니다.
    print("[CHANGE ANALYSIS - LEARNING SIMULATION ONLY]")
    print("이 결과는 실제 통신사 또는 실제 네트워크 운영 기준이 아닙니다.\n")

    # 변경 전후 비교에 사용할 가상 네트워크를 만듭니다.
    simulated_network = create_network()
    # 테스트가 매번 재현되도록 대상 링크 traffic을 500Mbps로 설정합니다.
    simulated_network[CHANGE_SOURCE][CHANGE_DESTINATION]["traffic_mbps"] = (
        TEST_TARGET_TRAFFIC_MBPS
    )

    # 변경 전 latency/loss를 누적되지 않는 baseline으로 저장합니다.
    baseline_metrics = capture_link_baseline_metrics(simulated_network)
    # capacity 변경 전 path 기반 summary를 before에 저장합니다.
    before = collect_quality_metrics(simulated_network)

    # 대상 가상 링크의 capacity를 1000Mbps에서 450Mbps로 변경합니다.
    change_link_capacity(
        simulated_network,
        CHANGE_SOURCE,
        CHANGE_DESTINATION,
        NEW_CAPACITY_MBPS,
    )
    # utilization을 baseline 품질에 반영해 after 링크 값을 만듭니다.
    apply_utilization_effects(simulated_network, baseline_metrics)
    # 효과 적용 후 path 기반 summary를 after에 저장합니다.
    after = collect_quality_metrics(simulated_network)

    # before와 after를 표로 비교합니다.
    print_comparison_table(before, after)
    # 모든 판정 조건을 확인해 최종 결과와 근거 목록을 구합니다.
    result, reasons = evaluate_change(before, after)

    # 최종 PASS, WARNING, FAIL 결과와 근거 목록을 출력합니다.
    print(f"\nResult: {result}")
    print("\nReasons:")
    for reason in reasons:
        print(f"- {reason}")
