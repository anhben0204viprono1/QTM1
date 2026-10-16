import { useCallback, useEffect, useMemo, useState } from "react";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement,
  Tooltip, Legend
} from "chart.js";
import { api } from "./api";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);

function formatTime(value) {
  if (!value) return "Chưa có";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("vi-VN");
}
function percent(value) {
  return value == null ? "—" : `${Number(value).toFixed(1)}%`;
}
function traffic(value) {
  if (value == null) return "—";
  const n = Number(value);
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)} Mbps`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(2)} Kbps`;
  return `${n.toFixed(0)} bps`;
}
function Status({ value }) {
  const normalized = String(value || "unknown").toLowerCase();
  return <span className={`status ${normalized}`}>{value || "unknown"}</span>;
}

export default function Dashboard() {
  const [devices, setDevices] = useState([]);
  const [metrics, setMetrics] = useState([]);
  const [interfaces, setInterfaces] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [health, setHealth] = useState(null);
  const [error, setError] = useState("");
  const [lastRefresh, setLastRefresh] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [h, d, m, i, a] = await Promise.all([
        api.health(), api.devices(), api.metrics(100), api.interfaces(), api.alerts(0)
      ]);
      setHealth(h);
      setDevices(d);
      setMetrics(m);
      setInterfaces(i);
      setAlerts(a);
      setError("");
      setLastRefresh(new Date());
    } catch (e) {
      setError(e.message || "Không thể kết nối API");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [refresh]);

  const onlineCount = devices.filter(d => d.status === "up").length;
  const avgCpu = useMemo(() => {
    const values = devices.map(d => d.cpu_percent).filter(v => v != null).map(Number);
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  }, [devices]);
  const avgRam = useMemo(() => {
    const values = devices.map(d => d.ram_percent).filter(v => v != null).map(Number);
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  }, [devices]);

  const chartData = {
    labels: metrics.map(m => formatTime(m.timestamp)),
    datasets: [
      { label: "CPU (%)", data: metrics.map(m => m.cpu_percent), borderColor: "#2563eb", backgroundColor: "#2563eb", tension: 0.25, spanGaps: true },
      { label: "RAM (%)", data: metrics.map(m => m.ram_percent), borderColor: "#16a34a", backgroundColor: "#16a34a", tension: 0.25, spanGaps: true }
    ]
  };
  const chartOptions = {
    responsive: true, maintainAspectRatio: false,
    scales: { y: { min: 0, max: 100, title: { display: true, text: "%" } } },
    plugins: { legend: { position: "bottom" } }
  };

  return (
    <main className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">NETWORK OPERATIONS</p>
          <h1>Dashboard giám sát mạng</h1>
          <p className="muted">CPU, RAM, interface, traffic và cảnh báo</p>
        </div>
        <button onClick={refresh}>↻ Làm mới</button>
      </header>

      {error && <div className="error"><strong>Không tải được dữ liệu:</strong> {error}<br />
        Kiểm tra API tại <code>http://127.0.0.1:8000/api/health</code> và đường dẫn SQLite.</div>}
      {health && <p className="connection">API/Database: <Status value={health.status} /> · Cập nhật giao diện: {lastRefresh?.toLocaleTimeString("vi-VN") || "đang tải"} · Tự làm mới mỗi 5 giây</p>}

      <section className="cards">
        <article className="card"><span>Tổng thiết bị</span><strong>{devices.length}</strong><small>Thiết bị trong Database</small></article>
        <article className="card"><span>Đang hoạt động</span><strong>{onlineCount}</strong><small>Trạng thái up</small></article>
        <article className="card"><span>CPU trung bình</span><strong>{percent(avgCpu)}</strong><small>Theo số liệu mới nhất mỗi thiết bị</small></article>
        <article className="card"><span>RAM trung bình</span><strong>{percent(avgRam)}</strong><small>Theo số liệu mới nhất mỗi thiết bị</small></article>
        <article className="card"><span>Cảnh báo mở</span><strong>{alerts.length}</strong><small>Chưa xử lý</small></article>
      </section>

      <section className="panel">
        <div className="panel-heading"><div><h2>CPU / RAM theo thời gian</h2><p className="muted">Tối đa 100 bản ghi gần nhất từ API</p></div></div>
        <div className="chart">{metrics.length ? <Line data={chartData} options={chartOptions} /> : <p className="empty">{loading ? "Đang tải..." : "Chưa có dữ liệu metrics để vẽ biểu đồ."}</p>}</div>
      </section>

      <section className="panel">
        <div className="panel-heading"><h2>Thiết bị</h2><span>{devices.length} thiết bị</span></div>
        <div className="table-wrap"><table><thead><tr><th>Hostname</th><th>IP</th><th>Hãng</th><th>Trạng thái</th><th>CPU</th><th>RAM</th><th>Lần thấy gần nhất</th></tr></thead>
          <tbody>{devices.map(d => <tr key={d.id}><td>{d.hostname}</td><td>{d.ip}</td><td>{d.vendor || "—"}</td><td><Status value={d.status} /></td><td>{percent(d.cpu_percent)}</td><td>{percent(d.ram_percent)}</td><td>{formatTime(d.last_seen || d.metrics_timestamp)}</td></tr>)}
          {!devices.length && <tr><td colSpan="7" className="empty">Chưa có thiết bị trong Database.</td></tr>}</tbody></table></div>
      </section>

      <section className="panel">
        <div className="panel-heading"><h2>Interface mới nhất</h2><span>{interfaces.length} interface</span></div>
        <div className="table-wrap"><table><thead><tr><th>Thiết bị</th><th>Interface</th><th>Trạng thái</th><th>In traffic</th><th>Out traffic</th><th>In errors</th><th>CRC</th><th>Out drops</th></tr></thead>
          <tbody>{interfaces.map(i => <tr key={i.id}><td>{i.hostname}</td><td>{i.name}</td><td><Status value={i.status} /></td><td>{traffic(i.in_bps)}</td><td>{traffic(i.out_bps)}</td><td>{i.in_errors ?? "—"}</td><td>{i.in_crc ?? "—"}</td><td>{i.out_drops ?? "—"}</td></tr>)}
          {!interfaces.length && <tr><td colSpan="8" className="empty">Chưa có interface hoặc chưa có số liệu.</td></tr>}</tbody></table></div>
      </section>

      <section className="panel">
        <div className="panel-heading"><h2>Cảnh báo chưa xử lý</h2><span>{alerts.length} cảnh báo</span></div>
        <div className="table-wrap"><table><thead><tr><th>Thời gian</th><th>Thiết bị</th><th>Interface</th><th>Loại</th><th>Mức độ</th><th>Nội dung</th><th>Giá trị / Ngưỡng</th></tr></thead>
          <tbody>{alerts.map(a => <tr key={a.id}><td>{formatTime(a.timestamp)}</td><td>{a.hostname}</td><td>{a.interface_name || "—"}</td><td>{a.type}</td><td><span className={`severity ${a.severity}`}>{a.severity}</span></td><td>{a.message}</td><td>{a.value ?? "—"} / {a.threshold ?? "—"}</td></tr>)}
          {!alerts.length && <tr><td colSpan="7" className="empty">Không có cảnh báo đang mở.</td></tr>}</tbody></table></div>
      </section>
      <footer>Network Monitoring · Dữ liệu hiển thị lấy từ SQLite qua FastAPI</footer>
    </main>
  );
}
