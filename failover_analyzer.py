"""NetworkX alternative path를 이용한 학습용 failover simulation입니다."""

# NetworkX의 path 탐색 기능을 사용합니다.
import networkx as nx

# 기존 utilization rule과 path 기반 network summary 함수를 재사용합니다.
from change_analyzer import (
    apply_utilization_effects,
    capture_link_baseline_metrics,
    collect_quality_metrics,
)
# 기존 가상 topology와 active graph 생성 함수를 재사용합니다.
from network_simulator import create_active_network, create_network


# 기본 테스트에서 DOWN 처리할 primary link입니다.
FAILED_LINK = ("AGG-01", "CORE-01")
# 결과를 재현하기 위해 failed primary link traffic을 500Mbps로 설정합니다.
TEST_PRIMARY_TRAFFIC_MBPS = 500
# path latency가 before보다 50% 이상 증가하면 DEGRADED로 판단합니다.
FAILOVER_LATENCY_DEGRADE_PERCENT = 50
# path loss가 0.1%p 이상 증가하면 DEGRADED로 판단합니다.
FAILOVER_LOSS_DEGRADE_PERCENT_POINT = 0.1
# path 안의 max utilization이 85% 이상이면 DEGRADED로 판단합니다.
FAILOVER_UTILIZATION_DEGRADE_PERCENT = 85


# DOWN link를 제외하고 source에서 target까지 active path를 찾는 함수입니다.
def find_active_path(network, source, target):
    # network_simulator의 기존 함수로 DOWN link가 제거된 graph를 만듭니다.
    active_network = create_active_network(network)
    # 두 Node 사이에 사용할 수 있는 path가 있는지 확인합니다.
    if nx.has_path(active_network, source, target):
        # 실제 routing protocol이 아니라 routing_cost 합이 가장 작은 학습용
        # NetworkX weighted shortest path 하나를 반환합니다. ECMP는 구현하지 않습니다.
        return nx.shortest_path(
            active_network,
            source,
            target,
            weight="routing_cost",
        )
    # 사용할 수 있는 alternative path가 없으면 None을 반환합니다.
    return None


# 하나의 path에 포함된 link 품질을 단순 계산하는 함수입니다.
def calculate_path_metrics(network, path):
    # path가 없으면 품질을 계산할 수 없으므로 None을 반환합니다.
    if path is None:
        return None

    # path에 포함된 link latency와 loss를 더할 변수를 만듭니다.
    total_latency = 0.0
    path_packet_loss = 0.0
    # path link 중 가장 높은 utilization을 저장합니다.
    max_utilization = 0.0

    # zip으로 path에서 서로 이웃한 Node 쌍을 하나씩 가져옵니다.
    for source, destination in zip(path, path[1:]):
        # 현재 Node 쌍을 연결하는 link 속성을 가져옵니다.
        link = network[source][destination]
        # path에 포함된 모든 link latency를 합산합니다.
        total_latency += link["latency_ms"]
        # 학습용 단순 모델로 모든 link packet loss를 합산합니다.
        path_packet_loss += link["packet_loss_percent"]
        # 현재 link utilization을 계산합니다.
        utilization = link["traffic_mbps"] / link["capacity_mbps"] * 100
        # 지금까지 확인한 값 중 가장 높은 utilization을 저장합니다.
        max_utilization = max(max_utilization, utilization)

    # packet loss 합이 100%를 넘지 않도록 제한합니다.
    # 이는 실제 E2E loss 물리 계산이 아닌 learning simulation의 단순 합산입니다.
    path_packet_loss = min(path_packet_loss, 100.0)

    # 세 가지 path metric을 딕셔너리로 반환합니다.
    return {
        "total_latency_ms": total_latency,
        "path_packet_loss_percent": path_packet_loss,
        "max_utilization_percent": max_utilization,
    }


