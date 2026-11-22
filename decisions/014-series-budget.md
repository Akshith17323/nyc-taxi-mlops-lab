# 014: Active series budget and relabeling rules

Stage: S5 · Date: 2026-11-22 · Author: Akshith · Drafted by agent: yes

## Choice

Enforce relabeling in `observability/alloy/budget.alloy` to keep active series at ~500–700 per host (~1,500–2,000 total across 3 hosts), well within Grafana Cloud's 10,000 free-tier ceiling:
1. **Host (`declare "host"`):** Keep key node metrics (`node_cpu_seconds_total`, `node_memory_Mem(Total|Available|Free)_bytes`, `node_filesystem_(free|size|avail)_bytes`, `node_network_(receive|transmit)_bytes_total`, `node_load[15]`, `node_disk_(read|write)s_completed_total`). Drop virtual interfaces (`lo`, `veth.*`, `br-.*`, `docker0`) and non-root mounts.
2. **Containers (`declare "containers"`):** Keep CPU (`container_cpu_usage_seconds_total`), memory (`container_memory_working_set_bytes`), and network I/O. Drop unnamed containers (`name=""`). Drop high-churn labels (`id`, `image`, `container_label_.*`).
3. **Services (`declare "services"`):** Keep all application and model contract metrics (`lab_.*`) and Traefik service metrics (`traefik_service_.*`).

## Rejected alternative

- Forwarding unfiltered cAdvisor and node metrics: initial series count exceeds 3,300, and container `id` churn from blue-green deployments rapidly explodes series past the 10,000 limit.
- Dropping container metrics entirely: leaves operators blind to container OOM kills and CPU throttling during blue-green switches.

## Why

1. **Deploy Churn Prevention:** cAdvisor tags container metrics with `id` (`/docker/<64-char-hash>`). Every blue-green deployment spins up new container instances with new hashes, generating hundreds of new time series on each deploy. By dropping `id` and `image` while keeping the stable `name` label (`app-blue`, `app-green`, `serving-champion`), metrics reuse existing series across deploys.
2. **Headroom for Future Stages:** Maintaining ~500–700 series per host across the app host, platform host, and upcoming S6 LLM host uses ~1,800 series total, leaving >80% (>8,000 series) headroom under Grafana Cloud's free-tier limit.
3. **Sufficient Diagnostic Power:** Retaining core host CPU, memory, disk, network, and container working set provides full visibility into resource exhaustion without paying for hundreds of unused subsystem metrics.

## What would show this was wrong

If an incident investigation requires correlating specific transient container hash IDs from Prometheus metrics rather than Docker/SSM logs, or if additional microservices push active series over 8,000, requiring tighter metric whitelisting.
