# NetOps Inspector

> Python 기반 네트워크 품질 모니터링 및 장애 대응 시뮬레이션 프로젝트

## 1. 프로젝트 개요

네트워크 운영에서
**품질 모니터링 → 이상 탐지 → 영향 범위 분석 → 원인 후보 도출 → 대응 → 정상화 검증**
과정이 어떻게 연결되는지 직접 구현하며 학습하기 위해 제작한 개인 프로젝트입니다.

Python과 NetworkX를 활용해 가상 네트워크를 구성하고,
Congestion, Link Failure, Device Overload 상황에서
utilization, latency, packet loss, CPU, memory 등 여러 지표를 기반으로
장애 원인 후보를 판단하고 대응 결과를 재검증하도록 구현했습니다.

또한 실제 Windows Ping을 통해 RTT와 Packet Loss를 수집하고,
시간에 따른 네트워크 품질 변화를 확인하도록 구성했습니다.

> **프로젝트 범위**
>
> 실제 측정 영역은 PC에서 수행한 ICMP Ping 결과입니다.
> Topology, Traffic, Device 상태, 장애 상황 등은
> 네트워크 운영 과정을 학습하기 위한 simulation입니다.
