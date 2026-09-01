"""기존 장애 분석 결과를 하나의 학습용 Incident 흐름으로 연결합니다."""

# 명령줄에서 간단한 장애 종류와 링크 이름을 받기 위해 sys를 불러옵니다.
import sys

# 기존 failover 함수가 장애 주입과 Before/After 분석을 한 번만 수행합니다.
from failover_analyzer import simulate_failover
# 기존 path 기반 network summary와 utilization 경고 기준을 재사용합니다.
from change_analyzer import collect_quality_metrics, UTILIZATION_WARNING_LIMIT
# 기존 topology 생성과 Root Cause Candidate 분석을 그대로 재사용합니다.
from network_simulator import (
    create_network,
    find_edge_paths,
    find_root_cause_candidates,
    inject_congestion,
    inject_device_overload,
)


# 이번 학습 단계에서 기본으로 실행할 Primary Link를 정합니다.
DEFAULT_FAILED_LINK = ("AGG-01", "CORE-01")


# Event를 운영자가 확인할 Alarm dict로 바꾸는 함수입니다.
def create_alarm(failure_type, target, network):
    # severity는 실제 통신사 기준이 아닌 이 프로젝트의 단순 학습용 규칙입니다.
    if failure_type == "LINK_FAILURE":
        alarm_type = "LINK_DOWN"
        severity = "CRITICAL"
        description = "가상 링크 상태가 DOWN입니다."
    elif failure_type == "CONGESTION":
        alarm_type = "HIGH_TRAFFIC"
        severity = "WARNING"
        description = "가상 링크에서 높은 트래픽이 관측되었습니다."
    elif failure_type == "DEVICE_OVERLOAD":
        alarm_type = "HIGH_CPU"
        severity = "WARNING"
        description = "가상 장비에서 높은 CPU 사용률이 관측되었습니다."
    else:
        raise ValueError(f"지원하지 않는 장애 종류입니다: {failure_type}")

    # Link 장애와 혼잡은 양 끝 장비를 잇는 Link가 있는지 확인합니다.
    if failure_type == "LINK_FAILURE" or failure_type == "CONGESTION":
        source = target[0]
        destination = target[1]
        if not network.has_edge(source, destination):
            raise ValueError(f"가상 링크를 찾을 수 없습니다: {source} <-> {destination}")

        target_text = f"{source} <-> {destination}"
    # 장비 과부하는 입력한 device가 graph의 Node인지 확인합니다.
    elif failure_type == "DEVICE_OVERLOAD":
        device = target
        if device not in network:
            raise ValueError(f"가상 장비를 찾을 수 없습니다: {device}")

        target_text = device
    else:
        target_text = str(target)

    # Alarm은 실제 NMS 알림 객체가 아닌 학습하기 쉬운 dict입니다.
    alarm = {
        "alarm_id": "ALARM-001",
        "alarm_type": alarm_type,
        "failure_type": failure_type,
        "target": target_text,
        "severity": severity,
        "description": description,
    }
    return alarm


# Alarm과 이후 분석 결과를 한곳에 모을 Incident dict를 만드는 함수입니다.
def create_incident(alarm):
    incident = {
        "incident_id": "INC-001",
        "status": "OPEN",
        "alarm": alarm,
        "affected_nodes": [],
        "path_changed_nodes": [],
        "before_paths": {},
        "after_paths": {},
        "probable_causes": [],
        "action": None,
        "post_check": None,
        "result": None,
        # 실제 timestamp가 아니라 처리 순서만 보여주는 학습용 목록입니다.
        "timeline": [
            "Event detected",
            "Alarm created",
            "Incident opened",
        ],
    }
    return incident


# failover analyzer의 EDGE별 기록에서 path만 읽기 쉬운 dict로 꺼냅니다.
def extract_paths(edge_records):
    paths = {}

    for edge_node in edge_records:
        record = edge_records[edge_node]
        paths[edge_node] = record["path"]

    return paths


