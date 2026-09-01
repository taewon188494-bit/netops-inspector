"""Traffic Flow가 이용하는 가상 E2E 경로의 서비스 품질을 분석합니다."""

# 명령줄에서 간단한 시나리오 종류와 대상을 받기 위해 sys를 불러옵니다.
import sys

# 기존 active path, path metric과 failover 기능을 그대로 재사용합니다.
from failover_analyzer import (
    calculate_path_metrics,
    find_active_path,
    simulate_failover,
)
# 기존 topology와 장애 주입 함수를 그대로 재사용합니다.
from network_simulator import (
    create_network,
    inject_congestion,
    inject_device_overload,
)


# 아래 숫자는 실제 KT 또는 실제 통신사의 SLA가 아닌 학습용 threshold입니다.
SERVICE_QUALITY_RULES = {
    "INTERNET": {
        "max_latency_ms": 100,
        "max_packet_loss_percent": 3.0,
    },
    "IPTV": {
        "max_latency_ms": 50,
        "max_packet_loss_percent": 2.0,
    },
    "VOICE": {
        "max_latency_ms": 30,
        "max_packet_loss_percent": 1.0,
    },
    "ENTERPRISE": {
        "max_latency_ms": 50,
        "max_packet_loss_percent": 1.0,
    },
}


# DOWN Link를 제외하고 Flow의 routing_cost 기반 Active Path를 찾습니다.
def find_service_path(network, flow):
    source = flow["source"]
    destination = flow["destination"]

    # 기존 함수가 active graph와 weight="routing_cost" 경로 선택을 담당합니다.
    path = find_active_path(network, source, destination)
    return path


# 기존 path metric 결과를 Service Quality에서 사용할 이름으로 정리합니다.
def calculate_service_path_metrics(network, path):
    if path is None:
        return None

    # 기존 함수가 Link별 latency/loss 합계와 최대 utilization을 계산합니다.
    path_metrics = calculate_path_metrics(network, path)

    metrics = {
        "total_latency_ms": path_metrics["total_latency_ms"],
        "total_packet_loss_percent": path_metrics[
            "path_packet_loss_percent"
        ],
        "max_link_utilization_percent": path_metrics[
            "max_utilization_percent"
        ],
    }
    return metrics


# 연결 여부와 서비스별 latency/loss 기준으로 현재 품질을 판정합니다.
def evaluate_service_quality(service, metrics, connected):
    if not connected:
        return {
            "status": "CRITICAL",
            "reasons": ["SERVICE_DISCONNECTED"],
        }

    # service 이름으로 dict 안의 학습용 threshold dict를 가져옵니다.
    quality_rule = SERVICE_QUALITY_RULES.get(service)
    if quality_rule is None:
        raise ValueError(f"품질 기준이 없는 Service입니다: {service}")

    latency_exceeded = (
        metrics["total_latency_ms"] > quality_rule["max_latency_ms"]
    )
    packet_loss_exceeded = (
        metrics["total_packet_loss_percent"]
        > quality_rule["max_packet_loss_percent"]
    )

    reasons = []
    if latency_exceeded:
        reasons.append("LATENCY_THRESHOLD_EXCEEDED")
    if packet_loss_exceeded:
        reasons.append("PACKET_LOSS_THRESHOLD_EXCEEDED")

    # 두 기준을 모두 넘으면 CRITICAL, 하나만 넘으면 DEGRADED로 단순화합니다.
    if latency_exceeded and packet_loss_exceeded:
        status = "CRITICAL"
    elif latency_exceeded or packet_loss_exceeded:
        status = "DEGRADED"
    else:
        status = "NORMAL"

    # Max Utilization은 Evidence로 기록하지만 직접 판정 기준으로 사용하지 않습니다.
    return {
        "status": status,
        "reasons": reasons,
    }


# 하나의 Traffic Flow에 대해 Path, Metric과 Quality를 모두 분석합니다.
def analyze_service_flow(network, flow):
    service = flow["service"]
    quality_rule = SERVICE_QUALITY_RULES.get(service)
    if quality_rule is None:
        raise ValueError(f"품질 기준이 없는 Service입니다: {service}")

    path = find_service_path(network, flow)
    connected = path is not None
    metrics = calculate_service_path_metrics(network, path)
    evaluation = evaluate_service_quality(service, metrics, connected)

    # 이 dict 하나를 Flow 한 개의 Service Quality Record로 사용합니다.
    record = {
        "flow_id": flow["flow_id"],
        "service": service,
        "source": flow["source"],
        "destination": flow["destination"],
        "traffic_mbps": flow["traffic_mbps"],
        "path": path,
        "connected": connected,
        "metrics": metrics,
        "quality_status": evaluation["status"],
        "quality_rule": quality_rule.copy(),
        "reasons": evaluation["reasons"],
    }
    return record


# 기존 network에 저장된 모든 Traffic Flow를 차례대로 분석합니다.
def analyze_all_services(network):
    flows = network.graph["flows"]
    results = []

    for flow in flows:
        result = analyze_service_flow(network, flow)
        results.append(result)

    return results


# Service Quality Record 목록에서 상태별 개수만 단순 계산합니다.
def create_service_quality_summary(results):
    summary = {
        "total_services": 0,
        "normal_services": 0,
        "degraded_services": 0,
        "critical_services": 0,
    }

    for result in results:
        summary["total_services"] = summary["total_services"] + 1

        if result["quality_status"] == "NORMAL":
            summary["normal_services"] = summary["normal_services"] + 1
        elif result["quality_status"] == "DEGRADED":
            summary["degraded_services"] = summary["degraded_services"] + 1
        else:
            summary["critical_services"] = summary["critical_services"] + 1

    return summary


