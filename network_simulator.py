"""NetworkX로 간단한 가상 통신 네트워크를 만듭니다."""

# 랜덤 장애 종류와 대상을 고르기 위해 random을 불러옵니다.
import random
# 명령줄에서 수동 장애 종류와 대상을 받기 위해 sys를 불러옵니다.
import sys

# 장비와 링크를 그래프 구조로 표현하기 위해 networkx를 불러옵니다.
import networkx as nx


# 혼잡 장애에서는 트래픽을 링크 용량의 95%로 설정합니다.
CONGESTION_TRAFFIC_RATIO = 0.95
# 혼잡 장애가 발생하면 기존 latency에 50ms를 더합니다.
CONGESTION_LATENCY_INCREASE_MS = 50
# 혼잡 장애가 발생하면 packet loss를 5% 증가시킵니다.
CONGESTION_PACKET_LOSS_INCREASE = 5
# 장비 과부하 장애에서는 CPU 사용률을 95%로 설정합니다.
OVERLOAD_CPU_USAGE_PERCENT = 95
# 혼잡 원인 후보를 판단할 트래픽 사용률 기준을 85%로 정합니다.
CAUSE_TRAFFIC_THRESHOLD_PERCENT = 85
# 장비 과부하 원인 후보를 판단할 CPU 사용률 기준을 90%로 정합니다.
CAUSE_CPU_THRESHOLD_PERCENT = 90


# 학습에 사용할 서비스별 Traffic Flow 목록을 새로 만들어 돌려줍니다.
# list 안에는 여러 개의 dict가 들어 있고, 각 dict 하나가 하나의 Flow입니다.
def create_traffic_flows():
    flows = [
        {"flow_id": "FLOW-001", "source": "EDGE-01", "destination": "CORE-01",
         "traffic_mbps": 120, "service": "INTERNET"},
        {"flow_id": "FLOW-002", "source": "EDGE-02", "destination": "CORE-01",
         "traffic_mbps": 180, "service": "IPTV"},
        {"flow_id": "FLOW-003", "source": "EDGE-03", "destination": "CORE-01",
         "traffic_mbps": 140, "service": "VOICE"},
        {"flow_id": "FLOW-004", "source": "EDGE-04", "destination": "CORE-01",
         "traffic_mbps": 90, "service": "ENTERPRISE"},
    ]
    return flows


# 새 Flow 계산 전에 모든 링크의 이전 트래픽을 0 Mbps로 초기화합니다.
def reset_link_traffic(network_graph):
    # graph.edges()는 각 링크 양 끝 노드의 tuple을 돌려줍니다.
    for node1, node2 in network_graph.edges():
        # graph[node1][node2]는 두 노드 사이 링크의 속성 dict입니다.
        network_graph[node1][node2]["traffic_mbps"] = 0


# Flow의 source와 destination 사이에서 가장 짧은 경로를 계산합니다.
def calculate_flow_path(network_graph, flow):
    source = flow["source"]
    destination = flow["destination"]
    try:
        # shortest_path()는 경로를 노드 이름의 list로 돌려줍니다.
        # 예: ["EDGE-01", "AGG-01", "CORE-01"]
        #
        # weight="routing_cost"를 지정하면 NetworkX는 링크 개수가 가장 적은
        # 경로가 아니라, 경로에 포함된 모든 링크의 routing_cost 합이 가장
        # 작은 경로를 선택합니다. 실제 OSPF가 아닌 cost 개념 학습용 모델입니다.
        path = nx.shortest_path(
            network_graph,
            source=source,
            target=destination,
            weight="routing_cost",
        )
    # 두 노드 사이에 경로가 없어도 프로그램을 종료하지 않고 처리합니다.
    except nx.NetworkXNoPath:
        path = None
    return path


