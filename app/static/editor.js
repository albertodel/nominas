// Editor de nómina: filas dinámicas + comprobaciones aritméticas en vivo.
// Misma lógica que app/calculos.py.
(() => {
  const form = document.getElementById('editor');
  const tbody = document.querySelector('#lineas tbody');
  const tpl = document.getElementById('fila');
  const checksEl = document.getElementById('checks');
  const resumenEl = document.getElementById('resumen-lineas');

  const DEVENGO = ['salarial', 'no_salarial'];
  const DEDUCCION = ['ss', 'irpf', 'otra_ded'];

  // Igual que parse_importe() del servidor
  function aCent(txt) {
    let s = (txt || '').replace(/[€\s]/g, '');
    if (!s) return null;
    if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.');
    else if ((s.match(/\./g) || []).length > 1 || /^-?\d{1,3}\.\d{3}$/.test(s)) s = s.replace(/\./g, '');
    const v = Number(s);
    return Number.isFinite(v) ? Math.round(v * 100) : NaN;
  }
  const fmt = c => (c / 100).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const campo = n => form.elements[n];

  function nuevaFila(cat = 'salarial', concepto = '', importe = '') {
    const tr = tpl.content.firstElementChild.cloneNode(true);
    tr.querySelector('[name=l_cat]').value = cat;
    tr.querySelector('[name=l_concepto]').value = concepto;
    tr.querySelector('[name=l_importe]').value = importe;
    tbody.appendChild(tr);
    return tr;
  }

  // Plantilla de partida para la entrada manual
  if (!tbody.children.length) {
    [['salarial', 'Salario base'],
     ['ss', 'Cotización Contingencias Comunes'],
     ['ss', 'Cotización Mecanismo Equidad Intergeneracional'],
     ['ss', 'Cotización Formación Profesional'],
     ['ss', 'Cotización Desempleo'],
     ['irpf', 'Retención IRPF']].forEach(([c, t]) => nuevaFila(c, t));
  }

  function sumas() {
    const s = { salarial: 0, no_salarial: 0, ss: 0, irpf: 0, otra_ded: 0, malas: 0 };
    tbody.querySelectorAll('tr').forEach(tr => {
      const cat = tr.querySelector('[name=l_cat]').value;
      const inp = tr.querySelector('[name=l_importe]');
      const v = aCent(inp.value);
      inp.style.borderColor = Number.isNaN(v) ? 'var(--bad)' : '';
      if (Number.isNaN(v)) { s.malas++; return; }
      if (v !== null && cat in s) s[cat] += v;
    });
    s.dev = DEVENGO.reduce((a, k) => a + s[k], 0);
    s.ded = DEDUCCION.reduce((a, k) => a + s[k], 0);
    return s;
  }

  function li(estado, texto, det) {
    const el = document.createElement('li');
    el.className = estado;
    el.innerHTML = `<span class="ico">${estado === 'ok' ? '✓' : estado === 'bad' ? '✗' : '!'}</span>` +
                   `<span></span><span class="det"></span>`;
    el.children[1].textContent = texto;
    el.children[2].textContent = det;
    checksEl.appendChild(el);
  }

  function comprobar() {
    const s = sumas();
    checksEl.innerHTML = '';
    const tDev = aCent(campo('total_devengado').value);
    const tDed = aCent(campo('total_deducir').value);
    const liq = aCent(campo('liquido').value);
    const cmp = (txt, impreso, calc) => {
      if (impreso === null || Number.isNaN(impreso)) {
        li('warn', txt, `falta el total impreso · líneas: ${fmt(calc)}`); return;
      }
      const ok = Math.abs(impreso - calc) <= 1;
      li(ok ? 'ok' : 'bad', txt, ok ? fmt(calc) : `impreso ${fmt(impreso)} · calculado ${fmt(calc)}`);
    };
    cmp('Suma de devengos = Total devengado', tDev, s.dev);
    cmp('Suma de deducciones = Total a deducir', tDed, s.ded);
    const baseLiq = (tDev !== null && tDed !== null && !isNaN(tDev) && !isNaN(tDed)) ? tDev - tDed : s.dev - s.ded;
    cmp('Devengado − Deducciones = Líquido', liq, baseLiq);
    const base = aCent(campo('base_irpf').value), pct = aCent(campo('irpf_pct').value);
    if (base && pct !== null && !isNaN(pct)) {
      const teo = Math.round(base * pct / 10000);
      const ok = Math.abs(teo - s.irpf) <= 5;
      li(ok ? 'ok' : 'warn', 'Base IRPF × % = Retención IRPF',
         ok ? fmt(s.irpf) : `esperado ${fmt(teo)} · líneas ${fmt(s.irpf)}`);
    }
    if (s.malas) li('bad', `${s.malas} importe(s) no válido(s)`, 'revisa los marcados en rojo');
    resumenEl.textContent =
      `Salarial ${fmt(s.salarial)} · Otros cobros ${fmt(s.no_salarial)} · ` +
      `S.S. ${fmt(s.ss)} · IRPF ${fmt(s.irpf)}` + (s.otra_ded ? ` · Otras ${fmt(s.otra_ded)}` : '');
  }

  document.getElementById('add').addEventListener('click', () => {
    nuevaFila().querySelector('[name=l_concepto]').focus();
  });
  tbody.addEventListener('click', e => {
    if (e.target.closest('.del')) { e.target.closest('tr').remove(); comprobar(); }
  });
  document.getElementById('autototal').addEventListener('click', () => {
    const s = sumas();
    campo('total_devengado').value = fmt(s.dev).replace(/\./g, '');
    campo('total_deducir').value = fmt(s.ded).replace(/\./g, '');
    if (!campo('liquido').value) campo('liquido').value = fmt(s.dev - s.ded).replace(/\./g, '');
    comprobar();
  });
  form.addEventListener('input', comprobar);
  form.addEventListener('change', comprobar);
  comprobar();
})();