# 기존 failover 결과를 Incident의 Connectivity와 Routing Change 영향에 연결합니다.
def add_impact_analysis(incident, failover_result):
    # 연결이 완전히 끊긴 EDGE는 Connectivity Impact입니다.
    incident["affected_nodes"] = failover_result["disconnected_nodes"]
    # 연결은 유지되지만 path가 바뀐 EDGE는 Routing Change Impact입니다.
    incident["path_changed_nodes"] = failover_result["failover_nodes"]
    incident["before_paths"] = extract_paths(failover_result["before_records"])
    incident["after_paths"] = extract_paths(failover_result["after_records"])
    incident["timeline"].append("Impact analyzed")


# EDGE별 path 중에서 지정한 undirected Link를 사용하는 EDGE를 찾습니다.
def find_nodes_using_link(paths, source, destination):
    nodes_using_link = []

    for edge_node in paths:
        path = paths[edge_node]
        if path is None:
            continue

        for path_index in range(len(path) - 1):
            node1 = path[path_index]
            node2 = path[path_index + 1]

            # NetworkX Graph는 무방향이므로 두 가지 방향을 모두 같은 링크로 봅니다.
            same_direction = node1 == source and node2 == destination
            opposite_direction = node1 == destination and node2 == source

            if same_direction or opposite_direction:
                nodes_using_link.append(edge_node)
                # 같은 EDGE를 한 번만 넣고 다음 EDGE path로 이동합니다.
                break

    return nodes_using_link


# EDGE별 path 중에서 지정한 device를 경유하는 EDGE를 찾습니다.
def find_nodes_using_device(paths, device):
    nodes_using_device = []

    for edge_node in paths:
        path = paths[edge_node]
        if path is not None and device in path:
            nodes_using_device.append(edge_node)

    return nodes_using_device


# 장애 종류와 alternative path 존재 여부를 보고 운영자 Action 기록을 만듭니다.
def select_action(alarm, failover_result=None):
    failure_type = alarm["failure_type"]

    if failure_type == "LINK_FAILURE":
        if failover_result["failover_nodes"]:
            action_type = "FAILOVER"
            description = "Backup path를 사용하여 서비스 연결을 유지합니다."
        else:
            action_type = "INVESTIGATE"
            description = "대체 경로가 없어 단절된 서비스 경로를 추가 확인합니다."
    elif failure_type == "CONGESTION":
        action_type = "MONITOR"
        description = "혼잡 링크의 트래픽과 품질 지표를 추가 확인합니다."
    else:
        action_type = "MONITOR_DEVICE"
        description = "과부하 장비의 CPU 상태를 추가 확인합니다."

    # 실제 자동 복구가 아니라 운영자가 선택했다고 가정한 Action 기록입니다.
    action = {
        "action_type": action_type,
        "description": description,
    }
    return action


# Action 이후 기존 failover 결과로 연결성과 품질을 다시 확인합니다.
def create_post_check(failover_result):
    after_summary = failover_result["after_summary"]

    post_check = {
        "connected_edge_nodes": after_summary["connected_edge_nodes"],
        "disconnected_edge_nodes": after_summary["disconnected_edge_nodes"],
        "path_changed_nodes": failover_result["failover_nodes"],
        "network_status": failover_result["overall"],
        "max_utilization_percent": after_summary["max_utilization_percent"],
    }
    return post_check


# CONGESTION 이후 연결성과 Before/After 품질을 확인합니다.
def create_congestion_post_check(before_summary, after_summary):
    # 연결 단절, 높은 utilization 또는 평균 품질 증가를 단순 저하 기준으로 봅니다.
    network_status = "NORMAL"

    if after_summary["disconnected_edge_nodes"] > 0:
        network_status = "DISCONNECTED"
    elif after_summary["max_utilization_percent"] >= UTILIZATION_WARNING_LIMIT:
        network_status = "DEGRADED"
    elif (
        after_summary["average_path_latency_ms"]
        > before_summary["average_path_latency_ms"]
    ):
        network_status = "DEGRADED"
    elif (
        after_summary["average_packet_loss_percent"]
        > before_summary["average_packet_loss_percent"]
    ):
        network_status = "DEGRADED"

    post_check = {
        "connected_edge_nodes": after_summary["connected_edge_nodes"],
        "disconnected_edge_nodes": after_summary["disconnected_edge_nodes"],
        "network_status": network_status,
        "max_utilization_percent": after_summary["max_utilization_percent"],
        "average_path_latency_ms": after_summary["average_path_latency_ms"],
        "average_packet_loss_percent": after_summary[
            "average_packet_loss_percent"
        ],
    }
    return post_check