# Path에 포함된 모든 링크의 routing cost를 더합니다.
def calculate_path_routing_cost(network_graph, path):
    # 경로가 없으면 합계를 계산할 수 없으므로 None을 돌려줍니다.
    if path is None:
        return None

    total_routing_cost = 0

    # 인접한 노드 두 개를 하나의 링크로 보고 cost를 차례대로 더합니다.
    for path_index in range(len(path) - 1):
        node1 = path[path_index]
        node2 = path[path_index + 1]
        link = network_graph[node1][node2]
        routing_cost = link["routing_cost"]
        total_routing_cost = total_routing_cost + routing_cost

    return total_routing_cost


# Flow 하나의 트래픽을 그 Flow가 지나가는 모든 링크에 더합니다.
def apply_flow_traffic(network_graph, flow):
    path = flow["path"]
    if path is None:
        return

    traffic_mbps = flow["traffic_mbps"]

    # 노드가 3개라면 링크는 2개이므로 마지막 노드 바로 전까지만 반복합니다.
    for path_index in range(len(path) - 1):
        node1 = path[path_index]
        node2 = path[path_index + 1]
        link = network_graph[node1][node2]
        # 여러 Flow가 같은 링크를 지나면 기존 값에 현재 Flow 값을 더합니다.
        link["traffic_mbps"] = link["traffic_mbps"] + traffic_mbps


# 모든 링크에서 트래픽이 용량의 몇 퍼센트인지 계산해 저장합니다.
def calculate_utilization(network_graph):
    for node1, node2 in network_graph.edges():
        link = network_graph[node1][node2]
        traffic_mbps = link["traffic_mbps"]
        capacity_mbps = link["capacity_mbps"]
        # utilization(%) = traffic_mbps / capacity_mbps * 100
        utilization = traffic_mbps / capacity_mbps * 100
        link["utilization_percent"] = utilization


# 모든 Flow의 경로, 링크 트래픽, 사용률을 순서대로 계산합니다.
def calculate_traffic_from_flows(network_graph, flows):
    reset_link_traffic(network_graph)

    # flows list에서 dict 하나를 차례대로 꺼내 flow 변수에 담습니다.
    for flow in flows:
        # 계산한 path를 같은 Flow dict에 새 key로 저장합니다.
        flow["path"] = calculate_flow_path(network_graph, flow)
        # 선택된 경로의 링크 cost 합계도 Flow dict에 저장합니다.
        flow["total_routing_cost"] = calculate_path_routing_cost(
            network_graph,
            flow["path"],
        )
        if flow["path"] is None:
            print(f"{flow['flow_id']} : 경로를 찾을 수 없습니다.")
        else:
            apply_flow_traffic(network_graph, flow)

    # 모든 Flow를 더한 뒤 최종 링크 사용률을 한 번 계산합니다.
    calculate_utilization(network_graph)


