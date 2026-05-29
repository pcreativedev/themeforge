/* ================= NEO-TOKYO · Gallery ================= */

function StatusDot({ status }) {
  const s = STATUS[status];
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{
        width: 7, height: 7, borderRadius: 99, background: s.color,
        boxShadow: status !== 'archived' ? `0 0 8px ${s.color}` : 'none',
        animation: status === 'building' ? 'blink 1.1s infinite' : 'none',
      }} />
      <span className="mono" style={{ fontSize: 10, letterSpacing: '0.12em', color: s.color }}>{s.label}</span>
    </span>
  );
}

function gop(slug, op, arg) {  // operación real de galería (favorito/tags/archivar/eliminar)
  const B = window.tfBridge;
  if (!B || !B.gallery_op) return Promise.resolve({});
  return B.gallery_op(slug, op, arg || '').then(j => { try { return JSON.parse(j); } catch (e) { return {}; } });
}
function ProjectCard({ p, onOpen, i, onChanged, archived }) {
  const ag = AGENTS[p.agent] || { color: 'var(--accent)', glyph: '◆', label: p.agent };
  const act = (e, op, arg) => { e.stopPropagation(); gop(p.id, op, arg).then(() => onChanged && onChanged()); };
  const cbtn = { cursor: 'pointer', fontSize: 10.5, padding: '3px 9px', borderRadius: 99, background: 'transparent', border: '1px solid var(--line)', color: 'var(--tx-dim)', fontFamily: 'var(--font-mono)' };
  return (
    <div className="panel card-corner fade-in" onClick={() => onOpen(p)}
      style={{
        padding: 0, overflow: 'hidden', cursor: 'pointer',
        animationDelay: (i * 0.05) + 's',
        opacity: p.status === 'archived' ? 0.62 : 1,
        '--accent': p.accent,
      }}
      onMouseEnter={e => { e.currentTarget.classList.add('neon-edge'); }}
      onMouseLeave={e => { e.currentTarget.classList.remove('neon-edge'); }}>
      {/* preview */}
      <div style={{ position: 'relative', height: 132, borderBottom: '1px solid var(--line)' }}>
        <MockPreview kind={p.preview} accent={p.accent} />
        <div style={{ position: 'absolute', top: 10, left: 10 }}><StatusDot status={p.status} /></div>
        <span title="favorito" onClick={(e) => act(e, 'favorite')}
          style={{ position: 'absolute', top: 8, left: '50%', transform: 'translateX(-50%)', cursor: 'pointer', fontSize: 15, color: p.fav ? '#ffd23f' : 'var(--tx-faint)', zIndex: 3 }}>{p.fav ? '★' : '☆'}</span>
        <div style={{
          position: 'absolute', top: 8, right: 10, fontFamily: 'var(--font-jp)',
          fontSize: 22, color: p.accent, opacity: 0.5, fontWeight: 700,
        }}>{p.jp}</div>
        <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(180deg, transparent 50%, rgba(4,6,12,0.85))` }} />
      </div>
      {/* body */}
      <div style={{ padding: '14px 16px 16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 17, fontWeight: 600, letterSpacing: '0.01em', lineHeight: 1.15, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.name}</div>
            <div className="dim" style={{ fontSize: 12, marginTop: 3 }}>{p.type}</div>
          </div>
          <div className="mono" style={{ fontSize: 11, color: p.accent, flexShrink: 0, paddingTop: 3 }}>${p.cost.toFixed(2)}</div>
        </div>
        <div className="faint" style={{ fontSize: 11.5, marginTop: 8, lineHeight: 1.5, height: 34 }}>{p.desc}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
          {p.tags.map(t => <Chip key={t}>{t}</Chip>)}
        </div>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line)',
        }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 11.5, color: ag.color }}>
            <span style={{ fontSize: 13 }}>{ag.glyph}</span> {ag.label}
          </span>
          <span className="mono faint" style={{ fontSize: 10.5 }}>{p.commits} commits · {p.updated}</span>
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }} onClick={e => e.stopPropagation()}>
          <button style={cbtn} title="editar tags" onClick={(e) => { const v = prompt('Tags (separados por coma):', (p.tags || []).join(', ')); if (v !== null) act(e, 'tags', v); }}>🏷 tags</button>
          {archived
            ? <button style={cbtn} title="restaurar" onClick={(e) => act(e, 'unarchive')}>♻ restaurar</button>
            : <button style={cbtn} title="archivar" onClick={(e) => act(e, 'archive')}>📦 archivar</button>}
          <button style={{ ...cbtn, color: 'var(--gemini, #ff2e88)', borderColor: 'var(--gemini, #ff2e88)' }} title="eliminar" onClick={(e) => { if (confirm('¿Eliminar «' + p.name + '» PARA SIEMPRE? (carpeta + contenedor)')) act(e, 'delete'); }}>🗑</button>
        </div>
      </div>
    </div>
  );
}

function GalleryScreen({ onOpen }) {
  const [filter, setFilter] = useState('all');
  const [q, setQ] = useState('');
  // Galería EN VIVO: re-escanea proyectos reales vía el puente al montar.
  const [projects, setProjects] = useState(PROJECTS);
  const [arch, setArch] = useState([]);
  const [showArch, setShowArch] = useState(false);
  const [favOnly, setFavOnly] = useState(false);
  const load = () => {
    const B = window.tfBridge;
    if (B && B.list_projects) B.list_projects().then(j => { try { const a = JSON.parse(j); if (Array.isArray(a)) setProjects(a); } catch (e) {} });
    if (B && B.list_archived) B.list_archived().then(j => { try { const a = JSON.parse(j); if (Array.isArray(a)) setArch(a); } catch (e) {} });
  };
  useEffect(load, []);
  const filters = ['all', 'live', 'building', 'draft'];
  const base = showArch ? arch : projects;
  const ql = q.toLowerCase();
  const list = base.filter(p =>
    (showArch || filter === 'all' || p.status === filter) && (!favOnly || p.fav) &&
    ((p.name || '').toLowerCase().includes(ql) || (p.type || '').toLowerCase().includes(ql) || (p.tags || []).join(' ').toLowerCase().includes(ql))
  );
  const total = projects.reduce((s, p) => s + (p.cost || 0), 0);

  return (
    <div style={{ padding: '34px 40px 60px', position: 'relative', zIndex: 2 }}>
      {/* header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 26 }}>
        <div>
          <Eyebrow jp="制作庫">REPOSITORY · 制作</Eyebrow>
          <h1 style={{ fontFamily: 'var(--font-mega)', fontSize: 40, margin: '12px 0 0', letterSpacing: '0.01em' }}>
            <span className="neon-text">GALLERY</span>
          </h1>
          <div className="dim" style={{ fontSize: 13.5, marginTop: 6 }}>
            {projects.length} proyectos forjados · <span className="mono" style={{ color: 'var(--accent)' }}>${total.toFixed(2)}</span> en cómputo IA
          </div>
        </div>
        <Btn variant="primary" icon="plus" onClick={() => onOpen({ __new: true })}>Nuevo proyecto</Btn>
      </div>

      {/* toolbar */}
      <div style={{ display: 'flex', gap: 14, alignItems: 'center', marginBottom: 24, flexWrap: 'wrap' }}>
        <div className="panel" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 14px', flex: '1 1 280px', maxWidth: 360 }}>
          <Icon name="search" size={16} style={{ color: 'var(--tx-faint)' }} />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Buscar proyectos…  ⌘K"
            style={{ background: 'none', border: 'none', outline: 'none', color: 'var(--tx)', fontFamily: 'var(--font-display)', fontSize: 13.5, width: '100%' }} />
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {filters.map(f => (
            <button key={f} onClick={() => setFilter(f)}
              style={{
                fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase',
                padding: '7px 13px', borderRadius: 99, cursor: 'pointer',
                background: filter === f ? 'rgba(var(--accent-rgb),0.14)' : 'transparent',
                border: '1px solid ' + (filter === f ? 'rgba(var(--accent-rgb),0.5)' : 'var(--line)'),
                color: filter === f ? 'var(--accent)' : 'var(--tx-dim)',
                boxShadow: filter === f ? '0 0 14px rgba(var(--accent-rgb),0.25)' : 'none',
                transition: 'all 0.15s',
              }}>{f === 'all' ? 'todos' : STATUS[f].label.toLowerCase()}</button>
          ))}
          {(() => { const on = (active) => ({ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', padding: '7px 13px', borderRadius: 99, cursor: 'pointer', background: active ? 'rgba(var(--accent-rgb),0.14)' : 'transparent', border: '1px solid ' + (active ? 'rgba(var(--accent-rgb),0.5)' : 'var(--line)'), color: active ? 'var(--accent)' : 'var(--tx-dim)' }); return [
            <button key="fav" style={on(favOnly)} onClick={() => setFavOnly(v => !v)}>★ favoritos</button>,
            <button key="arch" style={on(showArch)} onClick={() => setShowArch(v => !v)}>📦 archivados</button>,
            <button key="rl" style={on(false)} onClick={load}>↻</button>,
          ]; })()}
        </div>
      </div>

      {/* grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))', gap: 18 }}>
        {list.map((p, i) => <ProjectCard key={p.id} p={p} onOpen={onOpen} i={i} onChanged={load} archived={showArch} />)}
      </div>
      {list.length === 0 && (
        <div className="faint" style={{ textAlign: 'center', padding: 60, fontFamily: 'var(--font-mono)' }}>
          // sin resultados — 該当なし
        </div>
      )}
    </div>
  );
}

Object.assign(window, { GalleryScreen, StatusDot });