# DEVICE_OVERLOAD 이후 CPU 상태와 해당 장비를 지나는 경로를 확인합니다.
def create_device_overload_post_check(network, device, paths_using_device):
    summary = collect_quality_metrics(network)
    cpu_usage_percent = network.nodes[device]["cpu_usage"]

    post_check = {
        "target_device": device,
        "cpu_usage_percent": cpu_usage_percent,
        "connected_edge_nodes": summary["connected_edge_nodes"],
        "disconnected_edge_nodes": summary["disconnected_edge_nodes"],
        "paths_using_device": paths_using_device,
        # CPU 값이 latency/loss를 바꾸지 않으므로 network 품질은 NORMAL로 둡니다.
        "network_status": "NORMAL",
    }
    return post_check


# Post-check 결과를 세 가지 Incident 종료 상태 중 하나로 정리합니다.
def determine_incident_result(incident):
    post_check = incident["post_check"]

    if post_check["disconnected_edge_nodes"] > 0:
        incident["status"] = "UNRESOLVED"
        incident["result"] = "SERVICE_DISCONNECTED"
    elif post_check["network_status"] == "DEGRADED":
        incident["status"] = "MONITORING"
        incident["result"] = "SERVICE_CONNECTED_BUT_DEGRADED"
    else:
        incident["status"] = "RESOLVED"
        incident["result"] = "SERVICE_CONNECTED"


# CPU 과부하가 계속 관측되는 동안 Incident를 MONITORING 상태로 둡니다.
def determine_device_overload_result(incident):
    incident["status"] = "MONITORING"
    incident["result"] = "DEVICE_OVERLOAD_UNDER_MONITORING"


# LINK_FAILURE Event부터 최종 Incident Result까지 전체 순서를 실행합니다.
def run_link_failure_incident(source, destination):
    network = create_network()
    failed_link = (source, destination)

    # Event가 관측되었다고 가정하고 운영자 확인용 Alarm을 생성합니다.
    alarm = create_alarm("LINK_FAILURE", failed_link, network)
    # 하나의 Alarm과 이후 처리 결과를 묶을 Incident를 OPEN 상태로 만듭니다.
    incident = create_incident(alarm)

    # simulate_failover()가 링크를 정확히 한 번 DOWN 처리하고 Before/After를 만듭니다.
    # Incident Manager는 같은 장애를 다시 주입하지 않습니다.
    failover_result = simulate_failover(
        network,
        failed_link,
        print_rule_details=False,
    )
    add_impact_analysis(incident, failover_result)

    # 확정 Root Cause가 아니라 기존 규칙에 맞는 원인 후보 목록을 저장합니다.
    incident["probable_causes"] = find_root_cause_candidates(network)

    # 자동 복구를 실행하지 않고 운영자가 선택했다고 가정한 Action만 기록합니다.
    incident["action"] = select_action(alarm, failover_result)
    incident["timeline"].append("Action selected")

    # Action 이후 연결 상태와 품질을 기존 analyzer 결과로 확인합니다.
    incident["post_check"] = create_post_check(failover_result)
    incident["timeline"].append("Post-check completed")
    determine_incident_result(incident)

    return incident