# 가상 네트워크 토폴로지를 만들어 돌려주는 함수입니다.
def create_network():
    # Graph는 장비를 노드(node), 장비 사이 연결을 엣지(edge)로 관리합니다.
    network = nx.Graph()

    # 각 링크의 양 끝 장비, 용량, 지연시간, 손실률, 역할, cost를 정의합니다.
    # routing_cost는 실제 통신사나 실제 OSPF metric이 아닌 학습용 고정값입니다.
    link_definitions = [
        # CORE와 AGG 사이의 상위 링크는 1,000Mbps 용량으로 설정합니다.
        ("CORE-01", "AGG-01", 1000, 5, 0.0, "PRIMARY", 10),
        ("CORE-01", "AGG-02", 1000, 6, 0.0, "PRIMARY", 10),
        # AGG와 EDGE 사이의 하위 링크는 500Mbps 용량으로 설정합니다.
        ("AGG-01", "EDGE-01", 500, 8, 0.0, "ACCESS", 5),
        ("AGG-01", "EDGE-02", 500, 9, 0.0, "ACCESS", 5),
        ("AGG-02", "EDGE-03", 500, 10, 0.0, "ACCESS", 5),
        ("AGG-02", "EDGE-04", 500, 11, 0.0, "ACCESS", 5),
    ]

    # 정의한 링크를 하나씩 꺼내 그래프에 추가합니다.
    for link_definition in link_definitions:
        source = link_definition[0]
        destination = link_definition[1]
        capacity = link_definition[2]
        latency = link_definition[3]
        packet_loss = link_definition[4]
        role = link_definition[5]
        routing_cost = link_definition[6]

        # 두 장비를 연결하고 해당 링크의 네트워크 속성을 함께 저장합니다.
        network.add_edge(
            source,
            destination,
            capacity_mbps=capacity,
            # 실제 트래픽은 모든 링크를 만든 뒤 Flow 경로를 따라 계산합니다.
            traffic_mbps=0,
            latency_ms=latency,
            packet_loss_percent=packet_loss,
            status="NORMAL",
            role=role,
            routing_cost=routing_cost,
            # 장애 후 latency 증가 여부를 비교하기 위해 정상 초기값을 보관합니다.
            baseline_latency_ms=latency,
            # 장애 후 packet loss 증가 여부를 비교하기 위해 정상 초기값을 보관합니다.
            baseline_packet_loss_percent=packet_loss,
        )

    # 두 AGG 사이에 학습용 alternative path를 제공하는 backup link를 추가합니다.
    network.add_edge(
        "AGG-01",
        "AGG-02",
        capacity_mbps=800,
        traffic_mbps=0,
        latency_ms=12,
        packet_loss_percent=0.0,
        status="NORMAL",
        role="BACKUP",
        # 정상 경로보다 비싸게 설정하여 평소에는 Backup Link를 선택하지 않습니다.
        routing_cost=30,
        baseline_latency_ms=12,
        baseline_packet_loss_percent=0.0,
    )

    # 테스트 Flow를 만들고 각 Flow의 path를 따라 링크 트래픽을 누적합니다.
    flows = create_traffic_flows()
    calculate_traffic_from_flows(network, flows)
    # 출력 함수에서도 Flow 목록을 찾을 수 있도록 그래프에 보관합니다.
    network.graph["flows"] = flows

    # 완성된 가상 네트워크 그래프를 돌려줍니다.
    return network


# 각 Flow의 서비스, 트래픽, 실제 이동 경로를 터미널에 출력합니다.
def print_flow_paths(flows):
    print("=" * 65)
    print("Traffic Flows and Paths")
    print("=" * 65)
    for flow in flows:
        print(flow["flow_id"])
        print(f"Service: {flow['service']}")
        print(f"Traffic: {flow['traffic_mbps']} Mbps")
        print("Path:")
        if flow["path"] is None:
            print("경로를 찾을 수 없습니다.")
        else:
            print(" -> ".join(flow["path"]))
            print(f"Routing Cost: {flow['total_routing_cost']}")
        print("-" * 65)


# Flow 계산 후 각 링크에 누적된 최종 트래픽을 터미널에 출력합니다.
def print_link_traffic(network_graph):
    print("Link Traffic")
    print("-" * 65)
    for node1, node2 in network_graph.edges():
        traffic_mbps = network_graph[node1][node2]["traffic_mbps"]
        print(f"{node1} - {node2} : {traffic_mbps} Mbps")