# 선택한 장애를 한 번 적용하고 모든 Service의 현재 품질을 분석합니다.
def run_service_quality_scenario(failure_type=None, target=None):
    network = create_network()
    scenario_name = "NORMAL"
    event_details = None

    if failure_type is None:
        scenario_name = "NORMAL"
    elif failure_type == "CONGESTION":
        source = target[0]
        destination = target[1]
        inject_congestion(network, source, destination, print_details=False)
        scenario_name = "CONGESTION"
        link = network[source][destination]
        event_details = {
            "target": f"{source} <-> {destination}",
            "traffic_mbps": link["traffic_mbps"],
            "latency_ms": link["latency_ms"],
            "packet_loss_percent": link["packet_loss_percent"],
        }
    elif failure_type == "LINK_FAILURE":
        source = target[0]
        destination = target[1]
        simulate_failover(
            network,
            (source, destination),
            print_rule_details=False,
        )
        scenario_name = "LINK_FAILURE"
        event_details = {
            "target": f"{source} <-> {destination}",
            "status": network[source][destination]["status"],
        }
    elif failure_type == "DEVICE_OVERLOAD":
        device = target
        inject_device_overload(network, device, print_details=False)
        scenario_name = "DEVICE_OVERLOAD"
        event_details = {
            "target": device,
            "cpu_usage_percent": network.nodes[device]["cpu_usage"],
        }
    else:
        raise ValueError(f"지원하지 않는 시나리오입니다: {failure_type}")

    results = analyze_all_services(network)
    summary = create_service_quality_summary(results)

    scenario = {
        "scenario": scenario_name,
        "event_details": event_details,
        "results": results,
        "summary": summary,
    }
    return scenario


# Service별 Path, Metric, Rule과 판정 결과를 터미널에 출력합니다.
def print_service_quality_report(scenario):
    print("=" * 68)
    print("SERVICE E2E QUALITY REPORT - LEARNING SIMULATION")
    print("실제 KT 또는 실제 통신사의 SLA와 Application 측정이 아닙니다.")
    print("=" * 68)
    print(f"Scenario: {scenario['scenario']}")

    event_details = scenario["event_details"]
    if event_details is not None:
        print("Event Details:")
        for key in event_details:
            print(f"- {key}: {event_details[key]}")

    for result in scenario["results"]:
        print("\n" + "-" * 68)
        print(f"{result['flow_id']} | {result['service']}")

        if result["path"] is None:
            print("Path       : DISCONNECTED")
        else:
            print(f"Path       : {' -> '.join(result['path'])}")

        print(f"Traffic    : {result['traffic_mbps']} Mbps")

        if result["metrics"] is None:
            print("Latency    : N/A")
            print("Loss       : N/A")
            print("Max Util   : N/A")
        else:
            print(f"Latency    : {result['metrics']['total_latency_ms']:.2f} ms")
            print(
                f"Loss       : "
                f"{result['metrics']['total_packet_loss_percent']:.2f}%"
            )
            print(
                f"Max Util   : "
                f"{result['metrics']['max_link_utilization_percent']:.2f}%"
            )

        quality_rule = result["quality_rule"]
        print(
            f"Rule       : Latency <= {quality_rule['max_latency_ms']} ms / "
            f"Loss <= {quality_rule['max_packet_loss_percent']:.2f}%"
        )
        print(f"Status     : {result['quality_status']}")
        if result["reasons"]:
            print(f"Reasons    : {', '.join(result['reasons'])}")

    summary = scenario["summary"]
    print("\n" + "=" * 68)
    print("Summary")
    print(f"Total      : {summary['total_services']}")
    print(f"NORMAL     : {summary['normal_services']}")
    print(f"DEGRADED   : {summary['degraded_services']}")
    print(f"CRITICAL   : {summary['critical_services']}")
    print("=" * 68)


# 이 파일을 직접 실행하면 선택한 Service Quality 시나리오를 출력합니다.
if __name__ == "__main__":
    arguments = sys.argv[1:]

    try:
        if not arguments:
            generated_scenario = run_service_quality_scenario()
        elif len(arguments) == 3 and arguments[0].upper() == "CONGESTION":
            generated_scenario = run_service_quality_scenario(
                "CONGESTION",
                (arguments[1], arguments[2]),
            )
        elif len(arguments) == 3 and arguments[0].upper() == "LINK_FAILURE":
            generated_scenario = run_service_quality_scenario(
                "LINK_FAILURE",
                (arguments[1], arguments[2]),
            )
        elif len(arguments) == 2 and arguments[0].upper() == "DEVICE_OVERLOAD":
            generated_scenario = run_service_quality_scenario(
                "DEVICE_OVERLOAD",
                arguments[1],
            )
        else:
            raise ValueError(
                "사용법: python src/service_quality_analyzer.py "
                "[CONGESTION 장비1 장비2 | LINK_FAILURE 장비1 장비2 | "
                "DEVICE_OVERLOAD 장비]"
            )

        print_service_quality_report(generated_scenario)
    except ValueError as error:
        print(f"Service Quality 분석을 실행할 수 없습니다: {error}")
