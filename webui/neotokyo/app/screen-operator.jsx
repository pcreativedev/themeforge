/* ================= NEO-TOKYO · Operator (Hermes Mission Control) ================= */

function MissionRow({ m }) {
  const ag = AGENTS[m.agent];
  const sc = m.status === 'running' ? 'var(--accent)' : m.status === 'done' ? 'var(--codex)' : 'var(--tx-faint)';
  const prog = useCountUp(m.progress, 1000, [m.id]);
  return (
    <div className="panel" style={{ padding: '14px 18px', borderColor: m.status === 'running' ? 'rgba(var(--accent-rgb),0.3)' : 'var(--line)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ color: ag.color, fontSize: 16 }}>{ag.glyph}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{m.name}</div>
          <div className="mono faint" style={{ fontSize: 11, marginTop: 2 }}>{m.step}</div>
        </div>
        <span className="mono" style={{ fontSize: 11, color: sc, letterSpacing: '0.08em' }}>{m.status.toUpperCase()}</span>
        <span className="mono dim" style={{ fontSize: 11, width: 58, textAlign: 'right' }}>{m.eta}</span>
      </div>
      <div style={{ height: 5, background: 'rgba(255,255,255,0.06)', borderRadius: 99, marginTop: 11, overflow: 'hidden' }}>
        <div style={{ width: prog + '%', height: '100%', borderRadius: 99,
          background: m.status === 'done' ? 'var(--codex)' : 'linear-gradient(90deg,var(--accent),var(--accent-2))',
          boxShadow: m.status === 'running' ? '0 0 10px rgba(var(--accent-rgb),0.6)' : 'none',
          transition: 'width 0.3s' }} />
      </div>
    </div>
  );
}

function OperatorScreen() {
  const running = MISSIONS.filter(m => m.status === 'running').length;
  const queued = MISSIONS.filter(m => m.status === 'queued').length;
  return (
    <div style={{ padding: '34px 40px 60px', position: 'relative', zIndex: 2 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 24 }}>
        <div>
          <Eyebrow jp="司令室">OPERATOR · HERMES MISSION CONTROL</Eyebrow>
          <h1 style={{ fontFamily: 'var(--font-mega)', fontSize: 38, margin: '12px 0 6px' }}>
            MISSION <span className="neon-text">CONTROL</span>
          </h1>
          <div className="dim" style={{ fontSize: 13.5 }}>Orquesta builds autónomos en paralelo · {running} activos · {queued} en cola</div>
        </div>
        <Btn variant="primary" icon="rocket">Lanzar misión</Btn>
      </div>

      {/* live stats strip */}
      <div style={{ display: 'flex', gap: 14, marginBottom: 22 }}>
        {[['ACTIVAS', running, 'var(--accent)'], ['EN COLA', queued, 'var(--gemini)'], ['HOY', '12', 'var(--codex)'], ['COSTE HOY', '$8.40', 'var(--accent-2)']].map(([l, v, c]) => (
          <div key={l} className="panel" style={{ flex: 1, padding: '14px 18px' }}>
            <div className="eyebrow" style={{ fontSize: 9.5 }}>{l}</div>
            <div style={{ fontFamily: 'var(--font-mega)', fontSize: 24, marginTop: 6, color: c }}>{v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20, alignItems: 'start' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="eyebrow" style={{ marginBottom: 2 }}>MISIONES · 任務</div>
          {MISSIONS.map(m => <MissionRow key={m.id} m={m} />)}
        </div>

        {/* agent pool */}
        <div className="panel card-corner" style={{ padding: 20 }}>
          <div className="eyebrow" style={{ marginBottom: 14 }}>POOL DE AGENTES · 代理</div>
          {Object.entries(AGENTS).map(([k, a]) => {
            const busy = MISSIONS.some(m => m.agent === k && m.status === 'running');
            return (
              <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', borderBottom: '1px solid var(--line)' }}>
                <span style={{ color: a.color, fontSize: 15 }}>{a.glyph}</span>
                <span style={{ flex: 1, fontSize: 13 }}>{a.label}</span>
                <span style={{ width: 7, height: 7, borderRadius: 99, background: busy ? a.color : 'var(--tx-faint)', boxShadow: busy ? `0 0 8px ${a.color}` : 'none', animation: busy ? 'blink 1.1s infinite' : 'none' }} />
                <span className="mono faint" style={{ fontSize: 10.5, width: 52, textAlign: 'right' }}>{busy ? 'busy' : 'idle'}</span>
              </div>
            );
          })}
          <div style={{ marginTop: 14, fontSize: 11.5 }} className="faint">
            <span className="jp">ヘルメス</span> · Hermes orquesta hasta 4 agentes simultáneos con presupuesto compartido.
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { OperatorScreen });