# 그래프에 저장된 모든 링크 상태를 터미널에 출력하는 함수입니다.
def print_link_status(network):
    # 출력 내용이 무엇인지 알 수 있도록 제목을 표시합니다.
    print("=" * 65)
    print("NetOps Inspector - 가상 네트워크 링크 상태")
    print("=" * 65)

    # 그래프의 각 링크와 그 링크에 저장된 속성을 하나씩 가져옵니다.
    for source, destination, attributes in network.edges(data=True):
        # 현재 트래픽이 전체 용량에서 차지하는 비율을 계산합니다.
        usage_percent = (
            attributes["traffic_mbps"] / attributes["capacity_mbps"] * 100
        )

        # 어떤 장비 사이의 링크인지 출력합니다.
        print(f"Link: {source} <-> {destination}")
        # 링크의 최대 전송 용량을 출력합니다.
        print(f"  Capacity    : {attributes['capacity_mbps']} Mbps")
        # 현재 트래픽과 용량 사용률을 함께 출력합니다.
        print(
            f"  Traffic     : {attributes['traffic_mbps']} Mbps "
            f"({usage_percent:.1f}%)"
        )
        # 경로 선택에 사용하는 학습용 routing cost를 출력합니다.
        print(f"  Routing Cost: {attributes['routing_cost']}")
        # 링크의 지연시간을 출력합니다.
        print(f"  Latency     : {attributes['latency_ms']} ms")
        # 링크의 패킷 손실률을 출력합니다.
        print(f"  Packet Loss : {attributes['packet_loss_percent']} %")
        # 현재 링크 상태를 출력합니다.
        print(f"  Status      : {attributes['status']}")
        # PRIMARY, ACCESS, BACKUP 중 링크 역할을 출력합니다.
        print(f"  Role        : {attributes['role']}")
        # 다음 링크와 구분하기 위한 선을 출력합니다.
        print("-" * 65)


# 출력이 가상 실험임을 명확하게 표시하는 함수입니다.
def print_simulation_notice():
    # 실제 네트워크에는 영향을 주지 않는다는 안내를 출력합니다.
    print("[SIMULATION ONLY] 가상 네트워크 장애 실험입니다.")
    print("[SIMULATION ONLY] 실제 장비나 실제 네트워크는 변경하지 않습니다.\n")


# 특정 가상 링크에 혼잡 장애를 주입하는 함수입니다.
def inject_congestion(network, source, destination, print_details=True):
    # 존재하지 않는 링크를 선택하면 이해하기 쉬운 오류를 만듭니다.
    if not network.has_edge(source, destination):
        raise ValueError(f"가상 링크를 찾을 수 없습니다: {source} <-> {destination}")

    # 선택한 링크에 저장된 속성 딕셔너리를 가져옵니다.
    link = network[source][destination]
    # 변경 전 값을 비교할 수 있도록 별도 딕셔너리에 복사합니다.
    before = link.copy()

    # 가상 트래픽을 링크 용량의 95%로 높입니다.
    link["traffic_mbps"] = round(link["capacity_mbps"] * CONGESTION_TRAFFIC_RATIO, 1)
    # 혼잡 상황을 표현하기 위해 가상 latency를 증가시킵니다.
    link["latency_ms"] += CONGESTION_LATENCY_INCREASE_MS
    # 혼잡 상황을 표현하기 위해 가상 packet loss를 증가시킵니다.
    link["packet_loss_percent"] += CONGESTION_PACKET_LOSS_INCREASE

    # 기존 simulator에서는 변경값을 출력하고 Incident 보고서에서는 생략합니다.
    if print_details:
        print(f"[SIMULATION] CONGESTION: {source} <-> {destination}")
        print(f"  traffic_mbps          : {before['traffic_mbps']} -> {link['traffic_mbps']}")
        print(f"  latency_ms            : {before['latency_ms']} -> {link['latency_ms']}")
        print(
            f"  packet_loss_percent   : {before['packet_loss_percent']} "
            f"-> {link['packet_loss_percent']}"
        )


# 특정 가상 링크에 단절 장애를 주입하는 함수입니다.
def inject_link_failure(network, source, destination):
    # 존재하지 않는 링크를 선택하면 이해하기 쉬운 오류를 만듭니다.
    if not network.has_edge(source, destination):
        raise ValueError(f"가상 링크를 찾을 수 없습니다: {source} <-> {destination}")

    # 선택한 링크에 저장된 속성 딕셔너리를 가져옵니다.
    link = network[source][destination]
    # 변경 전 링크 상태를 저장합니다.
    before_status = link["status"]
    # 가상 링크의 상태를 DOWN으로 바꿉니다.
    link["status"] = "DOWN"

    # 장애 종류와 선택한 가상 링크를 출력합니다.
    print(f"[SIMULATION] LINK_FAILURE: {source} <-> {destination}")
    # 단절 장애로 변경된 상태를 이전 값과 함께 출력합니다.
    print(f"  status                : {before_status} -> {link['status']}")