# 모든 EDGE Node의 현재 path와 metric을 기록하는 함수입니다.
def collect_edge_path_records(network):
    # 이름이 EDGE-로 시작하는 Node만 정렬해서 선택합니다.
    edge_nodes = sorted(node for node in network.nodes() if node.startswith("EDGE-"))
    # EDGE별 결과를 저장할 빈 딕셔너리를 만듭니다.
    records = {}

    # 각 EDGE에서 CORE-01까지 active path를 확인합니다.
    for edge_node in edge_nodes:
        # DOWN link를 제외한 path를 찾습니다.
        path = find_active_path(network, edge_node, "CORE-01")
        # path와 해당 품질 지표를 함께 저장합니다.
        records[edge_node] = {
            "path": path,
            "metrics": calculate_path_metrics(network, path),
        }

    # 모든 EDGE의 기록을 반환합니다.
    return records


# failed primary traffic을 alternative path의 backup link에 한 번 더하는 함수입니다.
def redistribute_failed_traffic(network, failed_link, failed_traffic_mbps):
    # DOWN된 link의 양 끝 Node 사이에서 alternative path를 찾습니다.
    alternative_path = find_active_path(network, failed_link[0], failed_link[1])
    # alternative path가 없으면 traffic을 옮길 backup link도 없습니다.
    if alternative_path is None:
        return None

    # alternative path에 포함된 link를 하나씩 확인합니다.
    for source, destination in zip(alternative_path, alternative_path[1:]):
        # 현재 link 속성을 가져옵니다.
        link = network[source][destination]
        # BACKUP 역할을 가진 link에만 failed traffic을 한 번 추가합니다.
        if link.get("role") == "BACKUP":
            # 변경 전 backup traffic을 출력과 비교를 위해 저장합니다.
            before_traffic = link["traffic_mbps"]
            # 실제 traffic engineering이 아닌 단순 학습 모델로 전체 traffic을 더합니다.
            link["traffic_mbps"] = before_traffic + failed_traffic_mbps
            # 어떤 값이 이동했는지 확인할 수 있도록 결과를 반환합니다.
            return {
                "link": (source, destination),
                "before_traffic_mbps": before_traffic,
                "after_traffic_mbps": link["traffic_mbps"],
            }

    # alternative path에 BACKUP 역할 link가 없다면 재분배하지 않습니다.
    return None


# before/after path와 metric을 이용해 EDGE별 상태를 정하는 함수입니다.
def classify_edge_result(before_record, after_record):
    # after path가 없으면 CORE-01에 연결할 수 없습니다.
    if after_record["path"] is None:
        return "DISCONNECTED"
    # path가 바뀌지 않았다면 기존 primary path를 계속 사용합니다.
    if before_record["path"] == after_record["path"]:
        return "NORMAL"

    # 여기부터는 alternative path를 사용한 failover 상태입니다.
    before_metrics = before_record["metrics"]
    after_metrics = after_record["metrics"]
    # before latency 대비 after latency 증가율을 계산합니다.
    latency_increase_percent = (
        (after_metrics["total_latency_ms"] - before_metrics["total_latency_ms"])
        / before_metrics["total_latency_ms"]
        * 100
    )
    # path packet loss가 몇 %p 증가했는지 계산합니다.
    loss_increase = (
        after_metrics["path_packet_loss_percent"]
        - before_metrics["path_packet_loss_percent"]
    )

    # 높은 utilization, latency 증가, loss 증가 중 하나라도 있으면 DEGRADED입니다.
    if (
        after_metrics["max_utilization_percent"]
        >= FAILOVER_UTILIZATION_DEGRADE_PERCENT
        or latency_increase_percent >= FAILOVER_LATENCY_DEGRADE_PERCENT
        or loss_increase >= FAILOVER_LOSS_DEGRADE_PERCENT_POINT
    ):
        return "DEGRADED"
    # path는 바뀌었지만 품질 저하 기준에 해당하지 않으면 성공입니다.
    return "FAILOVER_SUCCESS"


