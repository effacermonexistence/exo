<script lang="ts">
  import { onMount } from "svelte";
  import HeaderNav from "$lib/components/HeaderNav.svelte";

  interface MemoryValue {
    inBytes: number;
  }

  interface NodeIdentity {
    modelId?: string;
    chipId?: string;
    friendlyName?: string;
  }

  interface NodeMemory {
    ramTotal?: MemoryValue;
    ramAvailable?: MemoryValue;
  }

  interface NodeSystem {
    gpuUsage?: number;
    temp?: number;
    sysPower?: number;
    pcpuUsage?: number;
    ecpuUsage?: number;
  }

  interface ClusterState {
    topology?: { nodes?: string[] };
    nodeIdentities?: Record<string, NodeIdentity>;
    nodeMemory?: Record<string, NodeMemory>;
    nodeSystem?: Record<string, NodeSystem>;
    nodeNetwork?: Record<
      string,
      { interfaces?: Array<{ name?: string; ipAddress?: string }> }
    >;
    nodeDisk?: Record<
      string,
      { total?: MemoryValue; available?: MemoryValue }
    >;
  }

  interface FleetNode {
    cpu_logical_count?: number;
    device_id?: string;
    exo_nodes?: number;
    exo_ready?: boolean;
    has_claude?: boolean;
    has_codex?: boolean;
    hostname?: string;
    last_seen_ms?: number;
    load_average_1m?: number;
    memory_available_mib?: number;
    memory_total_mib?: number;
    queue_depth?: number;
    role?: string;
    zerotier_ip?: string;
  }

  interface FleetJob {
    execution_mode?: string;
    executor_device_id?: string;
    job_id?: string;
    objective_version?: string;
    profile?: string;
    state?: string;
    updated_at_ms?: number;
  }

  interface LocalActivity {
    api_origin?: string;
    node_id: string;
    sampled_at: string;
    sample_interval_seconds: number;
    host?: {
      hostname?: string;
      device_id?: string;
      role?: string;
      zerotier_ip?: string;
    };
    cpu: {
      system_percent: number;
      per_core_percent: number[];
      logical_count: number;
      load_average_1m: number;
      exo_process_percent: number;
    };
    memory: {
      total_bytes: number;
      used_bytes: number;
      available_bytes: number;
      swap_total_bytes: number;
      swap_used_bytes: number;
      exo_process_resident_bytes: number;
    };
    gpu: {
      usage_percent: number;
      temperature_celsius: number;
      performance_cpu_percent: number;
      efficiency_cpu_percent: number;
    };
    energy: {
      system_power_watts: number;
      monitor_session_joules: number;
      monitor_session_watt_hours: number;
      monitor_uptime_seconds: number;
    };
    disk: {
      read_bytes_per_second: number;
      write_bytes_per_second: number;
      read_operations_per_second: number;
      write_operations_per_second: number;
    };
    network: {
      received_bytes_per_second: number;
      sent_bytes_per_second: number;
      received_bytes_total: number;
      sent_bytes_total: number;
    };
    roaming?: {
      available: boolean;
      stale: boolean;
      state: string;
      sampled_at?: string;
      age_seconds?: number;
      recovery_count?: number;
      peer_reachable?: boolean;
      peer_api_ip?: string;
      network_changed_at?: string;
      last_recovery_at?: string;
    };
    exo: {
      topology_nodes: number;
      instances: number;
      runners: number;
      tasks: number;
      last_event_applied_index: number;
    };
    fleet: {
      nodes?: FleetNode[];
      recent_jobs?: FleetJob[];
      error?: string | null;
      cache_age_seconds?: number;
    };
  }

  interface HistoryPoint {
    at: number;
    cpu: number;
    memory: number;
    gpu: number;
    power: number;
    disk: number;
    network: number;
  }

  interface NodeRow {
    nodeId: string;
    name: string;
    model: string;
    ip: string;
    activity: LocalActivity | null;
    fleet: FleetNode | null;
    cpu: number;
    memoryPercent: number;
    memoryUsed: number;
    memoryTotal: number;
    gpu: number;
    temperature: number;
    power: number;
    diskRead: number;
    diskWrite: number;
    networkReceive: number;
    networkSend: number;
    diskAvailable: number;
    diskTotal: number;
    stale: boolean;
  }

  let clusterState: ClusterState | null = $state(null);
  let activities: Record<string, LocalActivity> = $state({});
  let histories: Record<string, HistoryPoint[]> = $state({});
  let stateError: string | null = $state(null);
  let lastRefresh = $state(0);
  let observedAt = $state(Date.now());
  let polling = false;
  let balance = $derived(convergence());
  let totals = $derived(clusterTotals());

  function clampPercent(value: number): number {
    return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  }

  function formatPercent(value: number): string {
    return `${clampPercent(value).toFixed(0)}%`;
  }

  function formatBytes(value: number): string {
    if (!Number.isFinite(value) || value <= 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const exponent = Math.min(
      Math.floor(Math.log(value) / Math.log(1024)),
      units.length - 1,
    );
    return `${(value / 1024 ** exponent).toFixed(exponent > 2 ? 1 : 0)} ${units[exponent]}`;
  }

  function formatRate(value: number): string {
    return `${formatBytes(value)}/s`;
  }

  function formatDuration(milliseconds: number): string {
    if (!Number.isFinite(milliseconds) || milliseconds < 0) return "—";
    if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
    return `${(milliseconds / 1000).toFixed(1)} s`;
  }

  function nodeIp(nodeId: string): string {
    const interfaces = clusterState?.nodeNetwork?.[nodeId]?.interfaces ?? [];
    const zeroTier = interfaces.find((item) =>
      item.ipAddress?.startsWith("10.215."),
    );
    return zeroTier?.ipAddress ?? interfaces[0]?.ipAddress ?? "";
  }

  function fleetNodes(): FleetNode[] {
    const byId = new Map<string, FleetNode>();
    for (const activity of Object.values(activities)) {
      for (const node of activity.fleet.nodes ?? []) {
        const key = node.device_id ?? node.hostname ?? node.zerotier_ip;
        if (key) byId.set(key, node);
      }
    }
    return [...byId.values()];
  }

  function recentJobs(): FleetJob[] {
    const byId = new Map<string, FleetJob>();
    for (const activity of Object.values(activities)) {
      for (const job of activity.fleet.recent_jobs ?? []) {
        if (job.job_id) byId.set(job.job_id, job);
      }
    }
    return [...byId.values()]
      .sort((a, b) => (b.updated_at_ms ?? 0) - (a.updated_at_ms ?? 0))
      .slice(0, 12);
  }

  function nodeRows(): NodeRow[] {
    const now = observedAt;
    const nodeIds = new Set([
      ...(clusterState?.topology?.nodes ?? []),
      ...Object.keys(activities),
    ]);
    return [...nodeIds].map((nodeId) => {
      const identity = clusterState?.nodeIdentities?.[nodeId];
      const memory = clusterState?.nodeMemory?.[nodeId];
      const system = clusterState?.nodeSystem?.[nodeId];
      const disk = clusterState?.nodeDisk?.[nodeId];
      const activity = activities[nodeId] ?? null;
      const originIp = activity?.api_origin
        ? new URL(activity.api_origin).hostname
        : "";
      const activityIp = activity?.host?.zerotier_ip ?? originIp;
      const ip = nodeIp(nodeId) || activityIp;
      const fleet =
        fleetNodes().find(
          (item) =>
            item.zerotier_ip === ip ||
            item.device_id === activity?.host?.device_id,
        ) ?? null;
      const memoryTotal =
        activity?.memory.total_bytes ?? memory?.ramTotal?.inBytes ?? 0;
      const memoryUsed =
        activity?.memory.used_bytes ??
        Math.max(
          memoryTotal - (memory?.ramAvailable?.inBytes ?? memoryTotal),
          0,
        );
      const sampledAt = activity ? Date.parse(activity.sampled_at) : 0;

      return {
        nodeId,
        name:
          identity?.friendlyName ??
          (fleet?.role === "pro"
            ? "MacBook Pro"
            : fleet?.role === "air"
              ? "MacBook Air"
              : activity?.host?.hostname ?? nodeId.slice(0, 12)),
        model:
          identity?.modelId ??
          identity?.chipId ??
          (fleet?.role === "pro"
            ? "Apple M4 Max"
            : fleet?.role === "air"
              ? "Apple M5"
              : "Unknown Mac"),
        ip,
        activity,
        fleet,
        cpu:
          activity?.cpu.system_percent ??
          ((system?.pcpuUsage ?? 0) + (system?.ecpuUsage ?? 0)) * 50,
        memoryPercent: memoryTotal > 0 ? (memoryUsed / memoryTotal) * 100 : 0,
        memoryUsed,
        memoryTotal,
        gpu: activity?.gpu.usage_percent ?? (system?.gpuUsage ?? 0) * 100,
        temperature:
          activity?.gpu.temperature_celsius ?? system?.temp ?? 0,
        power: activity?.energy.system_power_watts ?? system?.sysPower ?? 0,
        diskRead: activity?.disk.read_bytes_per_second ?? 0,
        diskWrite: activity?.disk.write_bytes_per_second ?? 0,
        networkReceive: activity?.network.received_bytes_per_second ?? 0,
        networkSend: activity?.network.sent_bytes_per_second ?? 0,
        diskAvailable: disk?.available?.inBytes ?? 0,
        diskTotal: disk?.total?.inBytes ?? 0,
        stale:
          !activity ||
          !Number.isFinite(sampledAt) ||
          now - sampledAt > 15_000 ||
          sampledAt - now > 5_000,
      };
    });
  }

  function roamingStatus(row: NodeRow): { label: string; healthy: boolean } {
    const roaming = row.activity?.roaming;
    if (!roaming?.available) {
      return { label: "자동 복구 정보 없음 · 설치 확인 필요", healthy: false };
    }
    const age = observedAt - Date.parse(roaming.sampled_at ?? "");
    if (row.stale || roaming.stale || !Number.isFinite(age) || age > 60_000 || age < -5_000) {
      return { label: "자동 복구 상태 갱신 대기", healthy: false };
    }
    const labels: Record<string, string> = {
      starting: "자동 복구 시작 중",
      connected: "연결 정상 · Wi-Fi 이동 감시 중",
      waiting_for_network: "네트워크 또는 상대 Mac 연결 대기",
      reconnecting: "네트워크 복구됨 · EXO 재연결 중",
      waiting_for_idle: "실행 중인 작업 보호 · 복구 대기",
      recovering: "EXO 자동 복구 중",
      cooldown: "재시도 간격 대기",
      attention_required: "자동 복구 점검 필요",
      degraded: "연결 복구 확인 필요",
    };
    return {
      label: labels[roaming.state] ?? "자동 복구 상태 확인 필요",
      healthy: roaming.state === "connected",
    };
  }

  function clusterTotals() {
    const rows = nodeRows();
    return {
      cpu: rows.length
        ? rows.reduce((sum, row) => sum + row.cpu, 0) / rows.length
        : 0,
      memoryUsed: rows.reduce((sum, row) => sum + row.memoryUsed, 0),
      memoryTotal: rows.reduce((sum, row) => sum + row.memoryTotal, 0),
      gpu: rows.length
        ? rows.reduce((sum, row) => sum + row.gpu, 0) / rows.length
        : 0,
      power: rows.reduce((sum, row) => sum + row.power, 0),
      disk: rows.reduce((sum, row) => sum + row.diskRead + row.diskWrite, 0),
      network: rows.reduce(
        (sum, row) => sum + row.networkReceive + row.networkSend,
        0,
      ),
    };
  }

  function convergence(): {
    score: number | null;
    spread: number | null;
    status: string;
  } {
    const rows = nodeRows();
    if (rows.length < 2 || rows.some((row) => row.stale)) {
      return { score: null, spread: null, status: "WAITING FOR 2 FRESH NODES" };
    }
    const loads = rows.map((row) => {
      const queuePressure = Math.min((row.fleet?.queue_depth ?? 0) / 4, 1);
      return (
        0.35 * (clampPercent(row.cpu) / 100) +
        0.35 * (clampPercent(row.memoryPercent) / 100) +
        0.2 * (clampPercent(row.gpu) / 100) +
        0.1 * queuePressure
      );
    });
    const spread = (Math.max(...loads) - Math.min(...loads)) * 100;
    return {
      score: Math.max(0, Math.min(100, 100 - spread)),
      spread,
      status: spread <= 15 ? "CONVERGED" : "OBSERVED LOAD IMBALANCE",
    };
  }

  function sparkline(nodeId: string, field: keyof HistoryPoint): string {
    const points = histories[nodeId] ?? [];
    if (points.length < 2) return "";
    const values = points.map((point) => Number(point[field]));
    const maximum = Math.max(...values, field === "power" ? 1 : 100);
    return values
      .map((value, index) => {
        const x = (index / Math.max(values.length - 1, 1)) * 100;
        const y = 28 - (Math.max(value, 0) / maximum) * 26;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }

  function appendHistory(activity: LocalActivity): void {
    const memoryPercent = activity.memory.total_bytes
      ? (activity.memory.used_bytes / activity.memory.total_bytes) * 100
      : 0;
    const next: HistoryPoint = {
      at: Date.now(),
      cpu: activity.cpu.system_percent,
      memory: memoryPercent,
      gpu: activity.gpu.usage_percent,
      power: activity.energy.system_power_watts,
      disk:
        activity.disk.read_bytes_per_second +
        activity.disk.write_bytes_per_second,
      network:
        activity.network.received_bytes_per_second +
        activity.network.sent_bytes_per_second,
    };
    histories = {
      ...histories,
      [activity.node_id]: [...(histories[activity.node_id] ?? []), next].slice(
        -60,
      ),
    };
  }

  async function fetchJson(url: string): Promise<unknown> {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 7000);
    try {
      const response = await fetch(url, {
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      return await response.json();
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function poll(): Promise<void> {
    observedAt = Date.now();
    if (polling) return;
    polling = true;
    try {
      clusterState = (await fetchJson("/state")) as ClusterState;
      stateError = null;

      const origins = new Set<string>([window.location.origin]);
      for (const nodeId of clusterState.topology?.nodes ?? []) {
        const ip = nodeIp(nodeId);
        if (ip) origins.add(`http://${ip}:52415`);
      }

      const results = await Promise.allSettled(
        [...origins].map(async (origin) => {
          const activity = (await fetchJson(
            `${origin}/activity/local`,
          )) as LocalActivity;
          activity.api_origin = origin;
          return activity;
        }),
      );
      const nextActivities = { ...activities };
      for (const result of results) {
        if (result.status === "fulfilled" && result.value.node_id) {
          nextActivities[result.value.node_id] = result.value;
          appendHistory(result.value);
        }
      }
      activities = nextActivities;
      lastRefresh = Date.now();
    } catch (error) {
      stateError = error instanceof Error ? error.message : "EXO state unavailable";
    } finally {
      polling = false;
    }
  }

  onMount(() => {
    void poll();
    const interval = window.setInterval(() => void poll(), 1000);
    return () => window.clearInterval(interval);
  });
</script>

<svelte:head>
  <title>Cluster Activity — EXO</title>
  <meta
    name="description"
    content="Two-node EXO and OS1 Fleet resource activity monitor"
  />
</svelte:head>

<div class="min-h-screen bg-exo-black text-white grid-bg">
  <HeaderNav showHome={true} />

  <main class="mx-auto max-w-[1600px] px-4 md:px-8 pb-12">
    <section
      class="command-panel rounded-lg p-5 md:p-7 mb-5 border-t border-t-exo-yellow/40"
    >
      <div class="flex flex-col xl:flex-row xl:items-end justify-between gap-5">
        <div>
          <div class="text-[11px] tracking-[0.28em] text-exo-yellow uppercase mb-2">
            OS1 Fleet Objective Function · Live telemetry
          </div>
          <h1 class="text-2xl md:text-3xl font-semibold tracking-tight">
            Two-Mac Cluster Activity
          </h1>
          <p class="mt-2 text-sm text-white/55 max-w-3xl">
            EXO 추론 자원과 OS1의 Codex·Claude 작업 단위 배정을 한 화면에서
            봅니다. 모든 값은 실측값이며 1초 간격으로 갱신됩니다.
          </p>
        </div>

        <div class="grid grid-cols-2 gap-3 min-w-[320px]">
          <div class="rounded border border-white/10 bg-black/30 px-4 py-3">
            <div class="text-[10px] text-white/45 tracking-widest uppercase">
              Balance convergence
            </div>
            <div class="mt-1 text-2xl font-semibold text-exo-yellow">
              {balance.score === null ? "—" : `${balance.score.toFixed(1)}`}
              <span class="text-xs text-white/40">/100</span>
            </div>
          </div>
          <div class="rounded border border-white/10 bg-black/30 px-4 py-3">
            <div class="text-[10px] text-white/45 tracking-widest uppercase">
              Status
            </div>
            <div
              class="mt-2 text-xs font-semibold {balance.score !== null &&
              balance.score >= 85
                ? 'text-emerald-400'
                : 'text-amber-300'}"
            >
              {balance.status}
            </div>
            <div class="mt-1 text-[10px] text-white/35">
              load spread {balance.spread === null
                ? "—"
                : `${balance.spread.toFixed(1)} pts`}
            </div>
          </div>
        </div>
      </div>

      <div class="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px]">
        <span class="text-white/45">Objective</span>
        <span class="text-white/80">os1-fleet-objective-v1</span>
        <span class="text-white/45">EXO topology</span>
        <span class="text-white/80"
          >{clusterState?.topology?.nodes?.length ?? 0} nodes</span
        >
        <span class="text-white/45">Last refresh</span>
        <span class="text-white/80"
          >{lastRefresh ? new Date(lastRefresh).toLocaleTimeString() : "—"}</span
        >
        {#if stateError}
          <span class="text-red-400">{stateError}</span>
        {/if}
      </div>
    </section>

    <section class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3 mb-5">
      {#each [
        ["CPU AVG", formatPercent(totals.cpu)],
        ["MEMORY", `${formatBytes(totals.memoryUsed)} / ${formatBytes(totals.memoryTotal)}`],
        ["GPU AVG", formatPercent(totals.gpu)],
        ["ENERGY", `${totals.power.toFixed(1)} W`],
        ["DISK I/O", formatRate(totals.disk)],
        ["NETWORK", formatRate(totals.network)],
        ["FLEET QUEUE", `${fleetNodes().reduce((sum, node) => sum + (node.queue_depth ?? 0), 0)}`],
      ] as summary}
        <div class="command-panel rounded px-4 py-3 min-w-0">
          <div class="text-[9px] text-white/40 tracking-[0.18em]">
            {summary[0]}
          </div>
          <div class="mt-1 text-sm text-white/90 truncate" title={summary[1]}>
            {summary[1]}
          </div>
        </div>
      {/each}
    </section>

    <section class="grid grid-cols-1 2xl:grid-cols-2 gap-5 mb-5">
      {#each nodeRows() as row}
        {@const roaming = roamingStatus(row)}
        <article
          class="command-panel rounded-lg p-5 border-l-2 {row.stale
            ? 'border-l-amber-400'
            : 'border-l-emerald-400'}"
        >
          <div class="flex items-start justify-between gap-4 mb-5">
            <div>
              <div class="flex items-center gap-2">
                <span
                  class="h-2 w-2 rounded-full {row.stale
                    ? 'bg-amber-400'
                    : 'bg-emerald-400 status-pulse'}"
                ></span>
                <h2 class="text-lg font-semibold">{row.name}</h2>
                <span class="text-[10px] text-exo-yellow uppercase"
                  >{row.fleet?.role ?? "EXO"}</span
                >
              </div>
              <div class="mt-1 text-xs text-white/45">
                {row.model} · {row.ip || "address pending"}
              </div>
            </div>
            <div class="text-right text-[10px] text-white/40">
              <div>{row.activity?.cpu.logical_count ?? 0} logical CPU</div>
              <div>
                EXO {row.activity?.exo.topology_nodes ?? 0} · queue {row.fleet?.queue_depth ?? 0}
              </div>
            </div>
          </div>

          <div
            class="mb-4 rounded border px-3 py-2 text-[11px] {roaming.healthy
              ? 'border-emerald-400/20 bg-emerald-400/5 text-emerald-300'
              : 'border-amber-400/20 bg-amber-400/5 text-amber-200'}"
          >
            <span class="mr-2 text-white/45">Wi-Fi 이동</span>
            {roaming.label}
            {#if row.activity?.roaming?.available && !row.activity.roaming.stale && !row.stale}
              <span class="ml-2 text-white/40">
                복구 {row.activity.roaming.recovery_count ?? 0}회
              </span>
            {/if}
          </div>

          <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div class="rounded border border-white/10 bg-black/25 p-3">
              <div class="flex justify-between text-[10px] text-white/45">
                <span>CPU</span><span>{formatPercent(row.cpu)}</span>
              </div>
              <svg class="mt-2 h-8 w-full" viewBox="0 0 100 30" preserveAspectRatio="none">
                <polyline
                  points={sparkline(row.nodeId, "cpu")}
                  fill="none"
                  stroke="var(--exo-yellow)"
                  stroke-width="1.5"
                  vector-effect="non-scaling-stroke"
                />
              </svg>
              <div class="mt-1 text-[9px] text-white/35">
                EXO process {formatPercent(row.activity?.cpu.exo_process_percent ?? 0)}
              </div>
            </div>

            <div class="rounded border border-white/10 bg-black/25 p-3">
              <div class="flex justify-between text-[10px] text-white/45">
                <span>MEMORY</span><span>{formatPercent(row.memoryPercent)}</span>
              </div>
              <div class="mt-3 h-2 rounded bg-white/10 overflow-hidden">
                <div
                  class="h-full bg-blue-400 transition-all duration-500"
                  style={`width: ${clampPercent(row.memoryPercent)}%`}
                ></div>
              </div>
              <div class="mt-3 text-[9px] text-white/35">
                {formatBytes(row.memoryUsed)} / {formatBytes(row.memoryTotal)}
              </div>
            </div>

            <div class="rounded border border-white/10 bg-black/25 p-3">
              <div class="flex justify-between text-[10px] text-white/45">
                <span>GPU</span><span>{formatPercent(row.gpu)}</span>
              </div>
              <svg class="mt-2 h-8 w-full" viewBox="0 0 100 30" preserveAspectRatio="none">
                <polyline
                  points={sparkline(row.nodeId, "gpu")}
                  fill="none"
                  stroke="#a78bfa"
                  stroke-width="1.5"
                  vector-effect="non-scaling-stroke"
                />
              </svg>
              <div class="mt-1 text-[9px] text-white/35">
                {row.temperature.toFixed(0)}°C · P {formatPercent(row.activity?.gpu.performance_cpu_percent ?? 0)} · E {formatPercent(row.activity?.gpu.efficiency_cpu_percent ?? 0)}
              </div>
            </div>

            <div class="rounded border border-white/10 bg-black/25 p-3">
              <div class="flex justify-between text-[10px] text-white/45">
                <span>ENERGY</span><span>{row.power.toFixed(1)} W</span>
              </div>
              <svg class="mt-2 h-8 w-full" viewBox="0 0 100 30" preserveAspectRatio="none">
                <polyline
                  points={sparkline(row.nodeId, "power")}
                  fill="none"
                  stroke="#34d399"
                  stroke-width="1.5"
                  vector-effect="non-scaling-stroke"
                />
              </svg>
              <div class="mt-1 text-[9px] text-white/35">
                session {row.activity?.energy.monitor_session_watt_hours.toFixed(3) ?? "0.000"} Wh
              </div>
            </div>
          </div>

          <div class="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3 text-[10px]">
            <div class="rounded border border-white/10 px-3 py-2.5">
              <div class="text-white/40">DISK</div>
              <div class="mt-1 flex justify-between">
                <span>Read {formatRate(row.diskRead)}</span>
                <span>Write {formatRate(row.diskWrite)}</span>
              </div>
              <div class="mt-1 text-white/35">
                {formatBytes(row.diskAvailable)} free / {formatBytes(row.diskTotal)}
              </div>
            </div>
            <div class="rounded border border-white/10 px-3 py-2.5">
              <div class="text-white/40">NETWORK</div>
              <div class="mt-1 flex justify-between">
                <span>In {formatRate(row.networkReceive)}</span>
                <span>Out {formatRate(row.networkSend)}</span>
              </div>
              <div class="mt-1 text-white/35">ZeroTier · EXO API 52415</div>
            </div>
            <div class="rounded border border-white/10 px-3 py-2.5">
              <div class="text-white/40">OS1 EXECUTOR</div>
              <div class="mt-1 flex justify-between">
                <span>Codex {row.fleet?.has_codex ? "READY" : "—"}</span>
                <span>Claude {row.fleet?.has_claude ? "READY" : "—"}</span>
              </div>
              <div class="mt-1 text-white/35">
                heartbeat {formatDuration(Date.now() - (row.fleet?.last_seen_ms ?? 0))}
              </div>
            </div>
          </div>
        </article>
      {/each}
    </section>

    <section class="grid grid-cols-1 xl:grid-cols-[1.35fr_1fr] gap-5">
      <div class="command-panel rounded-lg overflow-hidden">
        <div class="px-5 py-4 border-b border-white/10 flex items-center justify-between">
          <div>
            <h2 class="text-sm font-semibold">Recent automatic placement</h2>
            <p class="text-[10px] text-white/40 mt-1">
              Prompt와 모델 출력은 표시하지 않고 배정 메타데이터만 표시합니다.
            </p>
          </div>
          <span class="text-[10px] text-exo-yellow">WORK UNIT ROUTING</span>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-left text-[11px]">
            <thead class="text-white/35 border-b border-white/10">
              <tr>
                <th class="px-5 py-3 font-normal">TIME</th>
                <th class="px-3 py-3 font-normal">PROVIDER</th>
                <th class="px-3 py-3 font-normal">EXECUTOR</th>
                <th class="px-3 py-3 font-normal">MODE</th>
                <th class="px-5 py-3 font-normal text-right">STATE</th>
              </tr>
            </thead>
            <tbody>
              {#each recentJobs() as job}
                {@const executor = fleetNodes().find(
                  (node) => node.device_id === job.executor_device_id,
                )}
                <tr class="border-b border-white/5 last:border-0">
                  <td class="px-5 py-3 text-white/45">
                    {job.updated_at_ms
                      ? new Date(job.updated_at_ms).toLocaleTimeString()
                      : "—"}
                  </td>
                  <td class="px-3 py-3 uppercase">{job.profile ?? "—"}</td>
                  <td class="px-3 py-3 text-exo-yellow uppercase">
                    {executor?.role ?? job.executor_device_id?.slice(-8) ?? "—"}
                  </td>
                  <td class="px-3 py-3 text-white/55">
                    {job.execution_mode ?? "—"}
                  </td>
                  <td
                    class="px-5 py-3 text-right {job.state === 'complete'
                      ? 'text-emerald-400'
                      : 'text-red-400'}"
                  >
                    {job.state ?? "—"}
                  </td>
                </tr>
              {:else}
                <tr><td class="px-5 py-8 text-white/35" colspan="5"
                    >No local Fleet receipts yet.</td
                  ></tr
                >
              {/each}
            </tbody>
          </table>
        </div>
      </div>

      <div class="command-panel rounded-lg p-5">
        <h2 class="text-sm font-semibold">Convergence definition</h2>
        <p class="mt-3 text-xs leading-5 text-white/55">
          각 노드의 관측 부하는 CPU 35% + 메모리 35% + GPU 20% + OS1 queue
          pressure 10%로 계산합니다. 두 노드 부하의 차이가 0이면 100입니다.
          노드가 누락되거나 15초 이상 오래되면 점수를 만들지 않습니다.
        </p>
        <div class="mt-4 rounded border border-amber-300/20 bg-amber-300/5 p-3 text-[10px] leading-4 text-amber-100/70">
          이 값은 현재 관측된 균형 편차입니다. 일반 macOS 프로세스의 RAM·GPU를
          투명하게 하나로 합친다는 뜻이 아닙니다. EXO 추론은 모델 shard 단위,
          Codex·Claude는 OS1 작업 단위로 배정됩니다.
        </div>
      </div>
    </section>
  </main>
</div>