# 특정 가상 장비에 과부하 장애를 주입하는 함수입니다.
def inject_device_overload(network, device, print_details=True):
    # 존재하지 않는 장비를 선택하면 이해하기 쉬운 오류를 만듭니다.
    if device not in network:
        raise ValueError(f"가상 장비를 찾을 수 없습니다: {device}")

    # cpu_usage가 아직 없다면 변경 전 상태를 NOT_SET으로 표시합니다.
    before_cpu_usage = network.nodes[device].get("cpu_usage", "NOT_SET")
    # 선택한 가상 장비에 CPU 사용률 95% 값을 추가합니다.
    network.nodes[device]["cpu_usage"] = OVERLOAD_CPU_USAGE_PERCENT

    # 기존 simulator에서는 변경값을 출력하고 Incident 보고서에서는 생략합니다.
    if print_details:
        print(f"[SIMULATION] DEVICE_OVERLOAD: {device}")
        print(
            f"  cpu_usage             : {before_cpu_usage} "
            f"-> {network.nodes[device]['cpu_usage']}%"
        )


# DOWN 링크를 제외한 경로 탐색용 가상 네트워크를 만드는 함수입니다.
def create_active_network(network):
    # 원본 simulation 상태를 보존하기 위해 그래프를 복사합니다.
    active_network = network.copy()
    # status가 DOWN인 링크만 찾아 목록으로 만듭니다.
    down_links = [
        (source, destination)
        for source, destination, attributes in active_network.edges(data=True)
        if attributes["status"] == "DOWN"
    ]
    # DOWN 링크는 통신에 사용할 수 없으므로 경로 탐색용 그래프에서 제거합니다.
    active_network.remove_edges_from(down_links)
    # 현재 사용할 수 있는 링크만 남은 그래프를 돌려줍니다.
    return active_network


# 모든 EDGE 노드에서 CORE-01까지의 현재 경로를 확인하는 함수입니다.
def find_edge_paths(network):
    # DOWN 링크가 제외된 가상 그래프를 준비합니다.
    active_network = create_active_network(network)
    # 이름이 EDGE-로 시작하는 노드만 골라 정렬합니다.
    edge_nodes = sorted(node for node in network.nodes() if node.startswith("EDGE-"))
    # EDGE 노드별 경로를 저장할 빈 딕셔너리를 만듭니다.
    paths = {}

    # 각 EDGE 노드의 CORE-01 연결 경로를 하나씩 확인합니다.
    for edge_node in edge_nodes:
        # NetworkX가 경로가 존재하는지 먼저 검사합니다.
        if nx.has_path(active_network, edge_node, "CORE-01"):
            # DOWN 링크를 제외한 뒤 routing_cost 합이 가장 작은 경로를 저장합니다.
            paths[edge_node] = nx.shortest_path(
                active_network,
                edge_node,
                "CORE-01",
                weight="routing_cost",
            )
        # 연결 경로가 없으면 None을 저장합니다.
        else:
            paths[edge_node] = None

    # 모든 EDGE 노드의 경로 확인 결과를 돌려줍니다.
    return paths


# EDGE 노드별 CORE-01 연결 여부와 경로를 출력하는 함수입니다.
def print_edge_connectivity(title, paths, network):
    # 장애 전인지 장애 후인지 알 수 있도록 제목을 출력합니다.
    print(f"\n[SIMULATION] {title}")
    # EDGE 노드와 확인된 경로를 하나씩 가져옵니다.
    for edge_node, path in paths.items():
        # 경로가 있으면 CONNECTED와 실제 경로를 출력합니다.
        if path:
            print(f"- {edge_node}: CONNECTED ({' -> '.join(path)})")
            total_routing_cost = calculate_path_routing_cost(network, path)
            print(f"  Routing Cost: {total_routing_cost}")
        # 경로가 없으면 DISCONNECTED를 출력합니다.
        else:
            print(f"- {edge_node}: DISCONNECTED (CORE-01 경로 없음)")