# primary link 장애 전후의 failover 결과를 만드는 함수입니다.
def simulate_failover(network, failed_link, print_rule_details=True):
    # 선택한 failed link가 graph에 존재하는지 확인합니다.
    if not network.has_edge(*failed_link):
        raise ValueError(f"가상 link를 찾을 수 없습니다: {failed_link}")
    # 이미 DOWN인 link에 traffic을 다시 더하면 중복 계산되므로 실행을 막습니다.
    if network[failed_link[0]][failed_link[1]]["status"] == "DOWN":
        raise ValueError("선택한 가상 link는 이미 DOWN 상태입니다.")

    # utilization 효과가 누적되지 않도록 모든 link의 before 품질을 저장합니다.
    baseline_metrics = capture_link_baseline_metrics(network)
    # 장애 전 EDGE별 primary path와 품질을 기록합니다.
    before_records = collect_edge_path_records(network)
    # 장애 전 network-level summary를 기록합니다.
    before_summary = collect_quality_metrics(network)
    # backup link의 장애 전 utilization을 기록합니다.
    backup_before = network["AGG-01"]["AGG-02"]
    backup_utilization_before = (
        backup_before["traffic_mbps"] / backup_before["capacity_mbps"] * 100
    )

    # failed primary link의 기존 traffic을 재분배 전에 한 번만 저장합니다.
    failed_traffic_mbps = network[failed_link[0]][failed_link[1]]["traffic_mbps"]
    # 선택한 primary link를 가상으로 DOWN 처리합니다.
    network[failed_link[0]][failed_link[1]]["status"] = "DOWN"
    # alternative path의 BACKUP link에 failed traffic을 한 번 추가합니다.
    redistribution = redistribute_failed_traffic(
        network, failed_link, failed_traffic_mbps
    )
    # change_analyzer와 동일한 학습용 utilization 품질 rule을 재사용합니다.
    apply_utilization_effects(
        network,
        baseline_metrics,
        print_details=print_rule_details,
    )

    # 장애와 traffic 재분배 후 EDGE별 path와 품질을 다시 기록합니다.
    after_records = collect_edge_path_records(network)
    # failover 후 network-level summary를 기록합니다.
    after_summary = collect_quality_metrics(network)
    # backup link의 장애 후 utilization을 기록합니다.
    backup_after = network["AGG-01"]["AGG-02"]
    backup_utilization_after = (
        backup_after["traffic_mbps"] / backup_after["capacity_mbps"] * 100
    )

    # 각 EDGE Node의 최종 상태를 저장합니다.
    edge_statuses = {}
    for edge_node in before_records:
        edge_statuses[edge_node] = classify_edge_result(
            before_records[edge_node], after_records[edge_node]
        )

    # path가 변경된 EDGE를 failover node로 선택합니다.
    failover_nodes = [
        edge_node
        for edge_node in before_records
        if before_records[edge_node]["path"] != after_records[edge_node]["path"]
        and after_records[edge_node]["path"] is not None
    ]
    # after path가 없는 EDGE를 disconnected node로 선택합니다.
    disconnected_nodes = [
        edge_node
        for edge_node, record in after_records.items()
        if record["path"] is None
    ]

    # 전체 상태는 DISCONNECTED, DEGRADED, FAILOVER_SUCCESS, NORMAL 순서로 정합니다.
    if disconnected_nodes:
        overall = "DISCONNECTED"
    elif "DEGRADED" in edge_statuses.values():
        overall = "DEGRADED"
    elif failover_nodes:
        overall = "FAILOVER_SUCCESS"
    else:
        overall = "NORMAL"

    # 출력과 테스트에서 사용할 모든 결과를 딕셔너리로 반환합니다.
    return {
        "failed_link": failed_link,
        "before_records": before_records,
        "after_records": after_records,
        "before_summary": before_summary,
        "after_summary": after_summary,
        "edge_statuses": edge_statuses,
        "failover_nodes": failover_nodes,
        "disconnected_nodes": disconnected_nodes,
        "backup_utilization_before": backup_utilization_before,
        "backup_utilization_after": backup_utilization_after,
        "redistribution": redistribution,
        "overall": overall,
    }


