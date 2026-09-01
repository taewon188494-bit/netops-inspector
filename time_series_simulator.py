"""여러 simulation Tick에서 네트워크 상태 변화를 관찰합니다."""

# 명령줄에서 장애 종류와 대상을 간단히 받기 위해 sys를 불러옵니다.
import sys

# 기존 network summary 계산 함수를 그대로 재사용합니다.
from change_analyzer import collect_quality_metrics
# 기존 failover 함수가 Link DOWN과 우회 분석을 한 번 수행합니다.
from failover_analyzer import simulate_failover
# 기존 topology, 장애 주입과 path 계산 함수를 그대로 재사용합니다.
from network_simulator import (
    create_network,
    find_edge_paths,
    inject_congestion,
    inject_device_overload,
)
# 각 Tick의 기존 Service E2E Quality 판정 결과를 그대로 재사용합니다.
from service_quality_analyzer import analyze_all_services


# 인자가 없을 때 사용할 대표 CONGESTION Link입니다.
DEFAULT_CONGESTION_LINK = ("AGG-01", "EDGE-01")
# T0부터 T4까지 다섯 개의 학습용 Tick을 사용합니다.
DEFAULT_TOTAL_TICKS = 5
# 세 번째 순서인 T2에서 Event를 발생시킵니다.
DEFAULT_EVENT_TICK = 2


# 현재 Tick의 전체 network quality를 하나의 dict로 만듭니다.
def collect_metric_snapshot(network, tick):
    # 기존 함수가 연결 EDGE 수, latency, loss와 utilization을 계산합니다.
    summary = collect_quality_metrics(network)

    snapshot = {
        "tick": tick,
        "connected_edge_nodes": summary["connected_edge_nodes"],
        "disconnected_edge_nodes": summary["disconnected_edge_nodes"],
        "average_path_latency_ms": summary["average_path_latency_ms"],
        "average_packet_loss_percent": summary[
            "average_packet_loss_percent"
        ],
        "max_utilization_percent": summary["max_utilization_percent"],
    }
    return snapshot


# 관심 Link 하나의 현재 값을 읽어 상세 snapshot으로 만듭니다.
def collect_link_snapshot(network, source, destination):
    if not network.has_edge(source, destination):
        raise ValueError(f"가상 링크를 찾을 수 없습니다: {source} <-> {destination}")

    link = network[source][destination]
    traffic_mbps = link["traffic_mbps"]
    capacity_mbps = link["capacity_mbps"]
    # 현재 traffic과 capacity로 이 Tick의 utilization을 직접 계산합니다.
    utilization_percent = traffic_mbps / capacity_mbps * 100

    link_snapshot = {
        "source": source,
        "destination": destination,
        "traffic_mbps": traffic_mbps,
        "capacity_mbps": capacity_mbps,
        "utilization_percent": utilization_percent,
        "latency_ms": link["latency_ms"],
        "packet_loss_percent": link["packet_loss_percent"],
        "status": link["status"],
    }
    return link_snapshot


# 관심 Device 하나의 현재 CPU 값을 읽어 상세 snapshot으로 만듭니다.
def collect_device_snapshot(network, device):
    if device not in network:
        raise ValueError(f"가상 장비를 찾을 수 없습니다: {device}")

    # CPU 값이 아직 설정되지 않은 정상 Tick은 일관되게 0%로 표시합니다.
    cpu_usage_percent = network.nodes[device].get("cpu_usage", 0)
    device_snapshot = {
        "device": device,
        "cpu_usage_percent": cpu_usage_percent,
    }
    return device_snapshot


# Tick 수와 Event Tick이 simulation 범위에 맞는지 확인합니다.
def validate_clock_settings(total_ticks, event_tick):
    if total_ticks <= 0:
        raise ValueError("total_ticks는 1 이상이어야 합니다.")
    if event_tick < 0 or event_tick >= total_ticks:
        raise ValueError("event_tick은 simulation Tick 범위 안에 있어야 합니다.")


# CONGESTION 전후 Link와 network metric을 여러 Tick에 걸쳐 기록합니다.
def run_congestion_time_series(
    source,
    destination,
    total_ticks=DEFAULT_TOTAL_TICKS,
    event_tick=DEFAULT_EVENT_TICK,
):
    validate_clock_settings(total_ticks, event_tick)
    network = create_network()
    snapshots = []
    event_active = False

    for tick in range(total_ticks):
        # Event Tick에서만 혼잡을 한 번 주입합니다. 이후에는 변경 상태를 관찰합니다.
        if tick == event_tick:
            inject_congestion(
                network,
                source,
                destination,
                print_details=False,
            )
            event_active = True

        # 상태 변경이 끝난 뒤 이 Tick의 현재 network metric을 관찰합니다.
        snapshot = collect_metric_snapshot(network, tick)
        if event_active:
            snapshot["event"] = "CONGESTION"
        else:
            snapshot["event"] = "NORMAL"
        snapshot["event_active"] = event_active
        snapshot["link_snapshot"] = collect_link_snapshot(
            network,
            source,
            destination,
        )
        snapshot["service_quality"] = analyze_all_services(network)
        snapshots.append(snapshot)

    return snapshots