# 가상 링크 단절 전후를 비교하여 영향 범위를 분석하는 함수입니다.
def analyze_link_failure_impact(network, source, destination):
    # 장애 전 모든 EDGE 노드의 CORE-01 경로를 확인합니다.
    paths_before = find_edge_paths(network)
    # 장애 전 연결 여부와 경로를 출력합니다.
    print_edge_connectivity("링크 장애 전 CORE-01 연결 상태", paths_before, network)

    # 선택한 링크를 가상으로 DOWN 처리합니다.
    inject_link_failure(network, source, destination)

    # 장애 후 같은 EDGE 노드의 CORE-01 경로를 다시 확인합니다.
    paths_after = find_edge_paths(network)
    # 장애 후 연결 여부와 경로를 출력합니다.
    print_edge_connectivity("링크 장애 후 CORE-01 연결 상태", paths_after, network)

    # 장애 전에는 연결됐지만 장애 후 끊긴 EDGE 노드만 찾습니다.
    affected_nodes = [
        edge_node
        for edge_node in paths_before
        if paths_before[edge_node] is not None and paths_after[edge_node] is None
    ]

    # 요청한 형식으로 영향받은 노드 목록의 제목을 출력합니다.
    print("\nAffected Nodes:")
    # 영향받은 EDGE 노드가 있으면 하나씩 출력합니다.
    if affected_nodes:
        for edge_node in affected_nodes:
            print(f"- {edge_node}")
    # 영향받은 노드가 없으면 없다고 표시합니다.
    else:
        print("- None")

    # 어떤 기존 경로에 DOWN 링크가 포함되어 있었는지 설명합니다.
    print("\nImpact Reason:")
    # 영향받은 노드마다 장애 전 경로를 출력합니다.
    for edge_node in affected_nodes:
        print(
            f"- {edge_node}: 기존 경로 {' -> '.join(paths_before[edge_node])}에서 "
            f"링크 {source} <-> {destination}가 DOWN되어 CORE-01에 연결할 수 없습니다."
        )

    # 다른 코드에서도 사용할 수 있도록 영향받은 노드 목록을 돌려줍니다.
    return affected_nodes