# CONGESTION Event부터 성능 Post-check까지의 흐름을 실행합니다.
def run_congestion_incident(source, destination):
    network = create_network()
    congested_link = (source, destination)

    alarm = create_alarm("CONGESTION", congested_link, network)
    incident = create_incident(alarm)

    # 혼잡 전 path와 품질 summary를 먼저 기록합니다.
    paths_before = find_edge_paths(network)
    before_summary = collect_quality_metrics(network)

    # 기존 함수가 traffic 95%, latency +50ms, loss +5%를 한 번만 적용합니다.
    inject_congestion(network, source, destination, print_details=False)
    after_summary = collect_quality_metrics(network)

    # 연결은 유지되지만 이 Link를 지나는 EDGE를 성능 영향 확인 대상으로 둡니다.
    incident["performance_affected_nodes"] = find_nodes_using_link(
        paths_before,
        source,
        destination,
    )
    incident["impact_metrics"] = {
        "before": before_summary,
        "after": after_summary,
    }
    incident["timeline"].append("Impact analyzed")

    incident["probable_causes"] = find_root_cause_candidates(network)
    incident["action"] = select_action(alarm)
    incident["timeline"].append("Action selected")

    incident["post_check"] = create_congestion_post_check(
        before_summary,
        after_summary,
    )
    incident["timeline"].append("Post-check completed")
    determine_incident_result(incident)

    return incident


# DEVICE_OVERLOAD Event부터 CPU와 관련 path Post-check까지 실행합니다.
def run_device_overload_incident(device):
    network = create_network()

    alarm = create_alarm("DEVICE_OVERLOAD", device, network)
    incident = create_incident(alarm)
    paths_before = find_edge_paths(network)

    # 기존 함수가 target device의 cpu_usage를 정확히 한 번 95%로 설정합니다.
    inject_device_overload(network, device, print_details=False)
    paths_using_device = find_nodes_using_device(paths_before, device)

    # 이는 실제 품질 저하가 아니라 과부하 장비를 경유하는 path 후보입니다.
    incident["paths_using_device"] = paths_using_device
    incident["device_impact"] = {
        "device": device,
        "cpu_usage_percent": network.nodes[device]["cpu_usage"],
    }
    incident["timeline"].append("Impact analyzed")

    incident["probable_causes"] = find_root_cause_candidates(network)
    incident["action"] = select_action(alarm)
    incident["timeline"].append("Action selected")

    incident["post_check"] = create_device_overload_post_check(
        network,
        device,
        paths_using_device,
    )
    incident["timeline"].append("Post-check completed")
    determine_device_overload_result(incident)

    return incident


# list가 비어 있으면 None, 값이 있으면 쉼표로 연결한 문자열을 돌려줍니다.
def format_node_list(nodes):
    if not nodes:
        return "None"
    return ", ".join(nodes)