# EDGE별 before/after 결과와 전체 summary를 출력하는 함수입니다.
def print_failover_result(result):
    # 실제 routing이나 traffic engineering이 아닌 학습용임을 명확히 표시합니다.
    print("[FAILOVER SIMULATION - LEARNING ONLY]")
    print("실제 routing protocol 또는 실제 traffic engineering 구현이 아닙니다.\n")
    print(f"Failed Link: {result['failed_link'][0]} <-> {result['failed_link'][1]}")

    # Before와 After EDGE별 path 품질을 순서대로 출력합니다.
    for section, records in (
        ("Before", result["before_records"]),
        ("After", result["after_records"]),
    ):
        print(f"\n{section}:")
        for edge_node, record in records.items():
            print(f"\n{edge_node}")
            if record["path"] is None:
                print("Path: None")
                print("Status: DISCONNECTED")
            else:
                print(f"Path: {' -> '.join(record['path'])}")
                print(f"Latency: {record['metrics']['total_latency_ms']:.2f} ms")
                print(
                    f"Packet Loss: "
                    f"{record['metrics']['path_packet_loss_percent']:.2f}%"
                )
                # Before는 모두 NORMAL, After는 계산한 상태를 표시합니다.
                status = (
                    "NORMAL"
                    if section == "Before"
                    else result["edge_statuses"][edge_node]
                )
                print(f"Status: {status}")

    # failed traffic이 backup link에 어떻게 더해졌는지 출력합니다.
    if result["redistribution"]:
        redistribution = result["redistribution"]
        print("\nTraffic Redistribution (Simplified Learning Rule):")
        print(
            f"- {redistribution['link'][0]} <-> {redistribution['link'][1]}: "
            f"{redistribution['before_traffic_mbps']} -> "
            f"{redistribution['after_traffic_mbps']} Mbps"
        )

    # 요청한 before/after network-level summary를 출력합니다.
    before = result["before_summary"]
    after = result["after_summary"]
    print("\nSummary:")
    print(f"Connected EDGE Nodes: {before['connected_edge_nodes']} -> {after['connected_edge_nodes']}")
    print(f"Disconnected EDGE Nodes: {before['disconnected_edge_nodes']} -> {after['disconnected_edge_nodes']}")
    print(f"Failover Nodes: {len(result['failover_nodes'])} ({', '.join(result['failover_nodes'])})")
    print(f"Average Path Latency: {before['average_path_latency_ms']:.2f} -> {after['average_path_latency_ms']:.2f} ms")
    print(f"Max Path Latency: {before['max_path_latency_ms']:.2f} -> {after['max_path_latency_ms']:.2f} ms")
    print(f"Average Packet Loss: {before['average_packet_loss_percent']:.2f} -> {after['average_packet_loss_percent']:.2f}%")
    print(f"Max Utilization: {before['max_utilization_percent']:.2f} -> {after['max_utilization_percent']:.2f}%")
    print(f"Backup Link Utilization: {result['backup_utilization_before']:.2f} -> {result['backup_utilization_after']:.2f}%")
    print(f"\nOverall: {result['overall']}")
    print("Connectivity가 유지돼도 Performance는 변할 수 있습니다.")


# 이 파일을 직접 실행하면 기본 primary link 장애를 시험합니다.
if __name__ == "__main__":
    # redundant topology를 새로 만듭니다.
    simulated_network = create_network()
    # 기본 테스트 결과를 재현하기 위해 failed primary traffic을 500Mbps로 고정합니다.
    simulated_network[FAILED_LINK[0]][FAILED_LINK[1]]["traffic_mbps"] = (
        TEST_PRIMARY_TRAFFIC_MBPS
    )
    # primary link 장애와 failover를 simulation합니다.
    failover_result = simulate_failover(simulated_network, FAILED_LINK)
    # EDGE별 path와 전체 결과를 출력합니다.
    print_failover_result(failover_result)
