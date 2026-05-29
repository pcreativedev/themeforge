/* ================= NEO-TOKYO · Command Palette (Ctrl+K) ================= */

function CommandPalette({ open, onClose, onNav, projects, onOpenProject }) {
  const [q, setQ] = useState('');
  const [sel, setSel] = useState(0);
  const inputRef = useRef(null);

  const actions = useMemo(() => {
    const nav = [
      { id: 'gallery', label: 'Ir a Gallery', kind: 'nav', icon: 'grid', jp: '制作庫' },
      { id: 'new', label: 'Nuevo proyecto · Vibe scaffolder', kind: 'nav', icon: 'box', jp: '新規' },
      { id: 'cost', label: 'Ver AI Cost Tracker', kind: 'nav', icon: 'dollar', jp: '費用' },
      { id: 'compare', label: 'Comparar agentes', kind: 'nav', icon: 'users', jp: '比較' },
      { id: 'market', label: 'Market Analyzer', kind: 'nav', icon: 'globe', jp: '市場' },
      { id: 'licensing', label: 'Licensing Forge', kind: 'nav', icon: 'key', jp: '認可' },
      { id: 'settings', label: 'Theme Editor / Settings', kind: 'nav', icon: 'settings', jp: '設定' },
    ];
    const cmds = [
      { id: 'deploy', label: 'Deploy demo → Netlify', kind: 'cmd', icon: 'rocket' },
      { id: 'preflight', label: 'Run pre-flight checker', kind: 'cmd', icon: 'check' },
      { id: 'zip', label: 'Build ZIP para ThemeForest', kind: 'cmd', icon: 'package' },
      { id: 'mcp', label: 'Abrir catálogo MCP (12 servers)', kind: 'cmd', icon: 'layers' },
      { id: 'pixel', label: '🎮 Toggle Pixel Office visualizer', kind: 'cmd', icon: 'cpu' },
    ];
    const projs = projects.map(p => ({ id: 'proj:' + p.id, label: 'Abrir · ' + p.name, kind: 'project', icon: 'folderOpen', proj: p, jp: p.jp }));
    return [...nav, ...projs, ...cmds];
  }, [projects]);

  const filtered = actions.filter(a => a.label.toLowerCase().includes(q.toLowerCase()) || (a.jp || '').includes(q));

  useEffect(() => { if (open) { setQ(''); setSel(0); setTimeout(() => inputRef.current?.focus(), 30); } }, [open]);
  useEffect(() => { setSel(0); }, [q]);

  const run = (a) => {
    if (!a) return;
    if (a.kind === 'nav') onNav(a.id);
    else if (a.kind === 'project') onOpenProject(a.proj);
    else if (a.kind === 'cmd') onNav('cmd:' + a.id);
    onClose();
  };

  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel(s => Math.min(filtered.length - 1, s + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(s => Math.max(0, s - 1)); }
    else if (e.key === 'Enter') { e.preventDefault(); run(filtered[sel]); }
    else if (e.key === 'Escape') onClose();
  };

  if (!open) return null;
  const kindLabel = { nav: 'IR A', cmd: 'COMANDO', project: 'PROYECTO' };
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 200, background: 'rgba(2,4,10,0.7)', backdropFilter: 'blur(6px)', display: 'grid', placeItems: 'start center', paddingTop: '12vh' }}>
      <div className="panel neon-edge fade-in" onClick={e => e.stopPropagation()}
        style={{ width: 'min(640px, 92vw)', padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '16px 20px', borderBottom: '1px solid var(--line)' }}>
          <Icon name="search" size={18} style={{ color: 'var(--accent)' }} />
          <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)} onKeyDown={onKey}
            placeholder="Escribe para buscar… acciones, proyectos, comandos"
            style={{ flex: 1, background: 'none', border: 'none', outline: 'none', color: 'var(--tx)', fontFamily: 'var(--font-display)', fontSize: 16 }} />
          <span className="chip" style={{ fontSize: 9.5 }}>ESC</span>
        </div>
        <div style={{ maxHeight: 380, overflowY: 'auto', padding: 8 }}>
          {filtered.map((a, i) => (
            <div key={a.id} onMouseEnter={() => setSel(i)} onClick={() => run(a)}
              style={{
                display: 'flex', alignItems: 'center', gap: 12, padding: '11px 14px', borderRadius: 9, cursor: 'pointer',
                background: i === sel ? 'rgba(var(--accent-rgb),0.12)' : 'transparent',
                border: '1px solid ' + (i === sel ? 'rgba(var(--accent-rgb),0.4)' : 'transparent'),
              }}>
              <Icon name={a.icon} size={17} style={{ color: i === sel ? 'var(--accent)' : 'var(--tx-faint)' }} />
              <span style={{ flex: 1, fontSize: 13.5, color: i === sel ? 'var(--tx)' : 'var(--tx-dim)' }}>{a.label}</span>
              {a.jp && <span className="jp faint" style={{ fontSize: 11 }}>{a.jp}</span>}
              <span className="mono" style={{ fontSize: 9, letterSpacing: '0.1em', color: 'var(--tx-faint)', border: '1px solid var(--line)', borderRadius: 5, padding: '2px 6px' }}>{kindLabel[a.kind]}</span>
            </div>
          ))}
          {filtered.length === 0 && <div className="faint mono" style={{ padding: 30, textAlign: 'center' }}>// sin coincidencias — 該当なし</div>}
        </div>
        <div style={{ display: 'flex', gap: 16, padding: '10px 18px', borderTop: '1px solid var(--line)', fontSize: 10.5 }} className="mono faint">
          <span>↑↓ navegar</span><span>⏎ ejecutar</span><span>esc cerrar</span>
          <span style={{ marginLeft: 'auto' }} className="jp">指揮システム</span>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { CommandPalette });