# Incident에 모인 Alarm, 영향, 조치, 확인 결과를 순서대로 출력합니다.
def print_incident_report(incident):
    alarm = incident["alarm"]
    action = incident["action"]
    post_check = incident["post_check"]

    print("=" * 65)
    print("INCIDENT REPORT - LEARNING SIMULATION ONLY")
    print("실제 NMS, OSS 또는 ITSM/Ticket 시스템이 아닙니다.")
    print("=" * 65)
    print(f"Incident ID : {incident['incident_id']}")
    print(f"Status      : {incident['status']}")
    print(f"Result      : {incident['result']}")

    print("\n[Alarm]")
    print(f"Type        : {alarm['alarm_type']}")
    print(f"Target      : {alarm['target']}")
    print(f"Severity    : {alarm['severity']}")
    print(f"Description : {alarm['description']}")

    print("\n[Impact]")
    failure_type = alarm["failure_type"]

    if failure_type == "LINK_FAILURE":
        print(f"Disconnected EDGE : {format_node_list(incident['affected_nodes'])}")
        print(f"Path Changed EDGE : {format_node_list(incident['path_changed_nodes'])}")

        # path가 변경된 EDGE는 장애 전후 경로를 나란히 출력합니다.
        for edge_node in incident["path_changed_nodes"]:
            before_path = incident["before_paths"][edge_node]
            after_path = incident["after_paths"][edge_node]
            print(f"- {edge_node} Before: {' -> '.join(before_path)}")
            print(f"  {edge_node} After : {' -> '.join(after_path)}")
    elif failure_type == "CONGESTION":
        before = incident["impact_metrics"]["before"]
        after = incident["impact_metrics"]["after"]
        print(
            "Performance Affected EDGE : "
            f"{format_node_list(incident['performance_affected_nodes'])}"
        )
        print(
            f"Max Utilization          : {before['max_utilization_percent']:.2f}% "
            f"-> {after['max_utilization_percent']:.2f}%"
        )
        print(
            f"Average Path Latency     : {before['average_path_latency_ms']:.2f} ms "
            f"-> {after['average_path_latency_ms']:.2f} ms"
        )
        print(
            "Average Packet Loss      : "
            f"{before['average_packet_loss_percent']:.2f}% -> "
            f"{after['average_packet_loss_percent']:.2f}%"
        )
    else:
        device_impact = incident["device_impact"]
        print(f"Target Device      : {device_impact['device']}")
        print(f"CPU Usage          : {device_impact['cpu_usage_percent']}%")
        print(
            "Paths Using Device : "
            f"{format_node_list(incident['paths_using_device'])}"
        )
        print(
            "현재 simulation은 CPU 과부하가 latency/loss를 자동으로 "
            "증가시키지 않습니다."
        )

    print("\n[Probable Cause Candidates]")
    if not incident["probable_causes"]:
        print("None")
    else:
        for candidate in incident["probable_causes"]:
            print(f"- {candidate['cause']}")
            print(f"  Evidence: {candidate['evidence']}")

    print("\n[Action]")
    print(f"Type        : {action['action_type']}")
    print(f"Description : {action['description']}")

    print("\n[Post-check]")
    print(f"Connected EDGE    : {post_check['connected_edge_nodes']}")
    print(f"Disconnected EDGE : {post_check['disconnected_edge_nodes']}")

    if failure_type == "LINK_FAILURE":
        print(f"Path Changed EDGE : {format_node_list(post_check['path_changed_nodes'])}")
        print(f"Network Status    : {post_check['network_status']}")
        print(f"Max Utilization   : {post_check['max_utilization_percent']:.2f}%")
    elif failure_type == "CONGESTION":
        print(f"Network Status    : {post_check['network_status']}")
        print(f"Max Utilization   : {post_check['max_utilization_percent']:.2f}%")
        print(f"Average Latency   : {post_check['average_path_latency_ms']:.2f} ms")
        print(
            f"Average Loss      : "
            f"{post_check['average_packet_loss_percent']:.2f}%"
        )
    else:
        print(f"Target Device     : {post_check['target_device']}")
        print(f"CPU Usage         : {post_check['cpu_usage_percent']}%")
        print(
            "Paths Using Device: "
            f"{format_node_list(post_check['paths_using_device'])}"
        )
        print(f"Network Status    : {post_check['network_status']}")

    print("\n[Timeline]")
    timeline_number = 1
    for timeline_item in incident["timeline"]:
        print(f"{timeline_number}. {timeline_item}")
        timeline_number = timeline_number + 1

    print("=" * 65)


# 이 파일을 직접 실행하면 기본 Primary Link Incident를 시험합니다.
if __name__ == "__main__":
    arguments = sys.argv[1:]

    try:
        # 입력이 없으면 가장 대표적인 LINK_FAILURE 시나리오를 실행합니다.
        if not arguments:
            generated_incident = run_link_failure_incident(
                DEFAULT_FAILED_LINK[0],
                DEFAULT_FAILED_LINK[1],
            )
        # 링크 장애와 혼잡은 장애 종류 뒤에 링크 양 끝 Node 두 개를 받습니다.
        elif len(arguments) == 3 and arguments[0].upper() == "LINK_FAILURE":
            generated_incident = run_link_failure_incident(
                arguments[1],
                arguments[2],
            )
        elif len(arguments) == 3 and arguments[0].upper() == "CONGESTION":
            generated_incident = run_congestion_incident(
                arguments[1],
                arguments[2],
            )
        # 장비 과부하는 장애 종류 뒤에 target device 하나를 받습니다.
        elif len(arguments) == 2 and arguments[0].upper() == "DEVICE_OVERLOAD":
            generated_incident = run_device_overload_incident(arguments[1])
        else:
            raise ValueError(
                "사용법: python src/incident_manager.py "
                "[LINK_FAILURE 장비1 장비2 | CONGESTION 장비1 장비2 | "
                "DEVICE_OVERLOAD 장비]"
            )

        print_incident_report(generated_incident)
    except ValueError as error:
        print(f"Incident simulation을 실행할 수 없습니다: {error}")