# 현재 관측된 가상 지표로 Root Cause Candidate를 찾는 함수입니다.
def find_root_cause_candidates(network):
    # 발견한 원인 후보와 근거를 저장할 빈 목록을 만듭니다.
    candidates = []

    # 모든 가상 링크의 상태와 지표를 하나씩 확인합니다.
    for source, destination, link in network.edges(data=True):
        # 현재 트래픽이 링크 용량에서 차지하는 비율을 계산합니다.
        traffic_percent = link["traffic_mbps"] / link["capacity_mbps"] * 100
        # 현재 latency가 simulation 시작 시의 정상값보다 증가했는지 확인합니다.
        latency_increased = link["latency_ms"] > link["baseline_latency_ms"]
        # 현재 packet loss가 simulation 시작 시의 정상값보다 증가했는지 확인합니다.
        packet_loss_increased = (
            link["packet_loss_percent"] > link["baseline_packet_loss_percent"]
        )

        # 트래픽이 85%를 넘고 latency와 packet loss도 함께 증가했는지 판단합니다.
        if (
            traffic_percent > CAUSE_TRAFFIC_THRESHOLD_PERCENT
            and latency_increased
            and packet_loss_increased
        ):
            # 조건을 만족한 링크를 TRAFFIC_CONGESTION 후보로 추가합니다.
            candidates.append(
                {
                    "cause": "TRAFFIC_CONGESTION",
                    "target": f"{source} <-> {destination}",
                    "evidence": (
                        f"traffic={traffic_percent:.1f}% "
                        f"({link['traffic_mbps']}/{link['capacity_mbps']} Mbps), "
                        f"latency={link['baseline_latency_ms']}->{link['latency_ms']} ms, "
                        f"packet_loss={link['baseline_packet_loss_percent']}"
                        f"->{link['packet_loss_percent']}%"
                    ),
                    "explanation": (
                        f"트래픽 사용률이 {CAUSE_TRAFFIC_THRESHOLD_PERCENT}%를 초과했고 "
                        "latency와 packet loss가 정상 초기값보다 함께 증가했습니다."
                    ),
                }
            )

        # 링크 상태가 DOWN인지 단순한 if문으로 확인합니다.
        if link["status"] == "DOWN":
            # DOWN 링크를 LINK_FAILURE 후보로 추가합니다.
            candidates.append(
                {
                    "cause": "LINK_FAILURE",
                    "target": f"{source} <-> {destination}",
                    "evidence": f"status={link['status']}",
                    "explanation": "관측된 가상 링크 상태가 DOWN입니다.",
                }
            )

    # 모든 가상 장비의 cpu_usage 값을 하나씩 확인합니다.
    for device, attributes in network.nodes(data=True):
        # cpu_usage가 없는 정상 장비는 0으로 간주합니다.
        cpu_usage = attributes.get("cpu_usage", 0)
        # CPU 사용률이 90%를 넘었는지 단순한 if문으로 확인합니다.
        if cpu_usage > CAUSE_CPU_THRESHOLD_PERCENT:
            # 조건을 만족한 장비를 DEVICE_OVERLOAD 후보로 추가합니다.
            candidates.append(
                {
                    "cause": "DEVICE_OVERLOAD",
                    "target": device,
                    "evidence": f"cpu_usage={cpu_usage}%",
                    "explanation": (
                        f"관측된 CPU 사용률이 {CAUSE_CPU_THRESHOLD_PERCENT}%를 초과했습니다."
                    ),
                }
            )

    # 발견된 후보 목록을 호출한 곳으로 돌려줍니다.
    return candidates


# Root Cause Candidate와 판단 근거를 터미널에 출력하는 함수입니다.
def print_root_cause_candidates(candidates):
    # 이 결과가 확정된 원인이 아니라 후보임을 명확히 표시합니다.
    print("\n[SIMULATION] Root Cause Candidates (Probable Causes)")
    print("이 결과는 관측된 가상 지표 기반의 원인 후보이며 확정 판정이 아닙니다.")

    # 조건에 맞는 후보가 없으면 없다고 출력합니다.
    if not candidates:
        print("- Candidate: NONE")
        print("  Explanation: 현재 단순 규칙을 만족하는 원인 후보가 없습니다.")
        return

    # 발견된 각 후보의 원인, 대상, 근거, 설명을 출력합니다.
    for candidate in candidates:
        print(f"- Candidate: {candidate['cause']}")
        print(f"  Target: {candidate['target']}")
        print(f"  Evidence: {candidate['evidence']}")
        print(f"  Explanation: {candidate['explanation']}")


# 세 종류 중 하나를 임의로 골라 가상 장애를 주입하는 함수입니다.
def inject_random_failure(network):
    # 지원하는 가상 장애 종류 중 하나를 무작위로 선택합니다.
    failure_type = random.choice(["CONGESTION", "LINK_FAILURE", "DEVICE_OVERLOAD"])

    # 혼잡 또는 링크 단절은 무작위 링크 하나를 대상으로 사용합니다.
    if failure_type in ("CONGESTION", "LINK_FAILURE"):
        # 그래프의 모든 링크 중 하나를 무작위로 선택합니다.
        source, destination = random.choice(list(network.edges()))
        # 선택된 종류가 혼잡이면 혼잡 주입 함수를 실행합니다.
        if failure_type == "CONGESTION":
            inject_congestion(network, source, destination)
        # 선택된 종류가 링크 단절이면 단절 주입 함수를 실행합니다.
        else:
            analyze_link_failure_impact(network, source, destination)
    # 장비 과부하는 무작위 장비 하나를 대상으로 사용합니다.
    else:
        # 그래프의 모든 장비 중 하나를 무작위로 선택합니다.
        device = random.choice(list(network.nodes()))
        # 선택한 장비에 과부하를 주입합니다.
        inject_device_overload(network, device)