# DEVICE_OVERLOAD 전후 CPU와 network metric을 여러 Tick에 걸쳐 기록합니다.
def run_device_overload_time_series(
    device,
    total_ticks=DEFAULT_TOTAL_TICKS,
    event_tick=DEFAULT_EVENT_TICK,
):
    validate_clock_settings(total_ticks, event_tick)
    network = create_network()
    snapshots = []
    event_active = False

    for tick in range(total_ticks):
        # Event Tick에서만 CPU 95%를 한 번 설정하고 이후 같은 상태를 관찰합니다.
        if tick == event_tick:
            inject_device_overload(network, device, print_details=False)
            event_active = True

        snapshot = collect_metric_snapshot(network, tick)
        if event_active:
            snapshot["event"] = "DEVICE_OVERLOAD"
        else:
            snapshot["event"] = "NORMAL"
        snapshot["event_active"] = event_active
        snapshot["device_snapshot"] = collect_device_snapshot(network, device)
        snapshot["service_quality"] = analyze_all_services(network)
        snapshots.append(snapshot)

    return snapshots


# LINK_FAILURE 전후 Link 상태와 EDGE path를 여러 Tick에 걸쳐 기록합니다.
def run_link_failure_time_series(
    source,
    destination,
    total_ticks=DEFAULT_TOTAL_TICKS,
    event_tick=DEFAULT_EVENT_TICK,
):
    validate_clock_settings(total_ticks, event_tick)
    network = create_network()
    snapshots = []
    event_active = False
    failed_link = (source, destination)

    for tick in range(total_ticks):
        # simulate_failover()는 같은 Link에 다시 실행할 수 없으므로 T2에서만 호출합니다.
        if tick == event_tick:
            simulate_failover(
                network,
                failed_link,
                print_rule_details=False,
            )
            event_active = True

        snapshot = collect_metric_snapshot(network, tick)
        if event_active:
            snapshot["event"] = "LINK_FAILURE"
        else:
            snapshot["event"] = "NORMAL"
        snapshot["event_active"] = event_active
        snapshot["link_snapshot"] = collect_link_snapshot(
            network,
            source,
            destination,
        )
        # 기존 함수로 각 Tick의 EDGE → CORE path를 그대로 기록합니다.
        snapshot["edge_paths"] = find_edge_paths(network)
        snapshot["service_quality"] = analyze_all_services(network)
        snapshots.append(snapshot)

    return snapshots


# 공통 network summary를 Tick 순서의 간단한 표로 출력합니다.
def print_time_series(snapshots):
    print("=" * 88)
    print("TIME SERIES SIMULATION - DISCRETE TICKS ONLY")
    print("Tick은 실제 초/분이 아니며 상태 변화 순서를 나타내는 학습용 step입니다.")
    print("=" * 88)
    print(
        "Tick | Event           | Connected | Disconnected | Avg Latency | "
        "Avg Loss | Max Util"
    )
    print("-" * 88)

    for snapshot in snapshots:
        tick_text = f"T{snapshot['tick']}"
        print(
            f"{tick_text:<4} | "
            f"{snapshot['event']:<15} | "
            f"{snapshot['connected_edge_nodes']:<9} | "
            f"{snapshot['disconnected_edge_nodes']:<12} | "
            f"{snapshot['average_path_latency_ms']:>8.2f} ms | "
            f"{snapshot['average_packet_loss_percent']:>7.2f}% | "
            f"{snapshot['max_utilization_percent']:>7.2f}%"
        )

    print("=" * 88)


# Event 종류에 맞는 Link, Device 또는 EDGE path 상세값을 출력합니다.
def print_snapshot_details(snapshots):
    print("\n[Snapshot Details]")

    for snapshot in snapshots:
        print(f"T{snapshot['tick']} - {snapshot['event']}")

        if "link_snapshot" in snapshot:
            link = snapshot["link_snapshot"]
            print(
                f"  Link: {link['source']} <-> {link['destination']}, "
                f"Traffic: {link['traffic_mbps']} Mbps, "
                f"Utilization: {link['utilization_percent']:.2f}%, "
                f"Latency: {link['latency_ms']} ms, "
                f"Loss: {link['packet_loss_percent']}%, "
                f"Status: {link['status']}"
            )

        if "device_snapshot" in snapshot:
            device = snapshot["device_snapshot"]
            print(
                f"  Device: {device['device']}, "
                f"CPU: {device['cpu_usage_percent']}%"
            )

        if "edge_paths" in snapshot:
            for edge_node in snapshot["edge_paths"]:
                path = snapshot["edge_paths"][edge_node]
                if path is None:
                    path_text = "DISCONNECTED"
                else:
                    path_text = " -> ".join(path)
                print(f"  {edge_node}: {path_text}")


# 이 파일을 직접 실행하면 선택한 Event의 기본 다섯 Tick을 출력합니다.
if __name__ == "__main__":
    arguments = sys.argv[1:]

    try:
        # 입력이 없으면 대표 CONGESTION 예시를 실행합니다.
        if not arguments:
            generated_snapshots = run_congestion_time_series(
                DEFAULT_CONGESTION_LINK[0],
                DEFAULT_CONGESTION_LINK[1],
            )
        elif len(arguments) == 3 and arguments[0].upper() == "CONGESTION":
            generated_snapshots = run_congestion_time_series(
                arguments[1],
                arguments[2],
            )
        elif len(arguments) == 3 and arguments[0].upper() == "LINK_FAILURE":
            generated_snapshots = run_link_failure_time_series(
                arguments[1],
                arguments[2],
            )
        elif len(arguments) == 2 and arguments[0].upper() == "DEVICE_OVERLOAD":
            generated_snapshots = run_device_overload_time_series(arguments[1])
        else:
            raise ValueError(
                "사용법: python src/time_series_simulator.py "
                "[CONGESTION 장비1 장비2 | LINK_FAILURE 장비1 장비2 | "
                "DEVICE_OVERLOAD 장비]"
            )

        print_time_series(generated_snapshots)
        print_snapshot_details(generated_snapshots)
    except ValueError as error:
        print(f"Time-series simulation을 실행할 수 없습니다: {error}")