# 명령줄에 입력한 장애 종류와 대상에 따라 수동 장애를 주입하는 함수입니다.
def inject_manual_failure(network, arguments):
    # 첫 번째 입력값을 대문자로 바꾸어 장애 종류로 사용합니다.
    failure_type = arguments[0].upper()

    # CONGESTION 뒤에는 링크 양 끝의 장비 이름 2개가 필요합니다.
    if failure_type == "CONGESTION" and len(arguments) == 3:
        inject_congestion(network, arguments[1], arguments[2])
    # LINK_FAILURE 뒤에는 링크 양 끝의 장비 이름 2개가 필요합니다.
    elif failure_type == "LINK_FAILURE" and len(arguments) == 3:
        analyze_link_failure_impact(network, arguments[1], arguments[2])
    # DEVICE_OVERLOAD 뒤에는 장비 이름 1개가 필요합니다.
    elif failure_type == "DEVICE_OVERLOAD" and len(arguments) == 2:
        inject_device_overload(network, arguments[1])
    # 입력 형식이 맞지 않으면 올바른 사용법을 알려주는 오류를 만듭니다.
    else:
        raise ValueError(
            "사용법: random | CONGESTION 장비1 장비2 | "
            "LINK_FAILURE 장비1 장비2 | DEVICE_OVERLOAD 장비"
        )


# 이 파일을 직접 실행했을 때만 아래 코드를 실행합니다.
if __name__ == "__main__":
    # 이 프로그램이 실제 장애 도구가 아닌 simulation임을 먼저 알립니다.
    print_simulation_notice()
    # 조건에 맞는 가상 네트워크를 하나 만듭니다.
    simulated_network = create_network()
    # Flow별 서비스와 NetworkX가 계산한 실제 경로를 먼저 출력합니다.
    print_flow_paths(simulated_network.graph["flows"])
    # 여러 Flow가 같은 링크에서 합산된 결과를 출력합니다.
    print_link_traffic(simulated_network)
    # 장애 주입 전 모든 가상 링크 상태를 터미널에 출력합니다.
    print("[SIMULATION] 장애 주입 전 상태")
    print_link_status(simulated_network)

    # 명령줄 입력이 없으면 기본값으로 랜덤 가상 장애를 사용합니다.
    simulation_arguments = sys.argv[1:] if len(sys.argv) > 1 else ["random"]

    # 잘못된 대상이나 입력 형식을 짧은 메시지로 처리합니다.
    try:
        # random을 입력했다면 임의 장애 주입 함수를 실행합니다.
        if simulation_arguments[0].lower() == "random":
            print("[SIMULATION] 랜덤 장애를 선택합니다.")
            inject_random_failure(simulated_network)
        # 그 외에는 사용자가 지정한 수동 장애를 주입합니다.
        else:
            print("[SIMULATION] 수동 장애를 적용합니다.")
            inject_manual_failure(simulated_network, simulation_arguments)
        # 장애 주입 후 관측된 값으로 가능한 원인 후보를 분석하고 출력합니다.
        candidates = find_root_cause_candidates(simulated_network)
        print_root_cause_candidates(candidates)
    # 가상 링크, 장비 또는 입력 형식에 문제가 있으면 아래 코드를 실행합니다.
    except ValueError as error:
        # 사용자가 수정할 수 있도록 오류 내용을 출력합니다.
        print(f"[SIMULATION] 장애를 적용할 수 없습니다: {error}")
